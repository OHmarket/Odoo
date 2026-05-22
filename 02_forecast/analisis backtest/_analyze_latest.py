"""Análisis del backtest más reciente — aplica filtro estándar de bolsas de ruido."""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).xlsx"

df = pd.read_excel(PATH)
print(f"Filas totales: {len(df):,}")
print(f"Columnas: {list(df.columns)}")
print()

# Cutoffs / semanas
print("Cutoffs distintos:", sorted(df["forecast_cutoff"].dropna().unique()))
print("Semanas objetivo:", sorted(df["target_week_start"].dropna().unique()))
print()

# Aplicar filtro estándar
mask_excl_cat = df["categ_id"].fillna("").str.contains(
    r"Cerveza|Cigarrillo|Tabaco|Snack|Impulso", case=False, regex=True
)
mask_excl_team = df["team_id"].fillna("").str.contains("Ventas San Jos", case=False)
core = df[~(mask_excl_cat | mask_excl_team)].copy()
noise = df[mask_excl_cat | mask_excl_team].copy()


def metricas(d, label):
    real = d["real_qty"].sum()
    fcst = d["forecast_qty"].sum()
    err = d["error_qty"].sum()  # forecast - real (signo según export)
    abs_err = d["abs_error_qty"].sum()
    wape = abs_err / real * 100 if real else 0
    bias = err / real * 100 if real else 0
    print(f"{label:>20s}: filas={len(d):>7,}  real={real:>9,.0f}  fcst={fcst:>9,.0f}  "
          f"WAPE={wape:>5.1f}%  BIAS={bias:>+5.1f}%")


print("=== Métricas globales ===")
metricas(df, "TOTAL")
metricas(noise, "RUIDO excluido")
metricas(core, "CORE limpio")
print()

# Por cutoff (core)
print("=== CORE: WAPE/BIAS por semana objetivo ===")
for wk in sorted(core["target_week_start"].dropna().unique()):
    metricas(core[core["target_week_start"] == wk], str(wk)[:10])
print()

# Por zona (core)
print("=== CORE: WAPE/BIAS por forecast_zone ===")
for z in sorted(core["forecast_zone"].dropna().unique()):
    metricas(core[core["forecast_zone"] == z], str(z))
print()

# Por ABCXYZ (core, top buckets)
print("=== CORE: WAPE/BIAS por abcxyz ===")
agrup = core.groupby("abcxyz").agg(
    filas=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcst=("forecast_qty", "sum"),
    abs_err=("abs_error_qty", "sum"),
    err=("error_qty", "sum"),
).sort_values("real", ascending=False)
agrup["WAPE%"] = (agrup["abs_err"] / agrup["real"] * 100).round(1)
agrup["BIAS%"] = (agrup["err"] / agrup["real"] * 100).round(1)
print(agrup[["filas", "real", "fcst", "WAPE%", "BIAS%"]].to_string())
print()

# Forecast=0 con real>0 en core
zero_fcst_real_pos = core[(core["forecast_qty"] == 0) & (core["real_qty"] > 0)]
print(f"=== CORE: forecast=0 con real>0 ===")
print(f"  filas: {len(zero_fcst_real_pos):,}")
print(f"  unidades perdidas: {zero_fcst_real_pos['real_qty'].sum():.0f}")
print()

# Por series_type (core)
if "series_type" in core.columns:
    print("=== CORE: WAPE/BIAS por series_type ===")
    for st in core["series_type"].dropna().unique():
        metricas(core[core["series_type"] == st], str(st))
