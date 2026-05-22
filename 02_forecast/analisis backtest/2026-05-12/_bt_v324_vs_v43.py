"""
Comparativa directa HM-SI v3.24 vs v4.3-revert sobre la misma semana objetivo (2026-05-04).

Fuentes:
  - v3.24: CSV backtest historico cuando v3.24 estaba en runner
           (analisis backtest/2026-05-12/OH Forecast Backtest (x_forecast_backtest).csv)
  - v4.3-revert: XLSX actual filtrado al cutoff 2026-05-04
           (OH Forecast Backtest (x_forecast_backtest) (8).xlsx, method='hm_si')

Pregunta a responder:
  - v3.24 era mejor o peor que v4.3-revert sobre el MISMO conjunto de SKU-team-week?
  - El delta vs OLD se redujo o creció con el cambio?
"""
import pandas as pd
import numpy as np

CSV_V324 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\OH Forecast Backtest (x_forecast_backtest).csv"
XLSX_V43 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (8).xlsx"

TARGET_WEEK = "2026-05-04"

print("=" * 90)
print(f"COMPARATIVA HM-SI v3.24 vs v4.3-revert  |  target_week = {TARGET_WEEK}")
print("=" * 90)

# ----------------------------------------------------------------------
# 1. CARGA v3.24 (CSV) — solo hay HM-SI ahi, no OLD
# ----------------------------------------------------------------------
df324 = pd.read_csv(CSV_V324)
print(f"\nv3.24 CSV: {len(df324):,} filas | columnas: {len(df324.columns)}")
print(f"  target_week distintos: {df324['target_week_start'].nunique()}")
print(f"  forecast_zone unique: {sorted(df324['forecast_zone'].dropna().unique())}")

# Filtrar a la semana target
df324 = df324[df324["target_week_start"] == TARGET_WEEK].copy()
for c in ["real_qty", "forecast_qty", "error_qty", "abs_error_qty"]:
    df324[c] = pd.to_numeric(df324[c], errors="coerce").fillna(0.0)
print(f"  v3.24 filas en {TARGET_WEEK}: {len(df324):,}")

# ----------------------------------------------------------------------
# 2. CARGA v4.3-revert (XLSX) — filtrar a la misma semana
# ----------------------------------------------------------------------
df43_all = pd.read_excel(XLSX_V43, engine="openpyxl")
df43_all["target_week_start"] = pd.to_datetime(df43_all["target_week_start"]).dt.strftime("%Y-%m-%d")
df43 = df43_all[df43_all["target_week_start"] == TARGET_WEEK].copy()
for c in ["real_qty", "forecast_qty", "error_qty", "abs_error_qty"]:
    df43[c] = pd.to_numeric(df43[c], errors="coerce").fillna(0.0)
print(f"\nv4.3-revert XLSX filtrado a {TARGET_WEEK}: {len(df43):,} filas")
print(f"  methods presentes: {sorted(df43['method'].dropna().unique())}")
print(f"  forecast_zone unique: {sorted(df43['forecast_zone'].dropna().unique())[:8]}")

hm43 = df43[df43["method"] == "hm_si"].copy()
old43 = df43[df43["method"] == "old"].copy()
print(f"  hm_si: {len(hm43):,}  |  old: {len(old43):,}")

# ----------------------------------------------------------------------
# 3. METRICAS GLOBALES (sin pareo) — cada uno con sus filas propias
# ----------------------------------------------------------------------
def wape_bias(sub):
    r = sub["real_qty"].sum()
    if r <= 0: return (np.nan, np.nan, 0, 0)
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return (ae / r * 100, e / r * 100, r, sub["forecast_qty"].sum())

print("\n" + "=" * 90)
print("3. METRICAS GLOBALES (todas las filas del cutoff)")
print("=" * 90)
print(f"{'scenario':<25} {'n':>8} {'real':>10} {'forecast':>12} {'wape_%':>10} {'bias_%':>10}")
for name, sub in [("v3.24 HM-SI (CSV)", df324),
                  ("v4.3-revert hm_si", hm43),
                  ("v4.3-revert OLD (baseline)", old43)]:
    w, b, r, f = wape_bias(sub)
    if pd.notna(w):
        print(f"{name:<25} {len(sub):>8,} {r:>10,.0f} {f:>12,.0f} {w:>10.2f} {b:>+10.2f}")
    else:
        print(f"{name:<25} {len(sub):>8,}  (real=0, sin metrica)")

# ----------------------------------------------------------------------
# 4. PAREADO v3.24 vs v4.3-revert (mismo SKU-team-week)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("4. PAREADO v3.24 vs v4.3-revert (SKU-team-week comun)")
print("=" * 90)
# v3.24 usa team_id con nombre ("Ventas Panguipulli 790"); v4.3 usa id numerico.
# Para parear necesitamos llave consistente. Veamos:
print(f"\n  team_id v3.24 sample: {df324['team_id'].iloc[0]!r}")
print(f"  team_id v4.3 sample:  {hm43['team_id'].iloc[0]!r}")
print(f"  product_id v3.24 sample: {df324['product_id'].iloc[0]!r}")
print(f"  product_id v4.3 sample:  {hm43['product_id'].iloc[0]!r}")

