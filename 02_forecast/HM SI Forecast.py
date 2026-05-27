# HM SI Forecast - Motor de demanda semanal con estacionalidad por nivel
# ============================================================
#
# Version activa: v3.43 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - Calcular mu_week y sigma_week por (sala, SKU) usando heuristica de
#     SMA blend (short/long con ratio_up/hold/collapse), deflactando por
#     estacionalidad SI multi-nivel (local_categ -> categ_global -> global)
#     y aplicando ajuste SKU si hay >=1 ano de historia.
#   - Routing por zona (Z1-Z4) y scope (core_hm_si, no_forecast, secondary,
#     core_canon_v42) segun ABCXYZ local, series_type, lifecycle, mu_week.
#   - Fair share canon SAP IBP / Blue Yonder para rescate de SKUs A/B sin
#     historia local (categoria share x growth_cap x conf_n).
#
# Reglas vivas (resumen operativo, no cronologia):
#   - ABC global (criterio economico). XYZ, series_type, lifecycle, regimen
#     LOCALES por team con fallback al global cuando hay senal insuficiente
#     (< MIN_ACTIVE_WEEKS = 4 sem).
#   - SI multi-nivel: local_categ (>= SI_MIN_OBS_LOCAL_CATEG=12 sem),
#     categ_global, global. Ajuste SKU con alpha 0.15 (low) / 0.30 (high)
#     cuando n_years_sku >= SI_MIN_YEARS_FOR_SKU (3). SI_FLOOR=0.05, CEIL=5.0.
#   - Caps anti-spike: BZ * 0.8 max, AZ/CZ/BY-Z3/Z4/AY-smooth-Z2/CY-Z4 * 1.2 max.
#   - Zero-gate Z4 si nz_recent==0 en ultimas 8 sem, excluyendo REG-8 seasonal
#     y ramp_up.
#   - P1: declining/dead -> forecast=0.
#   - Auto-model selection (v3.39): heuristico, SBA(0.15), Croston(0.10),
#     seasonal_naive_52 compiten sobre holdout 4 sem. Heur-bias 0.90 (gana
#     el heuristico salvo que otro sea >=10% mejor en MAE).
#   - Fair share canon (v3.42): conf_n por N salas activas (1->0.30 ... 5+->1.00),
#     growth_cap por XYZ (X=3.0, Y=2.0, Z=1.5), tried_penalty 0.15 sin floor
#     cuando active_weeks_target>0. Trigger: ABC=A siempre, B con gap<=2.
#   - Correccion de precio externa via x_price_coreccion (detector v5.8 en
#     02_forecast/OH Price Correccion.py). Se aplica DESPUES de caps P1/P3/P6.
#     Validacion empirica si factor<0.90 y >=3 sem post-cambio.
#   - Redondeo mu_week final medio-arriba (>=0.5 sube). sigma_week continuo.
#   - Trend correction (v3.43): factor multiplicativo por team basado en
#     weekly YoY asimetrico de las ultimas TREND_WINDOW_WEEKS=8 sem.
#     Clamp [0.70, 1.00] - solo recorta cuando hay deterioro, NO amplifica
#     teams en alza. Se aplica DESPUES de correccion_factor, ANTES de
#     redondeo. mu_week_pre_bias persiste el valor pre-trend.
#
# Detalles, fixes historicos y metricas de snapshots: ver CHANGELOG.md.
# ------------------------------------------------------------

VERSION_ID = "FWD_v3_43_TREND_CORRECTION"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009438


# ----------------------
# Parametros base
# ----------------------
FWD_MODEL_DEFAULT = 'x_hm_si_forecast'

HARD_RESET_DEFAULT = True
FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

DEMAND_HISTORY_MONTHS_DEFAULT = 24
DEMAND_WINDOW_WEEKS_DEFAULT   = 26
BATCH_SIZE = 500

# Normalizacion de demanda (proyecto 2026-05-25-normalizacion-demanda).
# Overlay x_demanda_normalizada(team, sku, week_start) = {qty_obs, qty_norm}
# corrige censura de quiebre. Default TRUE durante el backtest comparativo
# (no productivo). Una vez validado, queda como default permanente. Para
# desactivar temporalmente, pasar context use_demand_normalization=False.
USE_DEMAND_NORMALIZATION_DEFAULT = True
DEMAND_NORMALIZATION_MODEL       = 'x_demanda_normalizada'


# ----------------------
# Parametros HM-SI
# ----------------------
SI_ENABLED_DEFAULT              = True
SI_HISTORY_MONTHS_DEFAULT      = 36
SI_TARGET_WEEKS_DEFAULT        = 1
SI_SKU_ADJ_ALPHA_LOW_DEFAULT   = 0.15
SI_SKU_ADJ_ALPHA_HIGH_DEFAULT  = 0.30
SI_MIN_YEARS_FOR_SKU_DEFAULT   = 3
SI_MIN_OBS_LOCAL_CATEG_DEFAULT = 12
SI_FLOOR_DEFAULT               = 0.05
SI_CEIL_DEFAULT                = 5.00


# ----------------------
# Parametros demanda base
# ----------------------
SERVICE_BASE_SHORT_WEEKS_DEFAULT = 6
SERVICE_BASE_LONG_WEEKS_DEFAULT  = 16
SERVICE_RATIO_UP_DEFAULT         = 1.15
SERVICE_RATIO_HOLD_DEFAULT       = 0.90
SERVICE_RATIO_COLLAPSE_DEFAULT   = 0.30
SERVICE_DOWN_W_SHORT_DEFAULT     = 0.70
SERVICE_DOWN_W_LONG_DEFAULT      = 0.30

# v3.37: validacion empirica del factor de correccion
SERVICE_CORR_VALIDATION_MIN_WEEKS_DEFAULT  = 3
SERVICE_CORR_VALIDATION_BASELINE_DEFAULT   = 8
SERVICE_CORR_VALIDATION_THRESHOLD_DEFAULT  = 0.15

# v3.43: trend correction multiplicativo por team (weekly YoY asimetrico)
# Captura el deterioro estructural YoY de cada local sin doble-contar el
# nivel ya estimado por SMA en el motor. Asimetrico (cap_high=1.00) por
# diseno: NO amplifica teams en alza (que ya estan over-forecast por otras
# razones - SI suave en bebidas/verano). Solo recorta cuando hay deterioro.
APPLY_TREND_CORRECTION_DEFAULT = True
TREND_LOOKBACK_WEEKS_DEFAULT   = 60      # ventana historica para pull POS (>= 52 + window)
TREND_WINDOW_WEEKS_DEFAULT     = 8       # ventana reciente para promediar YoY
TREND_CLAMP_LOW_DEFAULT        = 0.70
TREND_CLAMP_HIGH_DEFAULT       = 1.00    # asimetrico: cap a 1.0 (no amplifica)


# ----------------------
# Fair share (v3.40)
# ----------------------
# Rescate de pares (sala, SKU clase A) sin historia local via demanda global
# ponderada por share de categoria. Ver header v3.40 para fundamento.
FAIR_SHARE_ENABLED_DEFAULT          = True
# v3.42: min_salas baja de 3 a 1 (la antigua regla se reemplaza por conf_n).
FAIR_SHARE_MIN_SALAS_ACTIVAS_DEFAULT = 1
FAIR_SHARE_MIN_HISTORIA_CATEG_DEFAULT = 12   # semanas en categoria => mu_categ_target real
FAIR_SHARE_BIAS_DEFAULT             = 1.00   # neutro
FAIR_SHARE_MIN_UNITS_DEFAULT        = 1.0    # v3.41: bajo de 2.0 -> 1.0 (factor ya escala)
FAIR_SHARE_SIGMA_CV_DEFAULT         = 0.5    # sigma_fs = mu_fs * CV (sin historia local)
FAIR_SHARE_BOTTOM_PCT_DEFAULT       = 0.5    # v3.41: 50% de salas con menor mu_categoria
                                              # para estimar sala objetivo nueva
# v3.42 canon SAP IBP: confianza estadistica del factor_normalizado segun N
# salas activas. Con n_active=1, el factor es practicamente ruido (1 sola
# observacion). Con >=5 salas, el factor es robusto.
FAIR_SHARE_CONF_N_MAP_DEFAULT       = {0: 0.00, 1: 0.30, 2: 0.50, 3: 0.75, 4: 0.75}
# n_active >= 5 -> 1.00 (no esta en el mapa).
# v3.42 canon Blue Yonder: techo de crecimiento por XYZ. Limita mu_fs total
# a mu_global x growth_cap para que no se infle la demanda en SKUs nicho.
FAIR_SHARE_GROWTH_CAP_DEFAULT       = {'X': 3.0, 'Y': 2.0, 'Z': 1.5}
# v3.42 canon Blue Yonder: penalty si la sala target ya probo y fallo
# (active_weeks_local_target > 0 con mu_local=0). Escala mu_fs por este factor.
FAIR_SHARE_TRIED_PENALTY_DEFAULT    = 0.15
# v3.42 canon: trigger expandido. Si abc_global IN allowed_abc, aplicar
# (con regla adicional para B: gap_count <= TERMINAR_COBERTURA_MAX_GAP).
FAIR_SHARE_ALLOWED_ABC_DEFAULT      = ('A', 'B')
FAIR_SHARE_B_MAX_GAP_DEFAULT        = 2  # solo TERMINAR COBERTURA para clase B


# ----------------------
# Parametros XYZ local por team
# ----------------------
# Clasificacion XYZ derivada de la serie local del team usando el MISMO metodo
# del XYZ global (archivo 1): una sola pasada con CV simple sobre la ventana
# completa (base_vals). Si active_weeks_local < MIN, xyz_local queda vacio y
# el consumidor cae al XYZ global (source='global'). Umbrales identicos al
# global para coherencia.
XYZ_LOCAL_MIN_WEEKS_DEFAULT   = 4     # alineado con MIN_ACTIVE_WEEKS global
XYZ_LOCAL_T1_DEFAULT          = 0.45  # umbral X/Y del global
XYZ_LOCAL_T2_DEFAULT          = 0.90  # umbral Y/Z del global


# ----------------------
# Ajuste por precio
# ----------------------
# v3.35: ELIMINADO el sistema legacy de ajuste de precio (PRICE_FACTOR_TABLE_L2,
# _lookup_calibrated_factor, _apply_decay, _load_price_context). El ajuste se
# delega 100% al detector externo (Detector v5.8 en `7- OH Price Correccion.py`)
# via el modelo x_price_coreccion. Aquí solo se consume el factor pre-calculado
# via _load_correccion_context y se aplica a mu_week despues de los caps.


# ----------------------
# Helpers
# ----------------------
def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
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


def _si_level_code(level):
    txt = _safe_text(level, 80)
    base = txt.replace('+sku_adj', '').strip()
    code = 0.0
    if base == 'local_categ':
        code = 3.0
    elif base == 'categ_global':
        code = 2.0
    elif base == 'global':
        code = 1.0
    else:
        code = 0.0
    if '+sku_adj' in txt:
        code += 0.1
    return code


def _selection_keys(field):
    keys = []
    try:
        sel = field.selection or []
        if callable(sel):
            return keys
        for item in sel:
            try:
                keys.append(item[0])
            except Exception:
                pass
    except Exception:
        pass
    return keys


def _put_field(vals, fields_map, fname, value, maxlen=255):
    f = fields_map.get(fname)
    if not f:
        return
    ftype = ''
    try:
        ftype = f.type or ''
    except Exception:
        ftype = ''

    if ftype in ('float', 'monetary'):
        vals[fname] = _safe_float(value, 0.0)
    elif ftype == 'integer':
        vals[fname] = _safe_int(value, 0)
    elif ftype == 'boolean':
        vals[fname] = bool(value)
    elif ftype == 'many2one':
        vals[fname] = value or False
    elif ftype in ('char', 'text', 'html'):
        vals[fname] = _safe_text(value, maxlen)
    elif ftype == 'selection':
        txt = _safe_text(value, maxlen)
        keys = _selection_keys(f)
        if (not keys) or (txt in keys):
            vals[fname] = txt
    elif ftype in ('date', 'datetime'):
        vals[fname] = value
    else:
        vals[fname] = value


def _put_si_level(vals, fields_map, level_txt):
    f = fields_map.get('x_studio_si_level')
    if f:
        ftype = ''
        try:
            ftype = f.type or ''
        except Exception:
            ftype = ''
        if ftype in ('float', 'monetary', 'integer'):
            _put_field(vals, fields_map, 'x_studio_si_level', _si_level_code(level_txt))
        else:
            _put_field(vals, fields_map, 'x_studio_si_level', level_txt, 40)

    for alt in ['x_studio_si_level_txt', 'x_studio_si_level_text', 'x_studio_si_level_label', 'x_studio_si_level_name']:
        if alt in fields_map:
            _put_field(vals, fields_map, alt, level_txt, 80)
            break


