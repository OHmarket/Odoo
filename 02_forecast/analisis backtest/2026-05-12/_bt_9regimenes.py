"""
Simulacion completa: aplicar los 9 regimenes propuestos al core y medir impacto.

3 escenarios por regimen:
 - BASELINE         : forecast actual del CSV (sin tocar)
 - SIM_RULE         : aplicar regla parametrica por regimen (mu_sku_team con factor)
 - ORACLE_MEAN      : forecast = mean(real) por (prod,team) — techo teorico

Las "reglas" por regimen son:
 REG-0  no_forecast        : forecast = 0
 REG-1  smooth_full        : forecast = mu * 1.00  (aplica SI implicito via mean)
 REG-2  smooth_moderado    : forecast = mu * 0.95
 REG-3  smooth_conservador : forecast = mu * 0.90
 REG-4  erratic_cap_120    : forecast = clip(mu, mu*0.85, mu*1.15)  + uso mu
 REG-5  lumpy_proteccion   : forecast = mu * 1.00  (sin cap inferior)
 REG-6  lumpy_C_floor      : forecast = max(mu, 0.3) si intensidad>=0.3, else mu*0.5
 REG-7  intermittent_floor : forecast = mu * 0.5
 REG-8  seasonal_amplif    : forecast = mu * 1.10
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
core = df[~(mask_excl_cat | mask_excl_team)].copy().reset_index(drop=True)


# ----------------------------------------------------------------------
# Asignacion de regimen por fila
# ----------------------------------------------------------------------
def regimen_de(row):
    abc_letter = (row["abcxyz"] or "")[:1] if isinstance(row["abcxyz"], str) else ""
    abc_xyz = (row["abcxyz"] or "")[-1:] if isinstance(row["abcxyz"], str) else ""
    s = row["series_type"]
    c = row["ciclo_de_vida"]

    if c in ("dead", "declining"):
        return "REG-0"
    if c == "seasonal":
        return "REG-8"
    if c == "ramp_up":
        return "REG-1"
    if s == "no_signal" and abc_letter == "C":
        return "REG-0"
    if s == "smooth":
        if abc_letter == "A":
            return "REG-1"
        if abc_letter == "B":
            return "REG-2"
        return "REG-3"
    if s == "erratic":
        return "REG-4"
    if s == "lumpy":
        return "REG-5" if abc_letter in ("A", "B") else "REG-6"
    if s in ("intermittent", "no_signal"):
        return "REG-7"
    return "REG-?"

core["regimen"] = core.apply(regimen_de, axis=1)


# ----------------------------------------------------------------------
# Mu por (product, team)
# ----------------------------------------------------------------------
mu_st = core.groupby(["product_id", "team_id"]).agg(
    mu=("real_qty", "mean"),
    n_sem=("real_qty", "size"),
    n_con_venta=("real_qty", lambda s: (s > 0).sum()),
).reset_index()
mu_st["intensidad"] = mu_st["n_con_venta"] / mu_st["n_sem"]
mu_st_map = mu_st.set_index(["product_id", "team_id"])[["mu", "intensidad"]].to_dict("index")

def lookup_mu(row):
    d = mu_st_map.get((row["product_id"], row["team_id"]), {"mu": 0.0, "intensidad": 0.0})
    return d["mu"], d["intensidad"]

mu_vals, int_vals = zip(*core.apply(lookup_mu, axis=1))
core["mu_sku_team"] = mu_vals
core["intensidad"] = int_vals


# ----------------------------------------------------------------------
# Aplicar reglas
# ----------------------------------------------------------------------
def aplica_regla(row):
    r = row["regimen"]
    mu = row["mu_sku_team"]
    inten = row["intensidad"]
    if r == "REG-0":
        return 0.0
    if r == "REG-1":
        return mu * 1.00
    if r == "REG-2":
        return mu * 0.95
    if r == "REG-3":
        return mu * 0.90
    if r == "REG-4":
        return mu * 1.00
    if r == "REG-5":
        return mu * 1.00
    if r == "REG-6":
        return max(mu, 0.3) if inten >= 0.3 else mu * 0.5
    if r == "REG-7":
        return mu * 0.5
    if r == "REG-8":
        return mu * 1.10
    return row["forecast_qty"]

core["fcst_sim_rule"] = core.apply(aplica_regla, axis=1)
core["fcst_oracle"] = core["mu_sku_team"]  # mean(real) puro


# ----------------------------------------------------------------------
# Metricas por regimen y total
# ----------------------------------------------------------------------
def metricas(real, fcst):
    ae = np.abs(real - fcst).sum()
    e = (real - fcst).sum()
    r = real.sum()
    return {
        "real": r,
        "fcst": fcst.sum(),
        "wape_%": ae / r * 100 if r else np.nan,
        "bias_%": e / r * 100 if r else np.nan,
        "abs_err": ae,
    }

# Por regimen
print("=" * 120)
print("METRICAS POR REGIMEN — BASELINE vs SIM_RULE vs ORACLE")
print("=" * 120)
out_rows = []
for reg in sorted(core["regimen"].unique()):
    sub = core[core["regimen"] == reg]
    base = metricas(sub["real_qty"], sub["forecast_qty"])
    sim = metricas(sub["real_qty"], sub["fcst_sim_rule"])
    orc = metricas(sub["real_qty"], sub["fcst_oracle"])
    out_rows.append({
        "regimen": reg,
        "n_filas": len(sub),
        "real": base["real"],
        "BASE wape_%": base["wape_%"],
        "BASE bias_%": base["bias_%"],
        "SIM wape_%": sim["wape_%"],
        "SIM bias_%": sim["bias_%"],
        "ORC wape_%": orc["wape_%"],
        "ORC bias_%": orc["bias_%"],
        "delta_wape_sim": sim["wape_%"] - base["wape_%"] if base["wape_%"] else np.nan,
        "delta_bias_sim": sim["bias_%"] - base["bias_%"] if base["bias_%"] else np.nan,
    })
res = pd.DataFrame(out_rows).sort_values("real", ascending=False)
print(res.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# Total core
# ----------------------------------------------------------------------
print("\n" + "=" * 120)
print("TOTAL CORE — comparativa")
print("=" * 120)
tot = pd.DataFrame([
    {"scenario": "BASELINE", **metricas(core["real_qty"], core["forecast_qty"])},
    {"scenario": "SIM_RULE 9 regimenes", **metricas(core["real_qty"], core["fcst_sim_rule"])},
    {"scenario": "ORACLE mean(real)", **metricas(core["real_qty"], core["fcst_oracle"])},
])
print(tot.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# Distribucion de regimenes en core
# ----------------------------------------------------------------------
print("\n" + "=" * 120)
print("DISTRIBUCION DE FILAS Y VOLUMEN POR REGIMEN")
print("=" * 120)
dist = core.groupby("regimen").agg(
    filas=("real_qty", "size"),
    real=("real_qty", "sum"),
    skus=("product_id", "nunique"),
).reset_index().sort_values("real", ascending=False)
dist["%_filas"] = dist["filas"] / len(core) * 100
dist["%_real"] = dist["real"] / core["real_qty"].sum() * 100
print(dist.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# Sensibilidad: variar factor de REG-1 (el que mas pesa)
# ----------------------------------------------------------------------
print("\n" + "=" * 120)
print("SENSIBILIDAD — afinar factor de cada regimen (busqueda lineal)")
print("=" * 120)
print("(Para cada regimen, factor que minimiza WAPE manteniendo |BIAS|<5%)")
for reg in sorted(core["regimen"].unique()):
    sub = core[core["regimen"] == reg].copy()
    r = sub["real_qty"].sum()
    if r == 0:
        continue
    mu_base = sub["mu_sku_team"].values
    real_v = sub["real_qty"].values
    best = None
    for f in [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5]:
        f_sim = mu_base * f
        ae = np.abs(real_v - f_sim).sum()
        e = (real_v - f_sim).sum()
        wape = ae / r * 100
        bias = e / r * 100
        if best is None or wape < best[1]:
            best = (f, wape, bias)
    print(f"  {reg}: factor optimo = {best[0]:.2f}  WAPE = {best[1]:6.2f}%  BIAS = {best[2]:+6.2f}%")


# ----------------------------------------------------------------------
# Simulacion con factores optimos
# ----------------------------------------------------------------------
print("\n" + "=" * 120)
print("SIM_OPTIM — aplicar factor optimo por regimen")
print("=" * 120)
factor_optimo = {}
for reg in sorted(core["regimen"].unique()):
    sub = core[core["regimen"] == reg]
    r = sub["real_qty"].sum()
    if r == 0:
        factor_optimo[reg] = 1.0
        continue
    mu_base = sub["mu_sku_team"].values
    real_v = sub["real_qty"].values
    best = None
    for f in np.arange(0.3, 2.01, 0.05):
        ae = np.abs(real_v - mu_base * f).sum()
        if best is None or ae < best[1]:
            best = (f, ae)
    factor_optimo[reg] = round(float(best[0]), 2)

core["fcst_sim_opt"] = core["mu_sku_team"] * core["regimen"].map(factor_optimo)
tot2 = pd.DataFrame([
    {"scenario": "BASELINE", **metricas(core["real_qty"], core["forecast_qty"])},
    {"scenario": "SIM_RULE (factor sugerido)", **metricas(core["real_qty"], core["fcst_sim_rule"])},
    {"scenario": "SIM_OPTIM (factor por regimen)", **metricas(core["real_qty"], core["fcst_sim_opt"])},
    {"scenario": "ORACLE mean(real)", **metricas(core["real_qty"], core["fcst_oracle"])},
])
print(tot2.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
print("\nFactores optimos por regimen:")
for r, f in sorted(factor_optimo.items()):
    print(f"  {r}: x{f:.2f}")


# ----------------------------------------------------------------------
# Comparativa por regimen con factor optimo
# ----------------------------------------------------------------------
print("\n" + "=" * 120)
print("METRICAS POR REGIMEN — BASELINE vs SIM_OPTIM")
print("=" * 120)
out_rows = []
for reg in sorted(core["regimen"].unique()):
    sub = core[core["regimen"] == reg]
    base = metricas(sub["real_qty"], sub["forecast_qty"])
    opt = metricas(sub["real_qty"], sub["fcst_sim_opt"])
    out_rows.append({
        "regimen": reg,
        "n_filas": len(sub),
        "real": base["real"],
        "factor_opt": factor_optimo.get(reg),
        "BASE wape_%": base["wape_%"],
        "BASE bias_%": base["bias_%"],
        "OPT wape_%": opt["wape_%"],
        "OPT bias_%": opt["bias_%"],
        "delta_wape_pp": opt["wape_%"] - base["wape_%"] if base["wape_%"] else np.nan,
        "delta_bias_pp": opt["bias_%"] - base["bias_%"] if base["bias_%"] else np.nan,
    })
print(pd.DataFrame(out_rows).sort_values("real", ascending=False).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# Comparativa cabeza (REG-1) vs cola larga (REG-4,5,6,7)
# ----------------------------------------------------------------------
print("\n" + "=" * 120)
print("AGREGADO: cabeza (REG-1/2/3) vs cola (REG-4/5/6/7) vs especial (REG-0/8)")
print("=" * 120)
cabeza_regs = {"REG-1", "REG-2", "REG-3"}
cola_regs = {"REG-4", "REG-5", "REG-6", "REG-7"}
esp_regs = {"REG-0", "REG-8"}
core["grupo"] = core["regimen"].map(
    lambda r: "cabeza" if r in cabeza_regs else ("cola" if r in cola_regs else "especial")
)
agg_rows = []
for g, sub in core.groupby("grupo"):
    agg_rows.append({"grupo": g, "n": len(sub),
                     **{f"BASE_{k}": v for k, v in metricas(sub["real_qty"], sub["forecast_qty"]).items()},
                     **{f"OPT_{k}": v for k, v in metricas(sub["real_qty"], sub["fcst_sim_opt"]).items()}})
print(pd.DataFrame(agg_rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\nDONE.")
