"""
Drill cruzado por method para entender la distribucion regimen + zone + model_code.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (7).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")

print("=" * 90)
print(f"Total filas: {len(df):,}")
print("=" * 90)

print("\n1. DISTRIBUCION POR METHOD")
print(df["method"].value_counts(dropna=False).to_string())

print("\n2. CRUCE method x forecast_zone")
ct = pd.crosstab(df["method"], df["forecast_zone"], dropna=False)
print(ct.to_string())

print("\n3. CRUCE method x regimen")
ct = pd.crosstab(df["method"], df["regimen"], dropna=False)
print(ct.to_string())

print("\n4. CRUCE method x forecast_model_code")
ct = pd.crosstab(df["method"], df["forecast_model_code"], dropna=False)
print(ct.to_string())

# Por method, contar cuantas filas tienen regimen NULL/REG-X
print("\n5. POR METHOD: cobertura de regimen")
for m in df["method"].dropna().unique():
    sub = df[df["method"] == m]
    n_total = len(sub)
    n_reg = sub["regimen"].notna().sum()
    n_zone = (sub["forecast_zone"] != "SIN_ZONA").sum()
    n_model = sub["forecast_model_code"].notna().sum()
    print(f"  method={m}: n={n_total:,}")
    print(f"    regimen poblado:      {n_reg:>7,} ({n_reg/n_total*100:5.1f}%)")
    print(f"    forecast_zone REG-X:  {n_zone:>7,} ({n_zone/n_total*100:5.1f}%)")
    print(f"    model_code poblado:   {n_model:>7,} ({n_model/n_total*100:5.1f}%)")
