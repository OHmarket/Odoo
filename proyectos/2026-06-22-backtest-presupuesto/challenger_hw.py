# -*- coding: utf-8 -*-
"""
Bake-off: Holt-Winters aditivo con damped trend (estacionalidad semanal m=7)
vs el presupuesto YoY actual. UNA VERSION, UN CAMBIO:

  - Dias NORMALES (no feriado/vispera): motor = HW damped.
  - Dias de EVENTO (feriado/vispera): motor = incumbente (CAL/LY4), SIN tocar.
  - Floor por local: identico al incumbente en ambos.

Aisla la palanca de TENDENCIA. HW en numpy puro (portable a safe_eval).

PROXY: HW se fitea sobre la serie diaria cruda; los ~16 feriados/anho
contaminan algo el nivel/estacional (incumbente los enmascara). 1a pasada.
"""
import datetime
import numpy as np
import pandas as pd
from scipy.optimize import minimize

import backtest_presupuesto as inc  # reusa datos + funciones del incumbente

M = 7  # estacionalidad semanal
RES = inc.RES

# ---------- Holt-Winters aditivo damped (numpy) ----------
def _hw_sse(params, y):
    alpha, beta, gamma, phi = params
    n = len(y)
    if n < 2 * M + 2:
        return 1e18
    # init
    l = y[:M].mean()
    b = (y[M:2 * M].mean() - y[:M].mean()) / M
    s = list(y[:M] - l)
    sse = 0.0
    for t in range(M, n):
        s_tm = s[t - M]
        fc = l + phi * b + s_tm
        e = y[t] - fc
        sse += e * e
        l_new = alpha * (y[t] - s_tm) + (1 - alpha) * (l + phi * b)
        b = beta * (l_new - l) + (1 - beta) * phi * b
        s.append(gamma * (y[t] - l_new) + (1 - gamma) * s_tm)
        l = l_new
    return sse

def hw_fit_forecast(y, h):
    """Fit HW damped sobre y, devuelve forecast h pasos (clamp >=0)."""
    y = np.asarray(y, dtype=float)
    if len(y) < 2 * M + 2:
        # serie corta: naive estacional (media por weekday de ultimas 4 sem)
        base = y[-4 * M:] if len(y) >= 4 * M else y
        prof = [np.mean(base[i::M]) if len(base[i::M]) else (base.mean() if len(base) else 0.0) for i in range(M)]
        start = len(y) % M
        return [max(0.0, prof[(start + k - 1) % M]) for k in range(1, h + 1)]
    res = minimize(_hw_sse, x0=[0.2, 0.05, 0.1, 0.92], args=(y,),
                   bounds=[(0, 1), (0, 0.5), (0, 0.5), (0.80, 0.98)],
                   method="L-BFGS-B")
    alpha, beta, gamma, phi = res.x
    n = len(y)
    l = y[:M].mean()
    b = (y[M:2 * M].mean() - y[:M].mean()) / M
    s = list(y[:M] - l)
    for t in range(M, n):
        s_tm = s[t - M]
        l_new = alpha * (y[t] - s_tm) + (1 - alpha) * (l + phi * b)
        b = beta * (l_new - l) + (1 - beta) * phi * b
        s.append(gamma * (y[t] - l_new) + (1 - gamma) * s_tm)
        l = l_new
    out, phi_pow = [], 0.0
    for k in range(1, h + 1):
        phi_pow += phi ** k
        s_idx = n - M + ((k - 1) % M)
        fc = l + phi_pow * b + s[s_idx]
        out.append(max(0.0, fc))
    return out

# ---------- serie diaria contigua por team hasta cutoff ----------
def daily_series(tid, C):
    days = sorted(d for d in inc.sales[tid] if d <= C)
    if not days:
        return [], None
    start = days[0]
    n = (C - start).days + 1
    y = [inc.sales[tid].get(start + datetime.timedelta(days=i), 0.0) for i in range(n)]
    return y, start

