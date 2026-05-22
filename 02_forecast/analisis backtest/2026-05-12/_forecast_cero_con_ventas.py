"""Analizar filas del backtest con forecast=0 pero real>0.

Bucket forecast=0 con ventas reales = sub-forecast severo.
Tipicamente proviene de:
  - P1 (declining/dead)
  - P3 (Z4 + nz_recent<=1)
  - Router Z4 con mu_week < 2.0 colapsado
  - mu_base = 0 por historia plana

Para cada filtro, contamos n, sum(real), volumen perdido y bucket.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (11).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")
df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
df = df[(df["method"] == "hm_si") & (df["target_week_start"].isin(weeks))].copy()

df["forecast_qty"] = df["forecast_qty"].astype(float)
df["real_qty"] = df["real_qty"].astype(float)

# Bucket: forecast=0 con ventas reales
mask_zero_fcast = df["forecast_qty"] <= 0.001
mask_real = df["real_qty"] > 0
problemas = df[mask_zero_fcast & mask_real]

print("=" * 90)
print("FILAS CON forecast=0 PERO real>0")
print("=" * 90)
print(f"  Total filas hm_si:        {len(df):,}")
print(f"  Filas forecast=0:         {(mask_zero_fcast).sum():,}")
print(f"  Filas forecast=0 + real>0: {len(problemas):,}  ({len(problemas)/len(df)*100:.1f}% del total)")
print(f"  Real perdido (no pronosticado): {problemas['real_qty'].sum():,.0f} unidades")
print(f"  Real total backtest:       {df['real_qty'].sum():,.0f}")
print(f"  Volumen perdido / total:   {problemas['real_qty'].sum() / df['real_qty'].sum() * 100:.2f}%")

# ==== Por zone ====
print("\n" + "=" * 90)
print("POR FORECAST_ZONE")
print("=" * 90)
print(f"{'zone':<6} {'n':>7} {'real_sum':>10}  {'avg_real':>9}")
print("-" * 50)
for z, sub in problemas.groupby("forecast_zone"):
    print(f"{str(z):<6} {len(sub):>7,} {sub['real_qty'].sum():>10,.0f}  {sub['real_qty'].mean():>9.2f}")

# ==== Por ABCXYZ ====
print("\n" + "=" * 90)
print("POR ABCXYZ")
print("=" * 90)
print(f"{'abc':<6} {'n':>7} {'real_sum':>10} {'avg_real':>9} {'%vol_perd':>10}")
print("-" * 60)
vol_total_class = df.groupby("abcxyz")["real_qty"].sum()
for abc, sub in problemas.groupby("abcxyz"):
    real_lost = sub["real_qty"].sum()
    vol_class = vol_total_class.get(abc, 1)
    print(f"{str(abc):<6} {len(sub):>7,} {real_lost:>10,.0f} {sub['real_qty'].mean():>9.2f} {real_lost/vol_class*100:>9.1f}%")

# ==== Por lifecycle ====
print("\n" + "=" * 90)
print("POR CICLO_DE_VIDA")
print("=" * 90)
print(f"{'lifecycle':<20} {'n':>7} {'real_sum':>10}")
print("-" * 50)
for lc, sub in problemas.groupby("ciclo_de_vida"):
    print(f"{str(lc)[:20]:<20} {len(sub):>7,} {sub['real_qty'].sum():>10,.0f}")

# ==== Por regimen ====
print("\n" + "=" * 90)
print("POR REGIMEN")
print("=" * 90)
print(f"{'regimen':<12} {'n':>7} {'real_sum':>10}")
print("-" * 50)
for rg, sub in problemas.groupby("regimen"):
    print(f"{str(rg):<12} {len(sub):>7,} {sub['real_qty'].sum():>10,.0f}")

# ==== Cruce zone × abcxyz (heatmap) ====
print("\n" + "=" * 90)
print("CRUCE zone × abcxyz (cantidad de filas con problema)")
print("=" * 90)
piv = problemas.pivot_table(index="abcxyz", columns="forecast_zone", values="real_qty",
                             aggfunc="count", fill_value=0)
print(piv)
print("\nReal perdido por cruce (suma de unidades):")
piv2 = problemas.pivot_table(index="abcxyz", columns="forecast_zone", values="real_qty",
                              aggfunc="sum", fill_value=0)
print(piv2.round(0).astype(int))

# ==== Top 20 SKUs con mayor perdida ====
print("\n" + "=" * 90)
print("TOP 20 SKUs con MAYOR pérdida (sum de real cuando forecast=0)")
print("=" * 90)
top_sku = problemas.groupby("product_id").agg(
    n=("real_qty", "size"),
    real_lost=("real_qty", "sum"),
).reset_index()
top_sku = top_sku.sort_values("real_lost", ascending=False).head(20)
top_sku["product_id"] = top_sku["product_id"].astype(str).str[:55]
print(top_sku.to_string(index=False))
