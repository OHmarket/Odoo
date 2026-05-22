"""
Medicion del fix v3.25 (REG-8 excluido del P3 zero-gate).

Compara archivo (10) [v3.25] contra archivo (9) [v3.24+regimen] en las
mismas 3 semanas, mismo SKU. Foco: REG-8 (esperabamos BIAS de +49.54%
acercarse a 0%).

Tambien valida que el fix NO degradó los otros regimenes (debia ser
targeted).
"""
import pandas as pd
import numpy as np

PATH_V324 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (9).xlsx"
PATH_V325 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"


def load_and_filter(path, label):
    df = pd.read_excel(path, engine="openpyxl")
    weeks = sorted(df["target_week_start"].dropna().unique())
    if len(weeks) > 3:
        df = df[df["target_week_start"].isin(weeks[-3:])].copy()
    for c in ["real_qty", "forecast_qty", "error_qty", "abs_error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    print(f"{label}: {len(df):,} filas | semanas: {sorted(df['target_week_start'].dropna().unique())}")
    return df


def metrics(sub):
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return {
        "n": len(sub),
        "real": r,
        "forecast": f,
        "wape_%": (ae / r * 100) if r > 0 else np.nan,
        "bias_%": (e / r * 100) if r > 0 else np.nan,
    }


print("=" * 90)
print("FIX v3.25 (REG-8 fuera de P3 zero-gate) — comparacion v3.24+regimen vs v3.25")
print("=" * 90)
df9 = load_and_filter(PATH_V324, "v3.24+regimen (file 9)")
df10 = load_and_filter(PATH_V325, "v3.25 (file 10)")

hm9 = df9[df9["method"] == "hm_si"].copy()
hm10 = df10[df10["method"] == "hm_si"].copy()


# ----------------------------------------------------------------------
# 1. METRICAS GLOBALES
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("1. METRICAS GLOBALES HM-SI")
print("=" * 90)
m9 = metrics(hm9)
m10 = metrics(hm10)
print(f"{'metrica':<15} {'v3.24+regimen':>15} {'v3.25':>15} {'delta':>12}")
print("-" * 60)
print(f"{'n':<15} {m9['n']:>15,} {m10['n']:>15,}")
print(f"{'real':<15} {m9['real']:>15,.0f} {m10['real']:>15,.0f}")
print(f"{'forecast':<15} {m9['forecast']:>15,.0f} {m10['forecast']:>15,.0f}  {m10['forecast']-m9['forecast']:>+10,.0f}")
print(f"{'WAPE %':<15} {m9['wape_%']:>15,.2f} {m10['wape_%']:>15,.2f}  {m10['wape_%']-m9['wape_%']:>+10,.2f} pp")
print(f"{'BIAS %':<15} {m9['bias_%']:>+15,.2f} {m10['bias_%']:>+15,.2f}  {m10['bias_%']-m9['bias_%']:>+10,.2f} pp")


# ----------------------------------------------------------------------
# 2. POR REGIMEN — foco en REG-8
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("2. PERFORMANCE POR REGIMEN — comparativa v3.24+regimen vs v3.25")
print("=" * 90)

regimenes = sorted(set(hm9["regimen"].dropna().unique()) | set(hm10["regimen"].dropna().unique()))
rows = []
for reg in regimenes:
    sub9 = hm9[hm9["regimen"] == reg]
    sub10 = hm10[hm10["regimen"] == reg]
    m9r = metrics(sub9)
    m10r = metrics(sub10)
    rows.append({
        "regimen": reg,
        "n_v324": m9r["n"],
        "n_v325": m10r["n"],
        "real_v325": m10r["real"],
        "fcst_v324": m9r["forecast"],
        "fcst_v325": m10r["forecast"],
        "wape_v324": m9r["wape_%"],
        "wape_v325": m10r["wape_%"],
        "delta_wape_pp": m10r["wape_%"] - m9r["wape_%"] if pd.notna(m9r["wape_%"]) and pd.notna(m10r["wape_%"]) else np.nan,
        "bias_v324": m9r["bias_%"],
        "bias_v325": m10r["bias_%"],
        "delta_bias_pp": m10r["bias_%"] - m9r["bias_%"] if pd.notna(m9r["bias_%"]) and pd.notna(m10r["bias_%"]) else np.nan,
    })
df_cmp = pd.DataFrame(rows)
print(df_cmp.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 3. ZOOM REG-8: que cambio?
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("3. ZOOM REG-8 — el fix targeted")
print("=" * 90)
r8_v324 = hm9[hm9["regimen"] == "REG-8"]
r8_v325 = hm10[hm10["regimen"] == "REG-8"]
print(f"\n  Filas REG-8 v3.24+regimen: {len(r8_v324):,}")
print(f"  Filas REG-8 v3.25:         {len(r8_v325):,}")

# Cuantos SKUs estaban con forecast=0 en v3.24 y ahora tienen forecast>0?
zero_v324 = (r8_v324["forecast_qty"] == 0).sum()
zero_v325 = (r8_v325["forecast_qty"] == 0).sum()
print(f"\n  Filas con forecast=0:")
print(f"    v3.24+regimen: {zero_v324:,} ({zero_v324/len(r8_v324)*100:.1f}%)")
print(f"    v3.25:         {zero_v325:,} ({zero_v325/len(r8_v325)*100:.1f}%)")

# Filas REG-8 + Z4 — los que el fix afecto directamente
r8z4_v324 = hm9[(hm9["regimen"] == "REG-8") & (hm9["forecast_zone"] == "Z4")]
r8z4_v325 = hm10[(hm10["regimen"] == "REG-8") & (hm10["forecast_zone"] == "Z4")]
print(f"\n  REG-8 + zona Z4 (los afectados por el fix):")
print(f"    v3.24+regimen: {len(r8z4_v324):,} filas")
print(f"    v3.25:         {len(r8z4_v325):,} filas")
if len(r8z4_v324) > 0 and len(r8z4_v325) > 0:
    m_v324 = metrics(r8z4_v324)
    m_v325 = metrics(r8z4_v325)
    print(f"    v3.24+regimen: fcst={m_v324['forecast']:>10,.0f}  WAPE={m_v324['wape_%']:>6.2f}%  BIAS={m_v324['bias_%']:>+7.2f}%")
    print(f"    v3.25:         fcst={m_v325['forecast']:>10,.0f}  WAPE={m_v325['wape_%']:>6.2f}%  BIAS={m_v325['bias_%']:>+7.2f}%")


# ----------------------------------------------------------------------
# 4. VALIDAR NO DEGRADACION EN OTROS REGIMENES
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("4. CHECK NO-DEGRADACION (regimenes != REG-8 deben tener delta_wape ~ 0)")
print("=" * 90)
for _, row in df_cmp.iterrows():
    reg = row["regimen"]
    dwape = row["delta_wape_pp"]
    if pd.isna(dwape):
        continue
    flag = ""
    if reg == "REG-8":
        flag = "  <- FIX TARGETED"
    elif abs(dwape) > 5:
        flag = "  <- DEGRADACION SIGNIFICATIVA!"
    elif abs(dwape) > 1:
        flag = "  <- pequena variacion (ruido?)"
    print(f"  {reg}: delta_wape = {dwape:+7.2f} pp{flag}")


# ----------------------------------------------------------------------
# 5. EVOLUCION DEL LINAJE
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. EVOLUCION HM-SI a lo largo de las versiones")
print("=" * 90)
print("  v4.3-revert (file 8):    WAPE 120.53%  BIAS -45.72%  (descartado)")
print(f"  v3.24+regimen (file 9):  WAPE {m9['wape_%']:>6.2f}%  BIAS {m9['bias_%']:>+6.2f}%")
print(f"  v3.25 REG-8 fix (file 10): WAPE {m10['wape_%']:>6.2f}%  BIAS {m10['bias_%']:>+6.2f}%")

print("\nDONE.")
