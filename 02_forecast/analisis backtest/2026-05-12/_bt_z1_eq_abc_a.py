"""
Validar la regla 'Z1 = ABC=A'.

Preguntas:
  1. Cuantos ABC=A estan HOY en Z1 vs Z4?
  2. Que ganamos / perdemos si redefinimos Z1=A?
  3. Que hacemos con B (525 SKUs, 13.2% del volumen)?
  4. Hay A con lifecycle=declining/dead?
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


def metrics(sub):
    n = len(sub)
    real = sub["real_qty"].sum()
    fcst = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return {
        "n_filas": n,
        "real": real,
        "fcst": fcst,
        "wape_%": (ae / real * 100) if real > 0 else np.nan,
        "bias_%": (e / real * 100) if real > 0 else np.nan,
    }


total_real = hm["real_qty"].sum()
total_n = len(hm)
total_skus = hm["product_id"].nunique()
print("=" * 110)
print(f"UNIVERSO: {total_n:,} filas | {total_skus:,} SKUs unicos | real total: {total_real:,.0f}")
print("=" * 110)


# ----------------------------------------------------------------------
# 1. SKUs UNICOS POR LETRA ABC x ZONA ACTUAL
# ----------------------------------------------------------------------
print("\n1. SKUs UNICOS por LETRA ABC × ZONA actual")
print("-" * 110)
sku_agg = hm.groupby("product_id", as_index=False).agg(
    abc_letter=("abc_letter", "first"),
    xyz_letter=("xyz_letter", "first"),
    abcxyz=("abcxyz", "first"),
    forecast_zone=("forecast_zone", "first"),
    real_total=("real_qty", "sum"),
    forecast_total=("forecast_qty", "sum"),
    ciclo_de_vida=("ciclo_de_vida", "first"),
)
ct = pd.crosstab(sku_agg["abc_letter"], sku_agg["forecast_zone"], margins=True)
print(ct.to_string())


# ----------------------------------------------------------------------
# 2. SI Z1 = ABC=A — performance esperada
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("2. SI REDEFINIMOS Z1 = ABC=A:  performance medida sobre filas backtest (no por SKU)")
print("=" * 110)
for letra in ['A', 'B', 'C']:
    sub = hm[hm["abc_letter"] == letra]
    m = metrics(sub)
    print(f"\n  ABC={letra}: n_filas={m['n_filas']:>6,}  real={m['real']:>9,.0f} ({m['real']/total_real*100:5.1f}%)  WAPE={m['wape_%']:>6.2f}%  BIAS={m['bias_%']:>+7.2f}%")


# ----------------------------------------------------------------------
# 3. COMPARATIVA: Z1 actual VS A propuesto
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("3. COMPARATIVA Z1 actual vs Z1 propuesto (=ABC=A)")
print("=" * 110)
z1_actual = hm[hm["forecast_zone"] == "Z1"]
abc_a = hm[hm["abc_letter"] == "A"]

print(f"\n  Z1 ACTUAL (smooth AX/AY/BX mu>=1-2 mature/ramp_up):")
m = metrics(z1_actual)
print(f"    n_filas: {m['n_filas']:>6,}  SKUs unicos: {z1_actual['product_id'].nunique():>4}")
print(f"    real:    {m['real']:>9,.0f}  ({m['real']/total_real*100:5.1f}% del volumen)")
print(f"    WAPE:    {m['wape_%']:.2f}%   BIAS: {m['bias_%']:+.2f}%")

print(f"\n  Z1 PROPUESTO (ABC=A, sin importar XYZ ni mu):")
m = metrics(abc_a)
print(f"    n_filas: {m['n_filas']:>6,}  SKUs unicos: {abc_a['product_id'].nunique():>4}")
print(f"    real:    {m['real']:>9,.0f}  ({m['real']/total_real*100:5.1f}% del volumen)")
print(f"    WAPE:    {m['wape_%']:.2f}%   BIAS: {m['bias_%']:+.2f}%")


# ----------------------------------------------------------------------
# 4. ABC=A QUE NO ESTAN EN Z1 ACTUAL (los 'nuevos entrantes')
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("4. ABC=A QUE NO ESTAN EN Z1 ACTUAL — donde estan y como performan?")
print("=" * 110)
a_no_z1 = hm[(hm["abc_letter"] == "A") & (hm["forecast_zone"] != "Z1")]
print(f"\n  Total filas ABC=A fuera de Z1: {len(a_no_z1):,} ({a_no_z1['product_id'].nunique():,} SKUs unicos)")
print(f"  Volumen real: {a_no_z1['real_qty'].sum():,.0f} ({a_no_z1['real_qty'].sum()/total_real*100:.1f}% del total)")
print(f"  Estos pasarian de tratamiento Z4 (forecast=0 mayoritariamente) a motor activo si Z1=A.")

print(f"\n  Por zona y XYZ:")
ct = pd.crosstab(a_no_z1["forecast_zone"], a_no_z1["xyz_letter"], margins=True)
print(ct.to_string())

print(f"\n  Por lifecycle:")
print(a_no_z1["ciclo_de_vida"].value_counts())


# ----------------------------------------------------------------------
# 5. ABC=A POR XYZ x LIFECYCLE (caracterizacion del grupo)
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("5. ABC=A: caracterizacion por XYZ × LIFECYCLE")
print("=" * 110)
ct = pd.crosstab(sku_agg[sku_agg["abc_letter"] == "A"]["xyz_letter"],
                 sku_agg[sku_agg["abc_letter"] == "A"]["ciclo_de_vida"].fillna("(NaN)"),
                 margins=True)
print(ct.to_string())


# ----------------------------------------------------------------------
# 6. AZ (whisky/vino premium probable) — detalle
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("6. AZ (alto margen, esporadico) — los 40 SKUs sospechosos de ser whisky/vino premium")
print("=" * 110)
az_skus = sku_agg[sku_agg["abcxyz"] == "AZ"]
print(f"  n={len(az_skus):,} SKUs unicos  |  real total: {az_skus['real_total'].sum():,.0f}")
print(f"  Distribucion por zona actual:")
print(az_skus["forecast_zone"].value_counts())
print(f"\n  Performance actual sobre filas backtest:")
az_rows = hm[hm["abcxyz"] == "AZ"]
m = metrics(az_rows)
print(f"    n_filas: {m['n_filas']:>6,}  real: {m['real']:>7,.0f}  fcst: {m['fcst']:>7,.0f}  WAPE: {m['wape_%']:.2f}%  BIAS: {m['bias_%']:+.2f}%")


# ----------------------------------------------------------------------
# 7. ABC=A CON LIFECYCLE DEAD/DECLINING (deberia ir forecast=0?)
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("7. ABC=A con lifecycle=declining/dead (paradoja: alto margen pero terminal)")
print("=" * 110)
a_dead = sku_agg[(sku_agg["abc_letter"] == "A") &
                  (sku_agg["ciclo_de_vida"].isin(["declining", "dead"]))]
print(f"  n={len(a_dead):,} SKUs")
if len(a_dead) > 0:
    print(f"  Volumen 3sem: {a_dead['real_total'].sum():,.0f}")
    print(f"  Estos seguramente van a REG-0 (forecast=0) por politica de lifecycle")

print("\nDONE.")
