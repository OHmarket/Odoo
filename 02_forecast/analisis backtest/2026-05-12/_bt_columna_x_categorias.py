"""
Desagregacion de la columna X por categoria L2.

Foco:
  - BX (113 SKUs): donde el motor over-forecastea 28% en Z1
  - CX (10 SKUs): los pocos C estables
  - AX (290 SKUs): para referencia (donde funciona bien)
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
df = pd.read_excel(PATH, engine="openpyxl")
weeks = sorted(df["target_week_start"].dropna().unique())
if len(weeks) > 3:
    df = df[df["target_week_start"].isin(weeks[-3:])].copy()
for c in ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
hm = df[df["method"] == "hm_si"].copy()


def cat_breakdown(sub_hm, label):
    print(f"\n{'=' * 110}")
    print(f"{label}")
    print('=' * 110)
    cat_agg = sub_hm.groupby("categ_id", as_index=False).agg(
        n_filas=("real_qty", "size"),
        n_skus=("product_id", "nunique"),
        real=("real_qty", "sum"),
        forecast=("forecast_qty", "sum"),
        ae=("abs_error_qty", "sum"),
        e=("error_qty", "sum"),
    )
    cat_agg["WAPE_%"] = (cat_agg["ae"] / cat_agg["real"] * 100).round(1)
    cat_agg["BIAS_%"] = (cat_agg["e"] / cat_agg["real"] * 100).round(1)
    cat_agg["fcst_vs_real"] = (cat_agg["forecast"] / cat_agg["real"]).round(2)
    cat_agg = cat_agg.sort_values("real", ascending=False)
    print(cat_agg[["categ_id", "n_skus", "n_filas", "real", "forecast", "WAPE_%", "BIAS_%", "fcst_vs_real"]].to_string(index=False))


# AX para referencia (donde el motor anda bien)
cat_breakdown(
    hm[hm["abcxyz"] == "AX"],
    "AX (290 SKUs, 52% volumen) — REFERENCIA: motor actual va bien aqui"
)

# BX agregado
cat_breakdown(
    hm[hm["abcxyz"] == "BX"],
    "BX agregado (113 SKUs, 5.6% volumen) — diagnostico general"
)

# BX en Z1 (donde el motor LO ATIENDE y BIAS=-28%)
print("\n" + "X" * 110)
print("CASO PROBLEMA: BX EN Z1 (motor activo, BIAS -28%)")
print("X" * 110)
cat_breakdown(
    hm[(hm["abcxyz"] == "BX") & (hm["forecast_zone"] == "Z1")],
    "BX en Z1 (96 SKUs) — el motor SOBRE-pronostica 28%"
)

# BX en Z4 (donde el motor NO LO ATIENDE y BIAS=+15%)
cat_breakdown(
    hm[(hm["abcxyz"] == "BX") & (hm["forecast_zone"] == "Z4")],
    "BX en Z4 (112 SKUs) — el motor NO los atiende, vendieron +15%"
)

# CX completo
print("\n" + "X" * 110)
print("CX (10 SKUs unicos, casi todos en Z4)")
print("X" * 110)
cx = hm[hm["abcxyz"] == "CX"]
cx_skus = cx.groupby("product_id", as_index=False).agg(
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    categ=("categ_id", "first"),
    forecast_zone=("forecast_zone", "first"),
    ciclo=("ciclo_de_vida", "first"),
)
cx_skus["WAPE_%"] = (abs(cx_skus["forecast"] - cx_skus["real"]) / cx_skus["real"].replace(0, np.nan) * 100).round(1)
print(cx_skus.to_string(index=False))

print("\nDONE.")
