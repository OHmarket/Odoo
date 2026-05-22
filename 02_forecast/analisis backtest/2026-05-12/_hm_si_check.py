"""
Verificacion post-corrida HM-SI v4.1.
Revisa que los modelos canonicos hayan corrido correctamente y diagnostica
si los SKUs cayeron al fallback Holt doble.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH HM SI Forecast (x_hm_si_forecast) (2).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")

print("=" * 90)
print("1. ESTRUCTURA")
print("=" * 90)
print(f"Filas: {len(df):,}")
print(f"Columnas ({len(df.columns)}):")
for c in df.columns:
    print(f"  {c}")


def find_col(*cands):
    for c in cands:
        if c in df.columns:
            return c
    for c in df.columns:
        cl = c.lower()
        for cand in cands:
            if cand.lower() in cl:
                return c
    return None


col_team       = find_col("x_studio_team_id", "team_id", "Team")
col_product    = find_col("x_studio_product_id", "product_id", "Producto")
col_categ      = find_col("x_studio_categ_id", "categ_id", "Categoria")
col_week_start = find_col("x_studio_week_start", "week_start")
col_mu_week    = find_col("x_studio_mu_week", "mu_week")
col_mu_pre     = find_col("x_studio_mu_week_pre_bias", "mu_week_pre_bias")
col_sigma      = find_col("x_studio_sigma_week", "sigma_week")
col_mu_base    = find_col("x_studio_mu_base", "mu_base")
col_si_curr    = find_col("x_studio_si_current", "si_current")
col_si_next    = find_col("x_studio_si_next", "si_next")
col_zone       = find_col("x_studio_forecast_zone", "forecast_zone")
col_regimen    = find_col("x_studio_regimen", "regimen")
col_model      = find_col("x_studio_forecast_model_code", "forecast_model_code")
col_abcxyz     = find_col("x_studio_abcxyz", "abcxyz")
col_series     = find_col("x_studio_series_type", "series_type")
col_ciclo      = find_col("x_studio_ciclo_de_vida", "ciclo_de_vida")


print("\n" + "=" * 90)
print("2. CAMPOS DETECTADOS")
print("=" * 90)
for label, c in [
    ("team_id", col_team), ("product_id", col_product),
    ("week_start", col_week_start), ("mu_week", col_mu_week),
    ("mu_week_pre_bias", col_mu_pre), ("sigma_week", col_sigma),
    ("forecast_zone", col_zone), ("regimen", col_regimen),
    ("forecast_model_code", col_model), ("abcxyz", col_abcxyz),
    ("series_type", col_series), ("ciclo_de_vida", col_ciclo),
]:
    flag = "OK" if c else "MISSING"
    print(f"  {label:25s} -> {c}    [{flag}]")


# ----------------------------------------------------------------------
# 3. CONTEOS POR REGIMEN — lo que cuenta
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("3. DISTRIBUCION POR REGIMEN")
print("=" * 90)
if col_regimen:
    g = df[col_regimen].value_counts(dropna=False)
    for k, v in g.items():
        print(f"  {k}: {v:,}")
else:
    print("  (campo regimen no encontrado)")


# ----------------------------------------------------------------------
# 4. CONTEOS POR MODELO APLICADO — la pregunta clave
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("4. DISTRIBUCION POR FORECAST_MODEL_CODE")
print("=" * 90)
if col_model:
    g = df[col_model].value_counts(dropna=False)
    total = len(df)
    for k, v in g.items():
        pct = v / total * 100
        print(f"  {k:30s} {v:>6,} ({pct:5.1f}%)")
    # Diagnostico critico
    print()
    if "holt_doble_fallback" in g.index:
        fb = g["holt_doble_fallback"]
        print(f"  >> holt_doble_fallback: {fb:,} SKUs ({fb/total*100:.1f}%)")
        print(f"     Si > 50%, el motor cayo al fallback porque history < 2*m=104 sem.")
    hw_count = sum(v for k, v in g.items() if str(k).startswith("hw_"))
    print(f"  >> HW triple activo en: {hw_count:,} SKUs ({hw_count/total*100:.1f}%)")
    sba_count = sum(v for k, v in g.items() if str(k).startswith("sba_"))
    print(f"  >> SBA (lumpy/intermittent): {sba_count:,} SKUs ({sba_count/total*100:.1f}%)")
    no_fc = g.get("no_forecast", 0)
    print(f"  >> no_forecast (REG-0): {no_fc:,} SKUs")
else:
    print("  (campo forecast_model_code no encontrado)")


# ----------------------------------------------------------------------
# 5. CONTEOS POR FORECAST_ZONE
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. DISTRIBUCION POR FORECAST_ZONE (deberia ser identica a regimen)")
print("=" * 90)
if col_zone:
    g = df[col_zone].value_counts(dropna=False)
    for k, v in g.items():
        print(f"  {k}: {v:,}")


# ----------------------------------------------------------------------
# 6. CRUCE REGIMEN x MODEL_CODE
# ----------------------------------------------------------------------
if col_regimen and col_model:
    print("\n" + "=" * 90)
    print("6. CRUCE regimen x model_code")
    print("=" * 90)
    print(pd.crosstab(df[col_regimen], df[col_model], dropna=False).to_string())


# ----------------------------------------------------------------------
# 7. RANGOS DE MU_WEEK
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("7. RANGOS DE MU_WEEK")
print("=" * 90)
if col_mu_week:
    s = pd.to_numeric(df[col_mu_week], errors="coerce")
    print(s.describe(percentiles=[0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]).to_string())
    n_zero = (s == 0).sum()
    print(f"\n  mu_week == 0: {n_zero:,} ({n_zero/len(df)*100:.1f}%)")
    print(f"  mu_week > 0 : {(s > 0).sum():,}")
    if col_mu_pre:
        sp = pd.to_numeric(df[col_mu_pre], errors="coerce")
        match = (s == sp).sum()
        print(f"\n  mu_week_pre_bias == mu_week: {match:,} ({match/len(df)*100:.1f}%)")
        print(f"  (en v4.1 deben ser iguales — no hay clamps que difieran)")


# ----------------------------------------------------------------------
# 8. TEAMS Y PRODUCTOS COBERTURA
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("8. COBERTURA")
print("=" * 90)
if col_team and col_product:
    print(f"  Teams unicos:    {df[col_team].nunique()}")
    print(f"  Productos unicos:{df[col_product].nunique()}")
    print(f"  Pares (team, prod): {len(df):,}")


# ----------------------------------------------------------------------
# 9. SANITY: forecast vs regimen
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("9. SANITY CHECK — forecast > 0 por regimen")
print("=" * 90)
if col_regimen and col_mu_week:
    s = pd.to_numeric(df[col_mu_week], errors="coerce")
    for reg in sorted(df[col_regimen].dropna().unique()):
        mask = df[col_regimen] == reg
        n = mask.sum()
        n_pos = ((s > 0) & mask).sum()
        mean_mu = s[mask].mean() if n > 0 else 0
        max_mu = s[mask].max() if n > 0 else 0
        print(f"  {reg}: n={n:,}  con_forecast>0={n_pos:,} ({n_pos/n*100 if n else 0:5.1f}%)  mu_avg={mean_mu:6.2f}  mu_max={max_mu:7.1f}")


print("\nDONE.")
