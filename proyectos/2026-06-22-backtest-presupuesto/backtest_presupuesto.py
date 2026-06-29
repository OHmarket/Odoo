# -*- coding: utf-8 -*-
"""
Backtest rolling-origin del presupuesto productivo (OH Presupuesto ventas v13).

Replica OFFLINE la logica del Server Action: nivel = venta LY (weekday-eq o
calendar-eq si feriado) x factor rolling acumulado (45d/365d blend) + paths
LY4/TY4 + floor por local + short-correction. Usa el factor_today al cierre
(igual que el modelo para dias futuros).

Ventana fiel a HOY: target 2026, base 2025 (unico par con calendario+ventas).
Mide WAPE/BIAS por tipo de dia y por local.

PROXY documentados (desviaciones vs productivo):
- mult={} en productivo -> adj=1 siempre (igual aqui).
- Anho Nuevo cross-year: se aplica la marca P de vispera; LY4 uplift portado.
- No se modela el override de floor por team (vacio en productivo hoy).
"""
import json
import datetime
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
RES = BASE / "resultados"

# ============ Parametros (espejo de OH Presupuesto ventas v13) ============
ALPHA_BLEND = 0.25
ROLL_WINDOW_DAYS = 45
LONG_WINDOW_DAYS = 365
WEEKS_FOR_WD_AVG = 4
MIN_BASE_IN_WINDOW = 30_000_000
FACTOR_WARMUP_DAYS = 14

ADJ_MIN, ADJ_MAX = 0.60, 1.80
ENABLE_SHORT_CORR = True
SHORT_CORR_MIN, SHORT_CORR_MAX = 0.70, 1.60

FERIADO_LY4_WD_UPLIFT = {0: 1.70, 1: 1.28, 2: 1.00, 3: 0.70, 4: 0.95, 5: 0.96, 6: 1.51}
FERIADO_LY4_WD_UPLIFT_MIN, FERIADO_LY4_WD_UPLIFT_MAX = 0.60, 2.00

ENABLE_TEAM_DAILY_FLOOR = True
TEAM_DAILY_FLOOR_MULT_ROLL30 = 0.45
TEAM_DAILY_FLOOR_ABS_MIN = 300_000
TEAM_DAILY_FLOOR_SCALE_MAX = 1.50

HOLIDAY_OFFSET_POLICY = {
    'NEWYEAR': [(0, 'H')], 'GOOD_FRIDAY': [(-1, 'P'), (0, 'H')], 'HOLY_SATURDAY': [(0, 'H')],
    'LABOR_DAY': [(-1, 'P'), (0, 'H')], 'NAVY_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')],
    'INDIGENOUS_PEOPLES_DAY': [(0, 'H')], 'SAINT_PETER_PAUL': [(0, 'H')],
    'VIRGIN_OF_CARMEN': [(0, 'H')], 'ASSUMPTION': [(0, 'H')],
    'INDEPENDENCE_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')], 'ARMY_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')],
    'ADDITIONAL_PATRIOTIC_HOLIDAY': [(0, 'H')], 'ENCOUNTER_OF_TWO_WORLDS': [(0, 'H')],
    'EVANGELICAL_CHURCHES_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')], 'ALL_SAINTS': [(0, 'H')],
    'IMMACULATE_CONCEPTION': [(0, 'H')], 'CHRISTMAS': [(-1, 'P'), (0, 'H')],
}
EASTER_SHORTCORR_CODES = {'GOOD_FRIDAY', 'HOLY_SATURDAY'}

# ============ Datos ============
df = pd.read_parquet(RES / "ventas_diarias.parquet")
df["d"] = df["day"].dt.date
TEAMS = sorted(df["team_id"].unique().tolist())
# sales[tid][date] = amt
sales = {t: {} for t in TEAMS}
for r in df.itertuples():
    sales[r.team_id][r.d] = sales[r.team_id].get(r.d, 0.0) + float(r.amt)

HOL = json.loads((RES / "holidays.json").read_text(encoding="utf-8"))
HOL = {int(y): v for y, v in HOL.items()}  # {year: {code: 'YYYY-MM-DD'}}

DAY = datetime.timedelta(days=1)

def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)

# ---- calendario: clase por dia (N/P/H) y taginfo por anho ----
def _set(d_map, day, cls):
    pr = {'N': 0, 'P': 1, 'H': 2}
    if pr[cls] >= pr.get(d_map.get(day, 'N'), 0):
        d_map[day] = cls

def build_holiday_maps(year):
    hmap, tag = {}, {}
    base = HOL.get(year, {})
    for code, ds in base.items():
        bd = datetime.date.fromisoformat(ds)
        for off, cls in HOLIDAY_OFFSET_POLICY.get(code, [(0, 'H')]):
            x = bd + datetime.timedelta(days=off)
            if x.year == year:
                _set(hmap, x, cls)
                pr = {'N': 0, 'P': 1, 'H': 2}
                old = tag.get(x)
                if old is None or pr[cls] >= pr[old[2]]:
                    tag[x] = (code, off, cls)
    # Anho Nuevo cross-year: 31-dic marca vispera P
    d31 = datetime.date(year, 12, 31)
    _set(hmap, d31, 'P')
    return hmap, tag

