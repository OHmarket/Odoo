"""Vista detallada del backtest file 12 (v3.30): forecast=0+real, AXY rescue,
P3 suavizado, foco en metricas operacionales y de servicio."""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (12).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")
df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
df = df[(df["method"] == "hm_si") & (df["target_week_start"].isin(weeks))].copy()
df["forecast_qty"] = df["forecast_qty"].astype(float)
df["real_qty"] = df["real_qty"].astype(float)
df["abs_err"] = df["abs_error_qty"].astype(float)
df["err"] = df["error_qty"].astype(float)

real_total = df["real_qty"].sum()
fcast_total = df["forecast_qty"].sum()
abs_err_total = df["abs_err"].sum()

print(f"\nSemanas medidas: {[str(w)[:10] for w in weeks]}")
print(f"Total filas hm_si: {len(df):,}")
print(f"Real:     {real_total:>10,.0f}")
print(f"Forecast: {fcast_total:>10,.0f}")
print(f"BIAS:     {(fcast_total-real_total)/real_total*100:>+10.2f}%")
print(f"WAPE:     {abs_err_total/real_total*100:>10.2f}%")

# ============ SUB-FORECAST vs OVER-FORECAST ============
print("\n" + "=" * 90)
print("DISTRIBUCION SUB-FORECAST vs OVER-FORECAST")
print("=" * 90)
mask_sub = df["err"] < 0
mask_over = df["err"] > 0
mask_exact = df["err"] == 0
print(f"  Sub-forecast (forecast < real): {mask_sub.sum():>7,} filas, error neto {df[mask_sub]['err'].sum():>+10,.0f}")
print(f"  Over-forecast (forecast > real): {mask_over.sum():>7,} filas, error neto {df[mask_over]['err'].sum():>+10,.0f}")
print(f"  Exacto (forecast = real):        {mask_exact.sum():>7,} filas")

# Cuanto del sub-forecast vino de filas que NO tienen forecast
mask_fcast_zero_real = (df["forecast_qty"] <= 0.001) & (df["real_qty"] > 0)
print(f"\n  Sub-forecast por forecast=0: {mask_fcast_zero_real.sum():>5,} filas, real perdido {df[mask_fcast_zero_real]['real_qty'].sum():>+10,.0f}")
print(f"  Sub-forecast resto:           {(mask_sub & ~mask_fcast_zero_real).sum():>5,} filas, error neto {df[mask_sub & ~mask_fcast_zero_real]['err'].sum():>+10,.0f}")

# ============ Por importancia (volumen) ============
print("\n" + "=" * 90)
print("POR IMPORTANCIA ABC (LETRA INICIAL)")
print("=" * 90)
df["abc_letter"] = df["abcxyz"].astype(str).str[0]
print(f"{'abc':<5} {'n':>7} {'real':>10} {'%vol':>6} {'BIAS%':>8} {'WAPE%':>8} {'fcast=0+real':>14}")
print("-" * 80)
for abc in sorted(df["abc_letter"].dropna().unique()):
    sub = df[df["abc_letter"] == abc]
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    e = sub["abs_err"].sum()
    z = ((sub["forecast_qty"] <= 0.001) & (sub["real_qty"] > 0)).sum()
    print(f"{abc:<5} {len(sub):>7,} {r:>10,.0f} {r/real_total*100:>5.1f}% {(f-r)/r*100 if r > 0 else 0:>+8.2f} {e/r*100 if r > 0 else 0:>8.2f} {z:>14,}")

# ============ TOP CATEGORIAS (volumen) por WAPE ============
print("\n" + "=" * 90)
print("TOP 15 CATEGORIAS POR VOLUMEN REAL")
print("=" * 90)
print(f"{'categ':<55} {'n':>6} {'real':>9} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 100)
agg_cat = df.groupby("categ_id").agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcast=("forecast_qty", "sum"),
    abs_err=("abs_err", "sum"),
).reset_index().sort_values("real", ascending=False).head(15)
agg_cat["bias"] = (agg_cat["fcast"] - agg_cat["real"]) / agg_cat["real"].replace(0, np.nan) * 100
agg_cat["wape"] = agg_cat["abs_err"] / agg_cat["real"].replace(0, np.nan) * 100
for _, r in agg_cat.iterrows():
    cat_name = str(r["categ_id"])[:53]
    print(f"{cat_name:<55} {r['n']:>6,} {r['real']:>9,.0f} {r['bias']:>+8.2f} {r['wape']:>8.2f}")

# ============ Por regimen ============
print("\n" + "=" * 90)
print("POR REGIMEN")
print("=" * 90)
print(f"{'regimen':<10} {'n':>7} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 60)
for rg in sorted(df["regimen"].dropna().unique()):
    sub = df[df["regimen"] == rg]
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    e = sub["abs_err"].sum()
    print(f"{str(rg):<10} {len(sub):>7,} {r:>10,.0f} {(f-r)/r*100 if r > 0 else 0:>+8.2f} {e/r*100 if r > 0 else 0:>8.2f}")

# ============ Por forecast_model_code ============
print("\n" + "=" * 90)
print("POR MODELO APLICADO (forecast_model_code)")
print("=" * 90)
print(f"{'modelo':<35} {'n':>7} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 80)
for mc in sorted(df["forecast_model_code"].dropna().unique()):
    sub = df[df["forecast_model_code"] == mc]
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    e = sub["abs_err"].sum()
    print(f"{str(mc)[:33]:<35} {len(sub):>7,} {r:>10,.0f} {(f-r)/r*100 if r > 0 else 0:>+8.2f} {e/r*100 if r > 0 else 0:>8.2f}")

# ============ Top 15 errores absolutos (outliers) ============
print("\n" + "=" * 90)
print("TOP 15 SKUs CON MAYOR |error| TOTAL (suma 3 semanas)")
print("=" * 90)
print(f"{'producto':<55} {'real':>6} {'fcast':>6} {'abs_err':>8} {'BIAS%':>7}")
print("-" * 100)
top = df.groupby("product_id").agg(
    real=("real_qty", "sum"),
    fcast=("forecast_qty", "sum"),
    abs_err=("abs_err", "sum"),
).reset_index().sort_values("abs_err", ascending=False).head(15)
top["bias"] = (top["fcast"] - top["real"]) / top["real"].replace(0, np.nan) * 100
for _, r in top.iterrows():
    name = str(r["product_id"])[:53]
    print(f"{name:<55} {r['real']:>6,.0f} {r['fcast']:>6,.0f} {r['abs_err']:>8,.0f} {r['bias']:>+7.1f}")
