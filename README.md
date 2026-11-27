# Proyecto 4 — Tiendita 24/7 (Polars, Parquet y Corte de Caja)

Proyecto final de Programación 4. Es la misma Tiendita Ed (abarrotes y snacks) que se fue armando en todo el semestre, pero ahora con un histórico de 1.5 millones de ventas. El histórico vive en `ventas.parquet`, las compras del día se van anotando en `ventas.csv` y el dashboard lee los dos archivos juntos con Polars. Cada cierto tiempo corre solo un corte de caja que pasa las ventas del CSV al Parquet, sin apagar la API.

## Lo que se hizo en cada unidad

**Unidad 1 — API y cliente web.** Backend en FastAPI con endpoints REST para el inventario y un cliente en HTML/CSS/JS que consume la API con `fetch()` sin recargar la página.

**Unidad 2 — Concurrencia y manejo de errores.** Validación de datos con Pydantic, respuestas 400/404/500 según el caso y un `asyncio.Lock()` para que dos compras al mismo tiempo no vendan más piezas de las que hay. Con Locust se comprobó que el producto con stock 1 solo se vende una vez.

**Unidad 3 — Persistencia y dashboard.** El inventario pasó a `productos.csv` y cada compra queda registrada en `ventas.csv`. Se agregaron tarjetas de KPIs y gráficas con Chart.js que se redibujan después de cada compra.

**Unidad 4 — Big Data y operación 24/7.**
- `generar_parquet.py` crea 1,500,000 ventas simuladas con NumPy, usando los productos y precios de `productos.csv`, y las guarda con Polars en `ventas.parquet`.
- Los endpoints de análisis usan `pl.scan_parquet()` y `pl.scan_csv()` y los unen con `pl.concat()` solo en memoria. Las compras nunca reescriben el Parquet, solo agregan una fila al CSV.
- APScheduler (`AsyncIOScheduler`) arranca dentro del `lifespan` de FastAPI y cada 2 minutos hace el corte de caja.

## Estructura

```
Proyecto-4-Tiendita/
├── backend/
│   ├── main.py              # API: inventario, compras, análisis con Polars y corte de caja
│   ├── generar_parquet.py   # Genera ventas.parquet con el histórico simulado
│   ├── productos.csv        # Inventario (id, nombre, precio, cantidad)
│   └── ventas.csv           # Ventas del turno, solo encabezados al inicio
├── frontend/
│   ├── index.html           # Dashboard y catálogo (Bootstrap + Chart.js)
│   └── app.js               # Llamadas a la API y gráficas
├── locust.py                # Prueba de carga
└── requirements.txt
```

`ventas.parquet` no se sube al repo porque pesa varios MB y además cambia con cada corte. Se genera con el script (ver abajo).

## Esquema de ventas

`ventas.csv` y `ventas.parquet` tienen exactamente las mismas columnas, si no Polars no podría concatenarlos:

| Columna       | Tipo     |
|---------------|----------|
| `id_venta`    | Int64    |
| `fecha`       | Datetime |
| `producto`    | String   |
| `precio`      | Float64  |
| `cantidad`    | Int64    |
| `monto_total` | Float64  |

En el CSV la fecha se guarda como texto (`2026-11-26 14:05:10`) y al leerlo se convierte a Datetime.

## Librerías

FastAPI, Uvicorn, Pydantic, Polars, NumPy, APScheduler (versión 3) y Locust para la prueba de carga. En el frontend, Bootstrap 5 y Chart.js desde CDN.

## Cómo levantarlo

1. Instalar dependencias:

```bash
pip install -r requirements.txt
```

2. Generar el histórico (**hay que hacerlo antes de levantar la API**, tarda menos de un segundo):

```bash
cd backend
python generar_parquet.py
```

Si se quiere otra cantidad de registros se pasa como argumento, por ejemplo `python generar_parquet.py 2000000`.

3. Levantar la API desde la misma carpeta `backend`:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

La documentación queda en http://127.0.0.1:8000/docs. Al arrancar se programa el corte de caja automático.

4. Abrir el frontend. Puede ser directo con `frontend/index.html`, con Live Server, o con:

```bash
cd frontend
python -m http.server 3000 --bind 127.0.0.1
```

y entrar a http://127.0.0.1:3000.

5. (Opcional) Prueba de carga:

```bash
locust -f locust.py --host http://127.0.0.1:8000
```

## Endpoints

| Método | Ruta                          | Qué hace |
|--------|-------------------------------|----------|
| GET    | `/productos`                  | Regresa el inventario |
| GET    | `/productos/{id}`             | Regresa un producto |
| POST   | `/productos`                  | Agrega un producto a `productos.csv` (201) |
| DELETE | `/productos/{id}`             | Quita el producto de `productos.csv` |
| POST   | `/productos/{id}`             | Compra: descuenta stock y agrega la venta al final de `ventas.csv`. Acepta `{"cantidad": n}`, si no se manda compra 1 |
| GET    | `/api/analisis/kpis`          | Transacciones, ingresos, ticket promedio y producto estrella |
| GET    | `/api/analisis/mas-vendidos`  | Piezas e ingresos por producto (gráfica de barras) |
| GET    | `/api/analisis/ventas-por-dia`| Piezas e ingresos por día (gráfica de línea) |
| GET    | `/api/corte-de-caja`          | Ventas que siguen en el CSV, último corte y próximo corte |
| POST   | `/api/corte-de-caja`          | Hace el corte en ese momento, para no esperar al automático |

Si el producto no existe regresa 404 y si no alcanza el stock regresa 400.

## Cómo funciona el corte de caja

Cada 2 minutos (para poder verlo en clase) APScheduler llama a `corteDeCaja()`, que dentro del `async with lock`:

1. Lee las ventas que hay en `ventas.csv`. Si no hay ninguna, no hace nada.
2. Las une con lo que ya había en `ventas.parquet` y guarda el archivo. Primero se escribe a un temporal y luego se reemplaza, para que nunca quede un Parquet a medias.
3. Deja `ventas.csv` solo con la fila de encabezados.

Como el corte pasa ventas de un archivo al otro, el total del dashboard no cambia: antes del corte la venta se cuenta desde el CSV y después desde el Parquet. Para que una consulta no agarre el momento exacto en que el Parquet ya se actualizó pero el CSV todavía no se vació (y cuente doble), las consultas de análisis también esperan el lock. La parte pesada se manda a otro hilo con `asyncio.to_thread`, así la API sigue respondiendo mientras tanto.

En una tienda real el corte sería una vez al día. En `main.py` está comentada la línea con `cron` para las 23:59.

En el dashboard hay un recuadro con las ventas del turno y la hora del próximo corte. Una forma de comprobarlo: hacer una compra y ver que "Total Transacciones" sube en 1 y "Ventas del turno" en 1. Al pasar el corte, "Ventas del turno" vuelve a 0 y el total se queda igual.

## Autor

Jorge Edwin Guevara Ayala — Programación 4, Proyecto 4.
