"""
Simulacion de validacion del diagnostico de respuesta estacional.

Genera venta semanal sintetica con estructura CONOCIDA (categorias con verano
fuerte, SKUs poolable / idiosincratico / plano, mas feriados) y corre el
diagnostico real:
  - regresion armonica (Fourier) por categoria  -> curva estacional semanal
  - FVA por SKU (vs base plana, usando curva de su categoria)
  - Fs strength of seasonality por SKU (fit propio)
  - clasificacion 2x2

Si el diagnostico recupera lo plantado, el metodo es confiable antes de
apuntarlo a la data real de x_pos_week_sku_sale.

Read-only / autocontenido. No toca Odoo.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

rng = np.random.default_rng(42)

# ----------------------------------------------------------------------
# 1. PARAMETROS DE LA SIMULACION (estructura conocida)
# ----------------------------------------------------------------------
N_WEEKS = 74                      # ene-2025 -> ~may-2026, como la data real
K_FOURIER = 3                     # terminos armonicos
HOLIDAY_WEEKS = {38: 0.45, 51: 0.30}   # iso_week -> uplift log (~+57%, +35%)

# iso_week por semana (arranca semana 1 de 2025, da la vuelta en 52)
weeks = np.arange(N_WEEKS)
iso_week = (weeks % 52) + 1       # 1..52 ciclico
t_norm = weeks / N_WEEKS          # tiempo normalizado para tendencia

def seasonal_curve(amp, peak_week):
    """Curva estacional log, media 0. Pico en peak_week (verano ~ semana 3)."""
    s = amp * np.cos(2 * np.pi * (iso_week - peak_week) / 52)
    return s - s.mean()

# Perfiles de categoria: (nombre, amplitud_verano, n_pool, n_idio, n_flat)
CATS = [
    ("Carbon",     0.55, 5, 0, 1),   # verano muy fuerte (asados)
    ("Cervezas",   0.40, 6, 2, 2),   # verano fuerte + 2 idiosincraticos + 2 planos
    ("Abarrotes",  0.06, 1, 0, 7),   # casi plano
]

# ----------------------------------------------------------------------
# 2. GENERAR DATA SINTETICA
# ----------------------------------------------------------------------
rows = []
truth = {}     # sku -> tipo plantado
for cat, amp, n_pool, n_idio, n_flat in CATS:
    cat_season = seasonal_curve(amp, peak_week=3)      # verano late-enero
    idio_season = seasonal_curve(amp, peak_week=29)    # invierno (forma propia)
    specs = ([("poolable", cat_season)] * n_pool
             + [("idiosincratico", idio_season)] * n_idio
             + [("plano", np.zeros(N_WEEKS))] * n_flat)
    for i, (tipo, season) in enumerate(specs):
        sku = f"{cat[:3].upper()}-{i:02d}"
        truth[sku] = tipo
        base = rng.uniform(40, 200)                    # nivel propio
        trend = rng.uniform(-0.25, 0.30)               # tendencia propia (log/year-ish)
        noise_sd = rng.uniform(0.10, 0.22)
        log_level = np.log(base) + trend * t_norm + season
        # feriados (afectan a todos)
        for wk, upl in HOLIDAY_WEEKS.items():
            log_level = log_level + upl * (iso_week == wk)
        y = np.exp(log_level + rng.normal(0, noise_sd, N_WEEKS))
        for w in range(N_WEEKS):
            rows.append((cat, sku, int(weeks[w]), int(iso_week[w]), float(y[w])))

df = pd.DataFrame(rows, columns=["categoria", "sku", "week", "iso_week", "qty"])

# ----------------------------------------------------------------------
# 3. DISENO DE REGRESION ARMONICA
# ----------------------------------------------------------------------
def design_matrix(iso_w, t, k=K_FOURIER, holidays=None, with_trend=True):
    cols = [np.ones_like(t, dtype=float)]
    names = ["const"]
    if with_trend:
        cols.append(t); names.append("trend")
    for kk in range(1, k + 1):
        cols.append(np.sin(2 * np.pi * kk * iso_w / 52)); names.append(f"sin{kk}")
        cols.append(np.cos(2 * np.pi * kk * iso_w / 52)); names.append(f"cos{kk}")
    if holidays:
        for wk in holidays:
            cols.append((iso_w == wk).astype(float)); names.append(f"hol{wk}")
    return np.column_stack(cols), names

def fit_ols(X, y_log):
    b, *_ = np.linalg.lstsq(X, y_log, rcond=None)
    return b

# ----------------------------------------------------------------------
# 4. CURVA ESTACIONAL POR CATEGORIA  (regresion armonica sobre agregado)
# ----------------------------------------------------------------------
cat_curves = {}          # categoria -> array[52] factor estacional (mean 1)
cat_holiday = {}
for cat in df["categoria"].unique():
    g = df[df["categoria"] == cat].groupby("week").agg(
        qty=("qty", "sum"), iso_week=("iso_week", "first")).reset_index()
    y_log = np.log(g["qty"].values)
    X, names = design_matrix(g["iso_week"].values, g["week"].values / N_WEEKS,
                             holidays=HOLIDAY_WEEKS.keys())
    b = fit_ols(X, y_log)
    # curva estacional: evaluar solo terminos Fourier sobre iso_week 1..52
    isow = np.arange(1, 53)
    Xs, ns = design_matrix(isow, np.zeros(52), holidays=None, with_trend=False)
    # quitar const, dejar solo sin/cos
    fourier_idx = [j for j, n in enumerate(ns) if n.startswith(("sin", "cos"))]
    coef_idx = [names.index(ns[j]) for j in fourier_idx]
    season_log = Xs[:, fourier_idx] @ b[coef_idx]
    season_log = season_log - season_log.mean()
    cat_curves[cat] = np.exp(season_log)            # factor mean~1
    hol = {nm.replace("hol", ""): float(b[names.index(nm)])
           for nm in names if nm.startswith("hol")}
    cat_holiday[cat] = hol

# ----------------------------------------------------------------------
# 5. FVA y Fs POR SKU
# ----------------------------------------------------------------------
def wape(actual, pred):
    return np.sum(np.abs(actual - pred)) / np.sum(np.abs(actual))

results = []
for (cat, sku), g in df.groupby(["categoria", "sku"]):
    g = g.sort_values("week")
    y = g["qty"].values
    y_log = np.log(y)
    isow = g["iso_week"].values
    t = g["week"].values / N_WEEKS

    # --- modelo A: base plana (nivel + tendencia, sin estacionalidad) ---
    Xa, _ = design_matrix(isow, t, k=0, with_trend=True)
    ba = fit_ols(Xa, y_log)
    base_log = Xa @ ba
    pred_A = np.exp(base_log)

    # --- modelo B: base + curva estacional DE SU CATEGORIA (0 params propios) ---
    season_cat_log = np.log(cat_curves[cat][isow - 1])
    pred_B = np.exp(base_log + season_cat_log)

    fva = wape(y, pred_A) - wape(y, pred_B)          # >0 => estacionalidad ayuda

    # --- Fs: fuerza de estacionalidad PROPIA (fit armonico del SKU) ---
    Xf, nf = design_matrix(isow, t, k=K_FOURIER, with_trend=True)
    bf = fit_ols(Xf, y_log)
    fidx = [j for j, n in enumerate(nf) if n.startswith(("sin", "cos"))]
    season_own = Xf[:, fidx] @ bf[fidx]
    season_own = season_own - season_own.mean()
    resid = y_log - Xf @ bf
    var_r = np.var(resid)
    fs = max(0.0, 1 - var_r / np.var(resid + season_own)) if np.var(resid + season_own) > 0 else 0.0

    results.append(dict(categoria=cat, sku=sku, plantado=truth[sku],
                        wape_A=wape(y, pred_A), wape_B=wape(y, pred_B),
                        fva=fva, fs=fs))

res = pd.DataFrame(results)

# ----------------------------------------------------------------------
# 6. CLASIFICACION 2x2
# ----------------------------------------------------------------------
FVA_THR = 0.005      # 0.5pp
FS_THR = 0.15

def classify(r):
    fva_pos = r["fva"] > FVA_THR
    fs_alta = r["fs"] > FS_THR
    if fs_alta and fva_pos:   return "poolable"
    if fs_alta and not fva_pos: return "idiosincratico"
    return "plano"

res["clase"] = res.apply(classify, axis=1)
res["acierto"] = res["clase"] == res["plantado"]

# ----------------------------------------------------------------------
# 7. REPORTE
# ----------------------------------------------------------------------
pd.set_option("display.width", 160, "display.max_rows", 100)
print("=" * 72)
print("CURVA ESTACIONAL RECUPERADA POR CATEGORIA (factor por iso_week, mean~1)")
print("=" * 72)
sample_weeks = [1, 3, 9, 20, 29, 38, 51]
hdr = "categoria   " + "  ".join(f"w{w:>2}" for w in sample_weeks) + "   feriados(log)"
print(hdr)
for cat in cat_curves:
    vals = "  ".join(f"{cat_curves[cat][w-1]:.2f}" for w in sample_weeks)
    hol = " ".join(f"{k}:+{v:.2f}" for k, v in cat_holiday[cat].items())
    print(f"{cat:<11} {vals}    {hol}")
print("  (w3=late-enero=verano, w29=julio=invierno, w38=18-sep, w51=navidad)")

print("\n" + "=" * 72)
print("DETALLE POR SKU")
print("=" * 72)
show = res[["categoria", "sku", "plantado", "wape_A", "wape_B", "fva", "fs", "clase", "acierto"]].copy()
show["wape_A"] = (show["wape_A"] * 100).round(1)
show["wape_B"] = (show["wape_B"] * 100).round(1)
show["fva"] = (show["fva"] * 100).round(1)
show["fs"] = show["fs"].round(2)
print(show.to_string(index=False))

print("\n" + "=" * 72)
print("VALIDACION: clase recuperada vs plantada")
print("=" * 72)
print(pd.crosstab(res["plantado"], res["clase"], margins=True))
acc = res["acierto"].mean()
print(f"\nAciertos: {res['acierto'].sum()}/{len(res)} = {acc:.0%}")

print("\nResumen por categoria (% de SKUs por clase):")
print(pd.crosstab(res["categoria"], res["clase"], normalize="index").mul(100).round(0))

# guardar
import os
os.makedirs(os.path.join(os.path.dirname(__file__), "resultados"), exist_ok=True)
res.to_csv(os.path.join(os.path.dirname(__file__), "resultados", "sim_sku_diag.csv"), index=False)
print("\n-> resultados/sim_sku_diag.csv")
