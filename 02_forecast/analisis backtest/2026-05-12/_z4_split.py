"""Analisis de la zona Z4 en file 2 (v3.31).
Dividir Z4 en dos grupos:
  A) forecast_qty == 0 (no pronostico): cuanto real perdimos?
  B) forecast_qty > 0 (si pronostico): cuanto erramos?
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (2).csv"

df = pd.read_csv(PATH)
df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
df = df[df["target_week_start"].isin(weeks)].copy()
df["forecast_qty"] = df["forecast_qty"].astype(float)
df["real_qty"] = df["real_qty"].astype(float)
df["abs_err"] = df["abs_error_qty"].astype(float)

z4 = df[df["forecast_zone"] == "Z4"].copy()
real_total = df["real_qty"].sum()

print(f"Universo total hm_si W17-W19: {len(df):,} filas, real {real_total:,.0f}")
print(f"Universo Z4:                  {len(z4):,} filas ({len(z4)/len(df)*100:.1f}%)")
print(f"Real Z4:                      {z4['real_qty'].sum():,.0f} ({z4['real_qty'].sum()/real_total*100:.2f}% del total)")

# ============ SPLIT ============
z4_zero = z4[z4["forecast_qty"] <= 0.001]
z4_pos  = z4[z4["forecast_qty"] > 0.001]

def _wb(df_sub):
    f, r, e = df_sub["forecast_qty"].sum(), df_sub["real_qty"].sum(), df_sub["abs_err"].sum()
    return f, r, e, (f-r)/r*100 if r > 0 else 0, e/r*100 if r > 0 else 0

print("\n" + "=" * 90)
print("Z4 SPLIT")
print("=" * 90)
print(f"{'grupo':<30} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 80)
for k, sub in [("Z4 forecast=0", z4_zero), ("Z4 forecast>0", z4_pos), ("Z4 TOTAL", z4)]:
    f, r, e, b, w = _wb(sub)
    print(f"{k:<30} {len(sub):>8,} {f:>10,.0f} {r:>10,.0f} {b:>+8.2f} {w:>8.2f}")

# ============ Z4 forecast=0: cuanto sub-forecast es? ============
print("\n" + "=" * 90)
print("Z4 forecast=0 -- sub-forecast por defecto del router")
print("=" * 90)
mask_real = z4_zero["real_qty"] > 0
sub_real = z4_zero[mask_real]
print(f"  Filas con forecast=0:       {len(z4_zero):,}")
print(f"     ... con real_qty == 0:  {(~mask_real).sum():,} ({(~mask_real).sum()/len(z4_zero)*100:.1f}%)  (motor acerto)")
print(f"     ... con real_qty > 0:   {mask_real.sum():,} ({mask_real.sum()/len(z4_zero)*100:.1f}%)  (sub-forecast)")
print(f"  Real perdido en Z4 forecast=0: {sub_real['real_qty'].sum():,.0f}")
print(f"     mean real por fila perdida: {sub_real['real_qty'].mean():.2f}" if len(sub_real) else "")

print("\nDistribucion de real_qty en filas Z4 forecast=0 con ventas:")
for lo, hi in [(0.5, 1.5), (1.5, 3), (3, 5), (5, 10), (10, 1000)]:
    n = ((sub_real["real_qty"] >= lo) & (sub_real["real_qty"] < hi)).sum()
    s = sub_real[(sub_real["real_qty"] >= lo) & (sub_real["real_qty"] < hi)]["real_qty"].sum()
    print(f"  real in [{lo:>4}, {hi:>4}):  {n:>5} filas, {s:>6,.0f} unid")

# ============ Z4 forecast>0: que pasa? ============
print("\n" + "=" * 90)
print("Z4 forecast>0 -- el router NO anulo, motor pronostico algo")
print("=" * 90)
print(f"  Filas: {len(z4_pos):,}")
print(f"  Mean forecast por fila: {z4_pos['forecast_qty'].mean():.2f}")
print(f"  Max forecast: {z4_pos['forecast_qty'].max():.2f}")

# Por ABCXYZ
print("\nDistribucion Z4 forecast>0 por ABCXYZ:")
print(f"{'abcxyz':<8} {'n':>7} {'fcast':>8} {'real':>8} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 60)
for abc in sorted(z4_pos["abcxyz"].dropna().unique()):
    sub = z4_pos[z4_pos["abcxyz"] == abc]
    f, r, e, b, w = _wb(sub)
    print(f"{str(abc):<8} {len(sub):>7,} {f:>8,.0f} {r:>8,.0f} {b:>+8.2f} {w:>8.2f}")

# ============ Por lifecycle ============
print("\n" + "=" * 90)
print("Z4 forecast=0 -- por lifecycle (para entender si son discontinuos)")
print("=" * 90)
print(f"{'lifecycle':<20} {'n_filas':>8} {'real_total':>12} {'real_perdido_>0':>16}")
print("-" * 70)
for lc in sorted(z4_zero["ciclo_de_vida"].dropna().unique()):
    sub = z4_zero[z4_zero["ciclo_de_vida"] == lc]
    sub_perd = sub[sub["real_qty"] > 0]
    print(f"{str(lc)[:18]:<20} {len(sub):>8,} {sub['real_qty'].sum():>12,.0f} {sub_perd['real_qty'].sum():>16,.0f}")

# ============ Top SKUs perdidos en Z4 forecast=0 ============
print("\n" + "=" * 90)
print("TOP 15 SKUs Z4 forecast=0 con mayor real perdido")
print("=" * 90)
top = sub_real.groupby("product_id").agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
).reset_index().sort_values("real", ascending=False).head(15)
print(top.to_string(index=False))

# ============ Top SKUs en Z4 forecast>0 con mayor abs_err ============
print("\n" + "=" * 90)
print("TOP 15 SKUs Z4 forecast>0 con mayor abs_err (over o under forecast)")
print("=" * 90)
top_pos = z4_pos.groupby("product_id").agg(
    n=("forecast_qty", "size"),
    fcast=("forecast_qty", "sum"),
    real=("real_qty", "sum"),
    abs_err=("abs_err", "sum"),
).reset_index()
top_pos["bias"] = (top_pos["fcast"] - top_pos["real"]) / top_pos["real"].replace(0, np.nan) * 100
top_pos = top_pos.sort_values("abs_err", ascending=False).head(15)
print(top_pos.to_string(index=False))
