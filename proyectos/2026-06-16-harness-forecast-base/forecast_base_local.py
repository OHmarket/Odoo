"""
forecast_base_local — Mirror local (sin Odoo) de 02_forecast/OH Forecast Base.py v1.6.

Lee los parquets del cache del harness y reproduce el forecast del motor productivo
ACTUAL (SES/SMA por forma de serie local). Iteracion ~segundos, cero carga al server.

Las funciones core (_classify_series_type, _ses_level, _median) son COPIA EXACTA
del motor productivo (OH Forecast Base.py, lineas 215-265) para garantizar paridad
numerica. El andamiaje de carga de cache (load_cache/load_abcxyz/_build_series_map)
se reusa del mirror viejo HM_SI_local.py.

LIMITE v0: la de-censura de entrada por quiebre (cleansing v1.5/v1.6) NO se replica:
el cache no tiene venta diaria (perfil dow) ni x_stock_balance_daily. Se corre con
decensor=False (input crudo), modo soportado por el propio motor. Ver diseno.md.

Uso:
    python forecast_base_local.py 2026-05-17
    # -> resultados/forecast_base_local_<cutoff>.parquet
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import sys

import pandas as pd

VERSION_ID = "FORECAST_BASE_LOCAL_v0_1"   # mirror de OH_FORECAST_BASE_v1_6

# --- Constantes del motor productivo (copia) ---
DEMAND_WINDOW_WEEKS = 26
MEDIAN_K = 4
SMA_TAIL_WEEKS = 6
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49
MIN_ACTIVE_WEEKS = 4
ALPHA_SMOOTH_A = 0.5
ALPHA_SMOOTH_BC = 0.6
ALPHA_ERRATIC = 0.7
# Cleansing de entrada por quiebre (de-censura v1.5, copia del motor)
CLEANSE_MIN_DAYS = 1
CLEANSE_BASE_WEEKS = 6
CLEANSE_SEVERE_WEIGHT = 0.5
CLEANSE_LOOKBACK_WEEKS = 16

CACHE_DIR_DEFAULT = Path(__file__).resolve().parent.parent / "2026-05-27-harness-local" / "cache"
RESULTS_DIR = Path(__file__).resolve().parent / "resultados"


def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


# ============================================================
# CORE — COPIA EXACTA del motor productivo (OH Forecast Base.py 215-265).
# No tocar sin re-sincronizar con el motor: aqui vive la paridad numerica.
# ============================================================
def _classify_series_type(vals):
    """Syntetos-Boylan sobre el vector semanal (incluye ceros)."""
    n = 0
    active = 0
    total = 0.0
    for x in vals:
        n += 1
        if x > 0.0:
            active += 1
            total += x
    if active < MIN_ACTIVE_WEEKS:
        return 'no_signal'
    adi = float(n) / active if active else 0.0
    if adi <= 0:
        return 'no_signal'
    mu = total / active
    if mu <= 0:
        return 'no_signal'
    sumsq = 0.0
    for x in vals:
        if x > 0.0:
            d = x - mu
            sumsq += d * d
    cv2 = (sumsq / active) / (mu * mu)   # var poblacional (ddof=0)
    intermittent = adi >= ADI_THRESHOLD
    high_var = cv2 >= CV2_THRESHOLD
    if intermittent:
        return 'lumpy' if high_var else 'intermittent'
    return 'erratic' if high_var else 'smooth'


def _ses_level(vals, alpha):
    """Nivel SES (adjust=False) tras la ultima semana cerrada = forecast 1-paso."""
    level = None
    for y in vals:
        if level is None:
            level = y
        else:
            level = alpha * y + (1.0 - alpha) * level
    return level if level is not None else 0.0


def _median(seq):
    s = sorted(seq)
    k = len(s)
    if k == 0:
        return 0.0
    return s[k // 2] if (k % 2) else (s[k // 2 - 1] + s[k // 2]) / 2.0


def _cleanse_stockout(raw_vals, weeks_list, tid, pid, qweight, min_days, base_k, severe_w,
                      cap_leve=True):
    """Cleansing de entrada por quiebre (COPIA EXACTA del motor, lineas 268-310).
    qweight[(tid,pid,w)] = (n_days, peso_perdido). Solo levanta. Retorna (vector, n_lift).
    cap_leve=True (default, == produccion): el leve se capa al baseline in-stock.
    cap_leve=False: leve sin cap (version previa), para backtest comparativo."""
    out = []
    instock = []
    n_lift = 0
    for i in range(len(weeks_list)):
        w = weeks_list[i]
        y = raw_vals[i]
        info = qweight.get((tid, pid, w))
        nd = info[0] if info else 0
        pw = info[1] if info else 0.0
        if nd >= min_days and pw > 0.0:
            recent = instock[-base_k:] if instock else []
            base = (sum(recent) / len(recent)) if recent else None
            if pw < severe_w and pw < 0.95:
                val = y / (1.0 - pw)
                if cap_leve and base is not None and val > base:
                    val = base if base > y else y
                out.append(val)
                if val > y + 1e-9:
                    n_lift += 1
            elif base is not None:
                if base > y:
                    out.append(base)
                    n_lift += 1
                else:
                    out.append(y)
            else:
                out.append(y)
        else:
            out.append(y)
            instock.append(y)
    return out, n_lift
# ============================================================


def _select_model(vals, abc):
    """Replica el bloque de seleccion de modelo del motor (lineas 630-653),
    modo normal (sin FORCE_*). Retorna (model_code, mu)."""
    last4 = vals[-MEDIAN_K:] if len(vals) >= MEDIAN_K else vals
    stype = _classify_series_type(vals)
    if stype == 'smooth':
        a = ALPHA_SMOOTH_A if abc == 'A' else ALPHA_SMOOTH_BC
        return stype, 'ses_a%.2f' % a, _ses_level(vals, a)
    if stype == 'erratic':
        a = ALPHA_ERRATIC
        return stype, 'ses_a%.2f' % a, _ses_level(vals, a)
    if stype == 'no_signal':
        tail = vals[-SMA_TAIL_WEEKS:] if vals else vals
        mu = (sum(tail) / len(tail)) if tail else 0.0
        return stype, 'sma%d_ns' % SMA_TAIL_WEEKS, mu
    # intermittent / lumpy
    tail = vals[-SMA_TAIL_WEEKS:] if vals else vals
    mu = (sum(tail) / len(tail)) if tail else 0.0
    return stype, 'sma%d' % SMA_TAIL_WEEKS, mu


# ----------------------------- Carga de cache (reuso HM_SI_local) -----------------------------
def load_cache(cache_dir):
    cache_dir = Path(cache_dir)
    pos = pd.read_parquet(cache_dir / "pos_weekly.parquet")
    return pos


def load_abc(cache_dir):
    """pid -> letra ABC (primer char de x_studio_abcxyz, igual que el motor)."""
    df = pd.read_parquet(Path(cache_dir) / "abcxyz.parquet")
    out = {}
    for _, r in df.iterrows():
        pid = r.get('product_id')
        if pd.isna(pid):
            continue
        ltr = (str(r.get('x_studio_abcxyz') or '').strip().upper()[:1])
        if ltr:
            out[int(pid)] = ltr
    return out


def load_dow_weight(cache_dir):
    """isodow(1..7) -> peso (suma 1). Fallback uniforme si no existe."""
    p = Path(cache_dir) / "dow_profile.parquet"
    if not p.exists():
        return {i: 1.0 / 7.0 for i in range(1, 8)}
    df = pd.read_parquet(p)
    out = {int(r['isodow']): float(r['weight']) for _, r in df.iterrows()}
    return out or {i: 1.0 / 7.0 for i in range(1, 8)}


def build_qweight(cache_dir, dow_weight, cutoff_monday):
    """qweight[(team,product,week_start)] = [n_days, peso_perdido] desde quiebres_daily,
    acotado a las ultimas CLEANSE_LOOKBACK_WEEKS sem (igual que el motor). Replica el
    GROUP BY (product, team, week, isodow) + acumulacion de peso dow."""
    p = Path(cache_dir) / "quiebres_daily.parquet"
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    df['date'] = pd.to_datetime(df['date']).dt.date
    cl_from = cutoff_monday - timedelta(weeks=max(CLEANSE_LOOKBACK_WEEKS - 1, 0))
    df = df[(df['date'] >= cl_from) & (df['date'] <= cutoff_monday + timedelta(days=6))].copy()
    df['week'] = df['date'].apply(lambda d: d - timedelta(days=d.weekday()))
    qweight = {}
    for r in df.itertuples(index=False):
        key = (int(r.team_id), int(r.product_id), r.week)
        wpen = dow_weight.get(int(r.isodow), 1.0 / 7.0) * int(r.ndays)
        e = qweight.get(key)
        if e is None:
            qweight[key] = [int(r.ndays), wpen]
        else:
            e[0] += int(r.ndays)
            e[1] += wpen
    return qweight


def _build_series_map(pos, cutoff_date, history_weeks):
    """dict (team,product)->list[float] weekly 0-filled, ventana
    [cutoff_monday-(history_weeks-1)*7, cutoff_monday]. Igual que el motor."""
    cutoff_monday = cutoff_date - timedelta(days=cutoff_date.weekday())
    history_from = cutoff_monday - timedelta(weeks=max(history_weeks - 1, 0))
    pos_f = pos[(pos['week_start'] >= history_from) & (pos['week_start'] <= cutoff_monday)].copy()

    weeks = []
    w = history_from
    while w <= cutoff_monday:
        weeks.append(w)
        w += timedelta(days=7)
    week_idx = {wk: i for i, wk in enumerate(weeks)}
    n_weeks = len(weeks)

    series = {}
    cat_by_pair = {}
    for (team, prod, categ), grp in pos_f.groupby(['team_id', 'product_id', 'categ_id'], dropna=False):
        arr = [0.0] * n_weeks
        for _, row in grp.iterrows():
            wi = week_idx.get(row['week_start'])
            if wi is not None:
                arr[wi] = float(row['qty_sold'] or 0.0)
        ti = int(team) if pd.notna(team) else 0
        pi = int(prod) if pd.notna(prod) else 0
        ci = int(categ) if pd.notna(categ) else 0
        series[(ti, pi)] = arr
        cat_by_pair[(ti, pi)] = ci
    return series, cat_by_pair, weeks


# ----------------------------- Run -----------------------------
def run(cutoff_date, cache_dir=CACHE_DIR_DEFAULT, decensor=True):
    """cutoff_date = domingo de la ultima semana cerrada (o cualquier dia: se
    alinea al lunes). decensor=True aplica el cleansing de quiebre (paridad con
    el motor productivo, que corre con de-censura ON por default).
    Devuelve DataFrame de forecast para target = lunes+1sem."""
    print(f"[{VERSION_ID}] cutoff={cutoff_date}  cache={cache_dir}  decensor={decensor}")
    pos = load_cache(cache_dir)
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abc_letter = load_abc(cache_dir)

    cutoff_monday = cutoff_date - timedelta(days=cutoff_date.weekday())
    target_date = cutoff_monday + timedelta(weeks=1)
    series, cat_by_pair, weeks = _build_series_map(pos, cutoff_date, DEMAND_WINDOW_WEEKS)

    qweight = {}
    if decensor:
        dow_weight = load_dow_weight(cache_dir)
        qweight = build_qweight(cache_dir, dow_weight, cutoff_monday)
    print(f"  pares (team,sku)={len(series)}  semanas={len(weeks)}  target={target_date}  "
          f"qweight_keys={len(qweight)}")

    rows = []
    model_counts = {}
    mu_total = 0.0
    n_nonzero = 0
    n_cleansed = 0
    for (tid, pid), raw_vals in series.items():
        if decensor and qweight:
            vals, n_lift = _cleanse_stockout(raw_vals, weeks, tid, pid, qweight,
                                             CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT)
            if n_lift > 0:
                n_cleansed += 1
        else:
            vals = raw_vals
        abc = abc_letter.get(pid, '')
        stype, model_code, mu = _select_model(vals, abc)
        if mu < 0.0:
            mu = 0.0
        last4 = vals[-MEDIAN_K:] if len(vals) >= MEDIAN_K else vals
        mean4 = sum(last4) / len(last4) if last4 else 0.0
        if len(last4) > 1:
            sigma = (sum((x - mean4) ** 2 for x in last4) / len(last4)) ** 0.5
        else:
            sigma = 0.0
        mu_total += mu
        if mu > 0.0:
            n_nonzero += 1
        model_counts[model_code] = model_counts.get(model_code, 0) + 1
        rows.append({
            'team_id': tid, 'product_id': pid, 'categ_id': cat_by_pair.get((tid, pid), 0),
            'week_start': target_date, 'mu_week': mu, 'sigma_week': sigma,
            'forecast_model_code': model_code, 'series_type': stype, 'abc': abc,
        })

    df = pd.DataFrame(rows)
    mc = ' '.join('%s=%s' % (k, v) for k, v in sorted(model_counts.items()))
    print(f"  forecasts={len(df)}  nonzero={n_nonzero}  mu_sum={round(mu_total,1)}  "
          f"cleansed_combos={n_cleansed}  models[{mc}]")
    return df


if __name__ == "__main__":
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    decensor = not ('--no-decensor' in sys.argv or 'off' in sys.argv[2:])
    out = run(cutoff, decensor=decensor)
    RESULTS_DIR.mkdir(exist_ok=True)
    tag = '' if decensor else '_crudo'
    dest = RESULTS_DIR / f"forecast_base_local_{cutoff}{tag}.parquet"
    out.to_parquet(dest, index=False)
    print(f"  escrito: {dest}")
