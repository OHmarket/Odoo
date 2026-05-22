"""
Validar hipotesis: reemplazar segmentacion por zonas (Z1-Z4) por reglas
sobre el triplete (series_type, ciclo_de_vida, abcxyz).

Pasos:
 1. Matriz triplete con metricas + cuantas zonas distintas convive
 2. Contraste: ¿que tanto agrega ruido la zona vs el triplete?
 3. Propuesta de matriz de reglas natural (4-5 buckets accionables)
 4. Simulacion: ¿cuanto mejora si se cambia de regla zona -> regla triplete?
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).csv"

df = pd.read_csv(PATH, encoding="utf-8", low_memory=False)
for c in ["abs_error_qty", "bias_pct", "cv2", "error_qty", "forecast_qty", "real_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df["categ_id"] = df["categ_id"].fillna("")

# CORE: misma exclusion (cervezas/cigarros/snacks/impulsivos/SJ tienen issues distintos)
EXCLUDE_PAT = r"Cerveza|Cigarrillo|Tabaco|Snack|Impulso"
mask_excl_cat = df["categ_id"].str.contains(EXCLUDE_PAT, case=False, regex=True, na=False)
mask_excl_team = df["team_id"].fillna("").str.contains("Ventas San Jos", case=False)
core = df[~(mask_excl_cat | mask_excl_team)].copy()


# ----------------------------------------------------------------------
# 1. MATRIZ DE TRIPLETES
# ----------------------------------------------------------------------
trip = core.groupby(
    ["abcxyz", "series_type", "ciclo_de_vida"], dropna=False, as_index=False
).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcst=("forecast_qty", "sum"),
    abs_err=("abs_error_qty", "sum"),
    err=("error_qty", "sum"),
    n_zonas_distintas=("forecast_zone", "nunique"),
    n_skus=("product_id", "nunique"),
)
trip["wape_%"] = trip["abs_err"] / trip["real"].replace(0, np.nan) * 100
trip["bias_%"] = trip["err"] / trip["real"].replace(0, np.nan) * 100
trip["%_vol_core"] = trip["real"] / core["real_qty"].sum() * 100
# Filtrar combos sin actividad
trip_act = trip[trip["real"] > 0].copy().sort_values("real", ascending=False)
print("=" * 100)
print(f"1. MATRIZ TRIPLETE (abcxyz x series_type x ciclo_de_vida) — core")
print(f"   Combos con real>0: {len(trip_act)} de {len(trip)} totales")
print("=" * 100)
print(trip_act.head(40).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 2. COMPRESION ZONA: ¿cuanta variabilidad esconde cada zona?
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. ¿Cuantos tripletes distintos hay dentro de cada zona? (alta variedad = zona esconde mix)")
print("=" * 100)
zona_compo = core.groupby("forecast_zone", as_index=False).agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    err=("error_qty", "sum"),
    abs_err=("abs_error_qty", "sum"),
    n_tripletes_distintos=("product_id", lambda s: core.loc[s.index].groupby(["abcxyz", "series_type", "ciclo_de_vida"]).ngroups),
    n_skus=("product_id", "nunique"),
)
zona_compo["wape_%"] = zona_compo["abs_err"] / zona_compo["real"].replace(0, np.nan) * 100
zona_compo["bias_%"] = zona_compo["err"] / zona_compo["real"].replace(0, np.nan) * 100
print(zona_compo.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 3. CONTRASTE: dentro de cada zona, bias por triplete (mostrar dispersion)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. DISPERSION DEL BIAS POR ZONA — tripletes top de cada zona (orden por |real|)")
print("=" * 100)
for z in ["Z1", "Z2", "Z3", "Z4"]:
    sub = core[core["forecast_zone"] == z]
    if len(sub) == 0:
        continue
    g = sub.groupby(["abcxyz", "series_type", "ciclo_de_vida"], as_index=False).agg(
        n=("real_qty", "size"),
        real=("real_qty", "sum"),
        err=("error_qty", "sum"),
        abs_err=("abs_error_qty", "sum"),
    )
    g["bias_%"] = g["err"] / g["real"].replace(0, np.nan) * 100
    g["wape_%"] = g["abs_err"] / g["real"].replace(0, np.nan) * 100
    g_act = g[g["real"] > 0].sort_values("real", ascending=False).head(8)
    bias_range = g_act["bias_%"].max() - g_act["bias_%"].min() if len(g_act) > 1 else 0
    print(f"\n--- {z} (real {sub['real_qty'].sum():,.0f} u, {len(g_act)} tripletes top, rango BIAS={bias_range:.1f} pp) ---")
    print(g_act.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 4. PROPUESTA: matriz de reglas natural por triplete
# ----------------------------------------------------------------------
# Idea: el triplete define un "regimen" sin necesidad de etiqueta de zona.
# Para cada triplete activo asignamos un regimen recomendado.
def regimen_propuesto(row):
    abc = (row["abcxyz"] or "")[:1]   # A / B / C
    xyz = (row["abcxyz"] or "")[-1:]  # X / Y / Z
    s = row["series_type"]
    c = row["ciclo_de_vida"]

    # 1. Estado terminal: sin forecast
    if c in ("dead", "declining"):
        return "REG-0  no_forecast (terminal)"
    if s == "no_signal" and abc == "C":
        return "REG-0  no_forecast (no senal + C)"

    # 2. Smooth bien comportado
    if s == "smooth":
        if abc == "A":
            return "REG-1  smooth_full (mu + SI completo)"
        if abc == "B":
            return "REG-2  smooth_moderado"
        return "REG-3  smooth_conservador (C)"

    # 3. Erratic: media movil + cap suave
    if s == "erratic":
        return "REG-4  erratic_cap_120"   # cap +20% sobre mu

    # 4. Lumpy: depende de A/B vs C
    if s == "lumpy":
        if abc in ("A", "B"):
            return "REG-5  lumpy_proteccion (mu sin cap inferior, cap superior 110)"
        return "REG-6  lumpy_C (mu floor 0.5)"

    # 5. Intermittent / no_signal residuales
    if s in ("intermittent", "no_signal"):
        return "REG-7  intermittent_floor (mu * 0.5)"

    # 6. seasonal / ramp_up especiales
    if c == "seasonal":
        return "REG-8  seasonal_SI_amplificado"
    if c == "ramp_up":
        return "REG-9  ramp_up_uplift (trayectoria creciente)"

    return "REG-?  revisar"

trip_act["regimen"] = trip_act.apply(regimen_propuesto, axis=1)

# Verificar cuantos regimenes salen
print("\n" + "=" * 100)
print("4. PROPUESTA — agregar por regimen sugerido")
print("=" * 100)
reg = trip_act.groupby("regimen", as_index=False).agg(
    combos=("regimen", "size"),
    n_filas=("n", "sum"),
    n_skus=("n_skus", "sum"),
    real=("real", "sum"),
    fcst=("fcst", "sum"),
    abs_err=("abs_err", "sum"),
    err=("err", "sum"),
)
reg["wape_%"] = reg["abs_err"] / reg["real"].replace(0, np.nan) * 100
reg["bias_%"] = reg["err"] / reg["real"].replace(0, np.nan) * 100
reg["%_vol_core"] = reg["real"] / core["real_qty"].sum() * 100
print(reg.sort_values("real", ascending=False).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 5. SOLAPE ZONA vs REGIMEN — matriz cruzada
# ----------------------------------------------------------------------
core_t = core.merge(
    trip_act[["abcxyz", "series_type", "ciclo_de_vida", "regimen"]],
    on=["abcxyz", "series_type", "ciclo_de_vida"], how="left"
)
core_t["regimen"] = core_t["regimen"].fillna("REG-? sin asignacion")

print("\n" + "=" * 100)
print("5. CROSS — ¿como se distribuye cada zona en regimenes propuestos? (% del real de la zona)")
print("=" * 100)
cross = core_t.groupby(["forecast_zone", "regimen"]).agg(real=("real_qty", "sum")).reset_index()
pivot = cross.pivot(index="forecast_zone", columns="regimen", values="real").fillna(0)
pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100
print(pivot_pct.to_string(float_format=lambda x: f"{x:5.1f}"))


# ----------------------------------------------------------------------
# 6. METRICAS POR REGIMEN — ¿cada uno tiene comportamiento coherente?
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. METRICAS POR REGIMEN — ¿son grupos coherentes?")
print("=" * 100)
print("(Si dispersion BIAS dentro de regimen es baja, el agrupamiento es bueno)")
reg_disp = core_t.groupby("regimen").agg(
    n=("real_qty", "size"),
    real=("real_qty", "sum"),
    fcst=("forecast_qty", "sum"),
    abs_err=("abs_error_qty", "sum"),
    err=("error_qty", "sum"),
).reset_index()
reg_disp["wape_%"] = reg_disp["abs_err"] / reg_disp["real"].replace(0, np.nan) * 100
reg_disp["bias_%"] = reg_disp["err"] / reg_disp["real"].replace(0, np.nan) * 100
print(reg_disp.sort_values("real", ascending=False).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 7. ZONA vs REGIMEN: ¿cual segmenta mejor?
# ----------------------------------------------------------------------
def coef_variacion_bias(grupos):
    """std del BIAS ponderado por volumen — proxy de "qué tan revuelto" está el grupo."""
    if grupos.empty:
        return np.nan
    bias_vals = grupos["bias_%"].values
    weights = grupos["real"].values
    media = np.average(bias_vals, weights=weights)
    var = np.average((bias_vals - media) ** 2, weights=weights)
    return np.sqrt(var)


# Por zona — variabilidad interna del bias
print("\n" + "=" * 100)
print("7. CALIDAD DE SEGMENTACION — std interna del BIAS (menor = grupo mas homogeneo)")
print("=" * 100)
zona_stats = []
for z, sub in core.groupby("forecast_zone"):
    g = sub.groupby(["abcxyz", "series_type", "ciclo_de_vida"], as_index=False).agg(
        real=("real_qty", "sum"), err=("error_qty", "sum")
    )
    g = g[g["real"] > 0].copy()
    g["bias_%"] = g["err"] / g["real"] * 100
    zona_stats.append({"agrupador": f"forecast_zone={z}", "real": sub["real_qty"].sum(),
                       "std_bias_pp": coef_variacion_bias(g)})

reg_stats = []
for r, sub in core_t.groupby("regimen"):
    g = sub.groupby(["abcxyz", "series_type", "ciclo_de_vida"], as_index=False).agg(
        real=("real_qty", "sum"), err=("error_qty", "sum")
    )
    g = g[g["real"] > 0].copy()
    g["bias_%"] = g["err"] / g["real"] * 100
    reg_stats.append({"agrupador": f"regimen={r}", "real": sub["real_qty"].sum(),
                      "std_bias_pp": coef_variacion_bias(g)})

stats_df = pd.DataFrame(zona_stats + reg_stats)
print(stats_df.sort_values("real", ascending=False).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 8. EXPORTAR MATRIZ COMPLETA PARA REVISION
# ----------------------------------------------------------------------
out = trip_act[[
    "abcxyz", "series_type", "ciclo_de_vida", "regimen",
    "n", "n_skus", "n_zonas_distintas", "real", "fcst",
    "wape_%", "bias_%", "%_vol_core"
]].sort_values("real", ascending=False)
out_path = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_bt_matriz_tripletes.csv"
out.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nExportado: {out_path}")
print("\nDONE.")