# Si team_id es nombre en v3.24 y id en v4.3, parear por product_id solo
# (asumiendo que product_id es legible en ambos)
df324_agg = df324.groupby("product_id", as_index=False).agg(
    real_324=("real_qty", "sum"),
    fcst_324=("forecast_qty", "sum"),
    ae_324=("abs_error_qty", "sum"),
    e_324=("error_qty", "sum"),
    n_324=("real_qty", "size"),
)
hm43_agg = hm43.groupby("product_id", as_index=False).agg(
    real_43=("real_qty", "sum"),
    fcst_43=("forecast_qty", "sum"),
    ae_43=("abs_error_qty", "sum"),
    e_43=("error_qty", "sum"),
    n_43=("real_qty", "size"),
)
pair = df324_agg.merge(hm43_agg, on="product_id", how="inner")
print(f"\n  Productos pareados: {len(pair):,}")
print(f"  v3.24 unicos: {len(df324_agg):,}  |  v4.3-revert unicos: {len(hm43_agg):,}")

# Coherencia: las ventas reales deberian ser similares (mismo SKU, misma semana, agg por todos los locales)
print(f"\n  Sum real_324: {pair['real_324'].sum():,.0f}")
print(f"  Sum real_43:  {pair['real_43'].sum():,.0f}")
print(f"  Coherencia: {abs(pair['real_324'].sum() - pair['real_43'].sum()) / pair['real_43'].sum() * 100:.1f}% de diferencia")

# Si los reales son coherentes, podemos comparar forecasts
r_common = pair["real_43"].sum()  # usar v4.3 como referencia
print(f"\n  Sobre real_43 = {r_common:,.0f}")
print(f"    v3.24:       fcst={pair['fcst_324'].sum():>10,.0f}  ae={pair['ae_324'].sum():>10,.0f}  WAPE~{pair['ae_324'].sum()/r_common*100:6.2f}%  BIAS~{pair['e_324'].sum()/r_common*100:+6.2f}%")
print(f"    v4.3-revert: fcst={pair['fcst_43'].sum():>10,.0f}  ae={pair['ae_43'].sum():>10,.0f}  WAPE~{pair['ae_43'].sum()/r_common*100:6.2f}%  BIAS~{pair['e_43'].sum()/r_common*100:+6.2f}%")

# ----------------------------------------------------------------------
# 5. POR FORECAST_ZONE (v3.24 legacy Z1-Z4)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. v3.24 POR ZONA LEGACY (Z1-Z4)")
print("=" * 90)
rows = []
for z in sorted(df324["forecast_zone"].dropna().unique()):
    sub = df324[df324["forecast_zone"] == z]
    w, b, r, f = wape_bias(sub)
    rows.append({"zone": z, "n": len(sub), "real": r, "fcst": f, "wape_%": w, "bias_%": b})
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 90)
print("6. v4.3-revert POR REGIMEN")
print("=" * 90)
rows = []
for reg in sorted(hm43["regimen"].dropna().unique()):
    sub = hm43[hm43["regimen"] == reg]
    w, b, r, f = wape_bias(sub)
    rows.append({"regimen": reg, "n": len(sub), "real": r, "fcst": f, "wape_%": w, "bias_%": b})
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ----------------------------------------------------------------------
# 7. CONCENTRACION DEL ERROR EN TOP SKUs
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("7. TOP 15 SKUs DONDE v4.3-revert EMPEORA vs v3.24 (delta abs_err)")
print("=" * 90)
pair["delta_ae"] = pair["ae_43"] - pair["ae_324"]
empeora = pair.sort_values("delta_ae", ascending=False).head(15)
cols = ["product_id", "real_43", "fcst_324", "fcst_43", "ae_324", "ae_43", "delta_ae"]
print(empeora[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 90)
print("8. TOP 15 SKUs DONDE v4.3-revert MEJORA vs v3.24")
print("=" * 90)
mejora = pair.sort_values("delta_ae", ascending=True).head(15)
print(mejora[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ----------------------------------------------------------------------
# 9. BALANCE NETO
# ----------------------------------------------------------------------
total_delta = pair["delta_ae"].sum()
n_worse = (pair["delta_ae"] > 0).sum()
n_better = (pair["delta_ae"] < 0).sum()
n_same = (pair["delta_ae"] == 0).sum()
print("\n" + "=" * 90)
print("9. BALANCE NETO PAREADO")
print("=" * 90)
print(f"  Productos pareados: {len(pair):,}")
print(f"  v4.3-revert peor:   {n_worse:,} ({n_worse/len(pair)*100:.1f}%)  delta total +{pair.loc[pair['delta_ae']>0,'delta_ae'].sum():,.0f}")
print(f"  v4.3-revert mejor:  {n_better:,} ({n_better/len(pair)*100:.1f}%)  delta total {pair.loc[pair['delta_ae']<0,'delta_ae'].sum():,.0f}")
print(f"  Igual:              {n_same:,}")
print(f"  Delta NETO abs_err: {total_delta:+,.0f}  (positivo = v4.3-revert peor)")

print("\nDONE.")
