"""
Título: Proyecto 4 - Generador de ventas históricas
Autor: Jorge Edwin Guevara Ayala
Descripción: Crea un histórico de ventas simuladas con NumPy usando los productos y
             precios de productos.csv, y lo guarda en ventas.parquet con Polars.
             Se corre una sola vez antes de levantar la API:  python generar_parquet.py
"""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import time

import numpy as np
import polars as pl

CARPETA = Path(__file__).resolve().parent
RUTA_PRODUCTOS = CARPETA / "productos.csv"
RUTA_PARQUET = CARPETA / "ventas.parquet"

# Mismas columnas y tipos que ventas.csv, para que la API pueda unir los dos archivos
ESQUEMA_VENTAS = {
    "id_venta": pl.Int64,
    "fecha": pl.Datetime("us"),
    "producto": pl.String,
    "precio": pl.Float64,
    "cantidad": pl.Int64,
    "monto_total": pl.Float64,
}

TOTAL_REGISTROS = 1_500_000
DIAS_DE_HISTORIA = 365


def generar(total: int) -> pl.DataFrame:
    rng = np.random.default_rng(2026)

    productos = pl.read_csv(RUTA_PRODUCTOS)
    nombres = productos["nombre"].to_numpy()
    precios = productos["precio"].cast(pl.Float64).to_numpy()

    # No todos los productos se venden igual; unos pesos al azar le dan más realismo
    pesos = rng.dirichlet(np.ones(len(nombres)) * 2)
    indices = rng.choice(len(nombres), size=total, p=pesos)

    # La mayoría de la gente compra 1 o 2 piezas
    cantidades = rng.choice([1, 2, 3, 4, 5], size=total, p=[0.55, 0.25, 0.10, 0.06, 0.04])

    # Fechas repartidas en el último año, terminando justo ahora
    fin = datetime.now().replace(microsecond=0)
    inicio = fin - timedelta(days=DIAS_DE_HISTORIA)
    segundos = np.sort(rng.integers(0, DIAS_DE_HISTORIA * 86_400, size=total))
    fechas = (np.datetime64(inicio, "s") + segundos.astype("timedelta64[s]")).astype("datetime64[us]")

    precio_venta = precios[indices]

    return pl.DataFrame({
        "id_venta": np.arange(1, total + 1),
        "fecha": fechas,
        "producto": nombres[indices],
        "precio": precio_venta,
        "cantidad": cantidades,
        "monto_total": np.round(precio_venta * cantidades, 2),
    }).cast(ESQUEMA_VENTAS)


if __name__ == "__main__":
    total = int(sys.argv[1]) if len(sys.argv) > 1 else TOTAL_REGISTROS

    inicio = time.perf_counter()
    df = generar(total)
    df.write_parquet(RUTA_PARQUET)
    duracion = time.perf_counter() - inicio

    tamano_mb = RUTA_PARQUET.stat().st_size / 1_048_576
    print(f"Se generaron {df.height:,} ventas en {duracion:.1f} s")
    print(f"Archivo: {RUTA_PARQUET.name} ({tamano_mb:.1f} MB)")
    print(df.head(5))
