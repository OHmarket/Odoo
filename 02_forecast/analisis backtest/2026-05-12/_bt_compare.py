"""
Comparativa HM-SI v4.3-revert vs OLD sobre el backtest (7).

Bloques:
  1. Metricas globales por method
  2. Cobertura del catalogo (SKUs unicos, gaps)
  3. Por bucket de comportamiento (vendio_y_forecast, etc.)
  4. Por regimen (solo aplica a hm_si)
  5. Comparativa pareada hm_si vs old en los mismos SKU-team-week
  6. Top SKUs donde HM-SI gana / pierde vs OLD
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (8).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")

# Si quedaron semanas viejas mezcladas en el archivo, filtrar solo las 3 mas recientes.
all_weeks = sorted(df["target_week_start"].dropna().unique())
print(f"Semanas en archivo: {len(all_weeks)} -> {all_weeks}")
if len(all_weeks) > 3:
    last_3 = all_weeks[-3:]
    print(f"Filtrando solo las 3 ultimas: {last_3}")
    df = df[df["target_week_start"].isin(last_3)].copy()
    print(f"Filas tras filtro: {len(df):,}")

# Tipos
for c in ["real_qty", "forecast_qty", "error_qty", "abs_error_qty", "bias_pct", "ape"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

print("=" * 90)
print(f"Universo: {len(df):,} filas | semanas: {df['target_week_start'].nunique()} | teams: {df['team_id'].nunique()}")
print("=" * 90)


def metrics(sub, label):
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()   # error_qty = real - forecast en el backtest
    return {
        "scenario": label,
        "n": len(sub),
        "real": r,
        "forecast": f,
        "wape_%": (ae / r * 100) if r > 0 else np.nan,
        "bias_%": (e / r * 100) if r > 0 else np.nan,
        "fcst_vs_real_%": ((f - r) / r * 100) if r > 0 else np.nan,
    }


# ----------------------------------------------------------------------
# 1. METRICAS GLOBALES POR METHOD
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("1. METRICAS GLOBALES POR METHOD")
print("=" * 90)
rows = []
for m in ["hm_si", "old"]:
    sub = df[df["method"] == m]
    rows.append(metrics(sub, f"{m} (todas las filas)"))
    # Solo donde HAY forecast > 0 (excluye sin_movimiento)
    sub2 = sub[(sub["forecast_qty"] > 0) | (sub["real_qty"] > 0)]
    rows.append(metrics(sub2, f"{m} (activas: real>0 o fcst>0)"))
res = pd.DataFrame(rows)
print(res.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 2. COBERTURA
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("2. COBERTURA POR METHOD")
print("=" * 90)
for m in ["hm_si", "old"]:
    sub = df[df["method"] == m]
    skus = sub["product_id"].nunique()
    teams = sub["team_id"].nunique()
    pares = len(sub.groupby(["team_id", "product_id"]))
    semanas = sub["target_week_start"].nunique()
    print(f"  method={m}: SKUs={skus:,}  teams={teams}  pares(team,sku)={pares:,}  semanas={semanas}")


# ----------------------------------------------------------------------
# 3. POR BUCKET (vendio_y_forecast, forecast_sin_venta, venta_sin_forecast, sin_movimiento)
# ----------------------------------------------------------------------
def bucket(row):
    f = row["forecast_qty"]
    r = row["real_qty"]
    if f > 0 and r > 0:
        return "vendio_y_forecast"
    if f > 0 and r <= 0:
        return "forecast_sin_venta"
    if f <= 0 and r > 0:
        return "venta_sin_forecast"
    return "sin_movimiento"

df["bucket"] = df.apply(bucket, axis=1)

print("\n" + "=" * 90)
print("3. COMPOSICION POR BUCKET (cuentas)")
print("=" * 90)
print(pd.crosstab(df["bucket"], df["method"]).to_string())

print("\n  Tasa de cobertura del forecast (cuando hubo venta):")
for m in ["hm_si", "old"]:
    sub = df[(df["method"] == m) & (df["real_qty"] > 0)]
    n_total = len(sub)
    n_match = (sub["forecast_qty"] > 0).sum()
    n_miss = (sub["forecast_qty"] <= 0).sum()
    if n_total > 0:
        print(f"  {m}: ventas con forecast {n_match:,}/{n_total:,} ({n_match/n_total*100:.1f}%); ventas sin forecast {n_miss:,}/{n_total:,} ({n_miss/n_total*100:.1f}%)")


# ----------------------------------------------------------------------
# 4. POR REGIMEN (hm_si)
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("4. METRICAS HM-SI POR REGIMEN")
print("=" * 90)
hm = df[df["method"] == "hm_si"].copy()
rows = []
for reg in sorted(hm["regimen"].dropna().unique()):
    sub = hm[hm["regimen"] == reg]
    rows.append({"regimen": reg, **metrics(sub, reg)})
rows.append({"regimen": "NaN (gaps)", **metrics(hm[hm["regimen"].isna()], "NaN (gaps)")})
print(pd.DataFrame(rows)[["regimen", "n", "real", "forecast", "wape_%", "bias_%", "fcst_vs_real_%"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 5. COMPARATIVA PAREADA hm_si vs old en SKU-team-week comunes
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("5. COMPARATIVA PAREADA — solo filas con MATCH (mismo team+product+week en ambos)")
print("=" * 90)

key_cols = ["team_id", "product_id", "target_week_start"]
hm_sub = df[df["method"] == "hm_si"][key_cols + ["real_qty", "forecast_qty", "abs_error_qty", "error_qty", "regimen", "forecast_zone"]].copy()
old_sub = df[df["method"] == "old"][key_cols + ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]].copy()
old_sub = old_sub.rename(columns={
    "real_qty": "real_qty_old",
    "forecast_qty": "forecast_qty_old",
    "abs_error_qty": "abs_error_qty_old",
    "error_qty": "error_qty_old",
})

pair = hm_sub.merge(old_sub, on=key_cols, how="inner")
print(f"\n  Filas pareadas: {len(pair):,}")
print(f"  Real coherente entre metodos: {(pair['real_qty'] == pair['real_qty_old']).mean()*100:.1f}%")

r = pair["real_qty"].sum()
ae_hm = pair["abs_error_qty"].sum()
ae_old = pair["abs_error_qty_old"].sum()
e_hm = pair["error_qty"].sum()
e_old = pair["error_qty_old"].sum()
print(f"\n  WAPE hm_si: {ae_hm/r*100:.2f}%  vs  WAPE old: {ae_old/r*100:.2f}%   delta: {(ae_hm-ae_old)/r*100:+.2f} pp")
print(f"  BIAS hm_si: {e_hm/r*100:+.2f}%  vs  BIAS old: {e_old/r*100:+.2f}%   delta: {(e_hm-e_old)/r*100:+.2f} pp")
print(f"  Forecast hm_si: {pair['forecast_qty'].sum():,.0f}  |  OLD: {pair['forecast_qty_old'].sum():,.0f}  |  Real: {r:,.0f}")


# Por regimen pareado
print("\n  Por regimen (solo filas pareadas con regimen poblado):")
pair_reg = pair[pair["regimen"].notna()]
rows = []
for reg in sorted(pair_reg["regimen"].unique()):
    sub = pair_reg[pair_reg["regimen"] == reg]
    rs = sub["real_qty"].sum()
    if rs <= 0:
        continue
    rows.append({
        "regimen": reg,
        "n": len(sub),
        "real": rs,
        "wape_hm_si_%": sub["abs_error_qty"].sum() / rs * 100,
        "wape_old_%": sub["abs_error_qty_old"].sum() / rs * 100,
        "bias_hm_si_%": sub["error_qty"].sum() / rs * 100,
        "bias_old_%": sub["error_qty_old"].sum() / rs * 100,
    })
    rows[-1]["delta_wape_pp"] = rows[-1]["wape_hm_si_%"] - rows[-1]["wape_old_%"]
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 6. TOP SKUs (PAIR) DONDE HM-SI MEJORA / EMPEORA VS OLD
# ----------------------------------------------------------------------
print("\n" + "=" * 90)
print("6. TOP 15 SKUs donde HM-SI MEJORA mas vs OLD (delta abs_err agregado)")
print("=" * 90)
pair["delta_abs_err"] = pair["abs_error_qty"] - pair["abs_error_qty_old"]
sku_diff = pair.groupby("product_id", as_index=False).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    abs_err_hm=("abs_error_qty", "sum"),
    abs_err_old=("abs_error_qty_old", "sum"),
    fcst_hm=("forecast_qty", "sum"),
    fcst_old=("forecast_qty_old", "sum"),
)
sku_diff["delta_abs_err"] = sku_diff["abs_err_hm"] - sku_diff["abs_err_old"]
sku_diff["wape_hm"] = sku_diff["abs_err_hm"] / sku_diff["real"].replace(0, np.nan) * 100
sku_diff["wape_old"] = sku_diff["abs_err_old"] / sku_diff["real"].replace(0, np.nan) * 100
mejora = sku_diff.sort_values("delta_abs_err", ascending=True).head(15)
print(mejora.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 90)
print("7. TOP 15 SKUs donde HM-SI EMPEORA mas vs OLD")
print("=" * 90)
empeora = sku_diff.sort_values("delta_abs_err", ascending=False).head(15)
print(empeora.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\nDONE.")
