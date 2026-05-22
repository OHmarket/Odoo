"""
Diagnostico rapido del problema con forecast_zone en el backtest nuevo.
Cruza con regimen / model_code / forecast_zone para ver si:
  - forecast_zone tiene valores REG-X (correcto v4.3-revert)
  - forecast_zone tiene Z1-Z4 (legacy, problema)
  - forecast_zone vacio (campo rechazado por _put_field)
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (7).xlsx"

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


col_zone     = find_col("x_studio_forecast_zone", "forecast_zone")
col_regimen  = find_col("x_studio_regimen", "regimen")
col_model    = find_col("x_studio_forecast_model_code", "forecast_model_code")
col_target   = find_col("target_week_start", "x_studio_target_week_start")
col_cutoff   = find_col("forecast_cutoff", "x_studio_forecast_cutoff")
col_real     = find_col("real_qty", "x_studio_real_qty")
col_fcst     = find_col("forecast_qty", "x_studio_forecast_qty")
col_abcxyz   = find_col("abcxyz", "x_studio_abcxyz")
col_series   = find_col("series_type", "x_studio_series_type")

print("\n" + "=" * 90)
print("2. CAMPOS DETECTADOS")
print("=" * 90)
for label, c in [
    ("forecast_zone", col_zone),
    ("regimen", col_regimen),
    ("forecast_model_code", col_model),
    ("target_week_start", col_target),
    ("forecast_cutoff", col_cutoff),
    ("real_qty", col_real),
    ("forecast_qty", col_fcst),
    ("abcxyz", col_abcxyz),
    ("series_type", col_series),
]:
    print(f"  {label:25s} -> {c}    [{'OK' if c else 'MISSING'}]")


# ----------------------------------------------------------------------
# 3. DISTRIBUCION FORECAST_ZONE — el campo critico
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("3. DISTRIBUCION FORECAST_ZONE")
print("=" * 90)
if col_zone:
    g = df[col_zone].value_counts(dropna=False)
    total = len(df)
    for k, v in g.items():
        pct = v / total * 100
        print(f"  {k!r:30s} {v:>7,} ({pct:5.1f}%)")
    n_null = df[col_zone].isnull().sum()
    n_z = df[col_zone].astype(str).str.startswith('Z').sum()
    n_reg = df[col_zone].astype(str).str.startswith('REG').sum()
    n_empty = (df[col_zone].astype(str).str.strip() == '').sum() + (df[col_zone].astype(str) == 'False').sum()
    print(f"\n  NULL: {n_null:,}")
    print(f"  Empieza con 'Z' (Z1-Z4 legacy): {n_z:,}")
    print(f"  Empieza con 'REG' (nuevo): {n_reg:,}")
    print(f"  Vacio / False: {n_empty:,}")


# ----------------------------------------------------------------------
# 4. DISTRIBUCION REGIMEN (deberia traer REG-X)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("4. DISTRIBUCION REGIMEN")
print("=" * 90)
if col_regimen:
    g = df[col_regimen].value_counts(dropna=False)
    for k, v in g.items():
        print(f"  {k!r:15s} {v:>7,}")
else:
    print("  Campo regimen no encontrado en el export")


# ----------------------------------------------------------------------
# 5. DISTRIBUCION MODEL_CODE
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. DISTRIBUCION FORECAST_MODEL_CODE")
print("=" * 90)
if col_model:
    g = df[col_model].value_counts(dropna=False)
    for k, v in g.items():
        print(f"  {k!r:40s} {v:>7,}")
else:
    print("  Campo model_code no encontrado")


# ----------------------------------------------------------------------
# 6. CRUCE forecast_zone x regimen (debe haber match perfecto)
# ----------------------------------------------------------------------
if col_zone and col_regimen:
    print("\n" + "=" * 90)
    print("6. CRUCE forecast_zone x regimen")
    print("=" * 90)
    ct = pd.crosstab(df[col_zone], df[col_regimen], dropna=False)
    print(ct.to_string())


# ----------------------------------------------------------------------
# 7. SEMANAS Y CUTOFFS
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("7. COBERTURA TEMPORAL")
print("=" * 90)
if col_target:
    target_weeks = sorted(df[col_target].dropna().unique())
    print(f"  Semanas objetivo distintas: {len(target_weeks)}")
    for w in target_weeks[:20]:
        print(f"    {w}")
if col_cutoff:
    cutoffs = sorted(df[col_cutoff].dropna().unique())
    print(f"\n  Cutoffs distintos: {len(cutoffs)}")
    for c in cutoffs[:20]:
        print(f"    {c}")


# ----------------------------------------------------------------------
# 8. MUESTRAS DE FILAS PROBLEMATICAS
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("8. MUESTRA — 5 filas con forecast_zone vacio o anormal")
print("=" * 90)
if col_zone:
    mask_anormal = df[col_zone].isnull() | (df[col_zone].astype(str).str.startswith('Z'))
    if mask_anormal.sum() > 0:
        cols_show = [c for c in [col_target, col_cutoff, col_zone, col_regimen, col_model, col_real, col_fcst] if c]
        print(df[mask_anormal][cols_show].head(5).to_string(index=False))
    else:
        print("  (no hay filas con forecast_zone vacio o Z*)")

print("\nDONE.")
