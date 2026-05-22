"""
Drill especifico sobre la COLA LARGA del backtest (core limpio).
Cola = Z4 OR abcxyz en {AZ,BZ,CZ,CY,CX} OR series_type en {lumpy,no_signal,intermittent}.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).csv"

df = pd.read_csv(PATH, encoding="utf-8", low_memory=False)
for c in ["abs_error_qty", "bias_pct", "cv2", "error_qty", "forecast_qty", "real_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df["categ_id"] = df["categ_id"].fillna("")

# CORE: misma exclusion que antes
EXCLUDE_PAT = r"Cerveza|Cigarrillo|Tabaco|Snack|Impulso"
mask_excl_cat = df["categ_id"].str.contains(EXCLUDE_PAT, case=False, regex=True, na=False)
mask_excl_team = df["team_id"].fillna("").str.contains("Ventas San Jos", case=False)
core = df[~(mask_excl_cat | mask_excl_team)].copy()

# COLA: definicion operativa
COLA_ABCXYZ = {"AZ", "BZ", "CZ", "CY", "CX"}
COLA_SERIES = {"lumpy", "no_signal", "intermittent"}
core["es_cola"] = (
    (core["forecast_zone"] == "Z4") |
    core["abcxyz"].isin(COLA_ABCXYZ) |
    core["series_type"].isin(COLA_SERIES)
)
cola = core[core["es_cola"]].copy()
cabeza = core[~core["es_cola"]].copy()


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
        "fcst_desperdiciado": sub[(sub["real_qty"] == 0) & (sub["forecast_qty"] > 0)]["forecast_qty"].sum(),
    }

fmt = lambda x: f"{x:,.2f}" if isinstance(x, float) else x


print("=" * 80)
print("1. DEFINICION DE COLA — CORE vs CABEZA vs COLA")
print("=" * 80)
comp = pd.DataFrame([
    metricas(core, "CORE TOTAL"),
    metricas(cabeza, "CABEZA (Z1/Z2/Z3 + AX/AY/BY/BX + smooth/erratic)"),
    metricas(cola, "COLA (Z4 OR abcxyz_Z OR lumpy/no_signal)"),
])
print(comp.to_string(index=False, float_format=fmt))
print(f"\nCola = {len(cola)/len(core)*100:.1f}% filas core / {cola['real_qty'].sum()/core['real_qty'].sum()*100:.1f}% volumen real core")


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("2. SALUD DE FILAS — COLA")
print("=" * 80)
n = len(cola)
both0 = ((cola["real_qty"] == 0) & (cola["forecast_qty"] == 0)).sum()
solo_r = ((cola["real_qty"] > 0) & (cola["forecast_qty"] == 0)).sum()
solo_f = ((cola["real_qty"] == 0) & (cola["forecast_qty"] > 0)).sum()
active = ((cola["real_qty"] > 0) | (cola["forecast_qty"] > 0)).sum()
print(f"Filas cola                : {n:>10,}")
print(f"Ambos 0 (inertes)         : {both0:>10,}  ({both0/n*100:5.1f}%)")
print(f"Solo real (falto fcst)    : {solo_r:>10,}  ({solo_r/n*100:5.1f}%)")
print(f"Solo fcst (sobra)         : {solo_f:>10,}  ({solo_f/n*100:5.1f}%)")
print(f"Con actividad             : {active:>10,}  ({active/n*100:5.1f}%)")


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("3. DESCOMPOSICION COLA por abcxyz x series_type (BIAS %)")
print("=" * 80)
g = cola.groupby(["abcxyz", "series_type"]).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcst=("forecast_qty", "sum"),
    err=("error_qty", "sum"),
).reset_index()
g["bias_%"] = g["err"] / g["real"].replace(0, np.nan) * 100
g["wape_%"] = (g["real"] - g["fcst"]).abs() / g["real"].replace(0, np.nan) * 100
print(g.sort_values("real", ascending=False).head(30).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("4. COLA — caracterizacion por SKU (no por fila)")
print("=" * 80)
prod = cola.groupby("product_id", as_index=False).agg(
    n_semanas=("real_qty", "size"),
    real_total=("real_qty", "sum"),
    fcst_total=("forecast_qty", "sum"),
    n_semanas_con_venta=("real_qty", lambda s: (s > 0).sum()),
    n_semanas_con_fcst=("forecast_qty", lambda s: (s > 0).sum()),
)
prod["intensidad_venta"] = prod["n_semanas_con_venta"] / prod["n_semanas"]
prod["intensidad_fcst"] = prod["n_semanas_con_fcst"] / prod["n_semanas"]

# Buckets por intensidad de venta
prod["bucket_venta"] = pd.cut(
    prod["intensidad_venta"],
    bins=[-0.01, 0, 0.15, 0.40, 0.70, 1.01],
    labels=["sin_venta", "esporadica (1-15%)", "lumpy (15-40%)", "regular (40-70%)", "constante (>70%)"],
)
print("\nSKUs de cola por intensidad de venta (fraccion de semanas con venta):")
print(prod.groupby("bucket_venta", observed=True).agg(
    skus=("product_id", "size"),
    real_total=("real_total", "sum"),
    fcst_total=("fcst_total", "sum"),
).to_string(float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("5. COLA — SKUs problema A: SIN venta pero CON forecast (poda candidatos)")
print("=" * 80)
candidato_poda = prod[(prod["real_total"] == 0) & (prod["fcst_total"] > 0)].copy()
print(f"SKUs sin venta en 7 sem pero con forecast >0: {len(candidato_poda):,}")
print(f"Forecast desperdiciado por ellos:             {candidato_poda['fcst_total'].sum():,.0f} u")
print(f"Promedio por SKU:                             {candidato_poda['fcst_total'].mean():.2f} u")
print(f"Top 15 SKUs candidatos a poda:")
print(candidato_poda.sort_values("fcst_total", ascending=False).head(15).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("6. COLA — SKUs problema B: CON venta pero SIN forecast (sub-pronostico)")
print("=" * 80)
sub_pron = prod[(prod["real_total"] > 0) & (prod["fcst_total"] == 0)].copy()
print(f"SKUs con venta pero forecast=0 en todo el periodo: {len(sub_pron):,}")
print(f"Demanda real perdida:                              {sub_pron['real_total'].sum():,.0f} u")
print(f"Top 15:")
print(sub_pron.sort_values("real_total", ascending=False).head(15).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("7. COLA — TOP 20 SKUs SOBRE-FORECAST (fcst >> real, indica caps debiles)")
print("=" * 80)
prod["abs_err"] = (prod["real_total"] - prod["fcst_total"]).abs()
prod["fcst_minus_real"] = prod["fcst_total"] - prod["real_total"]
print(prod[prod["fcst_total"] > 0].sort_values("fcst_minus_real", ascending=False).head(20).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("8. COLA — TOP 20 SKUs SUB-FORECAST (real >> fcst, indica caps muy estrictos)")
print("=" * 80)
prod["real_minus_fcst"] = prod["real_total"] - prod["fcst_total"]
print(prod[prod["real_total"] > 0].sort_values("real_minus_fcst", ascending=False).head(20).to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("9. COLA — SIMULACION: efecto de podar SKUs sin venta")
print("=" * 80)
# Mantener cola pero forzar forecast=0 a SKUs sin venta en periodo
skus_poda = set(candidato_poda["product_id"])
cola_poda = cola.copy()
mask_poda = cola_poda["product_id"].isin(skus_poda)
cola_poda.loc[mask_poda, "forecast_qty_sim"] = 0
cola_poda.loc[~mask_poda, "forecast_qty_sim"] = cola_poda.loc[~mask_poda, "forecast_qty"]
cola_poda["abs_err_sim"] = (cola_poda["real_qty"] - cola_poda["forecast_qty_sim"]).abs()
cola_poda["err_sim"] = cola_poda["real_qty"] - cola_poda["forecast_qty_sim"]

r = cola_poda["real_qty"].sum()
ae_now = cola["abs_error_qty"].sum()
ae_sim = cola_poda["abs_err_sim"].sum()
e_sim = cola_poda["err_sim"].sum()
print(f"WAPE actual cola:      {ae_now/r*100:.2f}%")
print(f"WAPE simulado (poda):  {ae_sim/r*100:.2f}%   (delta: {(ae_sim-ae_now)/r*100:+.2f} pp)")
print(f"BIAS simulado (poda):  {e_sim/r*100:.2f}%")
print(f"Forecast core total recuperado por poda: {cola[mask_poda]['forecast_qty'].sum():,.0f} u")


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("10. COLA — SIMULACION: aplicar uplift +15% al sub-forecast (CZ + lumpy)")
print("=" * 80)
# Hipotesis: caps P6 muy estrictos en BZ (0.8x), corregir a 1.0x
# Equivalente: subir forecast actual de Z-lumpy un factor.
uplift_mask = cola["abcxyz"].isin(["CZ", "BZ", "AZ"]) | (cola["series_type"] == "lumpy")
factor_pruebas = [1.05, 1.10, 1.15, 1.20, 1.30]
print("Factor | WAPE % | BIAS %")
for k in factor_pruebas:
    f_sim = np.where(uplift_mask, cola["forecast_qty"] * k, cola["forecast_qty"])
    ae = np.abs(cola["real_qty"] - f_sim).sum()
    e = (cola["real_qty"] - f_sim).sum()
    print(f"{k:.2f}x  | {ae/r*100:6.2f}% | {e/r*100:+6.2f}%")


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("11. COLA — caracterizacion temporal (semana x bias_signo)")
print("=" * 80)
cola["bias_dir"] = np.where(
    cola["forecast_qty"] > cola["real_qty"], "sobre",
    np.where(cola["forecast_qty"] < cola["real_qty"], "sub", "exacto")
)
pivot = cola.groupby(["target_week_start", "bias_dir"]).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcst=("forecast_qty", "sum"),
).reset_index()
print(pivot.to_string(index=False, float_format=fmt))


# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("12. COLA — Cuantos SKUs unicos hay y cuantos generan 80% del error")
print("=" * 80)
prod_sorted = prod.sort_values("abs_err", ascending=False).reset_index(drop=True)
prod_sorted["cum_err"] = prod_sorted["abs_err"].cumsum()
prod_sorted["cum_err_pct"] = prod_sorted["cum_err"] / prod_sorted["abs_err"].sum() * 100
total_skus_cola = len(prod_sorted)
skus_80 = (prod_sorted["cum_err_pct"] <= 80).sum() + 1
print(f"Total SKUs unicos en cola: {total_skus_cola:,}")
print(f"SKUs que acumulan 80% del error absoluto: {skus_80:,} ({skus_80/total_skus_cola*100:.1f}%)")
print(f"SKUs que acumulan 50% del error absoluto: {(prod_sorted['cum_err_pct'] <= 50).sum() + 1:,}")
print(f"Error absoluto total cola: {prod_sorted['abs_err'].sum():,.0f} u")

print("\nDONE.")
