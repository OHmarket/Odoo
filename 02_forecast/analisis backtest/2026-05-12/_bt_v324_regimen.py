"""
Medicion HM-SI v3.24 + regimen sobre el archivo (9).

Objetivos:
  1. Confirmar que el rollback recupero la performance (WAPE ~75%, BIAS ~-10%).
  2. Verificar que la inyeccion de regimen funciono (% filas con REG-X poblado).
  3. Cortar metricas por los 9 regimenes canonicos (primer corte de v3.24
     por la matriz canonica de ABCXYZ).
  4. Cortar tambien por zona Z1-Z4 nativa de v3.24, para comparar las dos
     dimensiones de segmentacion en el mismo dataset.
  5. Top SKUs problematicos por regimen, candidatos a intervencion targeted.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (9).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")

all_weeks = sorted(df["target_week_start"].dropna().unique())
print(f"Semanas en archivo: {len(all_weeks)} -> {all_weeks}")
if len(all_weeks) > 3:
    last_3 = all_weeks[-3:]
    print(f"Filtrando solo las 3 ultimas: {last_3}")
    df = df[df["target_week_start"].isin(last_3)].copy()

for c in ["real_qty", "forecast_qty", "error_qty", "abs_error_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

print("=" * 90)
print(f"Universo: {len(df):,} filas | semanas: {df['target_week_start'].nunique()} | teams: {df['team_id'].nunique()}")
print(f"Metodos: {sorted(df['method'].dropna().unique())}")
print("=" * 90)


def metrics(sub, label):
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return {
        "scenario": label,
        "n": len(sub),
        "real": r,
        "forecast": f,
        "wape_%": (ae / r * 100) if r > 0 else np.nan,
        "bias_%": (e / r * 100) if r > 0 else np.nan,
    }


# ----------------------------------------------------------------------
# 1. METRICAS GLOBALES — confirmar recuperacion vs v4.3-revert
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("1. METRICAS GLOBALES POR METHOD")
print("=" * 90)
rows = []
for m in sorted(df["method"].dropna().unique()):
    sub = df[df["method"] == m]
    rows.append(metrics(sub, f"{m} (todas)"))
res = pd.DataFrame(rows)
print(res.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n  Referencia 2026-05-12 (file 8, v4.3-revert):")
print("    HM-SI v4.3-revert: WAPE 120.53%, BIAS -45.72%")
print("    OLD baseline:      WAPE  79.71%, BIAS -18.70%")
print("  Target v3.24:        WAPE ~75%,   BIAS ~-10%")


# ----------------------------------------------------------------------
# 2. COBERTURA — verificar que la inyeccion de regimen funciono
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("2. COBERTURA DE REGIMEN POR METHOD")
print("=" * 90)
for m in sorted(df["method"].dropna().unique()):
    sub = df[df["method"] == m]
    n_total = len(sub)
    n_regimen = sub["regimen"].notna().sum() if "regimen" in sub.columns else 0
    n_regimen_valid = ((sub["regimen"].astype(str).str.startswith('REG-')).sum() if "regimen" in sub.columns else 0)
    n_zone = sub["forecast_zone"].notna().sum() if "forecast_zone" in sub.columns else 0
    n_zone_valid = ((sub["forecast_zone"].isin(['Z1', 'Z2', 'Z3', 'Z4'])).sum() if "forecast_zone" in sub.columns else 0)
    print(f"  method={m}: n={n_total:,}")
    print(f"    regimen poblado:         {n_regimen:>7,} ({n_regimen/n_total*100:5.1f}%)")
    print(f"    regimen valido (REG-X):  {n_regimen_valid:>7,} ({n_regimen_valid/n_total*100:5.1f}%)")
    print(f"    forecast_zone poblado:   {n_zone:>7,} ({n_zone/n_total*100:5.1f}%)")
    print(f"    forecast_zone Z1-Z4:     {n_zone_valid:>7,} ({n_zone_valid/n_total*100:5.1f}%)")


# ----------------------------------------------------------------------
# 3. WAPE/BIAS POR REGIMEN (los 9 canonicos)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("3. PERFORMANCE POR REGIMEN (los 9 canonicos)")
print("=" * 90)

for m in sorted(df["method"].dropna().unique()):
    print(f"\n  --- method = {m} ---")
    sub_m = df[df["method"] == m]
    rows = []
    for reg in sorted(sub_m["regimen"].dropna().unique()):
        sub = sub_m[sub_m["regimen"] == reg]
        d = metrics(sub, reg)
        d["regimen"] = reg
        rows.append(d)
    # Tambien para NaN
    sub_nan = sub_m[sub_m["regimen"].isna()]
    if len(sub_nan) > 0:
        d = metrics(sub_nan, "(NaN)")
        d["regimen"] = "(NaN)"
        rows.append(d)
    df_reg = pd.DataFrame(rows)[["regimen", "n", "real", "forecast", "wape_%", "bias_%"]]
    print(df_reg.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 4. WAPE/BIAS POR ZONA Z1-Z4 (dimension nativa de v3.24)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("4. PERFORMANCE POR ZONA Z1-Z4 (dimension nativa v3.24)")
print("=" * 90)
hm = df[df["method"] == "hm_si"]
rows = []
for z in sorted(hm["forecast_zone"].dropna().unique()):
    sub = hm[hm["forecast_zone"] == z]
    d = metrics(sub, z)
    d["zone"] = z
    rows.append(d)
df_zone = pd.DataFrame(rows)[["zone", "n", "real", "forecast", "wape_%", "bias_%"]]
print(df_zone.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 5. CRUCE REGIMEN x ZONA — entender que regimenes caen en cada zona
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. CRUCE REGIMEN x ZONA (solo hm_si)")
print("=" * 90)
if "regimen" in hm.columns and "forecast_zone" in hm.columns:
    ct = pd.crosstab(hm["regimen"].fillna("(NaN)"), hm["forecast_zone"].fillna("(NaN)"), margins=True)
    print(ct.to_string())


# ----------------------------------------------------------------------
# 6. COMPARATIVA PAREADA hm_si vs old
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("6. COMPARATIVA PAREADA hm_si (v3.24+regimen) vs old (baseline)")
print("=" * 90)

key = ["team_id", "product_id", "target_week_start"]
hm_sub = df[df["method"] == "hm_si"][key + ["real_qty", "forecast_qty", "abs_error_qty", "error_qty", "regimen", "forecast_zone"]].copy()
old_sub = df[df["method"] == "old"][key + ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]].copy()
old_sub = old_sub.rename(columns={
    "real_qty": "real_qty_old",
    "forecast_qty": "forecast_qty_old",
    "abs_error_qty": "abs_error_qty_old",
    "error_qty": "error_qty_old",
})
pair = hm_sub.merge(old_sub, on=key, how="inner")
print(f"\n  Filas pareadas: {len(pair):,}")

r = pair["real_qty"].sum()
ae_hm = pair["abs_error_qty"].sum()
ae_old = pair["abs_error_qty_old"].sum()
e_hm = pair["error_qty"].sum()
e_old = pair["error_qty_old"].sum()
if r > 0:
    print(f"  WAPE hm_si: {ae_hm/r*100:.2f}%  vs  WAPE old: {ae_old/r*100:.2f}%   delta: {(ae_hm-ae_old)/r*100:+.2f} pp")
    print(f"  BIAS hm_si: {e_hm/r*100:+.2f}%  vs  BIAS old: {e_old/r*100:+.2f}%   delta: {(e_hm-e_old)/r*100:+.2f} pp")
    print(f"  Forecast hm_si: {pair['forecast_qty'].sum():,.0f}  |  OLD: {pair['forecast_qty_old'].sum():,.0f}  |  Real: {r:,.0f}")


# Por regimen pareado
print("\n  Por regimen pareado:")
pair_reg = pair[pair["regimen"].notna()]
rows = []
for reg in sorted(pair_reg["regimen"].unique()):
    sub = pair_reg[pair_reg["regimen"] == reg]
    rs = sub["real_qty"].sum()
    if rs <= 0:
        rows.append({
            "regimen": reg, "n": len(sub), "real": rs,
            "wape_hm_%": np.nan, "wape_old_%": np.nan,
            "bias_hm_%": np.nan, "bias_old_%": np.nan,
            "delta_wape_pp": np.nan,
        })
        continue
    wape_hm = sub["abs_error_qty"].sum() / rs * 100
    wape_old = sub["abs_error_qty_old"].sum() / rs * 100
    rows.append({
        "regimen": reg, "n": len(sub), "real": rs,
        "wape_hm_%": wape_hm,
        "wape_old_%": wape_old,
        "bias_hm_%": sub["error_qty"].sum() / rs * 100,
        "bias_old_%": sub["error_qty_old"].sum() / rs * 100,
        "delta_wape_pp": wape_hm - wape_old,
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 7. TOP 15 SKUs DONDE v3.24 ESTA MAL (candidatos a intervencion)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("7. TOP 15 SKUs MAS PROBLEMATICOS PARA v3.24 (abs_err alto)")
print("=" * 90)
hm_full = df[df["method"] == "hm_si"].copy()
sku_agg = hm_full.groupby(["product_id", "regimen", "forecast_zone"], as_index=False, dropna=False).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    forecast=("forecast_qty", "sum"),
    ae=("abs_error_qty", "sum"),
)
sku_agg["wape_%"] = sku_agg.apply(lambda r: r["ae"]/r["real"]*100 if r["real"]>0 else np.nan, axis=1)
top = sku_agg.sort_values("ae", ascending=False).head(15)
print(top.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 8. RESUMEN — diagnostico rapido
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("8. DIAGNOSTICO RAPIDO")
print("=" * 90)
hm_metrics = metrics(df[df["method"] == "hm_si"], "hm_si")
old_metrics = metrics(df[df["method"] == "old"], "old")
print(f"  hm_si (v3.24+regimen): WAPE {hm_metrics['wape_%']:.2f}%  BIAS {hm_metrics['bias_%']:+.2f}%")
print(f"  old   (baseline):      WAPE {old_metrics['wape_%']:.2f}%  BIAS {old_metrics['bias_%']:+.2f}%")
delta_wape = hm_metrics['wape_%'] - old_metrics['wape_%']
print(f"  delta vs OLD: {delta_wape:+.2f} pp")

if hm_metrics['wape_%'] <= 80 and abs(hm_metrics['bias_%']) <= 15:
    print(f"  RESULTADO: ROLLBACK EXITOSO — v3.24+regimen en rango target.")
elif hm_metrics['wape_%'] <= 100:
    print(f"  RESULTADO: Mejor que v4.3-revert pero por encima del target. Revisar.")
else:
    print(f"  RESULTADO: PROBLEMATICO — performance peor de lo esperado. Verificar runner.")

print("\nDONE.")
