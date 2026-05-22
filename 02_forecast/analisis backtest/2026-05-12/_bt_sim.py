"""
Simulaciones de fixes A, B, C sobre la cola larga del backtest core.

Fix A — Reclasificar SKUs constantes-en-cola: usar flat-mean(real) por (product,team).
        Es un proxy de lo que un modelo "smooth bien calibrado" pronosticaria.
Fix B — Revertir caps P6: para BZ cap 0.8x lo dividimos por 0.8; para AZ cap 1.2x
        lo dividimos por 1.2 (no toca lumpy puro sin cap).
Fix C — Rescate Z4 no_forecast: para SKUs en cola con forecast_qty==0 todas las
        semanas y real_qty>0 en >=2 semanas, asignar flat-mean(real).

Para cada fix se compara WAPE/BIAS vs baseline cola.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).csv"

df = pd.read_csv(PATH, encoding="utf-8", low_memory=False)
for c in ["abs_error_qty", "bias_pct", "cv2", "error_qty", "forecast_qty", "real_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df["categ_id"] = df["categ_id"].fillna("")

# CORE
EXCLUDE_PAT = r"Cerveza|Cigarrillo|Tabaco|Snack|Impulso"
mask_excl_cat = df["categ_id"].str.contains(EXCLUDE_PAT, case=False, regex=True, na=False)
mask_excl_team = df["team_id"].fillna("").str.contains("Ventas San Jos", case=False)
core = df[~(mask_excl_cat | mask_excl_team)].copy()

COLA_ABCXYZ = {"AZ", "BZ", "CZ", "CY", "CX"}
COLA_SERIES = {"lumpy", "no_signal", "intermittent"}
core["es_cola"] = (
    (core["forecast_zone"] == "Z4")
    | core["abcxyz"].isin(COLA_ABCXYZ)
    | core["series_type"].isin(COLA_SERIES)
)
cola = core[core["es_cola"]].copy().reset_index(drop=True)


def report(real, fcst, label):
    """Imprime metricas y devuelve dict."""
    ae = np.abs(real - fcst).sum()
    e = (real - fcst).sum()
    r = real.sum()
    return {
        "scenario": label,
        "real": r,
        "fcst": fcst.sum(),
        "abs_err": ae,
        "wape_%": ae / r * 100 if r else np.nan,
        "bias_%": e / r * 100 if r else np.nan,
    }


# ----------------------------------------------------------------------
# BASELINE
# ----------------------------------------------------------------------
baseline = report(cola["real_qty"], cola["forecast_qty"], "BASELINE cola")

# ----------------------------------------------------------------------
# Caracterizar por SKU x team
# ----------------------------------------------------------------------
agg = cola.groupby(["product_id", "team_id"], as_index=False).agg(
    n_semanas=("real_qty", "size"),
    real_total=("real_qty", "sum"),
    real_mean=("real_qty", "mean"),
    fcst_total=("forecast_qty", "sum"),
    n_semanas_con_venta=("real_qty", lambda s: (s > 0).sum()),
    n_semanas_con_fcst=("forecast_qty", lambda s: (s > 0).sum()),
)
agg["intensidad_venta"] = agg["n_semanas_con_venta"] / agg["n_semanas"]
agg["mu_por_sem"] = agg["real_total"] / agg["n_semanas"]


# ----------------------------------------------------------------------
# FIX A — Reclasificar constantes (>70% intensidad) en cola
# ----------------------------------------------------------------------
constantes = agg[(agg["intensidad_venta"] > 0.70) & (agg["mu_por_sem"] > 1.0)]
constantes_keys = set(zip(constantes["product_id"], constantes["team_id"]))
print(f"\nFix A — SKUs (product,team) constantes en cola: {len(constantes_keys):,}")
print(f"        Cobertura: {constantes['real_total'].sum():,.0f} u real / {cola['real_qty'].sum():,.0f} u cola")

cola["key"] = list(zip(cola["product_id"], cola["team_id"]))
cola["mu_sku_team"] = cola["key"].map(dict(zip(zip(agg["product_id"], agg["team_id"]), agg["real_mean"])))

mask_A = cola["key"].isin(constantes_keys)
fcst_A = cola["forecast_qty"].copy()
fcst_A[mask_A] = cola.loc[mask_A, "mu_sku_team"]   # flat-mean simulado
fix_A = report(cola["real_qty"], fcst_A, "FIX A — reclasificar constantes")

# Sensibilidad: que pasa si el smooth simulado captura solo 80% del mean (mas conservador)
fcst_A_cons = cola["forecast_qty"].copy()
fcst_A_cons[mask_A] = cola.loc[mask_A, "mu_sku_team"] * 0.85
fix_A_cons = report(cola["real_qty"], fcst_A_cons, "FIX A — variante 0.85x")


# ----------------------------------------------------------------------
# FIX B — Revertir caps P6
# ----------------------------------------------------------------------
# Asuncion: el forecast actual de BZ-lumpy esta multiplicado por 0.8,
#           el de AZ-lumpy multiplicado por 1.2 (el cap del codigo).
# Restaurar dividiendo. Solo aplica donde forecast >0 (no toca filas inertes).
mask_BZ = (cola["abcxyz"] == "BZ") & (cola["series_type"] == "lumpy") & (cola["forecast_qty"] > 0)
mask_AZ = (cola["abcxyz"] == "AZ") & (cola["series_type"] == "lumpy") & (cola["forecast_qty"] > 0)
mask_CZ_cap = (cola["abcxyz"] == "CZ") & (cola["series_type"] == "lumpy") & (cola["forecast_qty"] > 0)
print(f"\nFix B — filas BZ-lumpy: {mask_BZ.sum():,} | AZ-lumpy: {mask_AZ.sum():,} | CZ-lumpy: {mask_CZ_cap.sum():,}")

fcst_B = cola["forecast_qty"].copy()
fcst_B[mask_BZ] = fcst_B[mask_BZ] / 0.8     # cap BZ inverso
fcst_B[mask_AZ] = fcst_B[mask_AZ] / 1.2     # cap AZ inverso
# CZ no toca: el cap 1.2 es para AZ/CZ pero ya vimos que CZ-lumpy es sub-forecast (+15%), reverter empeora
fix_B = report(cola["real_qty"], fcst_B, "FIX B — revertir caps BZ y AZ")


# ----------------------------------------------------------------------
# FIX C — Rescate Z4 no_forecast
# ----------------------------------------------------------------------
# SKUs con forecast_qty==0 TODAS las semanas pero real_qty>0 en >=2 semanas
rescate = agg[(agg["fcst_total"] == 0) & (agg["n_semanas_con_venta"] >= 2)]
rescate_keys = set(zip(rescate["product_id"], rescate["team_id"]))
print(f"\nFix C — SKUs rescate (forecast siempre 0, venta en >=2 sem): {len(rescate_keys):,}")
print(f"        Cobertura demanda: {rescate['real_total'].sum():,.0f} u")

mask_C = cola["key"].isin(rescate_keys)
fcst_C = cola["forecast_qty"].copy()
fcst_C[mask_C] = cola.loc[mask_C, "mu_sku_team"]
fix_C = report(cola["real_qty"], fcst_C, "FIX C — rescate Z4 no_forecast")


# ----------------------------------------------------------------------
# COMBINADO A+B+C
# ----------------------------------------------------------------------
fcst_ABC = cola["forecast_qty"].copy()
fcst_ABC[mask_BZ] = fcst_ABC[mask_BZ] / 0.8
fcst_ABC[mask_AZ] = fcst_ABC[mask_AZ] / 1.2
fcst_ABC[mask_A] = cola.loc[mask_A, "mu_sku_team"]
fcst_ABC[mask_C] = cola.loc[mask_C, "mu_sku_team"]
fix_ABC = report(cola["real_qty"], fcst_ABC, "FIX A+B+C combinado")


# ----------------------------------------------------------------------
# IMPACTO A NIVEL CORE TOTAL
# ----------------------------------------------------------------------
# Replicar el ABC en core completo (cabeza no cambia)
core["key"] = list(zip(core["product_id"], core["team_id"]))
core["mu_sku_team_core"] = core["key"].map(
    dict(zip(zip(agg["product_id"], agg["team_id"]), agg["real_mean"]))
)
mask_A_core = core["key"].isin(constantes_keys) & core["es_cola"]
mask_BZ_core = core["es_cola"] & (core["abcxyz"] == "BZ") & (core["series_type"] == "lumpy") & (core["forecast_qty"] > 0)
mask_AZ_core = core["es_cola"] & (core["abcxyz"] == "AZ") & (core["series_type"] == "lumpy") & (core["forecast_qty"] > 0)
mask_C_core = core["key"].isin(rescate_keys) & core["es_cola"]

fcst_core_ABC = core["forecast_qty"].copy()
fcst_core_ABC[mask_BZ_core] = fcst_core_ABC[mask_BZ_core] / 0.8
fcst_core_ABC[mask_AZ_core] = fcst_core_ABC[mask_AZ_core] / 1.2
fcst_core_ABC[mask_A_core] = core.loc[mask_A_core, "mu_sku_team_core"]
fcst_core_ABC[mask_C_core] = core.loc[mask_C_core, "mu_sku_team_core"]

core_baseline = report(core["real_qty"], core["forecast_qty"], "CORE baseline")
core_ABC = report(core["real_qty"], fcst_core_ABC, "CORE con A+B+C")


# ----------------------------------------------------------------------
# RESULTADOS
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("RESULTADOS — METRICAS COLA")
print("=" * 80)
res = pd.DataFrame([baseline, fix_A, fix_A_cons, fix_B, fix_C, fix_ABC])
res["delta_wape_pp"] = res["wape_%"] - baseline["wape_%"]
res["delta_bias_pp"] = res["bias_%"] - baseline["bias_%"]
print(res.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 80)
print("RESULTADOS — METRICAS CORE COMPLETO (cabeza no cambia)")
print("=" * 80)
res2 = pd.DataFrame([core_baseline, core_ABC])
res2["delta_wape_pp"] = res2["wape_%"] - core_baseline["wape_%"]
res2["delta_bias_pp"] = res2["bias_%"] - core_baseline["bias_%"]
print(res2.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# DESCOMPOSICION DEL EFECTO POR FIX
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("DESCOMPOSICION — efecto incremental al aplicar fixes en orden A -> B -> C")
print("=" * 80)
fcst_step1 = cola["forecast_qty"].copy()
fcst_step1[mask_A] = cola.loc[mask_A, "mu_sku_team"]
step1 = report(cola["real_qty"], fcst_step1, "Solo A")

fcst_step2 = fcst_step1.copy()
fcst_step2[mask_BZ] = fcst_step2[mask_BZ] / 0.8
fcst_step2[mask_AZ] = fcst_step2[mask_AZ] / 1.2
step2 = report(cola["real_qty"], fcst_step2, "A + B")

fcst_step3 = fcst_step2.copy()
fcst_step3[mask_C] = cola.loc[mask_C, "mu_sku_team"]
step3 = report(cola["real_qty"], fcst_step3, "A + B + C")

steps = pd.DataFrame([baseline, step1, step2, step3])
steps["delta_wape_pp"] = steps["wape_%"] - baseline["wape_%"]
steps["delta_bias_pp"] = steps["bias_%"] - baseline["bias_%"]
print(steps.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# ¿Que SKUs ya no quedan en top sub-forecast tras Fix A?
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("VALIDACION FIX A — Top 15 sub-forecast en cola DESPUES de Fix A")
print("=" * 80)
cola_post_A = cola.copy()
cola_post_A["forecast_post_A"] = fcst_A
cola_post_A["abs_err_post_A"] = (cola_post_A["real_qty"] - cola_post_A["forecast_post_A"]).abs()
cola_post_A["err_post_A"] = cola_post_A["real_qty"] - cola_post_A["forecast_post_A"]

prod_post = cola_post_A.groupby("product_id", as_index=False).agg(
    real=("real_qty", "sum"),
    fcst_post=("forecast_post_A", "sum"),
    abs_err_post=("abs_err_post_A", "sum"),
    err_post=("err_post_A", "sum"),
).sort_values("err_post", ascending=False).head(15)
print(prod_post.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\nDONE.")