HMAP = {y: build_holiday_maps(y) for y in (2025, 2026)}

def hclass(d):
    return HMAP.get(d.year, ({}, {}))[0].get(d, 'N')

def base_equiv_cal(d):
    """Para dia feriado: fecha base = base_main[code]+off del anho anterior."""
    tag = HMAP.get(d.year, ({}, {}))[1].get(d)
    if not tag:
        return None
    code, off, _ = tag
    bd = HOL.get(d.year - 1, {}).get(code)
    if not bd:
        return None
    return datetime.date.fromisoformat(bd) + datetime.timedelta(days=off)

def weekday_eq(d, base_year):
    x = d - datetime.timedelta(days=364)
    g = 0
    while x.year != base_year and g < 60:
        x = x - datetime.timedelta(days=7) if x.year > base_year else x + datetime.timedelta(days=7)
        g += 1
    return x

def avg_lastN_weekday_ly(tid, anchor, wd, n, base_year):
    vals, d, steps = [], anchor, 0
    bmap = HMAP.get(base_year, ({}, {}))[0]
    while len(vals) < n and steps < 12:
        if d.weekday() == wd and bmap.get(d, 'N') == 'N':
            v = sales[tid].get(d, 0.0)
            if v > 0:
                vals.append(v)
        d -= datetime.timedelta(days=7)
        steps += 1
    return sum(vals) / len(vals) if vals else 0.0

def avg_lastN_weekday_ty(tid, anchor, wd, n, cap):
    vals, d, steps = [], anchor - datetime.timedelta(days=7), 0
    tmap = HMAP.get(anchor.year, ({}, {}))[0]
    while len(vals) < n and steps < 12:
        if d <= cap and d.weekday() == wd and tmap.get(d, 'N') == 'N':
            v = sales[tid].get(d, 0.0)
            if v > 0:
                vals.append(v)
        d -= datetime.timedelta(days=7)
        steps += 1
    return sum(vals) / len(vals) if vals else 0.0

# ---- factor rolling al cierre C (factor_today) ----
def factor_today(tid, C):
    fac_start = C - datetime.timedelta(days=LONG_WINDOW_DAYS - 1)
    curr, base = [], []
    d = fac_start
    while d <= C:
        cv = sales[tid].get(d, 0.0)
        cls = hclass(d)
        bd = base_equiv_cal(d) if cls != 'N' else weekday_eq(d, d.year - 1)
        bv = sales[tid].get(bd, 0.0) if bd else 0.0
        curr.append(cv)
        base.append(bv)
        d += DAY
    n = len(curr)
    csum, bsum = sum(curr), sum(base)
    long_fac = (csum / bsum) if bsum > 0 else 1.0
    cs_short = sum(curr[-ROLL_WINDOW_DAYS:])
    bs_short = sum(base[-ROLL_WINDOW_DAYS:])
    if bs_short >= MIN_BASE_IN_WINDOW:
        short_fac = (cs_short / bs_short) if bs_short > 0 else long_fac
        fac = ALPHA_BLEND * long_fac + (1 - ALPHA_BLEND) * short_fac
    else:
        fac = long_fac
    if n < FACTOR_WARMUP_DAYS:
        fac = 1.0
    return fac

def roll30(tid, C):
    s, d, k = 0.0, C - datetime.timedelta(days=29), 0
    while d <= C:
        s += sales[tid].get(d, 0.0)
        d += DAY
        k += 1
    return s / k if k else 0.0

