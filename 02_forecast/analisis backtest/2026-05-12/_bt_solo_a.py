"""
PROBLEMA DEFINIDO SOLO EN ABC=A.

A son 540 SKUs = 27.5% de los SKUs = 82.6% del volumen = ~80% del margen.
Aqui esta donde el motor tiene que funcionar bien.

Diagnostico:
  1. A global: estado actual
  2. A por XYZ (AX/AY/AZ): donde duele
  3. A por zona actual (Z1/Z4): el detalle del rerouter
  4. Top 30 SKUs A por error absoluto (donde concentrar)
  5. A por categoria L2
  6. Direccion del error en A (over vs under)
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

# FILTRAR SOLO ABC=A
a = hm[hm["abc_letter"] == "A"].copy()


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
        "ae": ae,
    }


# ----------------------------------------------------------------------
# 0. CONTEXTO: A vs resto
# ----------------------------------------------------------------------
total_hm = metrics(hm)
m_a = metrics(a)
m_resto = metrics(hm[hm["abc_letter"] != "A"])

print("=" * 100)
print("PROBLEMA DEFINIDO SOLO EN ABC=A")
print("=" * 100)
print(f"\nUniverso total hm_si: n_skus={total_hm['n_skus']:,}  real={total_hm['real']:,.0f}  WAPE={total_hm['wape_%']:.2f}%  BIAS={total_hm['bias_%']:+.2f}%")
print(f"\n  A          : n_skus={m_a['n_skus']:>4} ({m_a['n_skus']/total_hm['n_skus']*100:5.1f}%)  real={m_a['real']:>9,.0f} ({m_a['real']/total_hm['real']*100:5.1f}%)  WAPE={m_a['wape_%']:>6.2f}%  BIAS={m_a['bias_%']:>+7.2f}%  ae={m_a['ae']:>8,.0f}")
print(f"  B+C+otros  : n_skus={m_resto['n_skus']:>4} ({m_resto['n_skus']/total_hm['n_skus']*100:5.1f}%)  real={m_resto['real']:>9,.0f} ({m_resto['real']/total_hm['real']*100:5.1f}%)  WAPE={m_resto['wape_%']:>6.2f}%  BIAS={m_resto['bias_%']:>+7.2f}%  ae={m_resto['ae']:>8,.0f}")


# ----------------------------------------------------------------------
# 1. A POR XYZ
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("1. A DESAGREGADO POR XYZ (donde duele)")
print("=" * 100)
real_a = m_a['real']
ae_a = m_a['ae']
print(f"{'cubeta':<10} {'n_skus':>8} {'real':>10} {'%vol_A':>8} {'WAPE_%':>8} {'BIAS_%':>8} {'ae':>10} {'%ae_A':>8}")
print("-" * 90)
for xyz in ['X', 'Y', 'Z']:
    sub = a[a["xyz_letter"] == xyz]
    m = metrics(sub)
    if m['real'] > 0:
        share_vol_a = m['real'] / real_a * 100
        share_ae_a = m['ae'] / ae_a * 100
        print(f"A{xyz:<9} {m['n_skus']:>8} {m['real']:>10,.0f} {share_vol_a:>7.1f}% {m['wape_%']:>7.2f}% {m['bias_%']:>+7.2f}% {m['ae']:>10,.0f} {share_ae_a:>7.1f}%")


# ----------------------------------------------------------------------
# 2. A POR ZONA ACTUAL (Z1 = motor activo, Z4 = forecast 0 mayoritariamente)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. A POR ZONA ACTUAL DEL ROUTER v3.24")
print("=" * 100)
for z in ['Z1', 'Z2', 'Z3', 'Z4', 'SIN_ZONA']:
    sub = a[a["forecast_zone"] == z]
    if len(sub) == 0:
        continue
    m = metrics(sub)
    share_vol_a = m['real'] / real_a * 100 if real_a > 0 else 0
    share_ae_a = m['ae'] / ae_a * 100 if ae_a > 0 else 0
    print(f"  {z:<10}: n_filas={m['n_filas']:>5,}  skus={m['n_skus']:>4}  real={m['real']:>8,.0f} ({share_vol_a:5.1f}% A)  WAPE={m['wape_%']:>6.2f}%  BIAS={m['bias_%']:>+7.2f}%  ae={m['ae']:>7,.0f} ({share_ae_a:5.1f}% ae_A)")


# ----------------------------------------------------------------------
# 3. CRUCE XYZ x ZONA dentro de A
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. DENTRO DE A: cruce XYZ x ZONA actual (donde estan los SKUs?)")
print("=" * 100)
sku_a = a.groupby("product_id", as_index=False).agg(
    xyz_letter=("xyz_letter", "first"),
    forecast_zone=("forecast_zone", "first"),
    real=("real_qty", "sum"),
    ae=("abs_error_qty", "sum"),
)
print(f"\nMatriz: filas=XYZ, columnas=zona (cuenta de SKUs)")
print(pd.crosstab(sku_a["xyz_letter"], sku_a["forecast_zone"], margins=True).to_string())

print(f"\nMatriz volumen real (3 sem) por XYZ x ZONA en A:")
pivot_real = sku_a.pivot_table(index="xyz_letter", columns="forecast_zone", values="real", aggfunc="sum", fill_value=0).round(0)
print(pivot_real.to_string(float_format=lambda x: f"{x:,.0f}"))


# ----------------------------------------------------------------------
# 4. TOP 30 SKUs A CON MAS ERROR ABSOLUTO
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. TOP 30 SKUs A — donde concentrar la atencion (mayor abs_err)")
print("=" * 100)
sku_a_agg = a.groupby("product_id", as_index=False).agg(
    abcxyz=("abcxyz", "first"),
    forecast_zone=("forecast_zone", "first"),
    ciclo=("ciclo_de_vida", "first"),
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    ae=("abs_error_qty", "sum"),
    categ=("categ_id", "first"),
)
sku_a_agg["ratio_fcst_real"] = sku_a_agg["forecast"] / sku_a_agg["real"].replace(0, np.nan)
sku_a_agg["direccion"] = np.where(sku_a_agg["forecast"] > sku_a_agg["real"], "OVER",
                                   np.where(sku_a_agg["forecast"] < sku_a_agg["real"], "UNDER", "EQ"))
top30 = sku_a_agg.sort_values("ae", ascending=False).head(30)
print(top30[["product_id", "abcxyz", "forecast_zone", "ciclo", "real", "forecast", "ratio_fcst_real", "direccion", "ae"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 5. A POR CATEGORIA L2 (top 15 por error absoluto)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. A POR CATEGORIA L2 (top 15 por abs_err)")
print("=" * 100)
cat_a = a.groupby("categ_id", as_index=False).agg(
    n_skus=("product_id", "nunique"),
    n_filas=("real_qty", "size"),
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    ae=("abs_error_qty", "sum"),
    e=("error_qty", "sum"),
)
cat_a["WAPE_%"] = (cat_a["ae"] / cat_a["real"] * 100).round(1)
cat_a["BIAS_%"] = (cat_a["e"] / cat_a["real"] * 100).round(1)
cat_a["share_ae_A_%"] = (cat_a["ae"] / ae_a * 100).round(1)
top_cat = cat_a.sort_values("ae", ascending=False).head(15)
print(top_cat[["categ_id", "n_skus", "real", "forecast", "WAPE_%", "BIAS_%", "ae", "share_ae_A_%"]].to_string(index=False))


# ----------------------------------------------------------------------
# 6. DIRECCION DEL ERROR EN A
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. DIRECCION DEL ERROR EN A")
print("=" * 100)
a_sold = a[a["real_qty"] > 0].copy()
n_sold = len(a_sold)
over = a_sold[a_sold["forecast_qty"] > a_sold["real_qty"]]
under = a_sold[a_sold["forecast_qty"] < a_sold["real_qty"]]
equal = a_sold[a_sold["forecast_qty"] == a_sold["real_qty"]]
print(f"\nFilas con venta>0: {n_sold:,}")
print(f"  Over-forecast:   {len(over):>5,} ({len(over)/n_sold*100:5.1f}%)  ae={over['abs_error_qty'].sum():>9,.0f} ({over['abs_error_qty'].sum()/ae_a*100:5.1f}% del ae_A)")
print(f"  Under-forecast:  {len(under):>5,} ({len(under)/n_sold*100:5.1f}%)  ae={under['abs_error_qty'].sum():>9,.0f} ({under['abs_error_qty'].sum()/ae_a*100:5.1f}% del ae_A)")
print(f"  Forecast = real: {len(equal):>5,}")

a_no_sale = a[a["real_qty"] == 0]
n_no_sale = len(a_no_sale)
n_no_sale_fcst_pos = (a_no_sale["forecast_qty"] > 0).sum()
print(f"\nFilas sin venta (real=0): {n_no_sale:,}")
print(f"  Con forecast>0 (over puro): {n_no_sale_fcst_pos:,} ({n_no_sale_fcst_pos/n_no_sale*100:.1f}%)  ae={a_no_sale[a_no_sale['forecast_qty']>0]['abs_error_qty'].sum():,.0f}")


# ----------------------------------------------------------------------
# 7. RESUMEN DEL PROBLEMA EN A
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("7. RESUMEN DEL PROBLEMA EN A")
print("=" * 100)
print(f"""
  PROBLEMA: en 540 SKUs A (82.6% del volumen), motor actual da:
    - WAPE {m_a['wape_%']:.2f}%
    - BIAS {m_a['bias_%']:+.2f}% (casi centrado a nivel agregado)
    - abs_err total: {m_a['ae']:,.0f} unidades en 3 semanas

  DONDE SE CONCENTRA EL ERROR:
""")
# Concentracion
for xyz in ['X', 'Y', 'Z']:
    sub = a[a["xyz_letter"] == xyz]
    m = metrics(sub)
    if m['real'] > 0:
        print(f"    A{xyz}: {m['ae']/ae_a*100:5.1f}% del abs_err A (BIAS {m['bias_%']:+.2f}%)")

print("\nDONE.")
