"""
Analisis profundo del backtest x_forecast_backtest sobre el CORE LIMPIO.
Excluye: cervezas, snacks, cigarros, impulsivos y team Ventas San Jose.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).csv"

df = pd.read_csv(PATH, encoding="utf-8", low_memory=False)
for c in ["abs_error_qty", "bias_pct", "cv2", "error_qty", "forecast_qty", "real_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df["categ_id"] = df["categ_id"].fillna("")

# ----------------------------------------------------------------------
# FILTRO DE EXCLUSION
# ----------------------------------------------------------------------
EXCLUDE_PAT = r"Cerveza|Cigarrillo|Tabaco|Snack|Impulso"
EXCLUDE_TEAM = "Ventas San Jos"   # cubre tilde rota en CSV

mask_excl_cat = df["categ_id"].str.contains(EXCLUDE_PAT, case=False, regex=True, na=False)
mask_excl_team = df["team_id"].fillna("").str.contains(EXCLUDE_TEAM, case=False, regex=False, na=False)
mask_excl = mask_excl_cat | mask_excl_team

excluded = df[mask_excl].copy()
core = df[~mask_excl].copy()

print("=" * 80)
print("0. FILTROS APLICADOS")
print("=" * 80)
print(f"Excluido por categoria  : {mask_excl_cat.sum():>7,} filas / {df[mask_excl_cat]['real_qty'].sum():>12,.0f} u real")
print(f"Excluido por team       : {mask_excl_team.sum():>7,} filas / {df[mask_excl_team]['real_qty'].sum():>12,.0f} u real")
print(f"Excluido (union)        : {mask_excl.sum():>7,} filas / {excluded['real_qty'].sum():>12,.0f} u real ({excluded['real_qty'].sum()/df['real_qty'].sum()*100:.1f}%)")
print(f"CORE                    : {len(core):>7,} filas / {core['real_qty'].sum():>12,.0f} u real ({core['real_qty'].sum()/df['real_qty'].sum()*100:.1f}%)")
print(f"Sanity (core+excl=tot)  : {core['real_qty'].sum() + excluded['real_qty'].sum():,.0f} vs {df['real_qty'].sum():,.0f}")


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def metricas(sub, label):
    r = sub["real_qty"].sum()
    f = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    return {
        "grupo": label, "n": len(sub),
        "real": r, "fcst": f,
        "wape_%": ae / r * 100 if r else np.nan,
        "bias_%": e / r * 100 if r else np.nan,
        "fcst_vs_real_%": (f - r) / r * 100 if r else np.nan,
    }

def tabla(data, col, top=None):
    rows = [metricas(sub, str(k)) for k, sub in data.groupby(col, dropna=False)]
    out = pd.DataFrame(rows).sort_values("real", ascending=False)
    if top:
        out = out.head(top)
    return out

fmt = lambda x: f"{x:,.2f}" if isinstance(x, float) else x


# ----------------------------------------------------------------------
# 1. METRICAS GLOBALES CORE vs ORIGINAL
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("1. METRICAS GLOBALES — comparativa")
print("=" * 80)
comp = pd.DataFrame([
    metricas(df, "ORIGINAL"),
    metricas(excluded, "EXCLUIDO"),
    metricas(core, "CORE"),
])
print(comp.to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
# 2. SALUD DE FILAS EN CORE
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("2. SALUD DE FILAS — CORE")
print("=" * 80)
n = len(core)
r0 = (core["real_qty"] == 0).sum()
f0 = (core["forecast_qty"] == 0).sum()
both0 = ((core["real_qty"] == 0) & (core["forecast_qty"] == 0)).sum()
solo_r = ((core["real_qty"] > 0) & (core["forecast_qty"] == 0)).sum()
solo_f = ((core["real_qty"] == 0) & (core["forecast_qty"] > 0)).sum()
active = ((core["real_qty"] > 0) | (core["forecast_qty"] > 0)).sum()
print(f"Filas totales core           : {n:>10,}")
print(f"real == 0                    : {r0:>10,}  ({r0/n*100:5.1f}%)")
print(f"forecast == 0                : {f0:>10,}  ({f0/n*100:5.1f}%)")
print(f"Ambos 0 (inertes)            : {both0:>10,}  ({both0/n*100:5.1f}%)")
print(f"Solo real >0 (falto fcst)    : {solo_r:>10,}  ({solo_r/n*100:5.1f}%)")
print(f"Solo fcst >0 (sobra)         : {solo_f:>10,}  ({solo_f/n*100:5.1f}%)")
print(f"Con actividad                : {active:>10,}  ({active/n*100:5.1f}%)")


# ----------------------------------------------------------------------
# 3-10. DRILLS PROFUNDOS SOBRE CORE
# ----------------------------------------------------------------------
for titulo, col, top in [
    ("3. CORE por target_week_start", "target_week_start", None),
    ("4. CORE por series_type", "series_type", None),
    ("5. CORE por abcxyz", "abcxyz", None),
    ("6. CORE por forecast_zone", "forecast_zone", None),
    ("7. CORE por ciclo_de_vida", "ciclo_de_vida", None),
    ("8. CORE por importancia", "importancia", None),
    ("9. CORE por price_dynamics_segment", "price_dynamics_segment", None),
    ("10. CORE por team_id", "team_id", 15),
]:
    print("\n" + "=" * 80)
    print(titulo)
    print("=" * 80)
    print(tabla(core, col, top=top).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
# 11. CORE por categoria L1 / L2
# ----------------------------------------------------------------------
core["categ_l1"] = core["categ_id"].str.split(" / ").str[0]
core["categ_l2"] = core["categ_id"].str.split(" / ").str[:2].str.join(" / ")

print("\n" + "=" * 80)
print("11a. CORE por categoria L1")
print("=" * 80)
print(tabla(core, "categ_l1").to_string(index=False, float_format=fmt))

print("\n" + "=" * 80)
print("11b. CORE por categoria L2 (top 20 por volumen real)")
print("=" * 80)
print(tabla(core, "categ_l2", top=20).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
# 12-14. TOP SKUs PROBLEMATICOS EN CORE
# ----------------------------------------------------------------------
prod = core.groupby("product_id", as_index=False).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcst=("forecast_qty", "sum"),
    abs_err=("abs_error_qty", "sum"),
    err=("error_qty", "sum"),
)
prod["wape_%"] = prod["abs_err"] / prod["real"].replace(0, np.nan) * 100
prod["bias_%"] = prod["err"] / prod["real"].replace(0, np.nan) * 100
prod["fcst_minus_real"] = prod["fcst"] - prod["real"]
prod["real_minus_fcst"] = prod["real"] - prod["fcst"]

print("\n" + "=" * 80)
print("12. CORE — TOP 20 SKUs por error absoluto")
print("=" * 80)
print(prod.sort_values("abs_err", ascending=False).head(20).to_string(index=False, float_format=fmt))

print("\n" + "=" * 80)
print("13. CORE — TOP 20 SKUs SOBRE-FORECAST (fcst >> real)")
print("=" * 80)
print(prod[prod["fcst"] > 0].sort_values("fcst_minus_real", ascending=False).head(20)
      .to_string(index=False, float_format=fmt))

print("\n" + "=" * 80)
print("14. CORE — TOP 20 SKUs SUB-FORECAST (real >> fcst)")
print("=" * 80)
print(prod.sort_values("real_minus_fcst", ascending=False).head(20)
      .to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
# 15. PIVOT target_week_start x series_type (WAPE)
# ----------------------------------------------------------------------
def pivot_metric(data, idx, cols, metric):
    """metric: 'wape' o 'bias'."""
    g = data.groupby([idx, cols]).agg(
        real=("real_qty", "sum"),
        abs_err=("abs_error_qty", "sum"),
        err=("error_qty", "sum"),
    ).reset_index()
    if metric == "wape":
        g["val"] = g["abs_err"] / g["real"].replace(0, np.nan) * 100
    else:
        g["val"] = g["err"] / g["real"].replace(0, np.nan) * 100
    return g.pivot(index=idx, columns=cols, values="val")

print("\n" + "=" * 80)
print("15. CORE — PIVOT target_week_start x series_type (WAPE %)")
print("=" * 80)
print(pivot_metric(core, "target_week_start", "series_type", "wape").to_string(float_format=fmt))

print("\n" + "=" * 80)
print("16. CORE — PIVOT forecast_zone x abcxyz (BIAS %)")
print("=" * 80)
print(pivot_metric(core, "forecast_zone", "abcxyz", "bias").to_string(float_format=fmt))

print("\n" + "=" * 80)
print("17. CORE — PIVOT ciclo_de_vida x importancia (BIAS %)")
print("=" * 80)
print(pivot_metric(core, "ciclo_de_vida", "importancia", "bias").to_string(float_format=fmt))


# ----------------------------------------------------------------------
# 18. DISTRIBUCION bias_pct en CORE (filas con real>0)
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("18. CORE — distribucion bias_pct (solo filas con real>0)")
print("=" * 80)
with_real = core[core["real_qty"] > 0].copy()
buckets = pd.cut(
    with_real["bias_pct"],
    bins=[-np.inf, -1.0, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 1.0, np.inf],
    labels=["<-100%", "-100..-50%", "-50..-20%", "-20..-5%", "-5..+5%",
            "+5..+20%", "+20..+50%", "+50..+100%", ">+100%"],
)
hist = with_real.groupby(buckets, observed=True).agg(
    filas=("real_qty", "size"),
    real=("real_qty", "sum"),
).reset_index()
hist["%_filas"] = hist["filas"] / hist["filas"].sum() * 100
hist["%_real"] = hist["real"] / hist["real"].sum() * 100
print(hist.to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
# 19. FORECAST DESPERDICIADO (fcst >0 con real=0) por categoria L1
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("19. CORE — FORECAST DESPERDICIADO (fcst>0 y real=0) por categoria L1")
print("=" * 80)
wasted = core[(core["real_qty"] == 0) & (core["forecast_qty"] > 0)].copy()
wast_g = wasted.groupby("categ_l1").agg(
    filas=("forecast_qty", "size"),
    fcst_perdido=("forecast_qty", "sum"),
).reset_index().sort_values("fcst_perdido", ascending=False)
print(wast_g.to_string(index=False, float_format=fmt))
print(f"\nTotal forecast desperdiciado en core: {wasted['forecast_qty'].sum():,.0f} u")

# Como fraccion del forecast total core
fcst_total_core = core["forecast_qty"].sum()
print(f"Forecast total core: {fcst_total_core:,.0f} u")
print(f"Fraccion desperdiciada: {wasted['forecast_qty'].sum()/fcst_total_core*100:.1f}%")


# ----------------------------------------------------------------------
# 20. DEMANDA NO ATENDIDA POR EL MODELO (real>0 y fcst=0) por categoria L1
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("20. CORE — DEMANDA NO PRONOSTICADA (real>0 y fcst=0) por categoria L1")
print("=" * 80)
missed = core[(core["real_qty"] > 0) & (core["forecast_qty"] == 0)].copy()
miss_g = missed.groupby("categ_l1").agg(
    filas=("real_qty", "size"),
    real_no_pronost=("real_qty", "sum"),
).reset_index().sort_values("real_no_pronost", ascending=False)
print(miss_g.to_string(index=False, float_format=fmt))
print(f"\nTotal demanda no pronosticada en core: {missed['real_qty'].sum():,.0f} u")
print(f"Real total core: {core['real_qty'].sum():,.0f} u")
print(f"Fraccion no pronosticada: {missed['real_qty'].sum()/core['real_qty'].sum()*100:.1f}%")

print("\nDONE.")