def _to_int_list(val):
    out = []
    if not val:
        return out
    try:
        for x in val:
            try:
                out.append(int(x))
            except Exception:
                pass
        return out
    except Exception:
        try:
            return [int(val)]
        except Exception:
            return []


def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def _week_range(dfrom, dto):
    start = _week_start(dfrom)
    end = _week_start(dto)
    weeks = []
    cur = start
    while cur <= end:
        weeks.append(cur)
        cur += datetime.timedelta(weeks=1)
    return weeks or [start]


def _iso_week_52(d):
    w = d.isocalendar()[1]
    return 52 if w > 52 else w


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


def _xyz_from_serie(vals, t1, t2):
    """Clasifica X/Y/Z sobre una ventana de la serie local.

    CV simple = sigma/mu sobre todos los periodos de la ventana.
    Vacio ('') si la ventana no tiene senal (mu<=0 o lista vacia).
    """
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


# v3.34: helpers portados del archivo 1 para calculo de series_type, lifecycle
# y regimen LOCAL por team. La logica es identica al script 1 — solo cambia
# que la serie de entrada es la local del team en vez de la global agregada.

ADI_THRESHOLD_LOCAL = 1.32   # Syntetos-Boylan: ADI < 1.32 -> smooth/erratic
CV2_THRESHOLD_LOCAL = 0.49   # Syntetos-Boylan: CV2 < 0.49 -> smooth/intermittent


