"""
Diagnostico forense: por que HM-SI v4.3-revert pierde 40pp vs OLD?
Foco: REG-5/6/7 (SBA), donde WAPE explota a 1338%, 474%, 341%.

Pregunta a responder:
  - Es over-forecast por outliers en historia (Hampel resolveria) ?
  - O es elegir mal modelo por regimen (problema de routing) ?
  - O es bug en SBA implementation ?

Si over-forecast es localizado en pocos SKUs con ratios extremos -> outliers.
Si es generalizado y consistente con z inflado -> SBA mal calibrado.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (8).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")

all_weeks = sorted(df["target_week_start"].dropna().unique())
if len(all_weeks) > 3:
    df = df[df["target_week_start"].isin(all_weeks[-3:])].copy()

for c in ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

hm = df[df["method"] == "hm_si"].copy()

print("=" * 90)
print("1. forecast_model_code POR REGIMEN (HM-SI)")
print("=" * 90)
if "forecast_model_code" in hm.columns:
    ct = pd.crosstab(hm["regimen"].fillna("(NaN)"), hm["forecast_model_code"].fillna("(NaN)"), dropna=False)
    print(ct.to_string())
else:
    print("  forecast_model_code NO ESTA EN COLUMNAS — chequear export")

print("\n" + "=" * 90)
print("2. OVER-FORECAST RATIO POR REGIMEN (solo donde real>0)")
print("=" * 90)
hm_sold = hm[hm["real_qty"] > 0].copy()
hm_sold["ratio"] = hm_sold["forecast_qty"] / hm_sold["real_qty"]
rows = []
for reg in sorted(hm_sold["regimen"].dropna().unique()):
    sub = hm_sold[hm_sold["regimen"] == reg]
    n = len(sub)
    if n == 0: continue
    rows.append({
        "regimen": reg, "n": n,
        "ratio_p50": sub["ratio"].median(),
        "ratio_p75": sub["ratio"].quantile(0.75),
        "ratio_p90": sub["ratio"].quantile(0.90),
        "ratio_p99": sub["ratio"].quantile(0.99),
        "ratio_max": sub["ratio"].max(),
        "n_ratio_gt_5": (sub["ratio"] > 5).sum(),
        "n_ratio_gt_10": (sub["ratio"] > 10).sum(),
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 90)
print("3. TOP 10 PEORES (abs_error) EN REG-5/6/7 — pareados con OLD")
print("=" * 90)

key = ["team_id", "product_id", "target_week_start"]
old = df[df["method"] == "old"][key + ["forecast_qty", "abs_error_qty"]].rename(
    columns={"forecast_qty": "fcst_old", "abs_error_qty": "ae_old"})

hm_cols = key + ["real_qty", "forecast_qty", "abs_error_qty", "regimen"]
if "forecast_model_code" in hm.columns:
    hm_cols.append("forecast_model_code")
pair = hm[hm_cols].merge(old, on=key, how="inner")

for reg in ["REG-5", "REG-6", "REG-7"]:
    sub = pair[pair["regimen"] == reg]
    if len(sub) == 0:
        print(f"\n  {reg}: sin filas")
        continue
    print(f"\n  --- {reg} ---")
    top = sub.nlargest(10, "abs_error_qty")
    cols = ["product_id", "team_id", "real_qty", "forecast_qty", "fcst_old", "abs_error_qty", "ae_old"]
    if "forecast_model_code" in top.columns:
        cols.append("forecast_model_code")
    print(top[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 90)
print("4. AGREGADO PAREADO POR REGIMEN — confirmar magnitud del problema")
print("=" * 90)
rows = []
for reg in sorted(pair["regimen"].dropna().unique()):
    sub = pair[pair["regimen"] == reg]
    r = sub["real_qty"].sum()
    if r <= 0: continue
    rows.append({
        "regimen": reg, "n": len(sub), "real": r,
        "fcst_hm": sub["forecast_qty"].sum(), "fcst_old": sub["fcst_old"].sum(),
        "wape_hm_%": sub["abs_error_qty"].sum() / r * 100,
        "wape_old_%": sub["ae_old"].sum() / r * 100,
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ----------------------------------------------------------------------
# 5. Distribucion: cuanto del abs_error total viene del top N peor?
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. CONCENTRACION DEL ERROR — top N SKUs explican que % del abs_err HM?")
print("=" * 90)
for reg in ["REG-5", "REG-6", "REG-7"]:
    sub = pair[pair["regimen"] == reg].sort_values("abs_error_qty", ascending=False)
    if len(sub) == 0:
        continue
    total_ae = sub["abs_error_qty"].sum()
    if total_ae == 0:
        continue
    for n in [5, 10, 20, 50]:
        if n > len(sub):
            break
        pct = sub.head(n)["abs_error_qty"].sum() / total_ae * 100
        print(f"  {reg} top{n:>3}/{len(sub):>5} filas explican {pct:5.1f}% del abs_err HM")

print("\nDONE.")
