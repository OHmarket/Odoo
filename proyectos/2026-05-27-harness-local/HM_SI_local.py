"""
HM-SI motor mirror local (sin Odoo). Lee parquets del cache y devuelve
DataFrame de forecasts.

Las funciones puras (_calc_si_from_weekly, _calc_base_demand, _get_si_final,
_avg_std, _clamp) son COPIA EXACTA del motor productivo HM-SI v3.46
para garantizar paridad numerica en el core.

Uso:
    from HM_SI_local import run
    from datetime import date
    df = run(cutoff_date=date(2026, 5, 17), config=DEFAULT_CONFIG, cache_dir='cache')

Returns:
    DataFrame con columnas: team_id, product_id, categ_id, week_start (target),
        mu_base, sigma_base, mu_week, si_factor, si_level, demand_method,
        collapse_detected, n_history_weeks.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import numpy as np

VERSION_ID = "HM_SI_LOCAL_v3_46_MIRROR_v0_1"


# ----------------------------- Config -----------------------------

DEFAULT_CONFIG = {
    # Ventanas SMA
    "SERVICE_BASE_SHORT_WEEKS": 6,
    "SERVICE_BASE_LONG_WEEKS": 16,
    "SERVICE_RATIO_UP": 1.15,
    "SERVICE_RATIO_HOLD": 0.90,
    "SERVICE_RATIO_COLLAPSE": 0.30,
    "SERVICE_DOWN_W_SHORT": 0.70,
    "SERVICE_DOWN_W_LONG": 0.30,

    # Ventana de historia (semanas hacia atras desde cutoff)
    "DEMAND_WINDOW_WEEKS": 26,
    "DEMAND_HISTORY_MONTHS": 24,  # ventana mayor para quarterly aggs lifecycle

    # SI
    "SI_ENABLED": True,
    "SI_HISTORY_MONTHS": 36,
    "SI_FLOOR": 0.05,
    "SI_CEIL": 5.0,
    "SI_SKU_ADJ_ALPHA_LOW": 0.15,
    "SI_SKU_ADJ_ALPHA_HIGH": 0.30,
    "SI_MIN_YEARS_FOR_SKU": 3,
    "SI_MIN_OBS_LOCAL_CATEG": 12,  # semanas para SI local_categ

    # Target: cuantas semanas adelante (1 = proxima semana)
    "SI_TARGET_WEEKS": 1,

    # XYZ local + series_type thresholds (Syntetos-Boylan)
    "XYZ_LOCAL_MIN_WEEKS": 4,
    "XYZ_LOCAL_T1": 0.45,
    "XYZ_LOCAL_T2": 0.90,
    "ADI_THRESHOLD_LOCAL": 1.32,
    "CV2_THRESHOLD_LOCAL": 0.49,
    "MIN_ACTIVE_WEEKS_LIFECYCLE": 4,

    # Bake-off Croston/SBA tunables (v3.39)
    "HEUR_BIAS": 0.90,
    "SBA_ALPHA": 0.15,
    "CROSTON_ALPHA": 0.10,

    # Trend correction (v3.43)
    "APPLY_TREND_CORRECTION": True,
    "TREND_LOOKBACK_WEEKS": 60,
    "TREND_WINDOW_WEEKS": 8,
    "TREND_CLAMP_LOW": 0.70,
    "TREND_CLAMP_HIGH": 1.00,  # asimetrico: NO amplifica

    # Fair share canon v3.42
    "FAIR_SHARE_ENABLED": True,
    "FAIR_SHARE_MIN_SALAS_ACTIVAS": 1,
    "FAIR_SHARE_MIN_HISTORIA_CATEG": 12,
    "FAIR_SHARE_BIAS": 1.00,
    "FAIR_SHARE_MIN_UNITS": 1.0,
    "FAIR_SHARE_SIGMA_CV": 0.5,
    "FAIR_SHARE_BOTTOM_PCT": 0.5,
    "FAIR_SHARE_CONF_N_MAP": {0: 0.00, 1: 0.30, 2: 0.50, 3: 0.75, 4: 0.75},
    "FAIR_SHARE_GROWTH_CAP": {'X': 3.0, 'Y': 2.0, 'Z': 1.5},
    "FAIR_SHARE_TRIED_PENALTY": 0.15,
    "FAIR_SHARE_ALLOWED_ABC": ('A', 'B'),
    "FAIR_SHARE_B_MAX_GAP": 2,
    "FAIR_SHARE_N_SALAS_TOTAL": 12,
}


# ----------------------------- Helpers (copia motor productivo) -----------------------------

def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _safe_text(v, maxlen=255):
    if v is None:
        return ''
    try:
        s = str(v)
    except Exception:
        s = ''
    if maxlen and len(s) > maxlen:
        return s[:maxlen]
    return s


def _norm_txt(v, maxlen=80):
    return _safe_text(v, maxlen).strip().lower()


def _clamp(v, lo, hi):
    x = _safe_float(v, 1.0)
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _avg_std(vals):
    n = len(vals or [])
    if n <= 0:
        return 0.0, 0.0
    total = 0.0
    sq = 0.0
    for v in vals:
        x = _safe_float(v, 0.0)
        total += x
        sq += x * x
    mu = total / n
    var = (sq / n) - (mu * mu)
    if var < 0.0:
        var = 0.0
    return mu, var ** 0.5


def _iso_week_52(d):
    w = d.isocalendar()[1]
    return 52 if w > 52 else w


# ----------------------------- Pure functions (copia exacta motor productivo) -----------------------------

# Syntetos-Boylan thresholds (motor productivo lines 392-393)
ADI_THRESHOLD_LOCAL = 1.32
CV2_THRESHOLD_LOCAL = 0.49


def _xyz_from_serie(vals, t1, t2):
    """Motor productivo line 369. CV simple sobre la serie."""
    if not vals:
        return ''
    mu, sigma = _avg_std(vals)
    if mu <= 0.0:
        return ''
    cv = sigma / mu
    if cv <= t1:
        return 'X'
    if cv <= t2:
        return 'Y'
    return 'Z'


def _classify_series_type_local(adi, cv2, active_weeks, min_active_weeks,
                                 adi_threshold=ADI_THRESHOLD_LOCAL,
                                 cv2_threshold=CV2_THRESHOLD_LOCAL):
    """Motor productivo line 401. Idéntico."""
    if (active_weeks or 0) < (min_active_weeks or 0):
        return 'no_signal'
    if not adi or adi <= 0:
        return 'no_signal'
    high_var = (cv2 or 0.0) >= cv2_threshold
    if adi >= adi_threshold:
        return 'lumpy' if high_var else 'intermittent'
    return 'erratic' if high_var else 'smooth'


def _infer_lifecycle_local(u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7, p_q8, xyz,
                            nz_recent_8w=0):
    """Motor productivo line 419. Idéntico (v3.44 fix declining via nz_recent_8w)."""
    u_rest = u_q1 + u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7
    u8 = u_q0 + u_rest
    if u8 <= 0:
        return 'dead'
    if p_q8 <= 2 and u_q1 <= 0:
        return 'intermittent'
    if u_q0 > 0 and u_rest <= 0:
        return 'new'
    if u_q0 <= 0 and (u_q1 + u_q2 + u_q3) > 0 and nz_recent_8w <= 0:
        return 'declining'
    if xyz == 'Z' and p_q8 <= 5:
        return 'seasonal'
    if u_q0 > 0 and u_q1 <= 0 and (u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7) > 0:
        return 'ramp_up'
    return 'mature'


def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _compute_fair_share(product_id, team_id, categ_id_local,
                        router_ctx, fs_ctx,
                        bias, sigma_cv, min_units,
                        min_salas, min_historia, bottom_pct,
                        active_weeks_target=0,
                        conf_n_map=None, growth_cap_map=None,
                        tried_penalty=0.15,
                        allowed_abc=('A', 'B'), b_max_gap=2,
                        n_salas_total=12):
    """Motor productivo line 1039 v3.42. Copia exacta."""
    rctx = router_ctx.get(product_id) if router_ctx else None
    if not rctx:
        return None

    abcxyz_global = _safe_text(rctx.get('abcxyz', ''), 20).upper()
    abc_global = abcxyz_global[:1] if abcxyz_global else ''
    xyz_global = abcxyz_global[1:2] if len(abcxyz_global) >= 2 else ''
    if abc_global not in allowed_abc:
        return None

    mu_global = _safe_float(rctx.get('mu_week_global', 0.0), 0.0)

    categ_efectiva = _safe_int(categ_id_local, 0) or _safe_int(rctx.get('categ_global_id'), 0)
    if not categ_efectiva:
        return None

    sku_qty_per_sala = fs_ctx.get('sku_qty_per_sala', {})
    categ_qty_per_sala = fs_ctx.get('categ_qty_per_sala', {})
    n_weeks_window = _safe_float(fs_ctx.get('n_weeks_window', 26.0), 26.0) or 26.0

    shares = []
    for (team_i, pid), qty_sku in sku_qty_per_sala.items():
        if pid != product_id or qty_sku <= 0.0:
            continue
        qty_categ = _safe_float(categ_qty_per_sala.get((team_i, categ_efectiva), 0.0), 0.0)
        if qty_categ <= 0.0:
            continue
        shares.append(qty_sku / qty_categ)
    n_active = len(shares)

    if n_active < min_salas:
        return None

    factor_normalizado = sum(shares) / float(n_active)
    if factor_normalizado <= 0.0:
        return None

    gap_count = max(1, int(n_salas_total) - n_active)

    if abc_global == 'B' and gap_count > b_max_gap:
        return None

    if conf_n_map is None:
        conf_n_map = {0: 0.0, 1: 0.30, 2: 0.50, 3: 0.75, 4: 0.75}
    conf_n = float(conf_n_map.get(n_active, 1.00))

    historia = _safe_int(fs_ctx.get('historia_categ', {}).get((team_id, categ_efectiva), 0), 0)
    if historia >= min_historia:
        qty_categ_target = _safe_float(categ_qty_per_sala.get((team_id, categ_efectiva), 0.0), 0.0)
        mu_categ_target = qty_categ_target / n_weeks_window
        method = 'canon_real'
    else:
        otras_salas_categ = []
        for (team_i, c), qty in categ_qty_per_sala.items():
            if c == categ_efectiva and team_i != team_id and qty > 0.0:
                otras_salas_categ.append(qty)
        if not otras_salas_categ:
            return None
        otras_salas_categ.sort()
        n_total = len(otras_salas_categ)
        n_bottom_raw = float(n_total) * float(bottom_pct)
        n_bottom = max(1, int(n_bottom_raw + 0.5))
        if n_bottom > n_total:
            n_bottom = n_total
        bottom_qtys = otras_salas_categ[:n_bottom]
        mu_categ_target = (sum(bottom_qtys) / float(len(bottom_qtys))) / n_weeks_window
        method = 'canon_bottom%d' % n_bottom

    if mu_categ_target <= 0.0:
        return None

    factor_efectivo = factor_normalizado * conf_n
    if factor_efectivo <= 0.0:
        return None
    mu_raw = factor_efectivo * mu_categ_target * float(bias)
    if mu_raw <= 0.0:
        return None

    if growth_cap_map is None:
        growth_cap_map = {'X': 3.0, 'Y': 2.0, 'Z': 1.5}
    growth = float(growth_cap_map.get(xyz_global, 1.5))
    mu_cap_per_par = (mu_global * growth) / float(gap_count) if mu_global > 0 else 0.0

    cap_applied = False
    if mu_cap_per_par > 0 and mu_raw > mu_cap_per_par:
        mu_capped = mu_cap_per_par
        cap_applied = True
    else:
        mu_capped = mu_raw

    tried_applied = False
    if active_weeks_target > 0:
        mu_capped = mu_capped * float(tried_penalty)
        tried_applied = True

    if (not tried_applied) and min_units > 0.0 and mu_capped < min_units:
        mu_fs = float(min_units)
        floor_applied = True
    else:
        mu_fs = mu_capped
        floor_applied = False

    sigma_fs = mu_fs * float(sigma_cv)

    reason = (
        'CANON_%s|abc=%s|xyz=%s|n=%d|conf=%.2f|gap=%d|factor=%.4f|'
        'mu_categ=%.2f|raw=%.2f|cap=%s|tried=%s|floor=%s'
        % (method, abc_global, xyz_global, n_active, conf_n, gap_count,
           factor_normalizado, mu_categ_target, mu_raw,
           'Y' if cap_applied else 'N',
           'Y' if tried_applied else 'N',
           'Y' if floor_applied else 'N')
    )[:240]
    return {
        'mu_week': mu_fs,
        'sigma_week': sigma_fs,
        'method': method,
        'reason': reason,
        'scope': 'core_canon_v42',
        'n_active': n_active,
        'gap_count': gap_count,
        'conf_n': conf_n,
        'cap_applied': cap_applied,
        'tried_applied': tried_applied,
    }


def _route_forecast_scope(abcxyz, series_type, lifecycle, mu_week):
    """Motor productivo line 1202 v3.46 (sin `mu < 2.0` threshold)."""
    abc = _safe_text(abcxyz, 20).strip().upper()
    st = _norm_txt(series_type, 40)
    lc = _norm_txt(lifecycle, 40)
    mu = _safe_float(mu_week, 0.0)

    if (st == 'smooth') and (abc == 'AX') and (lc in ('mature', 'ramp_up')) and (mu >= 1.0):
        return 'Z1', 'core_hm_si', 'hm_si_core', 'A_smooth_core_ax'

    if (abc == 'AZ') and (lc not in ('declining', 'dead')):
        return 'Z1', 'core_hm_si', 'hm_si_core_az', 'A_high_margin_sporadic'

    if (abc in ('AX', 'AY')) and (lc not in ('declining', 'dead')):
        return 'Z1', 'core_hm_si', 'hm_si_core_a_low_mu', 'A_low_velocity_rescue'

    if (st == 'no_signal') or (abc in ('CX', 'CY', 'CZ')) or (lc in ('declining', 'dead')):
        return 'Z4', 'no_forecast', 'min_stock_or_manual', 'D_no_signal_C_terminal'

    if (st == 'smooth') and (abc in ('AX', 'AY', 'BX')) and (lc in ('mature', 'ramp_up')) and (mu >= 2.0):
        return 'Z1', 'core_hm_si', 'hm_si_core', 'A_smooth_core'

    if (st in ('erratic', 'lumpy')) and (abc in ('AX', 'AY')) and (lc in ('mature', 'ramp_up')) and (mu >= 2.0):
        return 'Z2', 'controlled_hm_si', 'hm_si_controlled', 'B_erratic_lumpy_core'

    if (lc == 'seasonal') or ((st in ('erratic', 'lumpy')) and (abc in ('BY', 'BZ', 'AZ'))):
        return 'Z3', 'secondary_model', 'secondary_replenishment', 'C_secondary_pattern'

    return 'Z3', 'secondary_model', 'secondary_replenishment', 'C_fallback_secondary'


def _assign_regimen_local(abcxyz, series_type, ciclo_de_vida):
    """Motor productivo line 451. Idéntico."""
    abc_letter = (abcxyz or '')[:1].upper()
    s = (series_type or '').strip().lower()
    c = (ciclo_de_vida or '').strip().lower()

    if c in ('dead', 'declining'):
        return 'REG-0'
    if s == 'no_signal' and abc_letter == 'C':
        return 'REG-0'

    if c == 'seasonal':
        return 'REG-8'
    if c == 'ramp_up':
        return 'REG-1'

    if s == 'smooth':
        if abc_letter == 'A':
            return 'REG-1'
        if abc_letter == 'B':
            return 'REG-2'
        return 'REG-3'

    if s == 'erratic':
        return 'REG-4'

    if s == 'lumpy':
        if abc_letter in ('A', 'B'):
            return 'REG-5'
        return 'REG-6'

    if s in ('intermittent', 'no_signal'):
        return 'REG-7'

    return 'REG-0'


# ----------------------------- Helpers para clasificación local desde serie -----------------------------

def _compute_adi_cv2(series):
    """Calcula ADI y CV² desde una serie weekly.

    ADI = total_periods / num_active_periods (>=1 si hay venta).
    CV² = (sigma_active / mu_active)².
    """
    n = len(series or [])
    if n == 0:
        return 0.0, 0.0, 0
    active = [v for v in series if _safe_float(v, 0.0) > 0]
    n_active = len(active)
    if n_active == 0:
        return 0.0, 0.0, 0
    adi = n / n_active
    mu_a, sigma_a = _avg_std(active)
    cv2 = (sigma_a / mu_a) ** 2 if mu_a > 0 else 0.0
    return adi, cv2, n_active


def _compute_quarterly_aggs(series, weeks):
    """Devuelve (u_q0..u_q7, p_q8, nz_recent_8w) sobre serie weekly.

    series: lista de qty por semana, ordenada ascendente.
    weeks: lista de date (lunes) correspondiente, ordenada ascendente.
    q0 = trimestre más reciente, q7 = más antiguo.
    p_q8 = cantidad de trimestres con venta entre los 8 más recientes.
    nz_recent_8w = semanas con venta>0 en últimas 8.
    """
    if not series:
        return [0.0] * 8 + [0, 0]

    # Asignar cada semana a su quarter index relativo al final.
    # Q absoluto = year*4 + (month-1)//3 + 1
    if not weeks:
        return [0.0] * 8 + [0, 0]

    last_week = weeks[-1]
    q_last = last_week.year * 4 + ((last_week.month - 1) // 3) + 1

    q_sums = {}
    for w, v in zip(weeks, series):
        q_abs = w.year * 4 + ((w.month - 1) // 3) + 1
        q_rel = q_last - q_abs  # 0 = current, 1 = prev, etc.
        if 0 <= q_rel <= 7:
            q_sums[q_rel] = q_sums.get(q_rel, 0.0) + _safe_float(v, 0.0)

    q_vals = [q_sums.get(i, 0.0) for i in range(8)]
    p_q8 = sum(1 for q in q_vals if q > 0)

    nz_recent_8w = sum(1 for v in series[-8:] if _safe_float(v, 0.0) > 0)

    return q_vals + [p_q8, nz_recent_8w]


def _calc_si_from_weekly(weekly_by_isoweek):
    """Idéntico al motor productivo line 497."""
    avg_by_week = {}
    for w, totals in (weekly_by_isoweek or {}).items():
        clean = [_safe_float(x, 0.0) for x in (totals or [])]
        if clean:
            avg_by_week[w] = sum(clean) / len(clean)

    if not avg_by_week:
        return {w: 1.0 for w in range(1, 53)}

    global_avg = sum(avg_by_week.values()) / len(avg_by_week)
    if global_avg <= 0.0:
        return {w: 1.0 for w in range(1, 53)}

    si_norm = {}
    for w, v in avg_by_week.items():
        si_norm[w] = v / global_avg

    for w in range(1, 53):
        if w not in si_norm:
            si_norm[w] = 1.0

    return si_norm


def _get_si_final(iso_week, team_id, product_id, categ_id,
                  si_local_categ, si_categ_global, si_sku_raw, si_global,
                  n_years_sku, si_min_years,
                  sku_adj_alpha_low, sku_adj_alpha_high,
                  si_floor, si_ceil):
    """Idéntico al motor productivo line 527."""
    w = iso_week if 1 <= iso_week <= 52 else 52

    lc_key = (team_id, categ_id) if categ_id else None
    si_main = si_local_categ.get(lc_key, {}).get(w, None) if lc_key else None

    if si_main is not None:
        level = 'local_categ'
    else:
        si_main = si_categ_global.get(categ_id, {}).get(w, None) if categ_id else None
        if si_main is not None:
            level = 'categ_global'
        else:
            si_main = si_global.get(w, 1.0)
            level = 'global'

    si_main_factor = _safe_float(si_main, 1.0)
    si_sku_factor = 1.0

    si_s = si_sku_raw.get(product_id, {}).get(w, None)
    si_c = si_categ_global.get(categ_id, {}).get(w, 1.0) if categ_id else 1.0

    if si_s is not None and n_years_sku >= 1 and si_c > 0.001:
        si_sku_deviation = _safe_float(si_s, 1.0) / si_c
        alpha = sku_adj_alpha_high if n_years_sku >= si_min_years else sku_adj_alpha_low
        si_sku_factor = 1.0 + alpha * (si_sku_deviation - 1.0)
        level = level + '+sku_adj'

    si_final = _clamp(si_main_factor * si_sku_factor, si_floor, si_ceil)
    if si_main_factor > 0.0:
        si_sku_factor = si_final / si_main_factor
    else:
        si_sku_factor = 1.0

    return si_final, level, si_main_factor, si_sku_factor


def _croston(history, alpha=0.1):
    """Motor productivo line 627. Croston (1972) - demanda intermitente."""
    n = len(history or [])
    if n == 0:
        return 0.0
    z = None
    p = None
    q = 0
    for t in range(n):
        y = _safe_float(history[t], 0.0)
        q += 1
        if y > 0:
            if z is None:
                z = y
                p = float(q)
            else:
                z = alpha * y + (1.0 - alpha) * z
                p = alpha * q + (1.0 - alpha) * p
            q = 0
    if z is None or p is None or p <= 0:
        return 0.0
    return z / p


def _sba(history, alpha=0.1):
    """Motor productivo line 656. SBA (Syntetos-Boylan 2005)."""
    base = _croston(history, alpha=alpha)
    return (1.0 - alpha / 2.0) * base


def _mae_of_forecast(forecast_val, actual_list):
    """Motor productivo line 666."""
    n = len(actual_list or [])
    if n == 0:
        return float('inf')
    total = 0.0
    for a in actual_list:
        total += abs(_safe_float(a, 0.0) - forecast_val)
    return total / float(n)


def _calc_base_demand(base_vals, raw_vals,
                      short_weeks, long_weeks,
                      ratio_up, ratio_hold, ratio_collapse,
                      down_w_short, down_w_long):
    """Idéntico al motor productivo line 568."""
    n = len(base_vals or [])
    if n <= 0:
        return 0.0, 0.0, 'no_history', False

    mu_all, sigma_all = _avg_std(base_vals)

    if n < long_weeks:
        return mu_all, sigma_all, 'avg_base_%sw' % n, False

    short_vals = base_vals[-short_weeks:]
    long_vals = base_vals[-long_weeks:]

    sma_short, sigma_short = _avg_std(short_vals)
    sma_long, sigma_long = _avg_std(long_vals)

    if sma_long > 0.0:
        ratio = sma_short / sma_long
    else:
        ratio = 9.99 if sma_short > 0.0 else 1.0

    raw_n = len(raw_vals or [])
    if raw_n >= long_weeks:
        raw_short_avg, _ = _avg_std(raw_vals[-short_weeks:])
        raw_long_avg, _ = _avg_std(raw_vals[-long_weeks:])
        if raw_long_avg > 0.0:
            raw_ratio = raw_short_avg / raw_long_avg
        else:
            raw_ratio = 9.99 if raw_short_avg > 0.0 else 1.0
    else:
        raw_ratio = ratio

    if ratio >= ratio_up:
        return sma_short, sigma_short, 'sma%s_base_up_r=%s' % (short_weeks, round(ratio, 3)), False

    if ratio >= ratio_hold:
        return sma_long, sigma_long, 'sma%s_base_hold_r=%s' % (long_weeks, round(ratio, 3)), False

    if raw_ratio < ratio_collapse:
        return sma_short, sigma_short, 'sma%s_base_collapse_rawr=%s' % (short_weeks, round(raw_ratio, 3)), True

    mu_blend = (down_w_short * sma_short) + (down_w_long * sma_long)
    sigma_blend = (down_w_short * sigma_short) + (down_w_long * sigma_long)
    return mu_blend, sigma_blend, 'blend_down_base_r=%s' % round(ratio, 3), False


def _select_best_model(base_vals, raw_vals,
                       short_weeks, long_weeks,
                       ratio_up, ratio_hold, ratio_collapse,
                       down_w_short, down_w_long,
                       heur_bias=0.90,
                       sba_alpha=0.15, croston_alpha=0.10):
    """Motor productivo line 705. Bake-off heur vs SBA vs Croston
    vs seasonal_naive_52. Holdout 4 sem. Heur gana si mejora del otro < (1-heur_bias).

    sba_alpha, croston_alpha: tunables (defaults igual al motor productivo).
    """
    n = len(base_vals or [])
    if n < 12:
        return _calc_base_demand(
            base_vals, raw_vals,
            short_weeks, long_weeks,
            ratio_up, ratio_hold, ratio_collapse,
            down_w_short, down_w_long,
        )

    n_holdout = 4
    train_b = base_vals[:-n_holdout]
    train_r = raw_vals[:-n_holdout]
    actual = base_vals[-n_holdout:]

    heur_mu, heur_sigma, heur_method, heur_collapse = _calc_base_demand(
        train_b, train_r,
        short_weeks, long_weeks,
        ratio_up, ratio_hold, ratio_collapse,
        down_w_short, down_w_long,
    )
    heur_mae = _mae_of_forecast(heur_mu, actual)

    candidates = [('heur', heur_mae, heur_mu)]

    sba_f = _sba(train_b, alpha=sba_alpha)
    if sba_f > 0:
        candidates.append(('sba_a%.2f' % sba_alpha, _mae_of_forecast(sba_f, actual), sba_f))

    crost_f = _croston(train_b, alpha=croston_alpha)
    if crost_f > 0:
        candidates.append(('croston_a%.2f' % croston_alpha, _mae_of_forecast(crost_f, actual), crost_f))

    if n >= 56:
        sn_f = _safe_float(train_b[-52], 0.0)
        if sn_f > 0:
            candidates.append(('seasonal_naive_52', _mae_of_forecast(sn_f, actual), sn_f))

    best_idx = 0
    for _i in range(1, len(candidates)):
        if candidates[_i][1] < candidates[best_idx][1]:
            best_idx = _i
    best_code = candidates[best_idx][0]
    best_mae = candidates[best_idx][1]

    if best_code != 'heur' and best_mae > heur_mae * heur_bias:
        best_code = 'heur'

    if best_code == 'heur':
        return _calc_base_demand(
            base_vals, raw_vals,
            short_weeks, long_weeks,
            ratio_up, ratio_hold, ratio_collapse,
            down_w_short, down_w_long,
        )

    if best_code.startswith('sba_'):
        mu = _sba(base_vals, alpha=sba_alpha)
    elif best_code.startswith('croston_'):
        mu = _croston(base_vals, alpha=croston_alpha)
    elif best_code == 'seasonal_naive_52':
        mu = _safe_float(base_vals[-52], 0.0) if n >= 52 else 0.0
    else:
        mu = heur_mu

    if mu <= 0:
        return _calc_base_demand(
            base_vals, raw_vals,
            short_weeks, long_weeks,
            ratio_up, ratio_hold, ratio_collapse,
            down_w_short, down_w_long,
        )

    _, sigma_full, _, _ = _calc_base_demand(
        base_vals, raw_vals,
        short_weeks, long_weeks,
        ratio_up, ratio_hold, ratio_collapse,
        down_w_short, down_w_long,
    )
    return mu, sigma_full, best_code, False


# ----------------------------- Local cache loader -----------------------------

def load_cache(cache_dir):
    cache_dir = Path(cache_dir)
    pos = pd.read_parquet(cache_dir / "pos_weekly.parquet")
    catalog = pd.read_parquet(cache_dir / "catalog_products.parquet")
    return pos, catalog


def load_price_corr(cache_dir, target_date):
    """Lee price_corr.parquet y devuelve dict product_id -> dict con factor,
    tipo, razon, target_week_start, weeks_since. Los factores son GLOBALES
    por producto (no por team — el detector v5.x emite a nivel SKU).
    Filtra al factor mas reciente cuya target_week_start <= target_date.
    """
    cache_dir = Path(cache_dir)
    df = pd.read_parquet(cache_dir / "price_corr.parquet")
    df = df.copy()
    df['target_week_dt'] = pd.to_datetime(df['x_studio_target_week_start']).dt.date
    df = df[df['target_week_dt'] <= target_date]
    if 'x_studio_active' in df.columns:
        df = df[df['x_studio_active'].fillna(True)]
    df = df.sort_values('target_week_dt', ascending=False)

    out = {}
    for _, r in df.iterrows():
        pid = r.get('product_id')
        if pd.isna(pid):
            continue
        pid = int(pid)
        if pid in out:
            continue
        out[pid] = {
            'factor': _safe_float(r.get('x_studio_factor_corr'), 1.0),
            'tipo': _safe_text(r.get('x_studio_tipo_alerta'), 60),
            'razon': _safe_text(r.get('x_studio_razon'), 240),
            'weeks_since': int(r.get('x_studio_weeks_since_change') or 0),
            'target_week_start': r.get('target_week_dt'),
        }
    return out


def load_abcxyz(cache_dir):
    """Lee abcxyz.parquet y devuelve dict pid -> dict con abcxyz, series_type,
    lifecycle, mu_week_global, categ_global_id, regimen."""
    cache_dir = Path(cache_dir)
    df = pd.read_parquet(cache_dir / "abcxyz.parquet")
    out = {}
    # El parquet ya tiene 'product_id' como columna integer (extraída del m2o)
    for _, r in df.iterrows():
        pid = r.get('product_id')
        if pd.isna(pid):
            continue
        # Preferir series_type_active sobre series_type cuando existe
        st = r.get('x_studio_series_type_active') or r.get('x_studio_series_type') or ''
        out[int(pid)] = {
            'abcxyz': (r.get('x_studio_abcxyz') or '').upper().strip(),
            'abc': (r.get('x_studio_abc') or '').upper().strip(),
            'xyz': (r.get('x_studio_xyz') or '').upper().strip(),
            'series_type': str(st).strip().lower() if st else '',
            'lifecycle': str(r.get('x_studio_ciclo_de_vida') or '').strip().lower(),
            'mu_week_global': _safe_float(r.get('x_studio_mu_week'), 0.0),
            'categ_global_id': int(r.get('categ_id')) if pd.notna(r.get('categ_id')) else 0,
            'regimen': (r.get('x_studio_regimen') or '').upper().strip(),
        }
    return out


# ----------------------------- Build series & SI dictionaries -----------------------------

def _build_series_map(pos, cutoff_date, history_weeks):
    """Devuelve dict (team_id, product_id) -> list[float] de qty weekly,
    ordenado ascendente, completando ceros para semanas sin venta dentro
    de la ventana [cutoff_monday - (history_weeks-1)*7, cutoff_monday].

    Replica motor productivo:
      demand_from = cutoff_monday - (history_weeks - 1) * 7 days
      weeks = monday-by-monday entre demand_from y cutoff_monday (incl).
    Total semanas = history_weeks (alineado al motor productivo).
    """
    cutoff_monday = cutoff_date - timedelta(days=cutoff_date.weekday())
    history_from_monday = cutoff_monday - timedelta(weeks=max(history_weeks - 1, 0))

    pos_f = pos[(pos['week_start'] >= history_from_monday) & (pos['week_start'] <= cutoff_monday)].copy()

    weeks = []
    w = history_from_monday
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
        team_int = int(team) if pd.notna(team) else 0
        prod_int = int(prod) if pd.notna(prod) else 0
        categ_int = int(categ) if pd.notna(categ) else 0
        series[(team_int, prod_int)] = arr
        cat_by_pair[(team_int, prod_int)] = categ_int

    return series, cat_by_pair, weeks


def _build_fair_share_ctx(pos, cutoff_date, window_weeks):
    """Pre-compute fs_ctx: sku_qty_per_sala, categ_qty_per_sala, historia_categ,
    n_weeks_window. Sobre ventana [cutoff - window_weeks, cutoff].
    """
    history_from = cutoff_date - timedelta(days=window_weeks * 7 + 6)
    history_from_monday = history_from - timedelta(days=history_from.weekday())
    pos_w = pos[(pos['week_start'] >= history_from_monday) & (pos['week_start'] <= cutoff_date)].copy()

    # sku_qty_per_sala: (team, pid) -> total qty
    sku_qty = pos_w.groupby(['team_id', 'product_id'], dropna=False)['qty_sold'].sum().reset_index()
    sku_qty_per_sala = {}
    for _, r in sku_qty.iterrows():
        if pd.isna(r['team_id']) or pd.isna(r['product_id']):
            continue
        q = float(r['qty_sold'] or 0.0)
        if q > 0:
            sku_qty_per_sala[(int(r['team_id']), int(r['product_id']))] = q

    # categ_qty_per_sala: (team, categ) -> total qty
    cat_qty = pos_w.groupby(['team_id', 'categ_id'], dropna=False)['qty_sold'].sum().reset_index()
    categ_qty_per_sala = {}
    for _, r in cat_qty.iterrows():
        if pd.isna(r['team_id']) or pd.isna(r['categ_id']):
            continue
        q = float(r['qty_sold'] or 0.0)
        if q > 0:
            categ_qty_per_sala[(int(r['team_id']), int(r['categ_id']))] = q

    # historia_categ: (team, categ) -> n_weeks distintas con venta
    hist = pos_w[pos_w['qty_sold'] > 0].groupby(['team_id', 'categ_id'], dropna=False)['week_start'].nunique().reset_index()
    historia_categ = {}
    for _, r in hist.iterrows():
        if pd.isna(r['team_id']) or pd.isna(r['categ_id']):
            continue
        historia_categ[(int(r['team_id']), int(r['categ_id']))] = int(r['week_start'])

    return {
        'sku_qty_per_sala': sku_qty_per_sala,
        'categ_qty_per_sala': categ_qty_per_sala,
        'historia_categ': historia_categ,
        'n_weeks_window': float(window_weeks),
    }


def _compute_trend_factors_by_team(pos, cutoff_date, lookback_weeks,
                                    window_weeks, clamp_low, clamp_high):
    """Motor productivo line 1840. weekly YoY asimetrico por team.

    Para cada team, compara qty_total_week_t (cutoff_week - i) vs misma sem LY (-52).
    Promedia window_weeks YoY ratios. Aplica clamp [clamp_low, clamp_high].
    Retorna dict team_id -> factor.
    """
    cutoff_monday = cutoff_date - timedelta(days=cutoff_date.weekday())
    trend_from = cutoff_monday - timedelta(weeks=lookback_weeks)

    pos_t = pos[(pos['week_start'] >= trend_from) & (pos['week_start'] <= cutoff_date)].copy()
    # Agregar a (team, week)
    agg = pos_t.groupby(['team_id', 'week_start'], dropna=False)['qty_sold'].sum().reset_index()

    weekly_team_units = {}
    for _, r in agg.iterrows():
        if pd.isna(r['team_id']) or pd.isna(r['week_start']):
            continue
        weekly_team_units[(int(r['team_id']), r['week_start'])] = float(r['qty_sold'] or 0.0)

    trend_factor_by_team = {}
    trend_log = {}
    team_ids = sorted({int(t) for t in pos_t['team_id'].dropna().unique()})
    for tid in team_ids:
        yoy_vals = []
        for i in range(window_weeks):
            wk = cutoff_monday - timedelta(weeks=i)
            wk_ly = wk - timedelta(weeks=52)
            curr = weekly_team_units.get((tid, wk))
            prev = weekly_team_units.get((tid, wk_ly))
            if curr is not None and prev and prev > 0:
                yoy_vals.append(curr / prev - 1.0)
        if yoy_vals:
            avg = sum(yoy_vals) / len(yoy_vals)
            fac = _clamp(1.0 + avg, clamp_low, clamp_high)
        else:
            avg = 0.0
            fac = 1.0
        trend_factor_by_team[tid] = fac
        trend_log[tid] = {'factor': fac, 'avg_yoy': avg, 'n_obs': len(yoy_vals)}

    return trend_factor_by_team, trend_log


def _build_si_dicts(pos, cutoff_date, si_history_months, si_min_obs_local_categ=12):
    """Construye:
    - si_local_categ: dict (team, categ) -> {iso_week: factor}  (solo si >= 12 obs)
    - si_categ_global: dict categ_id -> {iso_week: factor}
    - si_sku_raw: dict product_id -> {iso_week: factor}
    - si_global: dict iso_week -> factor (sobre todo el universo)
    Usa los ultimos si_history_months meses hasta cutoff.
    """
    si_from = cutoff_date - timedelta(days=si_history_months * 31)
    pos_si = pos[(pos['week_start'] >= si_from) & (pos['week_start'] <= cutoff_date)].copy()
    pos_si['iso_week'] = pos_si['week_start'].apply(lambda d: _iso_week_52(d))

    # SI por categoría (global, todos los teams)
    si_categ_global = {}
    for categ, sub in pos_si.groupby('categ_id'):
        if pd.isna(categ):
            continue
        by_isoweek = {}
        for iw, grp in sub.groupby('iso_week'):
            by_isoweek[int(iw)] = grp['qty_sold'].tolist()
        si_categ_global[int(categ)] = _calc_si_from_weekly(by_isoweek)

    # SI local_categ: por (team, categ) - solo si hay >= si_min_obs_local_categ obs
    si_local_categ = {}
    for (team, categ), sub in pos_si.groupby(['team_id', 'categ_id'], dropna=False):
        if pd.isna(team) or pd.isna(categ):
            continue
        if len(sub) < si_min_obs_local_categ:
            continue
        by_isoweek = {}
        for iw, grp in sub.groupby('iso_week'):
            by_isoweek[int(iw)] = grp['qty_sold'].tolist()
        si_local_categ[(int(team), int(categ))] = _calc_si_from_weekly(by_isoweek)

    # SI por SKU (raw, todos los teams)
    si_sku_raw = {}
    for prod, sub in pos_si.groupby('product_id'):
        if pd.isna(prod):
            continue
        by_isoweek = {}
        for iw, grp in sub.groupby('iso_week'):
            by_isoweek[int(iw)] = grp['qty_sold'].tolist()
        si_sku_raw[int(prod)] = _calc_si_from_weekly(by_isoweek)

    # SI global
    by_isoweek = {}
    for iw, grp in pos_si.groupby('iso_week'):
        by_isoweek[int(iw)] = grp['qty_sold'].tolist()
    si_global = _calc_si_from_weekly(by_isoweek)

    # n_years_sku: cuantos anos distintos vio cada SKU
    n_years_sku = {}
    for prod, sub in pos_si.groupby('product_id'):
        if pd.isna(prod):
            continue
        years = sub['week_start'].apply(lambda d: d.year).nunique()
        n_years_sku[int(prod)] = int(years)

    return si_local_categ, si_categ_global, si_sku_raw, si_global, n_years_sku


# ----------------------------- Main runner -----------------------------

def run(cutoff_date, config=None, cache_dir="cache"):
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    print(f"[HM_SI_local] cutoff={cutoff_date}  version={VERSION_ID}")
    print(f"  cargando cache desde {cache_dir}...")
    pos, catalog = load_cache(cache_dir)
    router_ctx = load_abcxyz(cache_dir)
    print(f"  ABCXYZ context: {len(router_ctx):,} SKUs")
    # Target_week se usa abajo, mientras tanto cargamos en el orden correcto

    # Convertir week_start (object date) a date Python si es necesario
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    print(f"  filas POS: {len(pos):,}")

    # Target week: cutoff + SI_TARGET_WEEKS - alineada al lunes siguiente al cutoff
    cutoff_monday = cutoff_date - timedelta(days=cutoff_date.weekday())
    target_week = cutoff_monday + timedelta(days=7 * cfg['SI_TARGET_WEEKS'])
    target_iso_week = _iso_week_52(target_week)
    print(f"  target_week={target_week}  iso_week={target_iso_week}")

    correccion_ctx = load_price_corr(cache_dir, target_week)
    print(f"  price_corr context: {len(correccion_ctx):,} productos con factor")

    print("  construyendo series weekly (window corta SMA)...")
    series_map, categ_by_pair, weeks = _build_series_map(pos, cutoff_date, cfg['DEMAND_WINDOW_WEEKS'])
    print(f"  pares (team, sku): {len(series_map):,}  semanas: {len(weeks)}")

    print("  construyendo series weekly (window larga para lifecycle)...")
    series_long, _, weeks_long = _build_series_map(
        pos, cutoff_date, int(cfg['DEMAND_HISTORY_MONTHS'] * 4.345)  # months -> weeks
    )
    print(f"  semanas largas: {len(weeks_long)}")

    print("  construyendo SI dicts...")
    si_local_categ, si_categ_global, si_sku_raw, si_global, n_years_sku = _build_si_dicts(
        pos, cutoff_date, cfg['SI_HISTORY_MONTHS'], cfg['SI_MIN_OBS_LOCAL_CATEG']
    )
    print(f"  SI local_categ (team,categ): {len(si_local_categ):,}  categ_global: {len(si_categ_global):,}  SKUs: {len(si_sku_raw):,}")

    # Bloque G: pre-compute fair_share_ctx
    fair_share_ctx = {}
    if cfg['FAIR_SHARE_ENABLED']:
        print("  computando fair_share_ctx...")
        fair_share_ctx = _build_fair_share_ctx(pos, cutoff_date, cfg['DEMAND_WINDOW_WEEKS'])
        print(f"    sku_qty_per_sala: {len(fair_share_ctx['sku_qty_per_sala']):,}")
        print(f"    categ_qty_per_sala: {len(fair_share_ctx['categ_qty_per_sala']):,}")

    # Bloque D: pre-compute trend factors por team (v3.43)
    trend_factor_by_team = {}
    if cfg['APPLY_TREND_CORRECTION']:
        print("  computando trend factors por team (YoY asimetrico)...")
        trend_factor_by_team, trend_log = _compute_trend_factors_by_team(
            pos, cutoff_date,
            cfg['TREND_LOOKBACK_WEEKS'], cfg['TREND_WINDOW_WEEKS'],
            cfg['TREND_CLAMP_LOW'], cfg['TREND_CLAMP_HIGH'],
        )
        for tid, info in sorted(trend_log.items()):
            print(f"    team {tid}: factor={info['factor']:.3f}  yoy_avg={info['avg_yoy']*100:+.1f}%  n={info['n_obs']}")

    print("  main loop...")
    out_rows = []

    for (team_id, product_id), series in series_map.items():
        if not any(v > 0 for v in series):
            continue

        categ_id = categ_by_pair.get((team_id, product_id), 0)
        n_years = n_years_sku.get(product_id, 0)

        long_series = series_long.get((team_id, product_id), [])
        active_w_short = sum(1 for v in series if v > 0)

        # ABCXYZ + series_type + lifecycle: GLOBAL desde x_calculo_abc_xyz (paridad
        # con motor productivo que persiste estos campos del global como input
        # al router cuando no hay señal local suficiente).
        rctx = router_ctx.get(product_id, {})
        abc_global = rctx.get('abc', '')
        abcxyz_global = rctx.get('abcxyz', '')
        # series_type_active (12 sem) es preferido en motor productivo v3.32
        # Pero el archivo trae el series_type principal en rctx['series_type']
        # que load_abcxyz mapeo de series_type_active primero, series_type fallback
        series_type_eff = rctx.get('series_type', '')
        lifecycle_eff = rctx.get('lifecycle', '')

        # Para fines de auditoría + fallback si no hay rctx, calcular local
        adi, cv2, active_w_long = _compute_adi_cv2(long_series)
        xyz_local = _xyz_from_serie(
            long_series, cfg['XYZ_LOCAL_T1'], cfg['XYZ_LOCAL_T2']
        ) if active_w_long >= cfg['XYZ_LOCAL_MIN_WEEKS'] else ''
        series_type_local = _classify_series_type_local(
            adi, cv2, active_w_long, cfg['MIN_ACTIVE_WEEKS_LIFECYCLE'],
            cfg['ADI_THRESHOLD_LOCAL'], cfg['CV2_THRESHOLD_LOCAL'],
        )
        q_data = _compute_quarterly_aggs(long_series, weeks_long)
        u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7 = q_data[:8]
        p_q8 = q_data[8]
        nz_recent_8w = q_data[9]
        lifecycle_local = _infer_lifecycle_local(
            u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7, p_q8, xyz_local,
            nz_recent_8w=nz_recent_8w,
        )

        # Fallback: si no hay global, usar local
        if not series_type_eff:
            series_type_eff = series_type_local
        if not lifecycle_eff:
            lifecycle_eff = lifecycle_local
        abcxyz_eff = abcxyz_global or (abc_global + xyz_local) if abc_global else ''

        # Regimen efectivo (con valores efectivos, no locales)
        regimen_eff = _assign_regimen_local(abcxyz_eff, series_type_eff, lifecycle_eff)

        # Replicar motor productivo: construir base_vals (SI-deflated) y raw_vals
        # sobre la VENTANA DEMAND_WINDOW_WEEKS=26 (no la larga).
        # base_vals[i] = q_raw[i] / si_w[i]  donde si_w viene del SI dict
        # multi-nivel (local_categ > categ_global > global) en la iso_week de wk.
        raw_vals = []
        base_vals = []
        lc_key = (team_id, categ_id) if categ_id else None
        for wk_i, wk in enumerate(weeks):
            q_raw = series[wk_i]
            if q_raw < 0.0:
                q_raw = 0.0
            iso_w = _iso_week_52(wk)
            # SI multi-nivel
            si_main_w = None
            if lc_key:
                si_main_w = si_local_categ.get(lc_key, {}).get(iso_w)
            if si_main_w is None and categ_id:
                si_main_w = si_categ_global.get(categ_id, {}).get(iso_w)
            if si_main_w is None:
                si_main_w = si_global.get(iso_w, 1.0)
            # SKU adjust
            si_sku_w = si_sku_raw.get(product_id, {}).get(iso_w)
            si_c_w = si_categ_global.get(categ_id, {}).get(iso_w, 1.0) if categ_id else 1.0
            if si_sku_w is not None and n_years >= 1 and si_c_w > 0.001:
                alpha = (cfg['SI_SKU_ADJ_ALPHA_HIGH']
                          if n_years >= cfg['SI_MIN_YEARS_FOR_SKU']
                          else cfg['SI_SKU_ADJ_ALPHA_LOW'])
                si_w = _clamp(
                    si_main_w * (1.0 + alpha * (float(si_sku_w) / si_c_w - 1.0)),
                    cfg['SI_FLOOR'], cfg['SI_CEIL']
                )
            else:
                si_w = _clamp(si_main_w, cfg['SI_FLOOR'], cfg['SI_CEIL'])

            q_base = q_raw / si_w if cfg['SI_ENABLED'] and si_w > 0.0 else q_raw
            raw_vals.append(q_raw)
            base_vals.append(q_base)

        # Bake-off sobre la ventana corta (26 sem, sin sn_52)
        mu_base, sigma_base, method, collapse = _select_best_model(
            base_vals, raw_vals,
            cfg['SERVICE_BASE_SHORT_WEEKS'], cfg['SERVICE_BASE_LONG_WEEKS'],
            cfg['SERVICE_RATIO_UP'], cfg['SERVICE_RATIO_HOLD'],
            cfg['SERVICE_RATIO_COLLAPSE'],
            cfg['SERVICE_DOWN_W_SHORT'], cfg['SERVICE_DOWN_W_LONG'],
            heur_bias=cfg.get('HEUR_BIAS', 0.90),
            sba_alpha=cfg.get('SBA_ALPHA', 0.15),
            croston_alpha=cfg.get('CROSTON_ALPHA', 0.10),
        )

        # SI final
        if cfg['SI_ENABLED'] and mu_base > 0:
            si_final, si_level, si_main, si_sku = _get_si_final(
                target_iso_week, team_id, product_id, categ_id,
                si_local_categ, si_categ_global, si_sku_raw, si_global,
                n_years, cfg['SI_MIN_YEARS_FOR_SKU'],
                cfg['SI_SKU_ADJ_ALPHA_LOW'], cfg['SI_SKU_ADJ_ALPHA_HIGH'],
                cfg['SI_FLOOR'], cfg['SI_CEIL'],
            )
        else:
            si_final, si_level, si_main, si_sku = 1.0, 'disabled', 1.0, 1.0

        # SI ya aplicado: mu_week_post_si = mu_base * si_final
        mu_week_post_si = mu_base * si_final
        sigma_week_post_si = sigma_base * si_final

        # Bloque C: router (usa mu post-SI para decisiones de threshold)
        forecast_zone, forecast_scope, forecast_model_code, scope_reason = _route_forecast_scope(
            abcxyz_eff, series_type_eff, lifecycle_eff, mu_week_post_si
        )

        # Si router dice no_forecast, mu = 0 antes de aplicar correcciones
        if forecast_model_code == 'min_stock_or_manual':
            mu_week_pre_corr = 0.0
            sigma_week_pre_corr = 0.0
        else:
            mu_week_pre_corr = mu_week_post_si
            sigma_week_pre_corr = sigma_week_post_si

        # Bloque G: fair share canonico (rescate cuando motor falla)
        fair_share_applied = False
        fair_share_reason = ''
        if (
            cfg['FAIR_SHARE_ENABLED']
            and mu_week_pre_corr == 0
            and lifecycle_eff in ('mature', 'ramp_up')
        ):
            fs_res = _compute_fair_share(
                product_id=product_id,
                team_id=team_id,
                categ_id_local=categ_id,
                router_ctx=router_ctx,
                fs_ctx=fair_share_ctx,
                bias=cfg['FAIR_SHARE_BIAS'],
                sigma_cv=cfg['FAIR_SHARE_SIGMA_CV'],
                min_units=cfg['FAIR_SHARE_MIN_UNITS'],
                min_salas=cfg['FAIR_SHARE_MIN_SALAS_ACTIVAS'],
                min_historia=cfg['FAIR_SHARE_MIN_HISTORIA_CATEG'],
                bottom_pct=cfg['FAIR_SHARE_BOTTOM_PCT'],
                active_weeks_target=active_w_short,
                conf_n_map=cfg['FAIR_SHARE_CONF_N_MAP'],
                growth_cap_map=cfg['FAIR_SHARE_GROWTH_CAP'],
                tried_penalty=cfg['FAIR_SHARE_TRIED_PENALTY'],
                allowed_abc=cfg['FAIR_SHARE_ALLOWED_ABC'],
                b_max_gap=cfg['FAIR_SHARE_B_MAX_GAP'],
                n_salas_total=cfg['FAIR_SHARE_N_SALAS_TOTAL'],
            )
            if fs_res is not None:
                mu_week_pre_corr = fs_res['mu_week']
                sigma_week_pre_corr = fs_res['sigma_week']
                forecast_zone = 'Z1'
                forecast_scope = fs_res.get('scope', 'core_canon_v42')
                forecast_model_code = 'fair_share_canon'
                fair_share_applied = True
                fair_share_reason = fs_res['reason']

        # Bloque E: detector precio (correccion_factor) - aplicado post-router, pre-trend
        # Factor es por product_id (global, no por team)
        corr = correccion_ctx.get(product_id)
        correccion_factor = 1.0
        correccion_tipo = ''
        if corr and mu_week_pre_corr > 0:
            correccion_factor = _safe_float(corr.get('factor'), 1.0)
            correccion_tipo = corr.get('tipo', '')
        mu_week_pre_trend = mu_week_pre_corr * correccion_factor
        sigma_week_pre_trend = sigma_week_pre_corr * correccion_factor

        # Bloque D: trend correction (factor por team, aplicado post-precio)
        trend_factor = trend_factor_by_team.get(team_id, 1.0)
        if trend_factor != 1.0 and mu_week_pre_trend > 0:
            mu_week_final = mu_week_pre_trend * trend_factor
            sigma_week_final = sigma_week_pre_trend * trend_factor
        else:
            mu_week_final = mu_week_pre_trend
            sigma_week_final = sigma_week_pre_trend

        out_rows.append({
            'team_id': team_id,
            'product_id': product_id,
            'categ_id': categ_id,
            'target_week_start': target_week,
            'target_iso_week': target_iso_week,
            'abc_global': abc_global,
            'abcxyz_global': abcxyz_global,
            'abcxyz_eff': abcxyz_eff,
            'series_type_eff': series_type_eff,
            'lifecycle_eff': lifecycle_eff,
            'regimen_eff': regimen_eff,
            'xyz_local': xyz_local,
            'series_type_local': series_type_local,
            'lifecycle_local': lifecycle_local,
            'adi_local': adi,
            'cv2_local': cv2,
            'active_weeks_local': active_w_long,
            'nz_recent_8w': nz_recent_8w,
            'forecast_zone': forecast_zone,
            'forecast_scope': forecast_scope,
            'forecast_model_code': forecast_model_code,
            'scope_reason': scope_reason,
            'fair_share_applied': fair_share_applied,
            'fair_share_reason': fair_share_reason,
            'mu_base': mu_base,
            'sigma_base': sigma_base,
            'mu_week_post_si': mu_week_post_si,
            'mu_week_pre_corr': mu_week_pre_corr,
            'correccion_factor': correccion_factor,
            'correccion_tipo': correccion_tipo,
            'mu_week_pre_trend': mu_week_pre_trend,
            'trend_factor': trend_factor,
            'mu_week': mu_week_final,
            'sigma_week': sigma_week_final,
            'si_factor': si_final,
            'si_level': si_level,
            'si_main_factor': si_main,
            'si_sku_factor': si_sku,
            'demand_method': method,
            'collapse_detected': collapse,
            'n_history_weeks': active_w_short,
            'n_years_sku': n_years,
        })

    df = pd.DataFrame(out_rows)
    print(f"  forecasts generados: {len(df):,}")
    return df


if __name__ == "__main__":
    import sys
    cutoff = date(2026, 5, 17)  # Default: domingo W20 2026
    if len(sys.argv) > 1:
        cutoff = date.fromisoformat(sys.argv[1])

    df = run(cutoff_date=cutoff, cache_dir=Path(__file__).parent / "cache")

    print("\nSample (5 rows):")
    print(df.head().to_string())

    out = Path(__file__).parent / "resultados" / f"forecast_local_{cutoff}.parquet"
    out.parent.mkdir(exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\nSaved: {out}")
