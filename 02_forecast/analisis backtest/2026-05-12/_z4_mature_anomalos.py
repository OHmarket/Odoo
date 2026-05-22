"""Investigar los SKUs Z4 mature con forecast=0 pero real>=5 unid/sem."""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (2).csv"

df = pd.read_csv(PATH)
df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
df = df[df["target_week_start"].isin(weeks)].copy()
df["forecast_qty"] = df["forecast_qty"].astype(float)
df["real_qty"] = df["real_qty"].astype(float)

# Filtro Z4 + forecast=0 + real>=5
anomalos = df[
    (df["forecast_zone"] == "Z4") &
    (df["forecast_qty"] <= 0.001) &
    (df["real_qty"] >= 5) &
    (df["ciclo_de_vida"] == "mature")
].copy()

print(f"Filas Z4 mature forecast=0 con real>=5: {len(anomalos):,}")
print(f"Real total perdido en este grupo: {anomalos['real_qty'].sum():,.0f}")

# Por ABCXYZ
print("\n" + "=" * 80)
print("POR ABCXYZ")
print("=" * 80)
print(f"{'abcxyz':<8} {'n':>5} {'real_sum':>10} {'avg_real':>10} {'max_real':>10}")
print("-" * 60)
for abc, sub in anomalos.groupby("abcxyz"):
    print(f"{str(abc):<8} {len(sub):>5,} {sub['real_qty'].sum():>10,.0f} {sub['real_qty'].mean():>10.2f} {sub['real_qty'].max():>10.0f}")

# Por regimen
print("\n" + "=" * 80)
print("POR REGIMEN")
print("=" * 80)
print(f"{'regimen':<12} {'n':>5} {'real_sum':>10}")
print("-" * 50)
if "regimen" in anomalos.columns:
    for rg, sub in anomalos.groupby("regimen"):
        print(f"{str(rg):<12} {len(sub):>5,} {sub['real_qty'].sum():>10,.0f}")
else:
    print("Columna regimen no esta en el CSV.")

# Por series_type
print("\n" + "=" * 80)
print("POR SERIES_TYPE")
print("=" * 80)
print(f"{'series_type':<15} {'n':>5} {'real_sum':>10}")
print("-" * 50)
for st, sub in anomalos.groupby("series_type"):
    print(f"{str(st):<15} {len(sub):>5,} {sub['real_qty'].sum():>10,.0f}")

# Top SKUs especificos
print("\n" + "=" * 100)
print("TODOS LOS SKUs ANOMALOS (Z4 mature forecast=0, real>=5)")
print("=" * 100)
print(f"{'producto':<70} {'abcxyz':<6} {'series':<10} {'real':>5}")
print("-" * 100)
for _, r in anomalos.sort_values("real_qty", ascending=False).iterrows():
    name = str(r["product_id"])[:68]
    print(f"{name:<70} {str(r['abcxyz']):<6} {str(r['series_type'])[:10]:<10} {r['real_qty']:>5.0f}")

# Tambien revisar agrupado por product_id (suma de 3 sem)
print("\n" + "=" * 100)
print("AGRUPADO POR product_id (suma 3 sem) - mismos SKUs anomalos")
print("=" * 100)
agg = anomalos.groupby(["product_id", "abcxyz", "series_type"]).agg(
    n_team_weeks=("real_qty", "size"),
    real_sum=("real_qty", "sum"),
).reset_index().sort_values("real_sum", ascending=False)
print(agg.to_string(index=False))
