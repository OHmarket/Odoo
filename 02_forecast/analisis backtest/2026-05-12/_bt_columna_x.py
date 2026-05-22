"""
Performance de la columna X de la matriz ABCXYZ.

X = demanda estable (CV<=0.45). Es donde el motor v3.24 (SMA + SI + price)
deberia funcionar mejor.

Pregunta:
  - AX: ya esta en Z1 hoy, sabemos que va bien
  - BX: solo parcialmente en Z1
  - CX: casi todo en Z4
  Si extendemos motor a TODA la columna X, que pasa?
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
hm["abc_letter"] = hm["abcxyz"].fillna("").str[:1].str.upper()
hm["xyz_letter"] = hm["abcxyz"].fillna("").str[-1:].str.upper()

total_real = hm["real_qty"].sum()


def metrics(sub):
    n = len(sub)
    real = sub["real_qty"].sum()
    fcst = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return {
        "n_filas": n,
        "n_skus": sub["product_id"].nunique(),
        "real": real,
        "fcst": fcst,
        "wape_%": (ae / real * 100) if real > 0 else np.nan,
        "bias_%": (e / real * 100) if real > 0 else np.nan,
    }


print("=" * 100)
print("COLUMNA X DE LA MATRIZ ABCXYZ — demanda estable (CV<=0.45)")
print("=" * 100)

# ----------------------------------------------------------------------
# 1. AX, BX, CX globales
# ----------------------------------------------------------------------
print("\n1. PERFORMANCE GLOBAL POR CUBETA X")
print("-" * 100)
for cubeta in ["AX", "BX", "CX"]:
    sub = hm[hm["abcxyz"] == cubeta]
    m = metrics(sub)
    print(f"\n  {cubeta}: n_filas={m['n_filas']:>6,}  n_skus={m['n_skus']:>4}  real={m['real']:>9,.0f} ({m['real']/total_real*100:5.1f}% vol)")
    print(f"        fcst={m['fcst']:>9,.0f}  WAPE={m['wape_%']:>6.2f}%  BIAS={m['bias_%']:>+7.2f}%")

# ----------------------------------------------------------------------
# 2. Distribucion por forecast_zone actual de cada cubeta X
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. DONDE ESTAN HOY (forecast_zone) y como performan")
print("=" * 100)
for cubeta in ["AX", "BX", "CX"]:
    sub = hm[hm["abcxyz"] == cubeta]
    print(f"\n  Cubeta {cubeta}:")
    for zone in ["Z1", "Z2", "Z3", "Z4", "SIN_ZONA"]:
        sub_z = sub[sub["forecast_zone"] == zone]
        if len(sub_z) == 0:
            continue
        m = metrics(sub_z)
        share_real_cubeta = m['real'] / sub["real_qty"].sum() * 100 if sub["real_qty"].sum() > 0 else 0
        print(f"    {zone}: n_filas={m['n_filas']:>5,}  skus={m['n_skus']:>4}  real={m['real']:>7,.0f} ({share_real_cubeta:5.1f}% del {cubeta})  WAPE={m['wape_%']:>6.2f}%  BIAS={m['bias_%']:>+7.2f}%")

# ----------------------------------------------------------------------
# 3. Hipotesis: si TODA la X entrara a Z1 (motor activo)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. HIPOTESIS: que pasaria si TODA la columna X estuviera con motor activo (Z1)?")
print("=" * 100)
col_x = hm[hm["xyz_letter"] == "X"]
m_total = metrics(col_x)
print(f"\n  Total columna X: n_filas={m_total['n_filas']:>6,}  n_skus={m_total['n_skus']:>4}")
print(f"  Real: {m_total['real']:>9,.0f} ({m_total['real']/total_real*100:5.1f}% del volumen total)")
print(f"  WAPE: {m_total['wape_%']:.2f}%  BIAS: {m_total['bias_%']:+.2f}%")

# Cuanto de la X esta hoy en Z1 vs Z4?
x_en_z1 = col_x[col_x["forecast_zone"] == "Z1"]
x_en_z4 = col_x[col_x["forecast_zone"] == "Z4"]
print(f"\n  De toda la columna X:")
print(f"    En Z1 hoy (motor activo):  {len(x_en_z1):>6,} filas ({len(x_en_z1)/len(col_x)*100:5.1f}%)  real={x_en_z1['real_qty'].sum():>8,.0f}")
print(f"    En Z4 hoy (forecast=0):    {len(x_en_z4):>6,} filas ({len(x_en_z4)/len(col_x)*100:5.1f}%)  real={x_en_z4['real_qty'].sum():>8,.0f}")

# ----------------------------------------------------------------------
# 4. SKUs CX (los 10) — para entender la naturaleza
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. LOS 10 SKUs CX (bajo margen + estable)")
print("=" * 100)
cx_skus = hm[hm["abcxyz"] == "CX"].groupby("product_id", as_index=False).agg(
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    forecast_zone=("forecast_zone", "first"),
    ciclo=("ciclo_de_vida", "first"),
    categ=("categ_id", "first"),
)
cx_skus["wape_%"] = (abs(cx_skus["forecast"] - cx_skus["real"]) / cx_skus["real"].replace(0, np.nan) * 100).round(1)
print(cx_skus.to_string(index=False))

# ----------------------------------------------------------------------
# 5. Comparativa BX en Z1 vs BX en Z4 (donde el motor SI vs NO trata)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. BX: comparativa entre los que estan HOY en motor vs los que no")
print("=" * 100)
bx_z1 = hm[(hm["abcxyz"] == "BX") & (hm["forecast_zone"] == "Z1")]
bx_z4 = hm[(hm["abcxyz"] == "BX") & (hm["forecast_zone"] == "Z4")]
if len(bx_z1) > 0:
    m = metrics(bx_z1)
    print(f"\n  BX en Z1 (motor activo):  n_filas={m['n_filas']:>4,}  skus={m['n_skus']:>3}  real={m['real']:>5,.0f}  WAPE={m['wape_%']:>6.2f}%  BIAS={m['bias_%']:>+7.2f}%")
if len(bx_z4) > 0:
    m = metrics(bx_z4)
    print(f"  BX en Z4 (forecast=0):    n_filas={m['n_filas']:>4,}  skus={m['n_skus']:>3}  real={m['real']:>5,.0f}  WAPE={m['wape_%']:>6.2f}%  BIAS={m['bias_%']:>+7.2f}%")

print("\nDONE.")
