"""
Paso 2c.9 — Simulacion FVA del overlay (a nivel CATEGORIA, out-of-sample).

Duda de Marco (2026-06-10): el HM-SI con factores SI semanales METIA ruido y
perdio contra SES(0.5). ¿Este overlay es distinto o va a repetir la historia?

Replay honesto: cortes quincenales oct-2025 -> abr-2026 (rampa de verano
completa del fact). En cada corte T, TODO se estima solo con datos <= T:
  - mu = SES(0.5) sobre la serie semanal de la categoria (nivel).
  - Curva SI: armonica destendenciada + dummy evento (metodo del Factor
    Semanal), con zona muerta y gate de amplitud.
  - Factor evento: uplift vs baseline local, medido <= T.
Y se pronostica h = 1, 2, 4 semanas con 3 brazos:
  A  base   : mu plano (lo productivo hoy)
  B  v13    : mu x ratio-to-mean crudo del ultimo anio (season_factor actual)
  C  overlay: mu x SI(T+h)/SI(T) x f_evento(T+h)
Metrica: WAPE y BIAS ponderados por unidades, por horizonte, vs venta real.
FVA = WAPE(A) - WAPE(C). El overlay debe ganarle a A y a B para existir.

Read-only local (lee el cache 2c.1). Salida: resultados/sim_fva_overlay*.csv
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "resultados"
ALPHA = 0.5
K = 3
MIN_WEEKS_FIT = 40
SEASONAL_MIN_AMP = 1.30
DEAD_ZONE = 0.10
SI_CLAMP = (0.40, 3.50)
EV_BL_HALF, EV_BL_MIN_W, EV_BL_MIN_QTY, EV_MIN_FACTOR = 6, 4, 10.0, 1.20
HORIZONS = [1, 2, 4]
CUTOFF_FROM, CUTOFF_TO, CUTOFF_STEP_W = dt.date(2025, 10, 6), dt.date(2026, 4, 27), 2

EVENT_DATES = {  # code -> fechas (mismas del Factor Semanal; A=feriado B=comercial)
    ("NEWYEAR", "A"): ["2025-01-01", "2026-01-01"],
    ("SAN_VALENTIN", "B"): ["2025-02-14", "2026-02-14"],
    ("GOOD_FRIDAY", "A"): ["2025-04-18", "2026-04-03"],
    ("LABOR_DAY", "A"): ["2025-05-01", "2026-05-01"],
    ("NAVY_DAY", "A"): ["2025-05-21"],
    ("VIRGIN_OF_CARMEN", "A"): ["2025-07-16"],
    ("ASSUMPTION", "A"): ["2025-08-15"],
    ("INDEPENDENCE_DAY", "A"): ["2025-09-18"],
    ("HALLOWEEN", "B"): ["2025-10-31"],
    ("ALL_SAINTS", "A"): ["2025-11-01"],
    ("IMMACULATE", "A"): ["2025-12-08"],
    ("CHRISTMAS", "A"): ["2025-12-25"],
}

def wk(d): return d - dt.timedelta(days=d.weekday())

ev_target, dirty = {}, set()
for (code, arq), dates in EVENT_DATES.items():
    for s in dates:
        d = dt.date.fromisoformat(s)
        tgt = wk(d if arq == "B" else d - dt.timedelta(days=1))
        ev_target.setdefault(code, []).append(tgt)
        dirty.add(wk(d)); dirty.add(wk(d - dt.timedelta(days=1)))

df = pd.read_parquet(OUT / "rank_week_sku_cache.parquet")
df["week"] = pd.to_datetime(df["week"]).dt.date
cat_w = df.groupby(["categoria", "week"], as_index=False)["qty"].sum()
all_weeks = sorted(cat_w["week"].unique())
series_by_cat = {c: dict(zip(g["week"], g["qty"])) for c, g in cat_w.groupby("categoria")}

def ses(vals):
    lvl = vals[0]
    for v in vals[1:]:
        lvl = ALPHA * v + (1 - ALPHA) * lvl
    return lvl

def fit_si(s, upto):
    """(dict iso->SI, trend_anual) o (None, trend_anual) si la categ es plana."""
    weeks = sorted([w for w in s if w <= upto and s[w] > 0])
    if len(weeks) < MIN_WEEKS_FIT:
        return None, None
    w0 = weeks[0]
    iso = np.array([min(w.isocalendar()[1], 52) for w in weeks])
    t = np.array([(w - w0).days / 365.0 for w in weeks])
    ev = np.array([1.0 if w in dirty else 0.0 for w in weeks])
    y = np.log(np.array([s[w] for w in weeks]))
    cols = [np.ones(len(weeks)), t]
    for k in range(1, K + 1):
        cols += [np.sin(2*np.pi*k*iso/52), np.cos(2*np.pi*k*iso/52)]
    if ev.any():
        cols.append(ev)
    X = np.column_stack(cols)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    trend = float(b[1])
    fc = b[2:2 + 2*K]
    isow = np.arange(1, 53)
    sl = np.zeros(52)
    for k in range(1, K + 1):
        sl += fc[2*(k-1)] * np.sin(2*np.pi*k*isow/52) + fc[2*k-1] * np.cos(2*np.pi*k*isow/52)
    curve = np.exp(sl - sl.mean()).clip(*SI_CLAMP)
    if curve.max() / curve.min() < SEASONAL_MIN_AMP:
        return None, trend
    return {i + 1: (1.0 if abs(curve[i] - 1) < DEAD_ZONE else float(curve[i]))
            for i in range(52)}, trend

def raw_ratio_to_mean(s, upto):
    """brazo B: season_factor estilo v13 (ultimas 52 sem, sin detrend ni eventos)."""
    weeks = [w for w in s if upto - dt.timedelta(weeks=52) <= w <= upto and s[w] > 0]
    if len(weeks) < 30:
        return None
    mean = np.mean([s[w] for w in weeks])
    by_iso = {}
    for w in weeks:
        by_iso.setdefault(min(w.isocalendar()[1], 52), []).append(s[w])
    return {i: (np.mean(v) / mean if v else 1.0) for i, v in by_iso.items()}, mean

def event_factors(s, upto):
    out = {}
    for code, tws in ev_target.items():
        ups = []
        for tw in tws:
            if tw >= upto:
                continue
            q = s.get(tw, 0.0)
            if q <= 0:
                continue
            clean = [v for w, v in s.items()
                     if abs((w - tw).days) <= EV_BL_HALF * 7 and w != tw
                     and w not in dirty and w <= upto]
            if len(clean) < EV_BL_MIN_W:
                continue
            bl = float(np.median(clean))
            if bl < EV_BL_MIN_QTY:
                continue
            ups.append(q / bl)
        if ups:
            med = float(np.median(ups))
            if med >= EV_MIN_FACTOR and (len(ups) < 2 or min(ups) > 1.0):
                out[code] = min(med, 8.0)
    return out

ev_week_code = {}
for code, tws in ev_target.items():
    for tw in tws:
        ev_week_code.setdefault(tw, []).append(code)

cutoffs = []
c = CUTOFF_FROM
while c <= CUTOFF_TO:
    cutoffs.append(c)
    c += dt.timedelta(weeks=CUTOFF_STEP_W)

recs = []
for cat, s in series_by_cat.items():
    hist_w = sorted([w for w in s if s[w] > 0])
    if len(hist_w) < MIN_WEEKS_FIT:
        continue
    for T in cutoffs:
        past = [w for w in hist_w if w <= T]
        if len(past) < MIN_WEEKS_FIT:
            continue
        mu = ses([s[w] for w in past])
        si, trend = fit_si(s, T)
        rr = raw_ratio_to_mean(s, T)
        evf = event_factors(s, T)
        iso_T = min(T.isocalendar()[1], 52)
        for h in HORIZONS:
            tw = T + dt.timedelta(weeks=h)
            real = s.get(tw)
            if real is None or real <= 0:
                continue
            iso_t = min(tw.isocalendar()[1], 52)
            f_ev = 1.0
            for code in ev_week_code.get(tw, []):
                if code in evf:
                    f_ev = max(f_ev, evf[code])
            fA = mu
            fB = mu * (rr[0].get(iso_t, 1.0) if rr else 1.0)
            fC = mu * ((si[iso_t] / si[iso_T]) if si else 1.0) * f_ev
            # brazo D: overlay + proyeccion de la tendencia ajustada (caida
            # same-store que el mu plano no anticipa dentro de la ventana)
            f_tr = np.exp(trend * h * 7 / 365.0) if trend is not None else 1.0
            fD = fC * f_tr
            recs.append(dict(categoria=cat, cutoff=T, h=h, semana=tw, real=real,
                             trend_fit=trend,
                             ramp=(tw.month in (11, 12, 1, 2, 3)),
                             evento=f_ev > 1.0, base=fA, v13=fB, overlay=fC,
                             overlay_t=fD))

R = pd.DataFrame(recs)
print(f"observaciones: {len(R):,} | categorias: {R['categoria'].nunique()} | "
      f"cortes: {R['cutoff'].nunique()}")
tr = (R.groupby("categoria")["trend_fit"].first().dropna())
tr_w = R.groupby("categoria").agg(t=("trend_fit", "first"), u=("real", "sum")).dropna()
tr_pond = (np.exp(tr_w["t"]) - 1).mul(tr_w["u"]).sum() / tr_w["u"].sum()
print(f"tendencia ajustada por categ (en el fit, datos pooled): mediana "
      f"{np.exp(tr.median())-1:+.1%}/año | ponderada por unidades {tr_pond:+.1%}/año")

def metrics(sub):
    out = {}
    tot = sub["real"].sum()
    for arm in ("base", "v13", "overlay", "overlay_t"):
        out[f"WAPE_{arm}"] = (sub[arm] - sub["real"]).abs().sum() / tot * 100
        out[f"BIAS_{arm}"] = (sub[arm] - sub["real"]).sum() / tot * 100
    out["FVA_vs_base"] = out["WAPE_base"] - out["WAPE_overlay"]
    out["FVA_t_vs_base"] = out["WAPE_base"] - out["WAPE_overlay_t"]
    out["n"] = len(sub)
    return pd.Series(out)

pd.set_option("display.width", 170)
print("\n" + "=" * 100)
print("WAPE/BIAS (%) POR HORIZONTE — todas las categorias, ponderado por unidades")
print("  FVA > 0: el overlay le gana | < 0: el overlay mete ruido")
print("=" * 100)
print(R.groupby("h").apply(metrics, include_groups=False).round(2).to_string())

print("\nSolo semanas de RAMPA (nov-mar):")
print(R[R["ramp"]].groupby("h").apply(metrics, include_groups=False).round(2).to_string())
print("\nSolo semanas FUERA de rampa:")
print(R[~R["ramp"]].groupby("h").apply(metrics, include_groups=False).round(2).to_string())
print("\nSolo semanas con EVENTO en el objetivo:")
ev_sub = R[R["evento"]]
if len(ev_sub):
    print(ev_sub.groupby("h").apply(metrics, include_groups=False).round(2).to_string())

# FVA por categoria a h=4 (donde el factor importa): ranking
h4 = R[R["h"] == 4]
by_cat = h4.groupby("categoria").apply(metrics, include_groups=False)
by_cat["units"] = h4.groupby("categoria")["real"].sum()
by_cat = by_cat.sort_values("units", ascending=False)
top = by_cat.head(20)[["n", "units", "WAPE_base", "WAPE_overlay", "FVA_vs_base"]]
top.index = [c.split("/")[-1].strip()[:30] for c in top.index]
print("\nTOP 20 categorias por volumen, h=4:")
print(top.round(1).to_string())
pos = (by_cat["FVA_vs_base"] > 0).sum()
print(f"\ncategorias con FVA+ a h=4: {pos} de {len(by_cat)} "
      f"({by_cat.loc[by_cat['FVA_vs_base'] > 0, 'units'].sum() / by_cat['units'].sum():.0%} del volumen)")

R.to_csv(OUT / "sim_fva_overlay_detalle.csv", index=False,
         sep=";", decimal=",", encoding="utf-8-sig")
by_cat.reset_index().to_csv(OUT / "sim_fva_overlay_por_categ.csv", index=False,
                            sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT/'sim_fva_overlay_detalle.csv'} | {OUT/'sim_fva_overlay_por_categ.csv'}")