# ---- proyeccion de un dia futuro d desde cierre C ----
def project(tid, d, C, fac, r30):
    wd = d.weekday()
    base_year = d.year - 1
    tgt_cls = hclass(d)
    d_we = weekday_eq(d, base_year)
    base_cls_eq = HMAP.get(base_year, ({}, {}))[0].get(d_we, 'N')
    v_show = sales[tid].get(d_we, 0.0)

    d_cal = base_equiv_cal(d) if tgt_cls != 'N' else None
    if not d_cal:
        try:
            d_cal = datetime.date(base_year, d.month, d.day)
        except Exception:
            d_cal = None
    v_cal = sales[tid].get(d_cal, 0.0) if d_cal else 0.0

    base_mode, proj, v_clean = 'WD', 0.0, 0.0
    if tgt_cls != 'N' and d_cal and v_cal > 0:
        base_mode, proj = 'CAL', v_cal * fac
    else:
        if tgt_cls == 'N' and base_cls_eq != 'N':
            v_clean = avg_lastN_weekday_ly(tid, d_we, wd, WEEKS_FOR_WD_AVG, base_year)
            if v_clean > 0:
                base_mode = 'LY4'
                upl = _clamp(FERIADO_LY4_WD_UPLIFT.get(wd, 1.0), FERIADO_LY4_WD_UPLIFT_MIN, FERIADO_LY4_WD_UPLIFT_MAX)
                proj = v_clean * fac * upl
            else:
                base_mode = 'TY4'
        else:
            if v_show > 0:
                base_mode, proj = 'WD', v_show * fac
            else:
                base_mode = 'TY4'

    if base_mode == 'TY4':
        cap = d - DAY
        ty4 = avg_lastN_weekday_ty(tid, d, wd, WEEKS_FOR_WD_AVG, cap)
        if ty4 <= 0:
            ty4 = r30
        proj = ty4

    # short correction (LY4 y Pascua-CAL)
    apply_sc = (base_mode == 'LY4')
    if (not apply_sc) and base_mode == 'CAL' and tgt_cls in ('P', 'H') and d_cal:
        tag = HMAP.get(d.year, ({}, {}))[1].get(d)
        if tag and tag[0] in EASTER_SHORTCORR_CODES and d.month != d_cal.month:
            apply_sc = True
    if ENABLE_SHORT_CORR and apply_sc:
        cap = d - DAY
        ty4 = avg_lastN_weekday_ty(tid, d, wd, WEEKS_FOR_WD_AVG, cap)
        if ty4 <= 0:
            ty4 = r30
        ly4 = v_clean or avg_lastN_weekday_ly(tid, (d_cal if base_mode == 'CAL' and d_cal else d_we), wd, WEEKS_FOR_WD_AVG, base_year)
        if ty4 > 0 and ly4 > 0:
            proj *= _clamp(ty4 / ly4, SHORT_CORR_MIN, SHORT_CORR_MAX)

    # floor por local
    if ENABLE_TEAM_DAILY_FLOOR:
        floor = max(TEAM_DAILY_FLOOR_MULT_ROLL30 * r30, float(TEAM_DAILY_FLOOR_ABS_MIN))
        if floor > 0 and proj < floor:
            if proj > 0 and proj >= TEAM_DAILY_FLOOR_ABS_MIN:
                if floor / proj > TEAM_DAILY_FLOOR_SCALE_MAX:
                    floor = proj * TEAM_DAILY_FLOOR_SCALE_MAX
            if proj < floor:
                proj = floor

    return proj, base_mode

def day_type(d):
    c = hclass(d)
    if c == 'H':
        return 'feriado'
    if c == 'P':
        return 'vispera'
    base_cls = HMAP.get(d.year - 1, ({}, {}))[0].get(weekday_eq(d, d.year - 1), 'N')
    if base_cls != 'N':
        return 'post_feriado_LY'
    return 'normal'

# ============ Rolling-origin backtest ============
HORIZON = 28

def make_cutoffs():
    cutoffs = []
    c = datetime.date(2026, 1, 4)
    while c <= datetime.date(2026, 5, 24):
        cutoffs.append(c)
        c += datetime.timedelta(days=7)
    return cutoffs

def metrics(g):
    a = g["actual"].sum()
    e = (g["proj"] - g["actual"]).abs().sum()
    bias = (g["proj"] - g["actual"]).sum()
    return pd.Series({
        "n": len(g),
        "venta_real_MM": round(a / 1e6, 1),
        "WAPE_%": round(100 * e / a, 1) if a else float("nan"),
        "BIAS_%": round(100 * bias / a, 1) if a else float("nan"),
    })

def run_incumbent():
    records = []
    for C in make_cutoffs():
        fac = {t: factor_today(t, C) for t in TEAMS}
        r30 = {t: roll30(t, C) for t in TEAMS}
        for k in range(1, HORIZON + 1):
            d = C + datetime.timedelta(days=k)
            if d > datetime.date(2026, 6, 21):
                continue
            for t in TEAMS:
                actual = sales[t].get(d)
                if actual is None:  # sin venta registrada ese dia/local -> excluir
                    continue
                proj, mode = project(t, d, C, fac[t], r30[t])
                records.append({
                    "cutoff": C, "d": d, "team": t, "horizon": k,
                    "dtype": day_type(d), "mode": mode,
                    "proj": proj, "actual": actual,
                })
    return pd.DataFrame(records)

# ----- ejecucion (solo como script; al importar solo se exponen funciones) -----
if __name__ == "__main__":
    bt = run_incumbent()
    bt.to_parquet(RES / "backtest_raw.parquet")
    print("registros backtest:", len(bt), "| cutoffs:", len(make_cutoffs()))

    print("\n===== WAPE global =====")
    print(metrics(bt).to_string())

    print("\n===== Por tipo de dia =====")
    print(bt.groupby("dtype").apply(metrics, include_groups=False).to_string())

    print("\n===== Por horizonte (semana de proyeccion) =====")
    bt["sem"] = ((bt["horizon"] - 1) // 7 + 1)
    print(bt.groupby("sem").apply(metrics, include_groups=False).to_string())

    print("\n===== Por local =====")
    print(bt.groupby("team").apply(metrics, include_groups=False).sort_values("WAPE_%", ascending=False).to_string())

    print("\n===== Tipo de dia x (normal vs evento) =====")
    bt["evento"] = bt["dtype"].apply(lambda x: "normal" if x == "normal" else "evento")
    print(bt.groupby("evento").apply(metrics, include_groups=False).to_string())
