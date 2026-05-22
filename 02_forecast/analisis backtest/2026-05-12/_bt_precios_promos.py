"""
Cruzar cambios de precio y promociones con SKUs problematicos de A.

Foco: verificar la hipotesis del usuario de que el problema en Cervezas
Premium (BIAS -140%) y Cervezas Tradicionales (BIAS +15%) viene de:
  1. Cambios de precio recientes NO detectados por el motor
  2. Promociones activas NO declaradas o no propagadas al forecast
  3. Canibalizacion entre SKUs (sustitucion)
"""
import pandas as pd
import numpy as np

PRICE = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
BACKTEST = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"

# ----------------------------------------------------------------------
# 1. ESTRUCTURA DE PRECIOS
# ----------------------------------------------------------------------
print("=" * 100)
print("1. ESTRUCTURA: x_price_change_event")
print("=" * 100)
dfp = pd.read_excel(PRICE, engine="openpyxl")
print(f"Filas: {len(dfp):,}")
print(f"Columnas: {list(dfp.columns)}")
print(f"\nMuestra (primeras 3 filas):")
print(dfp.head(3).to_string())

print("\n" + "=" * 100)
print("2. ESTRUCTURA: x_loyalty_promo_event")
print("=" * 100)
dfm = pd.read_excel(PROMO, engine="openpyxl")
print(f"Filas: {len(dfm):,}")
print(f"Columnas: {list(dfm.columns)}")
print(f"\nMuestra (primeras 3 filas):")
print(dfm.head(3).to_string())