def _quarter_abs_local(d):
    """Devuelve indice absoluto del trimestre (year*4 + q)."""
    return d.year * 4 + ((d.month - 1) // 3) + 1


def _classify_series_type_local(adi, cv2, active_weeks, min_active_weeks,
                                 adi_threshold=ADI_THRESHOLD_LOCAL,
                                 cv2_threshold=CV2_THRESHOLD_LOCAL):
    """Matriz Syntetos-Boylan sobre datos locales del team.

    Identica a _classify_series_type del archivo 1.
    Retorna: 'smooth' | 'erratic' | 'intermittent' | 'lumpy' | 'no_signal'.
    """
    if (active_weeks or 0) < (min_active_weeks or 0):
        return 'no_signal'
    if not adi or adi <= 0:
        return 'no_signal'
    high_var = (cv2 or 0.0) >= cv2_threshold
    if adi >= adi_threshold:
        return 'lumpy' if high_var else 'intermittent'
    return 'erratic' if high_var else 'smooth'


def _infer_lifecycle_local(u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7, p_q8, xyz):
    """PLC inferido por presencia trimestral local. Identico a archivo 1."""
    u_rest = u_q1 + u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7
    u8 = u_q0 + u_rest
    if u8 <= 0:
        return 'dead'
    if p_q8 <= 2 and u_q1 <= 0:
        return 'intermittent'
    if u_q0 > 0 and u_rest <= 0:
        return 'new'
    if u_q0 <= 0 and (u_q1 + u_q2 + u_q3) > 0:
        return 'declining'
    if xyz == 'Z' and p_q8 <= 5:
        return 'seasonal'
    if u_q0 > 0 and u_q1 <= 0 and (u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7) > 0:
        return 'ramp_up'
    return 'mature'


def _assign_regimen_local(abcxyz, series_type, ciclo_de_vida):
    """Matriz de 9 regimenes sobre (ABC, series_type, lifecycle) locales.

    Identica a _assign_regimen del archivo 1. Retorna 'REG-0' .. 'REG-8'.
    """
    abc_letter = (abcxyz or '')[:1].upper()
    s = (series_type or '').strip().lower()
    c = (ciclo_de_vida or '').strip().lower()

    # 1. Terminal: sin pronostico
    if c in ('dead', 'declining'):
        return 'REG-0'
    if s == 'no_signal' and abc_letter == 'C':
        return 'REG-0'

    # 2. Lifecycles especiales (precedencia sobre series)
    if c == 'seasonal':
        return 'REG-8'
    if c == 'ramp_up':
        return 'REG-1'

    # 3. Smooth segmentado por ABC
    if s == 'smooth':
        if abc_letter == 'A':
            return 'REG-1'
        if abc_letter == 'B':
            return 'REG-2'
        return 'REG-3'

    # 4. Erratic
    if s == 'erratic':
        return 'REG-4'

    # 5. Lumpy segmentado por ABC
    if s == 'lumpy':
        if abc_letter in ('A', 'B'):
            return 'REG-5'
        return 'REG-6'

    # 6. Residual: intermittent / no_signal no-C
    if s in ('intermittent', 'no_signal'):
        return 'REG-7'

    return 'REG-0'


def _calc_si_from_weekly(weekly_by_isoweek):
    # avg_by_week[w] = promedio de ventas de la semana ISO w sobre años con datos
    # (volvio al divisor len(clean) tras v3.23: el divisor /expected_n inflaba SI
    #  en presentes y deflactaba mu_base via q_base = q_adj/si_w, rompiendo Z-class)
    avg_by_week = {}
    for w, totals in (weekly_by_isoweek or {}).items():
        clean = [_safe_float(x, 0.0) for x in (totals or [])]
        if clean:
            avg_by_week[w] = sum(clean) / len(clean)

    if not avg_by_week:
        return {w: 1.0 for w in range(1, 53)}

    # global_avg sobre las semanas con datos (igual que v3.19)
    global_avg = sum(avg_by_week.values()) / len(avg_by_week)
    if global_avg <= 0.0:
        return {w: 1.0 for w in range(1, 53)}

    si_norm = {}
    for w, v in avg_by_week.items():
        si_norm[w] = v / global_avg

    # semanas sin ventas históricas → SI=1.0 (neutro)
    for w in range(1, 53):
        if w not in si_norm:
            si_norm[w] = 1.0

    return si_norm


def _get_si_final(iso_week, team_id, product_id, categ_id,
                  si_local_categ, si_categ_global, si_sku_raw, si_global,
                  n_years_sku, si_min_years,
                  sku_adj_alpha_low, sku_adj_alpha_high,
                  si_floor, si_ceil):
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


def _calc_base_demand(base_vals, raw_vals,
                      short_weeks, long_weeks,
                      ratio_up, ratio_hold, ratio_collapse,
                      down_w_short, down_w_long):
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

    # v3.36: ratio sobre RAW (sin SI deflation) para detectar colapso real.
    # base_vals deflactada por SI puede enmascarar caidas reales cuando coinciden
    # con baja estacionalidad (ej. cerveza en mayo). El ratio raw refleja lo que
    # se ve a ojo en la serie de ventas.
    raw_n = len(raw_vals or [])
    if raw_n >= long_weeks:
        raw_short_avg, _ = _avg_std(raw_vals[-short_weeks:])
        raw_long_avg, _ = _avg_std(raw_vals[-long_weeks:])
        if raw_long_avg > 0.0:
            raw_ratio = raw_short_avg / raw_long_avg
        else:
            raw_ratio = 9.99 if raw_short_avg > 0.0 else 1.0
    else:
        raw_ratio = ratio  # fallback al ratio SI-deflated si no hay raw suficiente

    if ratio >= ratio_up:
        return sma_short, sigma_short, 'sma%s_base_up_r=%s' % (short_weeks, round(ratio, 3)), False

    if ratio >= ratio_hold:
        return sma_long, sigma_long, 'sma%s_base_hold_r=%s' % (long_weeks, round(ratio, 3)), False

    # Bajada confirmada por ratio SI; chequear si raw indica colapso.
    if raw_ratio < ratio_collapse:
        return sma_short, sigma_short, 'sma%s_base_collapse_rawr=%s' % (short_weeks, round(raw_ratio, 3)), True

    mu_blend = (down_w_short * sma_short) + (down_w_long * sma_long)
    sigma_blend = (down_w_short * sigma_short) + (down_w_long * sigma_long)
    return mu_blend, sigma_blend, 'blend_down_base_r=%s' % round(ratio, 3), False


# ---------------------------------------------------------------------
# v3.38: Croston (1972) + SBA (Syntetos-Boylan 2005) para demanda
# intermitente. Portados de analisis backtest/2026-05-12/_forecast_models.py
# con 16 tests validados. Sin dependencias externas.
# ---------------------------------------------------------------------
def _croston(history, alpha=0.1):
    """Croston (1972) - demanda intermitente.

    Si y_t > 0: z = alpha*y + (1-alpha)*z; p = alpha*q + (1-alpha)*p; q=1.
    Si y_t == 0: q += 1.
    Forecast: z / p.
    """
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
    """Syntetos-Boylan Approximation (2005).

    SBA = (1 - alpha/2) * Croston. Corrige el sesgo positivo de Croston.
    Preferible para inventarios donde over-forecast = exceso de stock.
    """
    base = _croston(history, alpha=alpha)
    return (1.0 - alpha / 2.0) * base


def _mae_of_forecast(forecast_val, actual_list):
    """v3.39: MAE de un forecast constante vs lista de observados.

    Function module-level (no closure) para compatibilidad con el sandbox
    de Odoo Server Actions que prohibe LOAD_CLOSURE/STORE_DEREF/MAKE_CELL.
    """
    n = len(actual_list or [])
    if n == 0:
        return float('inf')
    total = 0.0
    for a in actual_list:
        total += abs(_safe_float(a, 0.0) - forecast_val)
    return total / float(n)


def _calc_base_demand_by_regimen(base_vals, raw_vals, regimen,
                                  short_weeks, long_weeks,
                                  ratio_up, ratio_hold, ratio_collapse,
                                  down_w_short, down_w_long):
    """v3.38 (DESCARTADO 2026-05-20): dispatcher por regimen. SBA(alpha=0.05)
    sobre base_vals para REG-7 empeoro WAPE +1.6pp y BIAS -4.5pp. Razon:
    SBA con alpha bajo + bias correction (1-alpha/2) + SI roundtrip da
    forecast mas conservador que SMA dilution para intermitentes con
    periodos cortos.

    Estado actual: el wrapper pasa SIEMPRE al motor heuristico (no-op).
    Las helpers _croston/_sba quedan disponibles para retomar con
    calibracion distinta: alpha mayor (0.15-0.20), input raw_vals, o
    diferente blend.
    """
    # v3.38 DESCARTADO: dispatcher no-op, siempre heuristico.
    return _calc_base_demand(
        base_vals, raw_vals,
        short_weeks, long_weeks,
        ratio_up, ratio_hold, ratio_collapse,
        down_w_short, down_w_long,
    )


def _select_best_model(base_vals, raw_vals,
                       short_weeks, long_weeks,
                       ratio_up, ratio_hold, ratio_collapse,
                       down_w_short, down_w_long,
                       heur_bias=0.90):
    """v3.39: SAP-style auto-model selection per SKU.

    Bake-off entre heuristico, SBA(0.15), Croston(0.10), seasonal_naive_52.
    Holdout de 4 semanas cerradas. Cada candidato entrena en base_vals[:-4]
    y predice un valor constante. MAE sobre el holdout decide el ganador.

    Heuristic-bias (default 0.90): otro modelo necesita MAE <= heur_mae *
    0.90 (10% mejor) para ganar. Si no, gana el heuristico. Protege REG-1
    y SKUs estables donde el motor base ya es competitivo.

    Devuelve (mu_base, sigma_base, demand_method, collapse_detected). El
    demand_method incluye el code del ganador ('heur', 'sba_015',
    'croston_010', 'seasonal_naive_52') para auditoria.

    Fallback al heuristico puro si len(base_vals) < 12 o ningun candidato
    produce forecast valido.
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

    # Heuristico (training en train_b)
    heur_mu, heur_sigma, heur_method, heur_collapse = _calc_base_demand(
        train_b, train_r,
        short_weeks, long_weeks,
        ratio_up, ratio_hold, ratio_collapse,
        down_w_short, down_w_long,
    )

    heur_mae = _mae_of_forecast(heur_mu, actual)

    # Otros candidatos sobre base_vals SI-deflated
    candidates = []  # list of (code, mae, forecast_train_value)
    candidates.append(('heur', heur_mae, heur_mu))

    sba_f = _sba(train_b, alpha=0.15)
    if sba_f > 0:
        candidates.append(('sba_015', _mae_of_forecast(sba_f, actual), sba_f))

    crost_f = _croston(train_b, alpha=0.10)
    if crost_f > 0:
        candidates.append(('croston_010', _mae_of_forecast(crost_f, actual), crost_f))

    # Seasonal naive lag-52 (requiere >=56 sem para que train tenga >=52)
    if n >= 56:
        sn_f = _safe_float(train_b[-52], 0.0)
        if sn_f > 0:
            candidates.append(('seasonal_naive_52', _mae_of_forecast(sn_f, actual), sn_f))

    # Pick best por MAE (sin lambda para evitar sandbox de Odoo Server Action)
    best_idx = 0
    for _i in range(1, len(candidates)):
        if candidates[_i][1] < candidates[best_idx][1]:
            best_idx = _i
    best_code = candidates[best_idx][0]
    best_mae = candidates[best_idx][1]

    # Heuristic-bias: heur gana en empate o si la mejora es < (1 - heur_bias)
    if best_code != 'heur' and best_mae > heur_mae * heur_bias:
        best_code = 'heur'

    # Re-entrenar el ganador con base_vals completo
    if best_code == 'heur':
        # heur conserva collapse_detected y demand_method del calculo full
        return _calc_base_demand(
            base_vals, raw_vals,
            short_weeks, long_weeks,
            ratio_up, ratio_hold, ratio_collapse,
            down_w_short, down_w_long,
        )

    if best_code == 'sba_015':
        mu = _sba(base_vals, alpha=0.15)
    elif best_code == 'croston_010':
        mu = _croston(base_vals, alpha=0.10)
    elif best_code == 'seasonal_naive_52':
        mu = _safe_float(base_vals[-52], 0.0) if n >= 52 else 0.0
    else:
        mu = heur_mu

    if mu <= 0:
        # Fallback al heuristico full si el ganador degenero
        return _calc_base_demand(
            base_vals, raw_vals,
            short_weeks, long_weeks,
            ratio_up, ratio_hold, ratio_collapse,
            down_w_short, down_w_long,
        )

    # sigma del heuristico re-entrenado en full data para mantener calidad
    # del safety stock. Si quisieramos sigma del modelo ganador habria que
    # implementarlo per-model; por ahora usamos el sigma del heuristico.
    _, sigma_full, _, _ = _calc_base_demand(
        base_vals, raw_vals,
        short_weeks, long_weeks,
        ratio_up, ratio_hold, ratio_collapse,
        down_w_short, down_w_long,
    )
    return mu, sigma_full, best_code, False


def _model_exists(model_name):
    try:
        env[model_name]
        return True
    except Exception:
        return False


def _first_m2o_field(model_obj, candidates, comodel_name):
    fields_map = model_obj._fields or {}
    for fname in candidates:
        f = fields_map.get(fname)
        if not f:
            continue
        try:
            if f.type == 'many2one' and f.comodel_name == comodel_name:
                return fname
        except Exception:
            pass
    return False


def _first_field(model_obj, candidates):
    fields_map = model_obj._fields or {}
    for fname in candidates:
        if fname in fields_map:
            return fname
    return False



# ----------------------
# Router (idéntico v3.7/v3.8)
# ----------------------
def _norm_txt(v, maxlen=80):
    return _safe_text(v, maxlen).strip().lower()


def _infer_series_type_from_xyz(series_type, abcxyz):
    """Fallback: deriva series_type de la letra XYZ cuando ABCXYZ no
    persiste el campo (version vieja sin la columna). NO replica la
    matriz Syntetos-Boylan ADI*CV2 de ABCXYZ - eso es trabajo del
    runner ABCXYZ. Solo mapea: X->smooth, Y->erratic, Z->lumpy.
    """
    if series_type:
        return series_type
    if not abcxyz:
        return ''
    letter = str(abcxyz).strip().upper()[-1:]
    if letter == 'X':
        return 'smooth'
    if letter == 'Y':
        return 'erratic'
    if letter == 'Z':
        return 'lumpy'
    return ''


def _load_forecast_router_context(product_ids):
    out = {}
    model_name = 'x_calculo_abc_xyz'
    if not product_ids:
        return out
    if not _model_exists(model_name):
        return out

    Abc = env[model_name].sudo()
    abc_fields = Abc._fields or {}

    product_field = _first_m2o_field(Abc, ['x_studio_product_id', 'x_product_id', 'x_studio_producto'], 'product.product')
    if not product_field:
        return out

    abcxyz_field = _first_field(Abc, ['x_studio_abcxyz', 'x_studio_abc_xyz', 'x_abcxyz'])
    # v3.32: preferir series_type_active (ABCXYZ v19.4) que combina vista
    # corta (12 sem) y larga (52 sem). Fallback a series_type largo si el
    # field nuevo no esta creado en Studio.
    series_field = _first_field(Abc, [
        'x_studio_series_type_active', 'x_studio_series_type', 'x_series_type',
    ])
    lifecycle_field = _first_field(Abc, ['x_studio_ciclo_de_vida', 'x_studio_lifecycle', 'x_ciclo_de_vida'])
    regimen_field = _first_field(Abc, ['x_studio_regimen', 'x_regimen'])
    company_field = _first_field(Abc, ['x_studio_company_id', 'x_company_id'])
    active_field = _first_field(Abc, ['x_active', 'x_studio_active', 'active'])
    # v3.40: mu_week global del ABCXYZ -> demanda_global para fair share
    mu_week_field = _first_field(Abc, ['x_studio_mu_week', 'x_studio_promedio_semanal', 'x_mu_week'])
    categ_field = _first_m2o_field(Abc, ['x_studio_categ_id', 'x_categ_id'], 'product.category')

    read_fields = [product_field]
    for f in [abcxyz_field, series_field, lifecycle_field, regimen_field, mu_week_field, categ_field]:
        if f and f not in read_fields:
            read_fields.append(f)

    pids = []
    for pid in product_ids:
        pidi = _safe_int(pid, 0)
        if pidi:
            pids.append(pidi)
    pids = list(set(pids))
    if not pids:
        return out

    domain = [(product_field, 'in', pids)]
    if company_field:
        domain.append((company_field, '=', company.id))
    if active_field:
        domain.append((active_field, '=', True))

    # Savepoint defensivo: si el search/read falla por columnas faltantes en
    # Studio o por otra razon, hacemos rollback al savepoint para que la
    # transaccion principal del forecast no quede abortada.
    env.cr.execute('SAVEPOINT router_ctx_lookup')
    try:
        rows = Abc.search(domain, order='write_date desc, id desc').read(read_fields)
        env.cr.execute('RELEASE SAVEPOINT router_ctx_lookup')
    except Exception:
        env.cr.execute('ROLLBACK TO SAVEPOINT router_ctx_lookup')
        return out

    for r in rows:
        pv = r.get(product_field)
        if isinstance(pv, (list, tuple)):
            pid = _safe_int(pv[0], 0)
        else:
            pid = _safe_int(pv, 0)
        if not pid or pid in out:
            continue
        # v3.40: mu_week y categ_id global del ABCXYZ
        mu_g = _safe_float(r.get(mu_week_field), 0.0) if mu_week_field else 0.0
        cv = r.get(categ_field) if categ_field else False
        if isinstance(cv, (list, tuple)):
            cg = _safe_int(cv[0], 0)
        else:
            cg = _safe_int(cv, 0)
        out[pid] = {
            'abcxyz': _safe_text(r.get(abcxyz_field), 20).upper() if abcxyz_field else '',
            'series_type': _norm_txt(r.get(series_field), 40) if series_field else '',
            'lifecycle': _norm_txt(r.get(lifecycle_field), 40) if lifecycle_field else '',
            'regimen': _safe_text(r.get(regimen_field), 20).upper() if regimen_field else '',
            'mu_week_global': mu_g,
            'categ_global_id': cg or 0,
        }

    return out


def _load_correccion_context(product_ids, target_date):
    """v3.29: Lee correcciones precalculadas por el detector x_price_coreccion
    (OJO con el typo: una 'r').  Devuelve dict pid -> {factor, tipo, razon}.

    Semantica v5.6 del detector: target_week_start = period_start del evento
    (puede ser pasada).  El motor toma la correccion mas RECIENTE por SKU
    cuya target_week_start <= target_date.

    Si el modelo no existe (caso initial deploy), retorna {} silenciosamente.
    """
    out = {}
    model_name = 'x_price_coreccion'
    if not product_ids or not target_date:
        return out
    if not _model_exists(model_name):
        return out

    Corr = env[model_name].sudo()
    cf = Corr._fields or {}
    pf = _first_m2o_field(Corr, ['x_studio_product_id'], 'product.product')
    tf = _first_field(Corr, ['x_studio_target_week_start', 'x_studio_target_week'])
    ff = _first_field(Corr, ['x_studio_factor_corr'])
    tipof = _first_field(Corr, ['x_studio_tipo_alerta'])
    rzf = _first_field(Corr, ['x_studio_razon'])
    activef = _first_field(Corr, ['x_studio_active', 'active'])
    wsf = _first_field(Corr, ['x_studio_weeks_since_change'])

    if not (pf and tf and ff):
        return out

    pids = list(set(_safe_int(pid, 0) for pid in product_ids if _safe_int(pid, 0)))
    if not pids:
        return out

    # v5.6: target_week_start es la fecha del evento (period_start), no la
    # proxima semana. Tomar correcciones cuya fecha sea <= target_date.
    domain = [(tf, '<=', target_date), (pf, 'in', pids)]
    if activef:
        domain.append((activef, '=', True))

    rfields = [pf, tf, ff]
    if tipof: rfields.append(tipof)
    if rzf: rfields.append(rzf)
    if wsf: rfields.append(wsf)

    # Savepoint defensivo: si la query falla (modelo recien creado sin tabla,
    # campos faltantes, etc.), hacemos rollback al savepoint para que la
    # transaccion principal del forecast no quede abortada.
    env.cr.execute('SAVEPOINT correccion_ctx_lookup')
    try:
        # Order por fecha desc -> primer match por SKU es el mas reciente.
        rows = Corr.search(domain, order='%s desc' % tf).read(rfields)
        env.cr.execute('RELEASE SAVEPOINT correccion_ctx_lookup')
    except Exception:
        env.cr.execute('ROLLBACK TO SAVEPOINT correccion_ctx_lookup')
        return out

    for r in rows:
        pv = r.get(pf)
        pid = pv[0] if isinstance(pv, (list, tuple)) else _safe_int(pv, 0)
        if not pid or pid in out:
            continue
        out[pid] = {
            'factor': _safe_float(r.get(ff), 1.0),
            'tipo': _safe_text(r.get(tipof), 60) if tipof else '',
            'razon': _safe_text(r.get(rzf), 240) if rzf else '',
            'weeks_since': _safe_int(r.get(wsf), 0) if wsf else 0,
            'target_week_start': r.get(tf) if tf else None,
        }
    return out


def _compute_fair_share(product_id, team_id, categ_id_local,
                        router_ctx, fs_ctx,
                        bias, sigma_cv, min_units,
                        min_salas, min_historia, bottom_pct,
                        active_weeks_target=0,
                        conf_n_map=None, growth_cap_map=None,
                        tried_penalty=0.15,
                        allowed_abc=('A', 'B'), b_max_gap=2,
                        n_salas_total=12):
    """v3.42: fair share canon SAP IBP / Blue Yonder.

    Devuelve dict con keys: mu_week, sigma_week, method, reason, scope.
    Devuelve None si no procede.

    Cambios sobre v3.41:
      - Trigger interno: abc='A' siempre, abc='B' solo si gap_count <= b_max_gap.
      - conf_n por N salas activas (canon SAP IBP): factor con N=1 vale 0.30.
      - growth_cap por XYZ (canon Blue Yonder): mu_fs por par <=
        mu_global * growth_cap(xyz) / max(1, gap_count).
      - tried_penalty: si active_weeks_target>0 (sala probo y mu=0) -> mu_fs * 0.15.
    """
    rctx = router_ctx.get(product_id) if router_ctx else None
    if not rctx:
        return None

    # ABC / XYZ globales para gating y growth_cap.
    abcxyz_global = _safe_text(rctx.get('abcxyz', ''), 20).upper()
    abc_global = abcxyz_global[:1] if abcxyz_global else ''
    xyz_global = abcxyz_global[1:2] if len(abcxyz_global) >= 2 else ''
    if abc_global not in allowed_abc:
        return None  # canon: solo A y B entran al fair share

    mu_global = _safe_float(rctx.get('mu_week_global', 0.0), 0.0)

    # Categoria efectiva: la local si existe, sino la global del ABCXYZ.
    categ_efectiva = _safe_int(categ_id_local, 0) or _safe_int(rctx.get('categ_global_id'), 0)
    if not categ_efectiva:
        return None

    sku_qty_per_sala = fs_ctx.get('sku_qty_per_sala', {})
    categ_qty_per_sala = fs_ctx.get('categ_qty_per_sala', {})
    n_weeks_window = _safe_float(fs_ctx.get('n_weeks_window', 26.0), 26.0) or 26.0

    # 1) Shares normalizados por sala activa
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

    # v3.42: gap_count = salas sin actividad (proxy gap_total)
    gap_count = max(1, int(n_salas_total) - n_active)

    # v3.42: clase B solo TERMINAR COBERTURA (gap pequeno)
    if abc_global == 'B' and gap_count > b_max_gap:
        return None

    # v3.42: conf_n por N salas activas
    if conf_n_map is None:
        conf_n_map = {0: 0.0, 1: 0.30, 2: 0.50, 3: 0.75, 4: 0.75}
    conf_n = float(conf_n_map.get(n_active, 1.00))

    # 2) mu_categ_target: real si hay historia, bottom-N% si es sala nueva.
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

    # 3) mu_raw con conf_n
    factor_efectivo = factor_normalizado * conf_n
    if factor_efectivo <= 0.0:
        return None
    mu_raw = factor_efectivo * mu_categ_target * float(bias)
    if mu_raw <= 0.0:
        return None

    # 4) Growth cap canon: mu_global * growth_cap(xyz) repartido entre salas faltantes
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

    # 5) Tried penalty si la sala target ya probo y fallo (active_weeks>0, mu=0)
    tried_applied = False
    if active_weeks_target > 0:
        mu_capped = mu_capped * float(tried_penalty)
        tried_applied = True

    # 6) Floor: SOLO si NO se aplico tried_penalty.
    # Canon: si la sala ya probo y mu=0, no insistir (insight empirico OH 2026-05-23:
    # 97% de flacos = "probo y fallo"). El threshold de stock (~0.23 u/sem) auto-filtra
    # los pares castigados que no pasan, manteniendo solo los que tenian mu_raw
    # naturalmente alto (senal real de demanda).
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
    abc = _safe_text(abcxyz, 20).strip().upper()
    st = _norm_txt(series_type, 40)
    lc = _norm_txt(lifecycle, 40)
    mu = _safe_float(mu_week, 0.0)

    # v3.13: AX smooth con threshold reducido (mu>=1) se evalua ANTES del floor global
    # para capturar productos de alta velocidad con demanda baja pero predecible.
    if (st == 'smooth') and (abc == 'AX') and (lc in ('mature', 'ramp_up')) and (mu >= 1.0):
        return 'Z1', 'core_hm_si', 'hm_si_core', 'A_smooth_core_ax'

    # v3.28: Rescatar AZ del catch-all Z4. ABC=A con XYZ=Z son alto margen
    # con demanda esporadica (whisky/vino premium probable). En el motor
    # actual caen en Z4 por mu_week<2 -> forecast=0 mayoritariamente.
    # Backtest 2026-05-04 mostro 40 SKUs AZ con BIAS +48% sub-forecast.
    # Decision: motor activo (Z1) para AZ no terminales. P6 cap por max_obs
    # × 1.2 sigue activo como red de seguridad contra over-forecast.
    if (abc == 'AZ') and (lc not in ('declining', 'dead')):
        return 'Z1', 'core_hm_si', 'hm_si_core_az', 'A_high_margin_sporadic'

    # v3.30: Rescatar AX/AY no terminales con mu_week < 2.0. Backtest 2026-05-12
    # mostro 256 filas AX/AY (511 unid reales) cayendo en Z4 -> forecast=0.
    # Son SKUs A (alto valor/margen) con baja velocidad pero demanda viva.
    # P6 cap por max_obs * 1.2 sigue activo como red de seguridad.
    if (abc in ('AX', 'AY')) and (lc not in ('declining', 'dead')):
        return 'Z1', 'core_hm_si', 'hm_si_core_a_low_mu', 'A_low_velocity_rescue'

    if (st == 'no_signal') or (abc in ('CX', 'CY', 'CZ')) or (lc in ('declining', 'dead')) or (mu < 2.0):
        return 'Z4', 'no_forecast', 'min_stock_or_manual', 'D_no_signal_C_or_low_mu'

    if (st == 'smooth') and (abc in ('AX', 'AY', 'BX')) and (lc in ('mature', 'ramp_up')) and (mu >= 2.0):
        return 'Z1', 'core_hm_si', 'hm_si_core', 'A_smooth_core'

    if (st in ('erratic', 'lumpy')) and (abc in ('AX', 'AY')) and (lc in ('mature', 'ramp_up')) and (mu >= 2.0):
        return 'Z2', 'controlled_hm_si', 'hm_si_controlled', 'B_erratic_lumpy_core'

    if (lc == 'seasonal') or ((st in ('erratic', 'lumpy')) and (abc in ('BY', 'BZ', 'AZ'))):
        return 'Z3', 'secondary_model', 'secondary_replenishment', 'C_secondary_pattern'

    return 'Z3', 'secondary_model', 'secondary_replenishment', 'C_fallback_secondary'


# ----------------------
# Context
# ----------------------
CTX = env.context or {}

FWD_MODEL = str(CTX.get('fwd_model', FWD_MODEL_DEFAULT) or FWD_MODEL_DEFAULT)

HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
TEAM_IDS = _to_int_list(CTX.get('team_ids'))
if not TEAM_IDS:
    TEAM_IDS = list(FILTERED_TEAM_IDS_DEFAULT)

DEMAND_HISTORY_MONTHS = int(CTX.get('demand_history_months', DEMAND_HISTORY_MONTHS_DEFAULT))
DEMAND_WINDOW_WEEKS = int(CTX.get('demand_window_weeks', DEMAND_WINDOW_WEEKS_DEFAULT))

USE_DEMAND_NORMALIZATION = bool(CTX.get('use_demand_normalization', USE_DEMAND_NORMALIZATION_DEFAULT))

SI_ENABLED = bool(CTX.get('si_enabled', SI_ENABLED_DEFAULT))
SI_HISTORY_MONTHS = int(CTX.get('si_history_months', SI_HISTORY_MONTHS_DEFAULT))
SI_TARGET_WEEKS = int(CTX.get('si_target_weeks', SI_TARGET_WEEKS_DEFAULT))
SI_SKU_ADJ_ALPHA_LOW = float(CTX.get('si_sku_adj_alpha_low', SI_SKU_ADJ_ALPHA_LOW_DEFAULT))
SI_SKU_ADJ_ALPHA_HIGH = float(CTX.get('si_sku_adj_alpha_high', SI_SKU_ADJ_ALPHA_HIGH_DEFAULT))
SI_MIN_YEARS_FOR_SKU = int(CTX.get('si_min_years_for_sku', SI_MIN_YEARS_FOR_SKU_DEFAULT))
SI_MIN_OBS_LOCAL_CATEG = int(CTX.get('si_min_obs_local_categ', SI_MIN_OBS_LOCAL_CATEG_DEFAULT))
SI_FLOOR = float(CTX.get('si_floor', SI_FLOOR_DEFAULT))
SI_CEIL = float(CTX.get('si_ceil', SI_CEIL_DEFAULT))

SERVICE_BASE_SHORT_WEEKS = int(CTX.get('service_base_short_weeks', SERVICE_BASE_SHORT_WEEKS_DEFAULT))
SERVICE_BASE_LONG_WEEKS = int(CTX.get('service_base_long_weeks', SERVICE_BASE_LONG_WEEKS_DEFAULT))
SERVICE_RATIO_UP = float(CTX.get('service_ratio_up', SERVICE_RATIO_UP_DEFAULT))
SERVICE_RATIO_HOLD = float(CTX.get('service_ratio_hold', SERVICE_RATIO_HOLD_DEFAULT))
SERVICE_RATIO_COLLAPSE = float(CTX.get('service_ratio_collapse', SERVICE_RATIO_COLLAPSE_DEFAULT))
SERVICE_DOWN_W_SHORT = float(CTX.get('service_down_w_short', SERVICE_DOWN_W_SHORT_DEFAULT))
SERVICE_DOWN_W_LONG = float(CTX.get('service_down_w_long', SERVICE_DOWN_W_LONG_DEFAULT))
SERVICE_CORR_VALIDATION_MIN_WEEKS = int(CTX.get('service_corr_validation_min_weeks', SERVICE_CORR_VALIDATION_MIN_WEEKS_DEFAULT))
SERVICE_CORR_VALIDATION_BASELINE = int(CTX.get('service_corr_validation_baseline', SERVICE_CORR_VALIDATION_BASELINE_DEFAULT))
SERVICE_CORR_VALIDATION_THRESHOLD = float(CTX.get('service_corr_validation_threshold', SERVICE_CORR_VALIDATION_THRESHOLD_DEFAULT))

# v3.43: trend correction
APPLY_TREND_CORRECTION = bool(CTX.get('apply_trend_correction', APPLY_TREND_CORRECTION_DEFAULT))
TREND_LOOKBACK_WEEKS   = int(CTX.get('trend_lookback_weeks', TREND_LOOKBACK_WEEKS_DEFAULT))
TREND_WINDOW_WEEKS     = int(CTX.get('trend_window_weeks', TREND_WINDOW_WEEKS_DEFAULT))
TREND_CLAMP_LOW        = float(CTX.get('trend_clamp_low', TREND_CLAMP_LOW_DEFAULT))
TREND_CLAMP_HIGH       = float(CTX.get('trend_clamp_high', TREND_CLAMP_HIGH_DEFAULT))

# v3.40: fair share
FAIR_SHARE_ENABLED            = bool(CTX.get('fair_share_enabled', FAIR_SHARE_ENABLED_DEFAULT))
FAIR_SHARE_MIN_SALAS_ACTIVAS  = int(CTX.get('fair_share_min_salas_activas', FAIR_SHARE_MIN_SALAS_ACTIVAS_DEFAULT))
FAIR_SHARE_MIN_HISTORIA_CATEG = int(CTX.get('fair_share_min_historia_categ', FAIR_SHARE_MIN_HISTORIA_CATEG_DEFAULT))
FAIR_SHARE_BIAS               = float(CTX.get('fair_share_bias', FAIR_SHARE_BIAS_DEFAULT))
FAIR_SHARE_MIN_UNITS          = float(CTX.get('fair_share_min_units', FAIR_SHARE_MIN_UNITS_DEFAULT))
FAIR_SHARE_SIGMA_CV           = float(CTX.get('fair_share_sigma_cv', FAIR_SHARE_SIGMA_CV_DEFAULT))
FAIR_SHARE_BOTTOM_PCT         = float(CTX.get('fair_share_bottom_pct', FAIR_SHARE_BOTTOM_PCT_DEFAULT))
# v3.42: canon SAP IBP / Blue Yonder
FAIR_SHARE_CONF_N_MAP         = dict(CTX.get('fair_share_conf_n_map', FAIR_SHARE_CONF_N_MAP_DEFAULT))
FAIR_SHARE_GROWTH_CAP         = dict(CTX.get('fair_share_growth_cap', FAIR_SHARE_GROWTH_CAP_DEFAULT))
FAIR_SHARE_TRIED_PENALTY      = float(CTX.get('fair_share_tried_penalty', FAIR_SHARE_TRIED_PENALTY_DEFAULT))
FAIR_SHARE_ALLOWED_ABC        = tuple(CTX.get('fair_share_allowed_abc', FAIR_SHARE_ALLOWED_ABC_DEFAULT))
FAIR_SHARE_B_MAX_GAP          = int(CTX.get('fair_share_b_max_gap', FAIR_SHARE_B_MAX_GAP_DEFAULT))

XYZ_LOCAL_MIN_WEEKS = int(CTX.get('xyz_local_min_weeks', XYZ_LOCAL_MIN_WEEKS_DEFAULT))
XYZ_LOCAL_T1 = float(CTX.get('xyz_local_t1', XYZ_LOCAL_T1_DEFAULT))
XYZ_LOCAL_T2 = float(CTX.get('xyz_local_t2', XYZ_LOCAL_T2_DEFAULT))

# v3.35: parametros del sistema legacy de ajuste de precio eliminados.
# El ajuste se delega al detector externo via _load_correccion_context.

company = env.company
FWD = env[FWD_MODEL].sudo()
ProductProduct = env['product.product'].sudo()
ProductTmpl = env['product.template'].sudo()
ProductCateg = env['product.category'].sudo()
fwd_fields = FWD._fields or {}
pt_fields = ProductTmpl._fields or {}

FWD_LOCAL_FIELD = 'x_studio_team_id'

required_fields = [
    'x_studio_product_id',
    'x_studio_categ_id',
    FWD_LOCAL_FIELD,
    'x_studio_week_start',
    'x_studio_mu_week',
    'x_studio_sigma_week',
    'x_studio_mu_base',
    'x_studio_sigma_base',
    'x_studio_si_current',
    'x_studio_si_next',
    'x_studio_si_n_years',
]
missing_fields = [f for f in required_fields if f not in fwd_fields]

# v3.34: validacion blanda de campos LOCALES por team. Si faltan, se loggea
# en la notification final pero el resto del forecast sigue funcionando
# (los campos se filtran silenciosamente en el write batched).
_xyz_local_required = (
    'x_studio_xyz_local',
    'x_studio_xyz_local_source',
    'x_studio_active_weeks_local',
    'x_studio_series_type_source',
    'x_studio_lifecycle_source',
    'x_studio_adi_local',
    'x_studio_cv2_local',
)
_xyz_local_missing = [f for f in _xyz_local_required if f not in fwd_fields]

config_errors = []
_prod_field = fwd_fields.get('x_studio_product_id')
if _prod_field:
    try:
        if _prod_field.type != 'many2one' or _prod_field.comodel_name != 'product.product':
            config_errors.append(
                'x_studio_product_id debe ser Many2one a product.product; hoy es %s a %s'
                % (_prod_field.type, getattr(_prod_field, 'comodel_name', ''))
            )
    except Exception:
        config_errors.append('No se pudo validar x_studio_product_id; revisar que apunte a product.product')


# ----------------------
# Lock
# ----------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
locked = env.cr.fetchone()[0]

if missing_fields or config_errors:
    if locked:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
    _msg_parts = []
    if missing_fields:
        _msg_parts.append('Faltan campos en %s: %s' % (FWD_MODEL, ', '.join(missing_fields)))
    if config_errors:
        _msg_parts.append('Errores configuracion: %s' % (' / '.join(config_errors)))
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'HM_SI_WEEKLY v3.10',
            'message': ' | '.join(_msg_parts),
            'type': 'danger',
            'sticky': True,
        }
    }
elif not locked:
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'HM_SI_WEEKLY v3.10',
            'message': 'Otro proceso HM_SI_WEEKLY esta ejecutandose. Reintenta.',
            'type': 'warning',
            'sticky': False,
        }
    }
else:
    try:
        purge_count = 0
        if HARD_RESET:
            if TEAM_IDS:
                old_domain = [(FWD_LOCAL_FIELD, 'in', TEAM_IDS)]
            else:
                old_domain = [(FWD_LOCAL_FIELD, '!=', False)]
            old = FWD.search(old_domain)
            purge_count = len(old)
            if old:
                old.unlink()

        env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
        today_local = env.cr.fetchone()[0]

        current_week_start = _week_start(today_local)
        last_closed_week_end = current_week_start - datetime.timedelta(days=1)

        date_to_ctx = CTX.get('date_to')
        if date_to_ctx:
            try:
                raw_date = datetime.datetime.fromisoformat(str(date_to_ctx)).date()
                date_to = _week_start(raw_date) + datetime.timedelta(days=6)
                if date_to >= current_week_start:
                    date_to = last_closed_week_end
            except Exception:
                date_to = last_closed_week_end
        else:
            date_to = last_closed_week_end

        env.cr.execute(
            "SELECT (date_trunc('month', %s::date)::date - (%s || ' months')::interval)::date",
            (date_to, DEMAND_HISTORY_MONTHS)
        )
        history_from = env.cr.fetchone()[0]

        env.cr.execute(
            "SELECT (date_trunc('month', %s::date)::date - (%s || ' months')::interval)::date",
            (date_to, SI_HISTORY_MONTHS)
        )
        si_history_from = env.cr.fetchone()[0] if SI_ENABLED else history_from

        demand_from = _week_start(date_to) - datetime.timedelta(weeks=max(DEMAND_WINDOW_WEEKS - 1, 0))
        if demand_from < history_from:
            demand_from = history_from
        demand_weeks_list = _week_range(demand_from, date_to)
        demand_isoweeks   = [_iso_week_52(wk) for wk in demand_weeks_list]

        # ----------------------
        # Universo maestro base
        # ----------------------
        dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'
        excluded_dtype_sql = "COALESCE(%s, '') NOT IN ('service', 'combo')" % dtype_sql

        env.cr.execute("""
            SELECT
                pp.id AS product_id,
                pp.product_tmpl_id AS tmpl_id,
                pt.categ_id AS categ_id
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pp.active = TRUE
              AND pt.active = TRUE
              AND pt.sale_ok = TRUE
              AND """ + excluded_dtype_sql + """
        """)

        active_product_ids = set()
        product_to_tmpl = {}
        product_to_categ = {}
        for product_id, tmpl_id, categ_id in env.cr.fetchall():
            pid = _safe_int(product_id)
            tid = _safe_int(tmpl_id)
            if not pid or not tid:
                continue
            active_product_ids.add(pid)
            product_to_tmpl[pid] = tid
            product_to_categ[pid] = categ_id or False

        # v3.35: product_to_categ_l2 era input para _load_price_context (eliminado).

        if not active_product_ids:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'HM_SI_WEEKLY v3.10',
                    'message': 'No hay variantes activas/vendibles para forecast.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        else:
            pc_fields = env['pos.config']._fields or {}
            team_col_sql = None
            try:
                f = pc_fields.get('crm_team_id')
                if f and f.type == 'many2one' and f.comodel_name == 'crm.team':
                    team_col_sql = 'pc.crm_team_id'
            except Exception:
                team_col_sql = team_col_sql
            if not team_col_sql:
                try:
                    f = pc_fields.get('team_id')
                    if f and f.type == 'many2one' and f.comodel_name == 'crm.team':
                        team_col_sql = 'pc.team_id'
                except Exception:
                    team_col_sql = team_col_sql

            if not team_col_sql:
                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'HM_SI_WEEKLY v3.10',
                        'message': 'No se encontro crm_team_id/team_id valido en pos.config.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            else:
                team_filter_sql = ''
                if TEAM_IDS:
                    team_filter_sql = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '

                sql_sales = """
                WITH base AS (
                    SELECT
                        __TEAM_COL__ AS team_id,
                        pol.id AS line_id,
                        pol.combo_parent_id,
                        pp.id AS product_id,
                        pt.categ_id AS categ_id,
                        __DTYPE_SQL__ AS dtype,
                        date_trunc('week',
                            po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s
                        )::date AS week,
                        COALESCE(pol.qty, 0.0) AS qty,
                        COALESCE(pol.price_subtotal, 0.0) AS line_rev
                    FROM pos_order_line pol
                    JOIN pos_order po ON po.id = pol.order_id
                    LEFT JOIN pos_session ps ON ps.id = po.session_id
                    LEFT JOIN pos_config pc ON pc.id = ps.config_id
                    JOIN product_product pp ON pp.id = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE po.company_id = %(company_id)s
                      AND po.state IN ('paid','done','invoiced')
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(history_from)s
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                      AND pp.active = TRUE
                      AND pt.sale_ok = TRUE
                      AND pt.active = TRUE
                      AND COALESCE(__DTYPE_SQL__, '') <> 'service'
                      AND __TEAM_COL__ IS NOT NULL
                      __TEAM_FILTER__
                ),
                standalone AS (
                    SELECT team_id, product_id, categ_id, week,
                           SUM(line_rev) AS net_revenue,
                           SUM(qty) AS units
                    FROM base
                    WHERE combo_parent_id IS NULL
                      AND COALESCE(dtype,'') <> 'combo'
                    GROUP BY 1,2,3,4
                ),
                combo_child_pre AS (
                    SELECT c.team_id, c.line_id, c.combo_parent_id,
                           c.product_id, c.categ_id, c.week, c.qty,
                           c.line_rev AS child_rev,
                           p.line_rev AS parent_rev,
                           CASE
                               WHEN ABS(COALESCE(c.line_rev,0.0)) > 0.00001 THEN ABS(c.line_rev)
                               WHEN COALESCE(c.qty,0.0) > 0 THEN c.qty
                               ELSE 0.0
                           END AS weight_value
                    FROM base c
                    JOIN base p ON p.line_id = c.combo_parent_id
                    WHERE c.combo_parent_id IS NOT NULL
                      AND COALESCE(c.dtype,'') <> 'service'
                      AND COALESCE(c.dtype,'') <> 'combo'
                ),
                combo_parent_stats AS (
                    SELECT team_id, combo_parent_id,
                           SUM(weight_value) AS weight_sum,
                           COUNT(*) AS child_count,
                           SUM(CASE WHEN ABS(child_rev) > 0.00001 THEN 1 ELSE 0 END) AS priced_child_count
                    FROM combo_child_pre
                    GROUP BY 1,2
                ),
                combo_children AS (
                    SELECT c.team_id, c.product_id, c.categ_id, c.week,
                           SUM(CASE
                               WHEN s.priced_child_count > 0 THEN c.child_rev
                               WHEN ABS(c.parent_rev) <= 0.00001 THEN 0.0
                               WHEN COALESCE(s.weight_sum,0.0) > 0.00001
                                   THEN c.parent_rev * (c.weight_value / s.weight_sum)
                               WHEN COALESCE(s.child_count,0) > 0
                                   THEN c.parent_rev / s.child_count
                               ELSE 0.0
                           END) AS net_revenue,
                           SUM(c.qty) AS units
                    FROM combo_child_pre c
                    JOIN combo_parent_stats s
                      ON s.combo_parent_id = c.combo_parent_id
                     AND s.team_id = c.team_id
                    GROUP BY 1,2,3,4
                )
                SELECT team_id, product_id, categ_id, week,
                       SUM(net_revenue) AS net_revenue,
                       SUM(units) AS units
                FROM (
                    SELECT * FROM standalone
                    UNION ALL
                    SELECT * FROM combo_children
                ) su
                GROUP BY 1,2,3,4
                """.replace('__TEAM_COL__', team_col_sql).replace('__DTYPE_SQL__', dtype_sql).replace('__TEAM_FILTER__', team_filter_sql)

                params = {
                    'company_id': company.id,
                    'history_from': si_history_from,
                    'date_to': date_to,
                    'tz': TZ_NAME,
                }
                if TEAM_IDS:
                    params['team_ids'] = TEAM_IDS

                env.cr.execute(sql_sales, params)

                data_si = {}
                buf_lc = {}
                buf_cat = {}
                buf_sku = {}
                buf_glo = {}
                team_ids_found = set()

                for team_id, product_id, categ_id_sql, wk, rev, qty in env.cr.fetchall():
                    team_i = _safe_int(team_id)
                    pid = _safe_int(product_id)
                    if not team_i or pid not in active_product_ids:
                        continue

                    q = _safe_float(qty, 0.0)
                    if q < 0.0:
                        q = 0.0
                    r = _safe_float(rev, 0.0)
                    categ_id = product_to_categ.get(pid) or categ_id_sql or False

                    team_ids_found.add(team_i)

                    key = (team_i, pid)
                    data_si.setdefault(key, {})
                    row = data_si[key].get(wk)
                    if row:
                        row[0] += r
                        row[1] += q
                    else:
                        data_si[key][wk] = [r, q]

                    buf_lc[(team_i, categ_id, wk)] = buf_lc.get((team_i, categ_id, wk), 0.0) + q
                    buf_cat[(categ_id, wk)] = buf_cat.get((categ_id, wk), 0.0) + q
                    buf_sku[(pid, wk)] = buf_sku.get((pid, wk), 0.0) + q
                    buf_glo[wk] = buf_glo.get(wk, 0.0) + q

                # ============================================================
                # v3.41 — Construir fair_share_ctx (insumos para _compute_fair_share)
                # ============================================================
                # categ_qty_per_sala[(team, categ_id)] = total qty (suma sobre ventana)
                # sku_qty_per_sala[(team, pid)]        = total qty (suma sobre ventana)
                # historia_categ[(team, categ_id)]    = n semanas con venta > 0
                # n_weeks_window                        = total semanas evaluadas
                fs_categ_qty_per_sala = {}
                fs_weeks_team_categ = {}
                for (team_i, categ_id, wk), qv in buf_lc.items():
                    if qv > 0.0:
                        key_tc = (team_i, categ_id)
                        fs_categ_qty_per_sala[key_tc] = fs_categ_qty_per_sala.get(key_tc, 0.0) + qv
                        fs_weeks_team_categ.setdefault(key_tc, set()).add(wk)

                fs_sku_qty_per_sala = {}
                for (team_i, pid), wkmap in data_si.items():
                    total_qty = 0.0
                    for row in wkmap.values():
                        q = _safe_float((row and row[1]) or 0.0, 0.0)
                        if q > 0.0:
                            total_qty += q
                    if total_qty > 0.0:
                        fs_sku_qty_per_sala[(team_i, pid)] = total_qty

                fs_historia_categ = {k: len(v) for k, v in fs_weeks_team_categ.items()}

                fair_share_ctx = {
                    'sku_qty_per_sala':   fs_sku_qty_per_sala,
                    'categ_qty_per_sala': fs_categ_qty_per_sala,
                    'historia_categ':     fs_historia_categ,
                    'n_weeks_window':     float(len(demand_weeks_list) or 26),
                }
                # ============================================================

                si_weekly_local_categ = {}
                si_weekly_categ_global = {}
                si_weekly_sku = {}
                si_weekly_global = {}

                for (team_i, categ_id, wk), total in buf_lc.items():
                    iso_w = _iso_week_52(wk)
                    si_weekly_local_categ.setdefault((team_i, categ_id), {}).setdefault(iso_w, []).append(total)

                for (categ_id, wk), total in buf_cat.items():
                    iso_w = _iso_week_52(wk)
                    si_weekly_categ_global.setdefault(categ_id, {}).setdefault(iso_w, []).append(total)

                for (pid, wk), total in buf_sku.items():
                    iso_w = _iso_week_52(wk)
                    si_weekly_sku.setdefault(pid, {}).setdefault(iso_w, []).append(total)

                for wk, total in buf_glo.items():
                    iso_w = _iso_week_52(wk)
                    si_weekly_global.setdefault(iso_w, []).append(total)

                if SI_ENABLED:
                    si_global = _calc_si_from_weekly(si_weekly_global)
                    si_categ_global = {}
                    for categ_id, weekly in si_weekly_categ_global.items():
                        si_categ_global[categ_id] = _calc_si_from_weekly(weekly)

                    si_local_categ = {}
                    for key_lc, weekly in si_weekly_local_categ.items():
                        n_weeks_with_data = sum(1 for totals in weekly.values() if totals)
                        if n_weeks_with_data >= SI_MIN_OBS_LOCAL_CATEG:
                            si_local_categ[key_lc] = _calc_si_from_weekly(weekly)

                    si_sku_raw = {}
                    for pid, weekly in si_weekly_sku.items():
                        si_sku_raw[pid] = _calc_si_from_weekly(weekly)
                else:
                    si_global = {w: 1.0 for w in range(1, 53)}
                    si_categ_global = {}
                    si_local_categ = {}
                    si_sku_raw = {}

                sku_n_years = {}
                for (team_i, pid), wkmap in data_si.items():
                    years = set()
                    for wk, row in wkmap.items():
                        if _safe_float((row and row[1]) or 0.0, 0.0) > 0.0:
                            years.add(wk.year)
                    if len(years) > sku_n_years.get(pid, 0):
                        sku_n_years[pid] = len(years)

                data = {}
                for key, wkmap in data_si.items():
                    filtered = {}
                    for wk, row in wkmap.items():
                        if wk >= history_from:
                            filtered[wk] = row
                    if filtered:
                        data[key] = filtered

                local_pairs = sorted(data.keys())

                # Overlay de normalizacion de demanda (proyecto 2026-05-25).
                # Si flag activo, carga x_demanda_normalizada por (team, sku, week)
                # para reemplazar q_raw en el loop principal. Dict vacio = sin efecto.
                demand_norm_overlay = {}
                if USE_DEMAND_NORMALIZATION and demand_weeks_list:
                    env.cr.execute("""
                        SELECT x_studio_team_id, x_studio_product_id,
                               x_studio_week_start, x_studio_qty_norm
                        FROM x_demanda_normalizada
                        WHERE x_studio_team_id = ANY(%s)
                          AND x_studio_week_start >= %s
                          AND x_studio_week_start <= %s
                    """, (list(TEAM_IDS), demand_weeks_list[0], demand_weeks_list[-1]))
                    for _tid, _pid, _wk, _qn in env.cr.fetchall():
                        if _tid is None or _pid is None or _wk is None:
                            continue
                        demand_norm_overlay[(int(_tid), int(_pid), _wk)] = float(_qn or 0.0)

                batch = []
                total_created = 0
                si_level_counts = {'local_categ': 0, 'categ_global': 0, 'global': 0}
                method_counts = {}
                norm_overlay_hits = 0

                fwd_create = FWD.with_context(
                    tracking_disable=True,
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                    mail_notrack=True,
                ).create

                target_date     = _week_start(date_to) + datetime.timedelta(weeks=max(SI_TARGET_WEEKS, 1))
                target_isoweek  = _iso_week_52(target_date)
                current_isoweek = _iso_week_52(date_to)

                product_ids_for_price = []
                for _lp in local_pairs:
                    try:
                        product_ids_for_price.append(_lp[1])
                    except Exception:
                        pass

                router_ctx = _load_forecast_router_context(product_ids_for_price)
                router_zone_counts = {}

                # v3.29: cargar correcciones del detector x_price_coreccion.
                # 1 query por run; se aplica al final del calculo de mu_week.
                correccion_ctx = _load_correccion_context(product_ids_for_price, target_date)
                correccion_applied_count = 0
                correccion_tipo_counts = {}

                # v3.33: contadores distribucion XYZ local por team.
                # 'global' agrega los casos sin datos locales suficientes que
                # heredan el XYZ global del producto desde router_ctx.
                xyz_local_counts = {'X': 0, 'Y': 0, 'Z': 0, 'global': 0}

                # Precompute SI base (without sku_adj) for all unique (team, categ, iso_week) combos.
                # Avoids repeating the level-resolution chain (local→categ→global) inside the hot loop.
                _unique_tc = set((t, product_to_categ.get(p)) for t, p in local_pairs)
                si_base_cache = {}
                for _t, _c in _unique_tc:
                    _lc_si  = si_local_categ.get((_t, _c), {}) if _c else {}
                    _cat_si = si_categ_global.get(_c, {}) if _c else {}
                    for _w in range(1, 53):
                        _sm = _lc_si.get(_w)
                        if _sm is not None:
                            si_base_cache[(_t, _c, _w)] = (float(_sm), 'local_categ')
                            continue
                        _sm = _cat_si.get(_w)
                        if _sm is not None:
                            si_base_cache[(_t, _c, _w)] = (float(_sm), 'categ_global')
                            continue
                        si_base_cache[(_t, _c, _w)] = (float(si_global.get(_w, 1.0)), 'global')

                # ============================================================
                # v3.43 — Trend correction por team (weekly YoY asimetrico)
                # ============================================================
                # Calcula trend_factor_by_team[tid] ANTES del loop principal,
                # 1 vez por corrida. Aplica en el loop a mu_week final.
                trend_factor_by_team = {}
                trend_factor_log = []  # para el msg final
                if APPLY_TREND_CORRECTION and TEAM_IDS:
                    trend_from = _week_start(date_to) - datetime.timedelta(weeks=TREND_LOOKBACK_WEEKS)
                    trend_sql = """
                        SELECT
                            __TEAM_COL__ AS team_id,
                            date_trunc('week',
                                po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s
                            )::date AS wk,
                            SUM(COALESCE(pol.qty, 0.0)) AS qty
                        FROM pos_order_line pol
                        JOIN pos_order po ON po.id = pol.order_id
                        LEFT JOIN pos_session ps ON ps.id = po.session_id
                        LEFT JOIN pos_config pc ON pc.id = ps.config_id
                        JOIN product_product pp ON pp.id = pol.product_id
                        JOIN product_template pt ON pt.id = pp.product_tmpl_id
                        WHERE po.company_id = %(company_id)s
                          AND po.state IN ('paid','done','invoiced')
                          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(trend_from)s
                          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                          AND pp.active = TRUE
                          AND pt.sale_ok = TRUE
                          AND pt.active = TRUE
                          AND __TEAM_COL__ IS NOT NULL
                          AND __TEAM_COL__ = ANY(%(team_ids)s)
                        GROUP BY 1, 2
                    """.replace('__TEAM_COL__', team_col_sql)
                    env.cr.execute(trend_sql, {
                        'tz': TZ_NAME,
                        'company_id': company.id,
                        'trend_from': trend_from,
                        'date_to': date_to,
                        'team_ids': list(TEAM_IDS),
                    })
                    weekly_team_units = {}
                    for _tid, _wk, _qty in env.cr.fetchall():
                        if _tid is None or _wk is None:
                            continue
                        weekly_team_units[(int(_tid), _wk)] = _safe_float(_qty, 0.0)

                    # Cutoff = lunes de la semana del date_to (la semana del cutoff incluido)
                    cutoff_week = _week_start(date_to)
                    for _tid in TEAM_IDS:
                        yoy_vals = []
                        for _i in range(TREND_WINDOW_WEEKS):
                            _wk = cutoff_week - datetime.timedelta(weeks=_i)
                            _wk_ly = _wk - datetime.timedelta(weeks=52)
                            _curr = weekly_team_units.get((int(_tid), _wk))
                            _prev = weekly_team_units.get((int(_tid), _wk_ly))
                            if _curr is not None and _prev and _prev > 0:
                                yoy_vals.append(_curr / _prev - 1.0)
                        if yoy_vals:
                            _avg = sum(yoy_vals) / float(len(yoy_vals))
                            _fac = _clamp(1.0 + _avg, TREND_CLAMP_LOW, TREND_CLAMP_HIGH)
                        else:
                            _avg = 0.0
                            _fac = 1.0
                        trend_factor_by_team[int(_tid)] = _fac
                        trend_factor_log.append('t%s:f=%.3f(yoy=%+.1f%%,n=%d)' % (
                            int(_tid), _fac, _avg * 100.0, len(yoy_vals)))

                for team_id, product_id in local_pairs:
                    categ_id = product_to_categ.get(product_id)
                    if not product_id or product_id not in active_product_ids:
                        continue

                    wkmap = data.get((team_id, product_id)) or {}

                    base_vals = []
                    raw_vals = []
                    total_units = 0.0
                    total_revenue = 0.0

                    # Per-product constants for fast SI lookup
                    si_sku_pid        = si_sku_raw.get(product_id, {})
                    si_c_dict         = si_categ_global.get(categ_id, {}) if categ_id else {}
                    si_lc_dict        = si_local_categ.get((team_id, categ_id), {}) if categ_id else {}
                    _uses_local_categ = bool(si_lc_dict)
                    n_years_pid = sku_n_years.get(product_id, 0)
                    alpha_pid   = SI_SKU_ADJ_ALPHA_HIGH if n_years_pid >= SI_MIN_YEARS_FOR_SKU else SI_SKU_ADJ_ALPHA_LOW

                    for wk, iso_w in zip(demand_weeks_list, demand_isoweeks):
                        row = wkmap.get(wk)
                        q_raw = _safe_float((row and row[1]) or 0.0, 0.0)
                        if q_raw < 0.0:
                            q_raw = 0.0
                        # Overlay: reemplazar q_raw por qty_norm si la celda
                        # esta en x_demanda_normalizada (semana con quiebre).
                        _norm_q = demand_norm_overlay.get((team_id, product_id, wk))
                        if _norm_q is not None:
                            q_raw = _norm_q
                            norm_overlay_hits += 1
                        r_raw = _safe_float((row and row[0]) or 0.0, 0.0)

                        _si_main, _ = si_base_cache.get((team_id, categ_id, iso_w), (1.0, 'global'))
                        _si_sku = si_sku_pid.get(iso_w)
                        if _si_sku is not None and n_years_pid >= 1:
                            # usar mismo nivel que si_main para la referencia del ajuste SKU
                            _si_c = (si_lc_dict.get(iso_w) or si_c_dict.get(iso_w, 1.0)) if _uses_local_categ else si_c_dict.get(iso_w, 1.0)
                            if _si_c > 0.001:
                                si_w = _clamp(_si_main * (1.0 + alpha_pid * (float(_si_sku) / _si_c - 1.0)), SI_FLOOR, SI_CEIL)
                            else:
                                si_w = _clamp(_si_main, SI_FLOOR, SI_CEIL)
                        else:
                            si_w = _clamp(_si_main, SI_FLOOR, SI_CEIL)

                        # v3.35: q_adj = q_raw (sin ajuste interno). El ajuste por
                        # cambio de precio se aplica al final via x_price_coreccion.
                        q_base = q_raw / si_w if SI_ENABLED and si_w > 0.0 else q_raw

                        raw_vals.append(q_raw)
                        base_vals.append(q_base)
                        total_units += q_raw
                        total_revenue += r_raw

                    # v3.39: auto-model selection per SKU (SAP-style bake-off).
                    # Heuristico, SBA(0.15), Croston(0.10), seasonal_naive_52
                    # compiten sobre holdout de 4 sem. Heur-bias 0.90: el
                    # heuristico gana a menos que otro modelo sea >=10% mejor
                    # en MAE. demand_method trae el code del ganador.
                    mu_base, sigma_base, demand_method, collapse_detected = _select_best_model(
                        base_vals,
                        raw_vals,
                        SERVICE_BASE_SHORT_WEEKS,
                        SERVICE_BASE_LONG_WEEKS,
                        SERVICE_RATIO_UP,
                        SERVICE_RATIO_HOLD,
                        SERVICE_RATIO_COLLAPSE,
                        SERVICE_DOWN_W_SHORT,
                        SERVICE_DOWN_W_LONG,
                    )

                    # v3.34: Clasificacion LOCAL por team. Cada variable contiene el
                    # valor a usar: si el calculo local tiene senal, es local;
                    # si no, se hereda el global del router (escrito por archivo 1).
                    # source identifica el origen para auditoria.
                    #
                    # ABC siempre global (criterio economico).
                    # XYZ, series_type, lifecycle, regimen: locales con fallback.
                    _rctx = router_ctx.get(product_id, {})
                    _global_abcxyz = (_rctx.get('abcxyz') or '').strip().upper()
                    _global_abc_letter = _global_abcxyz[0] if len(_global_abcxyz) == 2 and _global_abcxyz[0] in ('A', 'B', 'C') else ''
                    _global_xyz_letter = _global_abcxyz[1] if len(_global_abcxyz) == 2 and _global_abcxyz[1] in ('X', 'Y', 'Z') else ''
                    _global_series_type = _infer_series_type_from_xyz(
                        (_rctx.get('series_type') or '').strip().lower(),
                        _global_abcxyz,
                    )
                    _global_lifecycle = (_rctx.get('lifecycle') or '').strip().lower()
                    _global_regimen = (_rctx.get('regimen') or '').strip().upper()

                    active_weeks_local = sum(1 for v in base_vals if v > 0)
                    n_weeks_local = len(base_vals)

                    # --- XYZ local (CV simple) ---
                    if active_weeks_local < XYZ_LOCAL_MIN_WEEKS:
                        xyz_local        = _global_xyz_letter
                        xyz_local_source = 'global'
                    else:
                        _xyz_calc = _xyz_from_serie(base_vals, XYZ_LOCAL_T1, XYZ_LOCAL_T2)
                        if _xyz_calc:
                            xyz_local        = _xyz_calc
                            xyz_local_source = 'local'
                        else:
                            xyz_local        = _global_xyz_letter
                            xyz_local_source = 'global'
                    if xyz_local in ('X', 'Y', 'Z'):
                        xyz_local_counts[xyz_local] += 1
                    else:
                        xyz_local_counts['global'] += 1

                    # --- ADI y CV2 locales (Syntetos-Boylan) ---
                    # ADI = n_weeks / weeks_with_demand. CV2 sobre periodos positivos.
                    if active_weeks_local > 0:
                        adi_local = float(n_weeks_local) / float(active_weeks_local)
                    else:
                        adi_local = 0.0
                    _pos_vals = [v for v in base_vals if v > 0]
                    if len(_pos_vals) >= 2:
                        _mu_pos, _sigma_pos = _avg_std(_pos_vals)
                        cv2_local = ((_sigma_pos / _mu_pos) ** 2.0) if _mu_pos > 0 else 0.0
                    else:
                        cv2_local = 0.0

                    # --- series_type local: si no_signal, hereda global ---
                    _stype_calc = _classify_series_type_local(
                        adi_local, cv2_local, active_weeks_local, XYZ_LOCAL_MIN_WEEKS,
                    )
                    if _stype_calc in ('smooth', 'erratic', 'intermittent', 'lumpy'):
                        series_type_local        = _stype_calc
                        series_type_local_source = 'local'
                    else:
                        series_type_local        = _global_series_type
                        series_type_local_source = 'global'

                    # --- Presencia trimestral local (ultimos 8 trimestres) ---
                    # raw_vals[i] corresponde a demand_weeks_list[i].
                    _q_now_abs = _quarter_abs_local(date_to)
                    _u_q = [0.0] * 8
                    _q_offsets_seen = set()
                    for _wk_idx, _wk in enumerate(demand_weeks_list):
                        _off = _q_now_abs - _quarter_abs_local(_wk)
                        if 0 <= _off <= 7:
                            _u_q[_off] += _safe_float(raw_vals[_wk_idx], 0.0) if _wk_idx < len(raw_vals) else 0.0
                            _q_offsets_seen.add(_off)
                    _p_q8_local = sum(1 for _u in _u_q if _u > 0.0)

                    # --- lifecycle local: si dead por falta de datos pero el global
                    # dice otra cosa, prefiere global. Mismo criterio que series_type.
                    _lc_calc = _infer_lifecycle_local(
                        _u_q[0], _u_q[1], _u_q[2], _u_q[3],
                        _u_q[4], _u_q[5], _u_q[6], _u_q[7],
                        _p_q8_local, xyz_local,
                    )
                    # Si el local sale 'dead' pero hay senal global vigente, se usa global
                    # (caso tipico: producto vivo en otras sucursales sin presencia aqui).
                    if _lc_calc == 'dead' and _global_lifecycle and _global_lifecycle not in ('dead', 'declining'):
                        lifecycle_local        = _global_lifecycle
                        lifecycle_local_source = 'global'
                    elif _lc_calc:
                        lifecycle_local        = _lc_calc
                        lifecycle_local_source = 'local'
                    else:
                        lifecycle_local        = _global_lifecycle
                        lifecycle_local_source = 'global'

                    # --- abcxyz_local: ABC global + XYZ local ---
                    abcxyz_local = (_global_abc_letter + xyz_local) if (_global_abc_letter and xyz_local) else _global_abcxyz

                    # --- regimen: SIEMPRE se calcula con la matriz local usando
                    # los datos efectivos (sean locales o heredados del global).
                    # No hay fallback al regimen del router — el regimen se
                    # deriva siempre de los inputs validos. source='local'
                    # porque la matriz aplicada es la local.
                    regimen_local = _assign_regimen_local(
                        abcxyz_local, series_type_local, lifecycle_local,
                    )
                    regimen_local_source = 'local'

                    # v3.35: mu_base_no_adj eliminado — el ajuste por precio
                    # ya no se aplica internamente al historico.

                    if mu_base < 0.0:
                        mu_base = 0.0
                        sigma_base = 0.0
                        demand_method = (str(demand_method) + '|clamped_negative')[:120]
                    method_counts[demand_method] = method_counts.get(demand_method, 0) + 1

                    _si_main_next, si_next_level = si_base_cache.get((team_id, categ_id, target_isoweek), (1.0, 'global'))
                    si_main_factor = _si_main_next
                    si_sku_factor  = 1.0
                    _si_sku_next = si_sku_pid.get(target_isoweek)
                    if _si_sku_next is not None and n_years_pid >= 1:
                        _si_c = (si_lc_dict.get(target_isoweek) or si_c_dict.get(target_isoweek, 1.0)) if _uses_local_categ else si_c_dict.get(target_isoweek, 1.0)
                        if _si_c > 0.001:
                            _raw = _si_main_next * (1.0 + alpha_pid * (float(_si_sku_next) / _si_c - 1.0))
                            si_next = _clamp(_raw, SI_FLOOR, SI_CEIL)
                            si_sku_factor = si_next / _si_main_next if _si_main_next > 0.0 else 1.0
                            si_next_level = si_next_level + '+sku_adj'
                        else:
                            si_next = _clamp(_si_main_next, SI_FLOOR, SI_CEIL)
                    else:
                        si_next = _clamp(_si_main_next, SI_FLOOR, SI_CEIL)

                    _si_main_cur, _ = si_base_cache.get((team_id, categ_id, current_isoweek), (1.0, 'global'))
                    _si_sku_cur = si_sku_pid.get(current_isoweek)
                    if _si_sku_cur is not None and n_years_pid >= 1:
                        _si_c = (si_lc_dict.get(current_isoweek) or si_c_dict.get(current_isoweek, 1.0)) if _uses_local_categ else si_c_dict.get(current_isoweek, 1.0)
                        if _si_c > 0.001:
                            si_current = _clamp(_si_main_cur * (1.0 + alpha_pid * (float(_si_sku_cur) / _si_c - 1.0)), SI_FLOOR, SI_CEIL)
                        else:
                            si_current = _clamp(_si_main_cur, SI_FLOOR, SI_CEIL)
                    else:
                        si_current = _clamp(_si_main_cur, SI_FLOOR, SI_CEIL)

                    base_level = (si_next_level or 'global').replace('+sku_adj', '').strip()
                    si_level_counts[base_level] = si_level_counts.get(base_level, 0) + 1

                    mu_week = mu_base * si_next if SI_ENABLED else mu_base
                    sigma_week = sigma_base * si_next if SI_ENABLED else sigma_base

                    # v3.34: el motor consume las clasificaciones LOCALES por team
                    # (xyz_local, series_type_local, lifecycle_local, regimen_local,
                    # abcxyz_local). Cada una ya contiene el valor a usar — si el
                    # calculo local cayo a fallback, la variable trae el global.
                    forecast_zone, forecast_scope, forecast_model_code, forecast_scope_reason = _route_forecast_scope(
                        abcxyz_local,
                        series_type_local,
                        lifecycle_local,
                        mu_week,
                    )
                    router_zone_counts[forecast_zone] = router_zone_counts.get(forecast_zone, 0) + 1

                    # ============================================================
                    # v3.42 — Fair share canon (SAP IBP / Blue Yonder)
                    # ============================================================
                    # v3.42 expande v3.41 con tres parches canon:
                    #   1. conf_n por N salas activas (factor con 1 sola sala vale 0.30).
                    #   2. growth_cap por XYZ (mu_fs <= mu_global * cap / gap_count).
                    #   3. tried_penalty si la sala target ya probo y mu_local=0.
                    # Trigger: A siempre, B solo si gap<=2 (TERMINAR COBERTURA).
                    # La logica de gating ahora vive en _compute_fair_share.
                    fair_share_applied = False
                    if (
                        FAIR_SHARE_ENABLED
                        and mu_week == 0
                        and lifecycle_local in ('mature', 'ramp_up')
                    ):
                        fs_res = _compute_fair_share(
                            product_id=product_id,
                            team_id=team_id,
                            categ_id_local=categ_id,
                            router_ctx=router_ctx,
                            fs_ctx=fair_share_ctx,
                            bias=FAIR_SHARE_BIAS,
                            sigma_cv=FAIR_SHARE_SIGMA_CV,
                            min_units=FAIR_SHARE_MIN_UNITS,
                            min_salas=FAIR_SHARE_MIN_SALAS_ACTIVAS,
                            min_historia=FAIR_SHARE_MIN_HISTORIA_CATEG,
                            bottom_pct=FAIR_SHARE_BOTTOM_PCT,
                            active_weeks_target=active_weeks_local,
                            conf_n_map=FAIR_SHARE_CONF_N_MAP,
                            growth_cap_map=FAIR_SHARE_GROWTH_CAP,
                            tried_penalty=FAIR_SHARE_TRIED_PENALTY,
                            allowed_abc=FAIR_SHARE_ALLOWED_ABC,
                            b_max_gap=FAIR_SHARE_B_MAX_GAP,
                            n_salas_total=12,
                        )
                        if fs_res is not None:
                            mu_week = fs_res['mu_week']
                            sigma_week = fs_res['sigma_week']
                            forecast_zone = 'Z1'
                            forecast_scope = fs_res.get('scope', 'core_canon_v42')
                            forecast_model_code = 'fair_share_canon'
                            forecast_scope_reason = fs_res['reason']
                            fair_share_applied = True
                    # ============================================================

                    # ============================================================
                    # v3.17 — Correcciones de sobre-forecast (P1 + P3 + P6 ampliado)
                    # ============================================================

                    # P1: declining/dead nunca generan demanda — forzar cero
                    if lifecycle_local in ('declining', 'dead'):
                        mu_week = 0.0
                        sigma_week = 0.0

                    else:
                        # P3: zero-gate para Z4 sin actividad reciente
                        # v3.25: excluir REG-8 (seasonal). Los SKUs estacionales tienen ventanas
                        # naturales de cero entre temporadas que NO indican declive. El zero-gate
                        # los anulaba y producia sub-forecast severo cuando volvia la temporada
                        # (BIAS +49.54% en backtest 2026-05-04 sobre 5,291 SKUs REG-8). El
                        # regimen se lee de ABCXYZ via la matriz canonica.
                        # v3.30: suavizar de '<=1' a '==0'. SKUs con 1 venta en 8 sem son
                        # demanda viva intermitente; anularlos generaba sub-forecast en CY/CZ.
                        # Cuesta WAPE en colas (BZ/CZ) pero recupera 1,900 unid de ventas
                        # reales del sub-forecast.
                        if forecast_zone == 'Z4' and lifecycle_local not in ('ramp_up',) and regimen_local != 'REG-8':
                            nz_recent = sum(1 for v in (base_vals or [])[-8:] if v > 0)
                            if nz_recent == 0:
                                mu_week = 0.0
                                sigma_week = 0.0

                        # P6: cap absoluto anti-spike (v3.17 — ampliado)
                        # Reglas por segmento:
                        #   BZ cualquier zona  → cap 0.8x max (lumpy extremo)
                        #   AZ/CZ cualquier zona → cap 1.2x max
                        #   BY en Z3 o Z4      → cap 1.2x max (antes solo Z4)
                        #   AY smooth en Z2    → cap 1.2x max (erratic mal enrutado)
                        #   CY en Z4           → cap 1.2x max
                        if mu_week > 0 and base_vals:
                            max_obs = max(base_vals)
                            if max_obs > 0:
                                abc_last = abcxyz_local[-1:] if abcxyz_local else ''
                                is_ay_smooth_z2 = (
                                    abcxyz_local == 'AY'
                                    and series_type_local == 'smooth'
                                    and forecast_zone == 'Z2'
                                )
                                is_by_z3z4 = (
                                    abcxyz_local == 'BY'
                                    and forecast_zone in ('Z3', 'Z4')
                                )
                                is_cy_z4 = (
                                    abcxyz_local == 'CY'
                                    and forecast_zone == 'Z4'
                                )
                                if abcxyz_local == 'BZ':
                                    cap_val = max_obs * 0.8
                                    mu_week = min(mu_week, cap_val)
                                elif abc_last in ('Z',) or is_by_z3z4 or is_ay_smooth_z2 or is_cy_z4:
                                    cap_val = max_obs * 1.2
                                    mu_week = min(mu_week, cap_val)

                    # ============================================================
                    # Fin v3.17
                    # ============================================================

                    # ============================================================
                    # v3.29 — Aplicar correccion del detector x_price_coreccion
                    # Se aplica DESPUES de P1/P3/P6 para que:
                    #  - declining/dead sigan en 0 (factor sobre 0 = 0)
                    #  - Z4 zero-gate siga aplicando
                    #  - los caps absolutos protejan del motor, pero el factor
                    #    es senal externa intencional que puede superarlos
                    # ============================================================
                    correccion_factor = 1.0
                    correccion_tipo = ''
                    correccion_razon = ''
                    mu_week_pre_corr = mu_week
                    corr = correccion_ctx.get(product_id) if correccion_ctx else None
                    if corr and mu_week > 0:
                        correccion_factor = _safe_float(corr.get('factor'), 1.0)
                        correccion_tipo = _safe_text(corr.get('tipo'), 60)
                        correccion_razon = _safe_text(corr.get('razon'), 240)

                        # v3.37: validacion empirica del factor. Si tenemos >=3 semanas
                        # post-cambio cerradas, comparar base_vals pre vs post. Si la
                        # demanda real NO cayo lo que predijo el factor, blend hacia
                        # 1.0. Asimetrica: solo atenua over-correcciones, no aumenta
                        # cuts (memoria: sub-forecast cuesta mas que over-forecast).
                        weeks_since_emit = _safe_int(corr.get('weeks_since'), 0)
                        corr_target_ws = corr.get('target_week_start')
                        weeks_since_real = weeks_since_emit
                        if corr_target_ws:
                            try:
                                if isinstance(corr_target_ws, datetime.date):
                                    ref_date = corr_target_ws
                                else:
                                    ref_date = datetime.datetime.strptime(
                                        str(corr_target_ws)[:10], '%Y-%m-%d'
                                    ).date()
                                delta_days = (target_date - ref_date).days
                                weeks_since_real = max(0, weeks_since_emit + (delta_days // 7))
                            except Exception:
                                pass

                        if (correccion_factor < 0.90
                                and weeks_since_real >= SERVICE_CORR_VALIDATION_MIN_WEEKS
                                and base_vals):
                            n_post = min(weeks_since_real, 8)
                            n_pre = SERVICE_CORR_VALIDATION_BASELINE
                            if len(base_vals) >= (n_pre + n_post):
                                post_window = base_vals[-n_post:]
                                pre_window = base_vals[-(n_pre + n_post):-n_post]
                                if post_window and pre_window:
                                    post_avg = sum(post_window) / float(len(post_window))
                                    pre_avg = sum(pre_window) / float(len(pre_window))
                                    if pre_avg > 0:
                                        empirical_factor = post_avg / pre_avg
                                        if (empirical_factor - correccion_factor) > SERVICE_CORR_VALIDATION_THRESHOLD:
                                            correccion_factor = min(
                                                1.0,
                                                (correccion_factor + empirical_factor) / 2.0,
                                            )
                                            correccion_razon = (
                                                correccion_razon
                                                + ' [emp %.2f adj %.3f]'
                                                % (empirical_factor, correccion_factor)
                                            )[:240]

                        if correccion_factor != 1.0:
                            mu_week = mu_week * correccion_factor
                            sigma_week = sigma_week * correccion_factor
                            correccion_applied_count += 1
                            correccion_tipo_counts[correccion_tipo] = \
                                correccion_tipo_counts.get(correccion_tipo, 0) + 1

                    # ============================================================
                    # v3.43 — Trend correction multiplicativo por team
                    # Se aplica DESPUES de correccion_factor (precio) para que:
                    #  - mu_week_pre_bias capture el valor pre-trend
                    #  - el redondeo sea sobre el valor final corregido
                    # Asimetrico por design (cap_high=1.00 default): solo recorta
                    # cuando hay deterioro YoY, NO amplifica teams en alza.
                    # ============================================================
                    mu_week_pre_bias = mu_week
                    trend_factor = 1.0
                    if APPLY_TREND_CORRECTION:
                        trend_factor = _safe_float(
                            trend_factor_by_team.get(team_id, 1.0), 1.0)
                        if trend_factor != 1.0 and mu_week > 0:
                            mu_week = mu_week * trend_factor
                            sigma_week = sigma_week * trend_factor

                    # ============================================================
                    # v3.31 — Redondeo medio-arriba al entero del mu_week final.
                    # fraccion < 0.5 -> entero abajo; fraccion >= 0.5 -> entero arriba.
                    # 0.3 -> 0; 0.5 -> 1; 1.3 -> 1; 1.5 -> 2; 1.7 -> 2.
                    # No tocamos sigma_week (es metrica continua) ni mu_week_pre_corr
                    # (mantiene la trazabilidad pre-redondeo).
                    # ============================================================
                    if mu_week > 0:
                        mu_week = float(int(mu_week + 0.5))

                    rec_name = 'HM-SI LOC%s PP%s' % (team_id, product_id)

                    vals = {}
                    if 'x_name' in fwd_fields:
                        vals['x_name'] = rec_name

                    _put_field(vals, fwd_fields, 'x_studio_product_id', product_id)
                    _put_field(vals, fwd_fields, 'x_studio_team_id', team_id)
                    _put_field(vals, fwd_fields, 'x_studio_categ_id', categ_id)
                    _put_field(vals, fwd_fields, 'x_studio_week_start', target_date)
                    _put_field(vals, fwd_fields, 'x_studio_mu_week', mu_week)
                    _put_field(vals, fwd_fields, 'x_studio_mu_week_pre_bias', mu_week_pre_bias)
                    _put_field(vals, fwd_fields, 'x_studio_sigma_week', sigma_week)
                    _put_field(vals, fwd_fields, 'x_studio_mu_base', mu_base)
                    _put_field(vals, fwd_fields, 'x_studio_sigma_base', sigma_base)
                    _put_field(vals, fwd_fields, 'x_studio_collapse_detected', bool(collapse_detected))
                    _put_field(vals, fwd_fields, 'x_studio_si_current', si_current)
                    _put_field(vals, fwd_fields, 'x_studio_si_next', si_next)
                    _put_si_level(vals, fwd_fields, si_next_level or '')
                    _put_field(vals, fwd_fields, 'x_studio_si_n_years', int(n_years_pid))

                    _put_field(vals, fwd_fields, 'x_studio_si_main_factor', si_main_factor)
                    _put_field(vals, fwd_fields, 'x_studio_si_sku_factor', si_sku_factor)

                    # v3.29: campos de auditoria de la correccion externa
                    _put_field(vals, fwd_fields, 'x_studio_correccion_factor', correccion_factor)
                    _put_field(vals, fwd_fields, 'x_studio_correccion_tipo', correccion_tipo, 60)
                    _put_field(vals, fwd_fields, 'x_studio_correccion_razon', correccion_razon, 240)
                    _put_field(vals, fwd_fields, 'x_studio_mu_week_pre_corr', mu_week_pre_corr)

                    _put_field(vals, fwd_fields, 'x_studio_forecast_zone', forecast_zone, 20)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_scope', forecast_scope, 60)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_model_code', forecast_model_code, 60)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_scope_reason', forecast_scope_reason, 120)
                    # v3.39: codigo del modelo ganador del bake-off auto-model
                    # (heur, sba_015, croston_010, seasonal_naive_52, etc.).
                    # Si el campo no existe en Studio, _put_field lo omite.
                    _put_field(vals, fwd_fields, 'x_studio_demand_method', demand_method, 60)

                    # v3.34 - inputs del router (ya consumen valor LOCAL con
                    # fallback al global cuando hay senal insuficiente).
                    _put_field(vals, fwd_fields, 'x_studio_abcxyz', abcxyz_local, 10)
                    _put_field(vals, fwd_fields, 'x_studio_series_type', series_type_local, 20)
                    _put_field(vals, fwd_fields, 'x_studio_ciclo_de_vida', lifecycle_local, 40)
                    _put_field(vals, fwd_fields, 'x_studio_regimen', regimen_local, 20)

                    # XYZ local por team y trazabilidad de fuente (local/global)
                    _put_field(vals, fwd_fields, 'x_studio_xyz_local', xyz_local, 4)
                    _put_field(vals, fwd_fields, 'x_studio_xyz_local_source', xyz_local_source, 20)
                    _put_field(vals, fwd_fields, 'x_studio_active_weeks_local', int(active_weeks_local))

                    # v3.34: source de cada clasificacion para auditoria
                    _put_field(vals, fwd_fields, 'x_studio_series_type_source', series_type_local_source, 20)
                    _put_field(vals, fwd_fields, 'x_studio_lifecycle_source', lifecycle_local_source, 20)
                    _put_field(vals, fwd_fields, 'x_studio_adi_local', _safe_float(adi_local, 0.0))
                    _put_field(vals, fwd_fields, 'x_studio_cv2_local', _safe_float(cv2_local, 0.0))

                    batch.append(vals)

                    if len(batch) >= BATCH_SIZE:
                        fwd_create(batch)
                        total_created += len(batch)
                        batch = []

                if batch:
                    fwd_create(batch)
                    total_created += len(batch)

                _xyz_missing_msg = (
                    ' | xyz_local_missing=' + ','.join(_xyz_local_missing)
                ) if _xyz_local_missing else ''

                try:
                    log(
                        'HM_SI_WEEKLY v3.35 | purged=%s | created=%s | teams=%s | sku_local=%s'
                        ' | active_products=%s | hist=%s->%s | si_hist=%s | target_w=%s'
                        ' | si_lc=%s si_cat=%s si_global=%s'
                        ' | router_zones=%s'
                        ' | xyz_local: X=%s Y=%s Z=%s global=%s%s' % (
                            purge_count,
                            total_created,
                            len(team_ids_found),
                            len(local_pairs),
                            len(active_product_ids),
                            history_from,
                            date_to,
                            si_history_from,
                            SI_TARGET_WEEKS,
                            si_level_counts.get('local_categ', 0),
                            si_level_counts.get('categ_global', 0),
                            si_level_counts.get('global', 0),
                            ','.join([str(k)+':'+str(v) for k, v in router_zone_counts.items()]),
                            xyz_local_counts['X'],
                            xyz_local_counts['Y'],
                            xyz_local_counts['Z'],
                            xyz_local_counts['global'],
                            _xyz_missing_msg,
                        ),
                        level='info'
                    )
                except Exception:
                    pass

                _notif_type = 'danger' if _xyz_local_missing else 'success'
                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'HM_SI_WEEKLY v3.35 REGIMEN_LOCAL',
                        'message': (
                            'created=%s | sku_local=%s | zones=%s'
                            ' | xyz_local: X=%s Y=%s Z=%s global=%s%s'
                            ' | norm_overlay=%s (hits=%s)'
                            ' | trend=%s [%s]'
                        ) % (
                            total_created,
                            len(local_pairs),
                            ','.join([str(k)+':'+str(v) for k, v in router_zone_counts.items()]),
                            xyz_local_counts['X'],
                            xyz_local_counts['Y'],
                            xyz_local_counts['Z'],
                            xyz_local_counts['global'],
                            _xyz_missing_msg,
                            'ON' if USE_DEMAND_NORMALIZATION else 'OFF',
                            norm_overlay_hits,
                            'ON' if APPLY_TREND_CORRECTION else 'OFF',
                            ' '.join(trend_factor_log) if APPLY_TREND_CORRECTION else '',
                        ),
                        'sticky': True,
                        'type': _notif_type,
                    }
                }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))

