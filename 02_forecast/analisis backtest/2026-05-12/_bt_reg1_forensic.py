"""
Forensic dentro de REG-1: donde se dispara el error?

REG-1 global (file 10): WAPE 60.31%, BIAS +1.85%. n=16,845 SKUs (78.1% volumen).

Hipotesis a verificar:
  1. Z1 (mu>=2) vs Z4 (mu<2) dentro de REG-1: muy distinto?
  2. AX vs AY vs BX dentro de REG-1: alguno empeora?
  3. mature vs ramp_up dentro de REG-1: ramp_up es el problema?
  4. Concentracion: cuantos SKUs aportan el grueso del abs_err?
  5. Categoria L2: hay categorias problema?
  6. Distribucion de WAPE individual: cola larga o caso general?
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
r1 = hm[hm["regimen"] == "REG-1"].copy()

print("=" * 100)
print(f"REG-1 FORENSIC  |  n={len(r1):,}  |  real={r1['real_qty'].sum():,.0f}  |  fcst={r1['forecast_qty'].sum():,.0f}")
ae_total = r1["abs_error_qty"].sum()
e_total = r1["error_qty"].sum()
real_total = r1["real_qty"].sum()
print(f"WAPE: {ae_total/real_total*100:.2f}%   BIAS: {e_total/real_total*100:+.2f}%")
print("=" * 100)


def metrics_row(sub, label):
    n = len(sub)
    real = sub["real_qty"].sum()
    fcst = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return {
        "segmento": label,
        "n": n,
        "share_n_%": n / len(r1) * 100,
        "real": real,
        "share_real_%": real / real_total * 100 if real_total > 0 else 0,
        "forecast": fcst,
        "wape_%": (ae / real * 100) if real > 0 else np.nan,
        "bias_%": (e / real * 100) if real > 0 else np.nan,
        "share_ae_%": ae / ae_total * 100 if ae_total > 0 else 0,
    }


# ----------------------------------------------------------------------
# 1. POR FORECAST_ZONE (Z1 vs Z4: la division por mu_week)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("1. REG-1 POR FORECAST_ZONE (Z1=mu>=2 vs Z4=mu<2)")
print("=" * 100)
rows = []
for z in sorted(r1["forecast_zone"].dropna().unique()):
    sub = r1[r1["forecast_zone"] == z]
    rows.append(metrics_row(sub, f"forecast_zone={z}"))
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 2. POR ABCXYZ
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. REG-1 POR ABCXYZ")
print("=" * 100)
rows = []
for abc in sorted(r1["abcxyz"].dropna().unique()):
    sub = r1[r1["abcxyz"] == abc]
    rows.append(metrics_row(sub, f"abcxyz={abc}"))
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 3. POR CICLO DE VIDA
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. REG-1 POR CICLO DE VIDA")
print("=" * 100)
rows = []
for lc in sorted(r1["ciclo_de_vida"].dropna().unique()):
    sub = r1[r1["ciclo_de_vida"] == lc]
    rows.append(metrics_row(sub, f"lifecycle={lc}"))
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 4. CRUCE ABCXYZ × FORECAST_ZONE
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. REG-1 CRUCE ABCXYZ x FORECAST_ZONE (count de SKUs)")
print("=" * 100)
ct = pd.crosstab(r1["abcxyz"], r1["forecast_zone"], dropna=False)
print(ct.to_string())


# ----------------------------------------------------------------------
# 5. CONCENTRACION DEL ERROR — cuantos SKUs aportan el grueso del abs_err?
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. CONCENTRACION DEL ERROR (top N SKUs concentran que % del abs_err)")
print("=" * 100)
sku_agg = r1.groupby("product_id", as_index=False).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    ae=("abs_error_qty", "sum"),
    e=("error_qty", "sum"),
)
sku_agg = sku_agg.sort_values("ae", ascending=False)
total_skus = len(sku_agg)
for n in [10, 25, 50, 100, 250, 500]:
    if n > total_skus:
        break
    top_ae = sku_agg.head(n)["ae"].sum()
    print(f"  Top {n:>4} SKUs / {total_skus:,}: {top_ae/ae_total*100:5.1f}% del abs_err total ({top_ae:,.0f} / {ae_total:,.0f})")


# ----------------------------------------------------------------------
# 6. TOP 20 SKUs PROBLEMATICOS EN REG-1
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. TOP 20 SKUs CON MAS ABS_ERR EN REG-1")
print("=" * 100)
top20 = sku_agg.head(20).copy()
top20["wape_%"] = top20.apply(lambda x: x["ae"]/x["real"]*100 if x["real"] > 0 else np.nan, axis=1)
top20["ratio_fcst_real"] = top20.apply(lambda x: x["forecast"]/x["real"] if x["real"] > 0 else np.nan, axis=1)
# Para cada top, mostrar abcxyz y zone y categoria
detalles = r1.groupby("product_id").agg(
    abcxyz=("abcxyz", "first"),
    forecast_zone=("forecast_zone", "first"),
    ciclo_de_vida=("ciclo_de_vida", "first"),
    categ_id=("categ_id", "first"),
).reset_index()
top20 = top20.merge(detalles, on="product_id", how="left")
cols = ["product_id", "abcxyz", "forecast_zone", "ciclo_de_vida", "real", "forecast", "ae", "wape_%", "ratio_fcst_real"]
print(top20[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 7. POR CATEGORIA L2 — agrupar por categ_id (top 15)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("7. REG-1 POR CATEGORIA (top 15 por abs_err)")
print("=" * 100)
cat_agg = r1.groupby("categ_id", as_index=False).agg(
    n_filas=("real_qty", "size"),
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    ae=("abs_error_qty", "sum"),
    e=("error_qty", "sum"),
)
cat_agg["wape_%"] = cat_agg.apply(lambda x: x["ae"]/x["real"]*100 if x["real"] > 0 else np.nan, axis=1)
cat_agg["bias_%"] = cat_agg.apply(lambda x: x["e"]/x["real"]*100 if x["real"] > 0 else np.nan, axis=1)
cat_agg["share_ae_%"] = cat_agg["ae"] / ae_total * 100
cat_top = cat_agg.sort_values("ae", ascending=False).head(15)
print(cat_top.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 8. POR PRICE_DYNAMICS_SEGMENT
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("8. REG-1 POR PRICE_DYNAMICS_SEGMENT")
print("=" * 100)
if "price_dynamics_segment" in r1.columns:
    rows = []
    for ps in sorted(r1["price_dynamics_segment"].dropna().unique()):
        sub = r1[r1["price_dynamics_segment"] == ps]
        rows.append(metrics_row(sub, f"price={ps}"))
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
else:
    print("  (price_dynamics_segment no esta en columnas)")


# ----------------------------------------------------------------------
# 9. DIRECCION DE ERROR — over vs under forecast en REG-1
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("9. REG-1 DIRECCION DE ERROR (over vs under forecast)")
print("=" * 100)
r1_sold = r1[r1["real_qty"] > 0].copy()
r1_sold["over"] = r1_sold["forecast_qty"] > r1_sold["real_qty"]
r1_sold["under"] = r1_sold["forecast_qty"] < r1_sold["real_qty"]
r1_sold["zero"] = r1_sold["forecast_qty"] == 0
n_sold = len(r1_sold)
n_over = r1_sold["over"].sum()
n_under = r1_sold["under"].sum()
n_zero = r1_sold["zero"].sum()
print(f"  Total filas con venta>0: {n_sold:,}")
print(f"    over-forecast:   {n_over:,} ({n_over/n_sold*100:.1f}%)  abs_err contribuido: {r1_sold[r1_sold['over']]['abs_error_qty'].sum()/ae_total*100:.1f}%")
print(f"    under-forecast:  {n_under:,} ({n_under/n_sold*100:.1f}%)  abs_err contribuido: {r1_sold[r1_sold['under']]['abs_error_qty'].sum()/ae_total*100:.1f}%")
print(f"    forecast=0 con venta>0: {n_zero:,} ({n_zero/n_sold*100:.1f}%) [under puro]")
print(f"  Filas sin venta (real=0):")
sin_venta = r1[r1["real_qty"] == 0]
print(f"    Total: {len(sin_venta):,}")
print(f"    Con forecast>0 (over puro): {(sin_venta['forecast_qty']>0).sum():,}")

print("\nDONE.")
