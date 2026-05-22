"""
Mapa de percentiles de volumen de ventas (file 10).

Para entender:
  1. Como se distribuye el volumen real entre SKUs
  2. Donde queda el corte 2.0 unid/sem en la distribucion empirica
  3. Si hay cortes naturales que justifiquen otros thresholds
  4. Top 500 SKUs (los heavyweight del negocio)
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

# Agregar por SKU (suma sobre 3 semanas y 12 teams)
sku_agg = hm.groupby("product_id", as_index=False).agg(
    n_filas=("real_qty", "size"),  # filas en backtest (team x semana)
    real_total_3sem=("real_qty", "sum"),
    forecast_total_3sem=("forecast_qty", "sum"),
    ae_total=("abs_error_qty", "sum"),
    regimen=("regimen", "first"),
    abcxyz=("abcxyz", "first"),
    forecast_zone=("forecast_zone", "first"),
    lifecycle=("ciclo_de_vida", "first"),
    categ_id=("categ_id", "first"),
)

# Metricas derivadas
sku_agg["unid_por_semana_team"] = sku_agg["real_total_3sem"] / sku_agg["n_filas"]  # mu_week per team
sku_agg["unid_por_semana_global"] = sku_agg["real_total_3sem"] / 3  # total semanal del SKU sumando 12 teams

print("=" * 100)
print(f"UNIVERSO: {len(sku_agg):,} SKUs unicos en backtest hm_si (3 semanas x 12 teams)")
print(f"Total real: {sku_agg['real_total_3sem'].sum():,.0f} unidades en 3 semanas")
print("=" * 100)


# ----------------------------------------------------------------------
# 1. PERCENTILES DE mu_week_per_team (que es lo que ve el motor)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("1. PERCENTILES de unidades por semana POR TEAM (lo que ve el motor)")
print("=" * 100)
mu_pt = sku_agg["unid_por_semana_team"]
percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99, 99.5]
print(f"{'percentil':<12} {'mu_week_team':>15}")
print("-" * 30)
for p in percentiles:
    v = np.percentile(mu_pt, p)
    print(f"  p{p:<5}    {v:>15.4f}")
print(f"  max       {mu_pt.max():>15.4f}")
print(f"  mean      {mu_pt.mean():>15.4f}")

# Donde queda el 2.0?
above_2 = (mu_pt >= 2.0).sum()
above_1 = (mu_pt >= 1.0).sum()
above_05 = (mu_pt >= 0.5).sum()
above_01 = (mu_pt >= 0.1).sum()
total_skus = len(sku_agg)
print(f"\n  SKUs con mu_week_team >= 0.1: {above_01:,} ({above_01/total_skus*100:.1f}%)")
print(f"  SKUs con mu_week_team >= 0.5: {above_05:,} ({above_05/total_skus*100:.1f}%)")
print(f"  SKUs con mu_week_team >= 1.0: {above_1:,} ({above_1/total_skus*100:.1f}%)")
print(f"  SKUs con mu_week_team >= 2.0: {above_2:,} ({above_2/total_skus*100:.1f}%) <- THRESHOLD ACTUAL")


# ----------------------------------------------------------------------
# 2. PERCENTILES de volumen GLOBAL (suma 12 teams, 1 semana)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. PERCENTILES de unidades GLOBALES por semana (sumando 12 teams)")
print("=" * 100)
mu_glo = sku_agg["unid_por_semana_global"]
print(f"{'percentil':<12} {'unid_semana_global':>20}")
print("-" * 35)
for p in percentiles:
    v = np.percentile(mu_glo, p)
    print(f"  p{p:<5}    {v:>20.2f}")
print(f"  max       {mu_glo.max():>20.2f}")


# ----------------------------------------------------------------------
# 3. CONCENTRACION DEL VOLUMEN (Pareto)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. CONCENTRACION DEL VOLUMEN — top N SKUs aportan que % del total?")
print("=" * 100)
sku_sorted = sku_agg.sort_values("real_total_3sem", ascending=False)
total_real = sku_sorted["real_total_3sem"].sum()
for n in [10, 25, 50, 100, 200, 500, 1000]:
    if n > len(sku_sorted):
        break
    top_real = sku_sorted.head(n)["real_total_3sem"].sum()
    print(f"  Top {n:>5} SKUs / {len(sku_sorted):,} ({n/len(sku_sorted)*100:5.1f}%): {top_real/total_real*100:5.1f}% del volumen real ({top_real:,.0f} unid)")


# ----------------------------------------------------------------------
# 4. BUCKETS DE VENTA POR SEMANA POR TEAM (la dimension operativa)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. BUCKETS DE unidades por semana POR TEAM (la dimension del motor)")
print("=" * 100)
buckets = [
    (0, 0.01, "0 (sin venta)"),
    (0.01, 0.5, "0-0.5 unid/sem"),
    (0.5, 1.0, "0.5-1 unid/sem"),
    (1.0, 2.0, "1-2 unid/sem"),
    (2.0, 5.0, "2-5 unid/sem (Z1 zone)"),
    (5.0, 10.0, "5-10 unid/sem"),
    (10.0, 25.0, "10-25 unid/sem"),
    (25.0, 100.0, "25-100 unid/sem"),
    (100.0, float('inf'), "100+ unid/sem"),
]
print(f"{'bucket':<25} {'n_SKUs':>8} {'share_n':>8} {'real_3sem':>12} {'share_real':>10}")
print("-" * 80)
for low, high, label in buckets:
    mask = (sku_agg["unid_por_semana_team"] >= low) & (sku_agg["unid_por_semana_team"] < high)
    sub = sku_agg[mask]
    n = len(sub)
    real_sub = sub["real_total_3sem"].sum()
    print(f"  {label:<23} {n:>8,} {n/total_skus*100:>7.1f}% {real_sub:>12,.0f} {real_sub/total_real*100:>9.1f}%")


# ----------------------------------------------------------------------
# 5. TOP 500 SKUs — distribucion por regimen
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. TOP 500 SKUs: distribucion por regimen")
print("=" * 100)
top500 = sku_sorted.head(500)
print(f"\n  Top 500 representa: {top500['real_total_3sem'].sum()/total_real*100:.1f}% del volumen real total")
print(f"  Top 500 = {len(top500)/total_skus*100:.1f}% de los SKUs unicos")

print("\n  Composicion por regimen del Top 500:")
for reg in sorted(top500["regimen"].dropna().unique()):
    sub = top500[top500["regimen"] == reg]
    print(f"    {reg}: {len(sub):>4} SKUs ({len(sub)/500*100:5.1f}%)  real={sub['real_total_3sem'].sum():>9,.0f}")

print("\n  Composicion por abcxyz del Top 500:")
for abc in sorted(top500["abcxyz"].dropna().unique()):
    sub = top500[top500["abcxyz"] == abc]
    print(f"    {abc}: {len(sub):>4} SKUs ({len(sub)/500*100:5.1f}%)  real={sub['real_total_3sem'].sum():>9,.0f}")


# ----------------------------------------------------------------------
# 6. TOP 20 SKUs con info completa
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. TOP 20 SKUs por ventas (3 semanas)")
print("=" * 100)
top20 = sku_sorted.head(20).copy()
top20["unid_sem_team"] = top20["unid_por_semana_team"].round(2)
top20["unid_sem_global"] = top20["unid_por_semana_global"].round(0)
top20["wape_%"] = (top20["ae_total"] / top20["real_total_3sem"] * 100).round(1)
cols = ["product_id", "regimen", "abcxyz", "forecast_zone", "real_total_3sem", "unid_sem_team", "unid_sem_global", "wape_%"]
print(top20[cols].to_string(index=False))


# ----------------------------------------------------------------------
# 7. ZONA Z1 vs Z4: distribucion de mu_week_team
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("7. mu_week_team POR forecast_zone (donde queda el threshold 2.0)")
print("=" * 100)
for z in ['Z1', 'Z2', 'Z3', 'Z4']:
    sub = sku_agg[sku_agg["forecast_zone"] == z]
    if len(sub) == 0:
        continue
    mu = sub["unid_por_semana_team"]
    print(f"\n  Zone {z}: n={len(sub):,} SKUs")
    print(f"    mu p10={np.percentile(mu, 10):.3f}  p50={np.percentile(mu, 50):.3f}  p90={np.percentile(mu, 90):.3f}  max={mu.max():.2f}")
    print(f"    mu mean={mu.mean():.3f}  median={mu.median():.3f}")

print("\nDONE.")