# ---------- backtest challenger ----------
records = []
for C in inc.make_cutoffs():
    fac = {t: inc.factor_today(t, C) for t in inc.TEAMS}
    r30 = {t: inc.roll30(t, C) for t in inc.TEAMS}
    hwfc = {}
    for t in inc.TEAMS:
        y, _ = daily_series(t, C)
        hwfc[t] = hw_fit_forecast(y, inc.HORIZON) if y else [0.0] * inc.HORIZON
    for k in range(1, inc.HORIZON + 1):
        d = C + datetime.timedelta(days=k)
        if d > datetime.date(2026, 6, 21):
            continue
        for t in inc.TEAMS:
            actual = inc.sales[t].get(d)
            if actual is None:
                continue
            dt = inc.day_type(d)
            if dt in ("feriado", "vispera"):
                proj, _ = inc.project(t, d, C, fac[t], r30[t])  # evento: incumbente
                engine = "INC_event"
            else:
                proj = hwfc[t][k - 1]
                # floor identico al incumbente
                floor = max(inc.TEAM_DAILY_FLOOR_MULT_ROLL30 * r30[t], float(inc.TEAM_DAILY_FLOOR_ABS_MIN))
                if floor > 0 and proj < floor:
                    if proj > 0 and proj >= inc.TEAM_DAILY_FLOOR_ABS_MIN and floor / proj > inc.TEAM_DAILY_FLOOR_SCALE_MAX:
                        floor = proj * inc.TEAM_DAILY_FLOOR_SCALE_MAX
                    if proj < floor:
                        proj = floor
                engine = "HW"
            records.append({"cutoff": C, "d": d, "team": t, "horizon": k,
                            "dtype": dt, "engine": engine, "proj": proj, "actual": actual})

ch = pd.DataFrame(records)
ch.to_parquet(RES / "challenger_raw.parquet")

# incumbente para comparacion (mismas filas)
bt = inc.run_incumbent()

def block(df, label):
    a = df["actual"].sum()
    e = (df["proj"] - df["actual"]).abs().sum()
    bias = (df["proj"] - df["actual"]).sum()
    return {"modelo": label, "n": len(df), "venta_MM": round(a / 1e6, 1),
            "WAPE_%": round(100 * e / a, 1), "BIAS_%": round(100 * bias / a, 1)}

def compare(mask_name, inc_df, ch_df):
    rows = [block(inc_df, "YoY actual"), block(ch_df, "HW damped")]
    print("\n===== %s =====" % mask_name)
    print(pd.DataFrame(rows).to_string(index=False))

print("registros:", len(ch))
compare("GLOBAL", bt, ch)
compare("Solo dias NORMALES (la palanca)",
        bt[bt.dtype == "normal"], ch[ch.dtype == "normal"])
compare("Solo EVENTOS (debe quedar igual)",
        bt[bt.dtype.isin(["feriado", "vispera"])], ch[ch.dtype.isin(["feriado", "vispera"])])

print("\n===== NORMALES por semana de horizonte =====")
for sem in (1, 2, 3, 4):
    lo, hi = (sem - 1) * 7 + 1, sem * 7
    bi = bt[(bt.dtype == "normal") & (bt.horizon.between(lo, hi))]
    ci = ch[(ch.dtype == "normal") & (ch.horizon.between(lo, hi))]
    a = bi["actual"].sum()
    print("sem%d  YoY: WAPE %5.1f BIAS %+5.1f | HW: WAPE %5.1f BIAS %+5.1f" % (
        sem,
        100 * (bi.proj - bi.actual).abs().sum() / a, 100 * (bi.proj - bi.actual).sum() / a,
        100 * (ci.proj - ci.actual).abs().sum() / a, 100 * (ci.proj - ci.actual).sum() / a))

print("\n===== NORMALES por local =====")
rows = []
for t in inc.TEAMS:
    bi = bt[(bt.dtype == "normal") & (bt.team == t)]
    ci = ch[(ch.dtype == "normal") & (ch.team == t)]
    a = bi["actual"].sum()
    if not a:
        continue
    rows.append({"team": t,
                 "YoY_WAPE": round(100 * (bi.proj - bi.actual).abs().sum() / a, 1),
                 "YoY_BIAS": round(100 * (bi.proj - bi.actual).sum() / a, 1),
                 "HW_WAPE": round(100 * (ci.proj - ci.actual).abs().sum() / a, 1),
                 "HW_BIAS": round(100 * (ci.proj - ci.actual).sum() / a, 1)})
print(pd.DataFrame(rows).sort_values("YoY_WAPE", ascending=False).to_string(index=False))
