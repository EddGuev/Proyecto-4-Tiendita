"""
Título: Proyecto 4 - Tiendita 24/7: Big Data con Polars, Parquet y Corte de Caja
Autor: Jorge Edwin Guevara Ayala
Descripción: API de la tiendita. El inventario vive en productos.csv y las compras del
             turno se van agregando a ventas.csv. El histórico grande está en ventas.parquet.
             Los endpoints de análisis leen los dos archivos con Polars y los unen en memoria,
             y cada cierto tiempo un corte de caja automático pasa el CSV al Parquet.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import asyncio
import os

import polars as pl
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


CARPETA = Path(__file__).resolve().parent
RUTA_PRODUCTOS = CARPETA / "productos.csv"
RUTA_VENTAS = CARPETA / "ventas.csv"
RUTA_PARQUET = CARPETA / "ventas.parquet"

# En el CSV la fecha se guarda como texto; al leerlo se convierte a Datetime para que
# quede igual que en el Parquet y se puedan concatenar sin problemas
ESQUEMA_VENTAS = {
    "id_venta": pl.Int64,
    "fecha": pl.Datetime("us"),
    "producto": pl.String,
    "precio": pl.Float64,
    "cantidad": pl.Int64,
    "monto_total": pl.Float64,
}
ESQUEMA_VENTAS_CSV = {**ESQUEMA_VENTAS, "fecha": pl.String}
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"

# Para la demo en clase el corte corre cada 2 minutos.
# En una tienda real sería una vez al día, p. ej. a las 23:59:
#   scheduler.add_job(corteDeCaja, "cron", hour=23, minute=59)
MINUTOS_ENTRE_CORTES = 2

# Un solo candado para todo lo que toca los archivos de ventas o de productos
lock = asyncio.Lock()
scheduler = AsyncIOScheduler()
ultimo_corte = {"fecha": None, "ventas_archivadas": 0}


#Modelos de Pydantic
class crearProducto(BaseModel):
    nombre: str = Field(..., min_length=1, description="Nombre del producto")
    precio: float = Field(..., gt=0, description="Precio del producto")
    cantidad: int = Field(..., ge=0, description="stock del producto")


class respuestaProducto(BaseModel):
    id: int
    nombre: str
    precio: float
    cantidad: int


#Cuerpo opcional de la compra, si no se manda nada se compra una pieza
class compraProducto(BaseModel):
    cantidad: int = Field(1, ge=1, description="Piezas a comprar")


# ---------- Lectura y escritura de archivos ----------

def leerProductos() -> pl.DataFrame:
    return pl.read_csv(
        RUTA_PRODUCTOS,
        schema={"id": pl.Int64, "nombre": pl.String, "precio": pl.Float64, "cantidad": pl.Int64},
    )


def guardarProductos(df: pl.DataFrame):
    df.write_csv(RUTA_PRODUCTOS)


def asegurarVentasCsv():
    # Si el CSV no existe o se quedó vacío se vuelve a poner la fila de encabezados
    if not RUTA_VENTAS.exists() or RUTA_VENTAS.stat().st_size == 0:
        pl.DataFrame(schema=ESQUEMA_VENTAS_CSV).write_csv(RUTA_VENTAS)


def escanearVentasCsv() -> pl.LazyFrame:
    asegurarVentasCsv()
    return (
        pl.scan_csv(RUTA_VENTAS, schema=ESQUEMA_VENTAS_CSV)
        .with_columns(pl.col("fecha").str.to_datetime(FORMATO_FECHA, time_unit="us"))
    )


def escanearVentas() -> pl.LazyFrame:
    # Unión virtual: el histórico (Parquet) + lo que se ha vendido en el turno (CSV).
    # No se escribe nada a disco, la unión solo existe mientras se hace la consulta.
    partes = [escanearVentasCsv()]
    if RUTA_PARQUET.exists():
        partes.insert(0, pl.scan_parquet(RUTA_PARQUET))
    return pl.concat(partes, how="vertical")


def siguienteIdVenta() -> int:
    maximo = escanearVentas().select(pl.col("id_venta").max()).collect().item()
    return 1 if maximo is None else int(maximo) + 1


def agregarVentaCsv(venta: dict):
    # Se abre en modo "a" para escribir solo la fila nueva al final, sin reescribir el archivo
    asegurarVentasCsv()
    fila = pl.DataFrame([venta], schema=ESQUEMA_VENTAS_CSV)
    with open(RUTA_VENTAS, "a", encoding="utf-8") as archivo:
        fila.write_csv(archivo, include_header=False)


# ---------- Corte de caja ----------

def fusionarCsvEnParquet() -> int:
    ventas_turno = escanearVentasCsv().collect()
    if ventas_turno.height == 0:
        return 0

    if RUTA_PARQUET.exists():
        historico = pl.read_parquet(RUTA_PARQUET)
        completo = pl.concat([historico, ventas_turno], how="vertical")
    else:
        completo = ventas_turno

    # Primero se escribe a un archivo temporal y luego se reemplaza el original,
    # así nunca queda un ventas.parquet a medio escribir si algo falla
    temporal = RUTA_PARQUET.with_suffix(".parquet.tmp")
    completo.write_parquet(temporal)
    os.replace(temporal, RUTA_PARQUET)

    # El CSV queda solo con encabezados para el siguiente turno
    pl.DataFrame(schema=ESQUEMA_VENTAS_CSV).write_csv(RUTA_VENTAS)
    return ventas_turno.height


async def corteDeCaja():
    async with lock:
        # El trabajo pesado se manda a otro hilo para no congelar la API mientras dura
        archivadas = await asyncio.to_thread(fusionarCsvEnParquet)
    ultimo_corte["fecha"] = datetime.now().strftime(FORMATO_FECHA)
    ultimo_corte["ventas_archivadas"] = archivadas
    print(f"[Corte de caja] {ultimo_corte['fecha']} - ventas archivadas: {archivadas}")
    return archivadas


@asynccontextmanager
async def lifespan(app: FastAPI):
    asegurarVentasCsv()
    if not RUTA_PARQUET.exists():
        print("Aviso: no existe ventas.parquet, corre primero  python generar_parquet.py")
    scheduler.add_job(corteDeCaja, "interval", minutes=MINUTOS_ENTRE_CORTES, id="corte_de_caja")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="API Proyecto Tiendita 24/7", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ---------- CRUD de productos ----------

#GET Obtiene lista de productos de mi inventario
@app.get("/productos", response_model=list[respuestaProducto])
def getProductos():
    try:
        return leerProductos().to_dicts()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al leer los productos: {str(error)}"
        )


#GET Obtiene un producto por su ID
@app.get("/productos/{producto_id}", response_model=respuestaProducto)
def getProducto(producto_id: int):
    try:
        encontrado = leerProductos().filter(pl.col("id") == producto_id)
        if encontrado.is_empty():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No fue encontrado el producto"
            )
        return encontrado.row(0, named=True)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al consultar el producto: {str(error)}"
        )


#POST Agrega producto a mi inventario
@app.post("/productos", response_model=respuestaProducto, status_code=status.HTTP_201_CREATED)
async def addProducto(producto: crearProducto):
    try:
        async with lock:
            df = leerProductos()
            nuevo_id = 1 if df.is_empty() else int(df["id"].max()) + 1
            nuevo_producto = {
                "id": nuevo_id,
                "nombre": producto.nombre,
                "precio": producto.precio,
                "cantidad": producto.cantidad
            }
            df = pl.concat([df, pl.DataFrame([nuevo_producto], schema=df.schema)])
            guardarProductos(df)
        return nuevo_producto
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al agregar el producto: {str(error)}"
        )


#DELETE Borra producto de mi inventario (se reescribe el CSV sin esa fila)
@app.delete("/productos/{producto_id}")
async def deleteProducto(producto_id: int):
    try:
        async with lock:
            df = leerProductos()
            if df.filter(pl.col("id") == producto_id).is_empty():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No fue encontrado el producto"
                )
            guardarProductos(df.filter(pl.col("id") != producto_id))
        return {"Message": "El producto fue eliminado"}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar el producto: {str(error)}"
        )


#POST Compra un producto: descuenta stock y agrega la venta al final de ventas.csv
@app.post("/productos/{producto_id}")
async def comprarProducto(producto_id: int, compra: compraProducto | None = None):
    piezas = compra.cantidad if compra else 1
    try:
        # Leer, validar, descontar y registrar tiene que pasar de un jalón
        async with lock:
            df = leerProductos()
            encontrado = df.filter(pl.col("id") == producto_id)

            if encontrado.is_empty():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No existe el ID de ese producto"
                )

            producto = encontrado.row(0, named=True)
            stock = producto["cantidad"]
            if stock <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No hay stock de ese producto"
                )
            if piezas > stock:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Solo quedan {stock} piezas de ese producto"
                )

            await asyncio.sleep(0.05)  # Simula latencia de una operación real
            df = df.with_columns(
                pl.when(pl.col("id") == producto_id)
                .then(pl.col("cantidad") - piezas)
                .otherwise(pl.col("cantidad"))
                .alias("cantidad")
            )
            guardarProductos(df)

            venta = {
                "id_venta": siguienteIdVenta(),
                "fecha": datetime.now().strftime(FORMATO_FECHA),
                "producto": producto["nombre"],
                "precio": producto["precio"],
                "cantidad": piezas,
                "monto_total": round(producto["precio"] * piezas, 2),
            }
            agregarVentaCsv(venta)

        return {"Mensaje": "Producto comprado", "venta": venta}

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al comprar producto: {str(error)}"
        )


# ---------- Análisis con Polars (Parquet + CSV) ----------
# Las consultas también toman el lock. Si el corte de caja estuviera a la mitad
# (Parquet ya actualizado pero CSV sin vaciar) se podrían contar ventas dos veces.

def calcularKpis() -> dict:
    resumen = escanearVentas().select(
        pl.len().alias("total_transacciones"),
        pl.col("monto_total").sum().alias("ingresos_totales"),
    ).collect().row(0, named=True)

    total = resumen["total_transacciones"]
    if total == 0:
        return {"total_transacciones": 0, "ingresos_totales": 0.0,
                "ticket_promedio": 0.0, "producto_estrella": "Sin ventas"}

    estrella = (
        escanearVentas()
        .group_by("producto")
        .agg(pl.col("cantidad").sum())
        .sort("cantidad", descending=True)
        .limit(1)
        .collect()
    )
    ingresos = round(resumen["ingresos_totales"], 2)
    return {
        "total_transacciones": total,
        "ingresos_totales": ingresos,
        "ticket_promedio": round(ingresos / total, 2),
        "producto_estrella": estrella["producto"][0],
    }


def calcularMasVendidos() -> list[dict]:
    return (
        escanearVentas()
        .group_by("producto")
        .agg(
            pl.col("cantidad").sum().alias("cantidad_vendida"),
            pl.col("monto_total").sum().round(2).alias("ingresos"),
        )
        .sort("cantidad_vendida", descending=True)
        .collect()
        .to_dicts()
    )


def calcularVentasPorDia() -> list[dict]:
    return (
        escanearVentas()
        .group_by(pl.col("fecha").dt.date().alias("dia"))
        .agg(
            pl.col("cantidad").sum().alias("cantidad"),
            pl.col("monto_total").sum().round(2).alias("ingresos"),
        )
        .sort("dia")
        .with_columns(pl.col("dia").dt.strftime("%Y-%m-%d"))
        .collect()
        .to_dicts()
    )


async def consultar(funcion, mensaje_error: str):
    try:
        async with lock:
            return await asyncio.to_thread(funcion)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{mensaje_error}: {str(error)}"
        )


#GET KPIs: transacciones, ingresos, ticket promedio y producto más vendido
@app.get("/api/analisis/kpis")
async def getKpis():
    return await consultar(calcularKpis, "Error al calcular los KPIs")


#GET Piezas e ingresos por producto (gráfica de barras)
@app.get("/api/analisis/mas-vendidos")
async def getMasVendidos():
    return await consultar(calcularMasVendidos, "Error al calcular los más vendidos")


#GET Piezas e ingresos por día (gráfica de línea)
@app.get("/api/analisis/ventas-por-dia")
async def getVentasPorDia():
    return await consultar(calcularVentasPorDia, "Error al agrupar las ventas por día")


# ---------- Corte de caja ----------

#GET Cuántas ventas lleva el turno y cuándo toca el siguiente corte
@app.get("/api/corte-de-caja")
async def getEstadoCorte():
    async with lock:
        ventas_turno = await asyncio.to_thread(
            lambda: escanearVentasCsv().select(pl.len()).collect().item()
        )
    trabajo = scheduler.get_job("corte_de_caja")
    proximo = trabajo.next_run_time.strftime(FORMATO_FECHA) if trabajo and trabajo.next_run_time else None
    return {
        "ventas_en_turno": ventas_turno,
        "ultimo_corte": ultimo_corte["fecha"],
        "ventas_archivadas_ultimo_corte": ultimo_corte["ventas_archivadas"],
        "proximo_corte": proximo,
        "minutos_entre_cortes": MINUTOS_ENTRE_CORTES,
    }


#POST Hace el corte en ese momento, sin esperar al automático (útil para probar)
@app.post("/api/corte-de-caja")
async def hacerCorteManual():
    try:
        archivadas = await corteDeCaja()
        return {"Mensaje": "Corte de caja realizado", "ventas_archivadas": archivadas}
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en el corte de caja: {str(error)}"
        )
