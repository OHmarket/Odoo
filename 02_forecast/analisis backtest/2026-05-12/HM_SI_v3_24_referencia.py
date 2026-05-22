# VERSION_ID = "FWD_v3_24_CMP5"
# MODEL_NAME = "HM_SI_WEEKLY"
# v3.24: Cambios activos (todos validados o reverted):
#   - Mantenido: corrección de nivel mixto en ajuste SKU — usa local_categ
#     como referencia cuando si_main proviene de local_categ (antes mezclaba niveles)
#   - Mantenido: PRICE_FACTOR_TABLE_L2 limpia (sin duplicados, sin None, normalizado)
#   - Revertido v3.22: _calc_si_from_weekly vuelve a divisor len(clean) y len(avg_by_week)
#     porque /expected_n y /52 inflaban SI en semanas presentes → deflactaban mu_base
#     via q_base = q_adj/si_w → underforecast crónico en Z-class (AZ +19.7pp wMAPE)
#   - Revertido v3.22: semanas faltantes SI=1.0 (neutro) en vez de 0.0
# v3.21: PRICE_FACTOR_TABLE_L2 limpiada:
#   - Eliminados 4 duplicados sin tilde (Cocteles, Snack, Isotonicas, Electronicos)
#   - Todos los None reemplazados por valor DEFAULT correspondiente (tabla autoexplicativa)
#   - Lookup normalizado via _norm_categ() — resiste variaciones de tilde/mayúscula

VERSION_ID = "FWD_v3_24_CMP5"

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
SERVICE_DOWN_W_SHORT_DEFAULT     = 0.70
SERVICE_DOWN_W_LONG_DEFAULT      = 0.30


# ----------------------
# Parametros ajuste por precio real efectivo
# ----------------------
PRICE_ADJUST_ENABLED_DEFAULT       = True
PRICE_EVENT_MODEL_DEFAULT          = 'x_price_change_event'
PRICE_EVENT_HISTORY_WEEKS_DEFAULT  = 104
PRICE_EVENT_RECENT_WEEKS_DEFAULT   = 12
PRICE_FREQUENT_THRESHOLD_DEFAULT   = 4
PRICE_MODERATE_THRESHOLD_DEFAULT   = 2
PRICE_RECENT_UNSTABLE_THRESHOLD_DEFAULT = 2
PRICE_ELASTICITY_DEFAULT           = -0.60
PRICE_ADJ_MIN_FACTOR_DEFAULT       = 0.40
PRICE_ADJ_MAX_FACTOR_DEFAULT       = 3.00
PRICE_ADJ_MIN_PRICE_RATIO_DELTA_DEFAULT = 0.005
PRICE_DECAY_WEEKS_DEFAULT          = 16


# ============================================================
# v3.8 - TABLA DE FACTORES CALIBRADOS POR CATEGORIA L2 + RANGO
# Valores calibrados; donde no hay dato propio se usa PRICE_FACTOR_DEFAULT.
# Sin duplicados: nombres con tilde (forma que usa Odoo). Lookup normalizado.
# ============================================================
PRICE_FACTOR_TABLE_L2 = {
    'Cervezas':                  {'BAJADA_FUERTE': 1.99, 'BAJADA_LEVE': 1.46, 'SUBIDA_LEVE': 0.85, 'SUBIDA_FUERTE': 0.76},
    'Vinos':                     {'BAJADA_FUERTE': 2.00, 'BAJADA_LEVE': 1.90, 'SUBIDA_LEVE': 1.05, 'SUBIDA_FUERTE': 1.00},
    'Espumantes':                {'BAJADA_FUERTE': 2.00, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 1.05, 'SUBIDA_FUERTE': 0.90},
    'Destilados':                {'BAJADA_FUERTE': 1.58, 'BAJADA_LEVE': 1.05, 'SUBIDA_LEVE': 0.82, 'SUBIDA_FUERTE': 1.00},
    'Cócteles y Licores':        {'BAJADA_FUERTE': 1.21, 'BAJADA_LEVE': 1.08, 'SUBIDA_LEVE': 0.94, 'SUBIDA_FUERTE': 1.00},
    'Bebidas Gaseosas':          {'BAJADA_FUERTE': 1.46, 'BAJADA_LEVE': 1.07, 'SUBIDA_LEVE': 0.91, 'SUBIDA_FUERTE': 0.87},
    'Snack y Cóctel':            {'BAJADA_FUERTE': 1.41, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 0.84, 'SUBIDA_FUERTE': 0.71},
    'Chocolates y Dulces':       {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 0.70, 'SUBIDA_FUERTE': 0.77},
    'Galletas y Colaciones':     {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 1.05, 'SUBIDA_FUERTE': 0.56},
    'Helados':                   {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 0.95, 'SUBIDA_FUERTE': 0.90},
    'Aguas':                     {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 1.05, 'SUBIDA_FUERTE': 0.90},
    'Isotónicas y Energéticas':  {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 0.99, 'SUBIDA_FUERTE': 1.00},
    'Jugos':                     {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 1.00, 'SUBIDA_FUERTE': 0.90},
    'Despensa':                  {'BAJADA_FUERTE': 1.67, 'BAJADA_LEVE': 1.42, 'SUBIDA_LEVE': 0.96, 'SUBIDA_FUERTE': 0.98},
    'Electrónicos':              {'BAJADA_FUERTE': 1.20, 'BAJADA_LEVE': 1.05, 'SUBIDA_LEVE': 0.96, 'SUBIDA_FUERTE': 0.90},
}

PRICE_FACTOR_DEFAULT = {
    'BAJADA_FUERTE': 1.67,
    'BAJADA_LEVE':   1.42,
    'SUBIDA_LEVE':   0.96,
    'SUBIDA_FUERTE': 0.90,
}

def _norm_categ(s):
    _tr = str.maketrans('áéíóúÁÉÍÓÚñÑüÜ', 'aeiouAEIOUnNuU')
    return (s or '').strip().translate(_tr).lower()

_PRICE_FACTOR_TABLE_NORM = {_norm_categ(k): v for k, v in PRICE_FACTOR_TABLE_L2.items()}




def _classify_price_range(delta_pct):
    d = float(delta_pct or 0.0)
    if d <= -0.15:
        return 'BAJADA_FUERTE'
    if d <= -0.05:
        return 'BAJADA_LEVE'
    if d >= 0.15:
        return 'SUBIDA_FUERTE'
    if d >= 0.05:
        return 'SUBIDA_LEVE'
    return 'ESTABLE'


def _categ_l2_from_complete_name(complete_name):
    if not complete_name:
        return ''
    try:
        parts = str(complete_name).split(' / ')
        if len(parts) >= 2:
            return parts[1].strip()
    except Exception:
        pass
    return ''


def _lookup_calibrated_factor(delta_pct, categ_l2):
    rango = _classify_price_range(delta_pct)
    if rango == 'ESTABLE':
        return 1.0, 'STABLE'
    cat_rules = _PRICE_FACTOR_TABLE_NORM.get(_norm_categ(categ_l2 or ''))
    if cat_rules:
        f = cat_rules.get(rango)
        if f is not None:
            return float(f), 'L2'
    f = PRICE_FACTOR_DEFAULT.get(rango)
    if f is not None:
        return float(f), 'DEFAULT'
    return None, 'NONE'


def _apply_decay(factor_calibrated, weeks_since_change, decay_weeks):
    if factor_calibrated is None or factor_calibrated == 1.0:
        return 1.0
    n = max(0, int(weeks_since_change or 0))
    decay = max(1, int(decay_weeks or 1))
    if n >= decay:
        return 1.0
    weight = 1.0 - (float(n) / float(decay))
    return 1.0 + (float(factor_calibrated) - 1.0) * weight


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


def _calc_base_demand(base_vals,
                      short_weeks, long_weeks,
                      ratio_up, ratio_hold,
                      down_w_short, down_w_long):
    n = len(base_vals or [])
    if n <= 0:
        return 0.0, 0.0, 'no_history'

    mu_all, sigma_all = _avg_std(base_vals)

    if n < long_weeks:
        return mu_all, sigma_all, 'avg_base_%sw' % n

    short_vals = base_vals[-short_weeks:]
    long_vals = base_vals[-long_weeks:]

    sma_short, sigma_short = _avg_std(short_vals)
    sma_long, sigma_long = _avg_std(long_vals)

    if sma_long > 0.0:
        ratio = sma_short / sma_long
    else:
        ratio = 9.99 if sma_short > 0.0 else 1.0

    if ratio >= ratio_up:
        return sma_short, sigma_short, 'sma%s_base_up_r=%s' % (short_weeks, round(ratio, 3))

    if ratio >= ratio_hold:
        return sma_long, sigma_long, 'sma%s_base_hold_r=%s' % (long_weeks, round(ratio, 3))

    mu_blend = (down_w_short * sma_short) + (down_w_long * sma_long)
    sigma_blend = (down_w_short * sigma_short) + (down_w_long * sigma_long)
    return mu_blend, sigma_blend, 'blend_down_base_r=%s' % round(ratio, 3)


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


def _price_segment(events_104w, events_recent, frequent_th, moderate_th, recent_unstable_th):
    e104 = _safe_int(events_104w, 0)
    er = _safe_int(events_recent, 0)
    if er >= recent_unstable_th:
        return 'recent_price_unstable'
    if e104 >= frequent_th:
        return 'frequent_price_core'
    if e104 >= moderate_th:
        return 'moderate_price_changes'
    return 'stable_price'


def _price_at_week(events, wk):
    if not events:
        return 0.0
    first = events[0]
    if wk < first.get('week'):
        return _safe_float(first.get('base_price'), 0.0)
    current = 0.0
    for ev in events:
        evw = ev.get('week')
        if evw and evw <= wk:
            current = _safe_float(ev.get('price_eff'), 0.0)
        else:
            break
    return current


def _last_price_change_week_before(events, wk):
    if not events:
        return None
    last = None
    for ev in events:
        evw = ev.get('week')
        if evw and evw <= wk:
            last = evw
        else:
            break
    return last


# ----------------------
# Carga contexto de precio (idéntico v3.8)
# ----------------------
def _load_price_context(product_ids, week_list, date_to, product_to_categ_l2):
    out = {}
    if not PRICE_ADJUST_ENABLED:
        return out
    if not product_ids:
        return out
    if not _model_exists(PRICE_EVENT_MODEL):
        return out

    Ev = env[PRICE_EVENT_MODEL].sudo()
    ev_fields = Ev._fields or {}

    product_field = _first_m2o_field(Ev, [
        'x_studio_product_variant_id',
        'x_studio_product_product_id',
        'x_product_variant_id',
        'x_studio_product_id',
    ], 'product.product')

    if not product_field:
        return out

    week_field = _first_field(Ev, ['x_studio_period_start', 'x_studio_week_start', 'x_week_start'])
    base_field = _first_field(Ev, ['x_studio_base_price', 'x_base_price'])
    eff_field = _first_field(Ev, ['x_studio_price_eff', 'x_studio_week_price', 'x_price_eff'])
    delta_field = _first_field(Ev, ['x_studio_delta_pct', 'x_delta_pct'])
    direction_field = _first_field(Ev, ['x_studio_direction', 'x_direction'])
    is_real_change_field = _first_field(Ev, ['x_studio_is_real_change', 'x_is_real_change'])
    company_field = _first_field(Ev, ['x_studio_company_id', 'x_company_id'])

    if not week_field or not base_field or not eff_field:
        return out

    try:
        first_week = min(week_list) if week_list else (date_to - datetime.timedelta(weeks=PRICE_EVENT_HISTORY_WEEKS))
    except Exception:
        first_week = date_to - datetime.timedelta(weeks=PRICE_EVENT_HISTORY_WEEKS)

    history_start = date_to - datetime.timedelta(weeks=PRICE_EVENT_HISTORY_WEEKS)
    if history_start > first_week:
        history_start = first_week
    recent_start = date_to - datetime.timedelta(weeks=PRICE_EVENT_RECENT_WEEKS)

    pids = []
    for pid in product_ids:
        pidi = _safe_int(pid, 0)
        if pidi:
            pids.append(pidi)
    pids = list(set(pids))
    if not pids:
        return out

    domain = [
        (product_field, 'in', pids),
        (week_field, '>=', history_start),
        (week_field, '<=', date_to),
    ]
    if is_real_change_field:
        domain.append((is_real_change_field, '=', True))
    if company_field:
        domain.append((company_field, '=', company.id))

    read_fields = [product_field, week_field, base_field, eff_field]
    if delta_field:
        read_fields.append(delta_field)
    if direction_field:
        read_fields.append(direction_field)

    events_by_product = {}
    try:
        rows = Ev.search(domain, order='%s asc, id asc' % week_field).read(read_fields)
    except Exception:
        return out

    for r in rows:
        pv = r.get(product_field)
        if isinstance(pv, (list, tuple)):
            pid = _safe_int(pv[0], 0)
        else:
            pid = _safe_int(pv, 0)
        if not pid:
            continue
        wk = r.get(week_field)
        try:
            if not isinstance(wk, datetime.date):
                wk = datetime.datetime.fromisoformat(str(wk)).date()
        except Exception:
            continue
        base_price = _safe_float(r.get(base_field), 0.0)
        price_eff = _safe_float(r.get(eff_field), 0.0)
        if base_price <= 0.0 or price_eff <= 0.0:
            continue
        ev = {
            'week': wk,
            'base_price': base_price,
            'price_eff': price_eff,
            'delta_pct': _safe_float(r.get(delta_field), 0.0) if delta_field else 0.0,
            'direction': r.get(direction_field) if direction_field else '',
        }
        events_by_product.setdefault(pid, []).append(ev)

    for pid in pids:
        events = events_by_product.get(pid) or []
        events.sort(key=lambda x: x.get('week'))
        e104 = 0
        er = 0
        for ev in events:
            evw = ev.get('week')
            if evw and evw >= history_start and evw <= date_to:
                e104 += 1
            if evw and evw >= recent_start and evw <= date_to:
                er += 1

        segment = _price_segment(
            e104, er,
            PRICE_FREQUENT_THRESHOLD,
            PRICE_MODERATE_THRESHOLD,
            PRICE_RECENT_UNSTABLE_THRESHOLD,
        )

        price_target = _price_at_week(events, date_to)
        categ_l2 = product_to_categ_l2.get(pid, '')

        week_factor = {}
        week_factor_source = {}
        adj_count_l2 = 0
        adj_count_default = 0
        adj_count_fallback = 0

        if price_target > 0.0:
            for wk in (week_list or []):
                ph = _price_at_week(events, wk)
                if ph <= 0.0:
                    week_factor[wk] = 1.0
                    week_factor_source[wk] = 'STABLE'
                    continue

                ratio = price_target / ph
                if abs(ratio - 1.0) < PRICE_ADJ_MIN_PRICE_RATIO_DELTA:
                    week_factor[wk] = 1.0
                    week_factor_source[wk] = 'STABLE'
                    continue

                delta_pct = ratio - 1.0
                factor_cal, source = _lookup_calibrated_factor(delta_pct, categ_l2)

                if factor_cal is None:
                    try:
                        factor_cal = ratio ** PRICE_ELASTICITY
                        source = 'FALLBACK'
                    except Exception:
                        factor_cal = 1.0
                        source = 'STABLE'

                weeks_since_change = max(0, (date_to - wk).days // 7)

                factor_with_decay = _apply_decay(
                    factor_cal,
                    weeks_since_change,
                    PRICE_DECAY_WEEKS,
                )

                factor_final = _clamp(factor_with_decay, PRICE_ADJ_MIN_FACTOR, PRICE_ADJ_MAX_FACTOR)

                week_factor[wk] = factor_final
                week_factor_source[wk] = source

                if abs(factor_final - 1.0) > 0.0001:
                    if source == 'L2':
                        adj_count_l2 += 1
                    elif source == 'DEFAULT':
                        adj_count_default += 1
                    elif source == 'FALLBACK':
                        adj_count_fallback += 1

        out[pid] = {
            'events': events,
            'events_104w': e104,
            'events_recent': er,
            'segment': segment,
            'price_target': price_target,
            'week_factor': week_factor,
            'week_factor_source': week_factor_source,
            'adj_l2': adj_count_l2,
            'adj_default': adj_count_default,
            'adj_fallback': adj_count_fallback,
            'categ_l2': categ_l2,
        }

    return out


# ----------------------
# Router (idéntico v3.7/v3.8)
# ----------------------
def _norm_txt(v, maxlen=80):
    return _safe_text(v, maxlen).strip().lower()


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
    series_field = _first_field(Abc, ['x_studio_series_type', 'x_series_type'])
    lifecycle_field = _first_field(Abc, ['x_studio_ciclo_de_vida', 'x_studio_lifecycle', 'x_ciclo_de_vida'])
    company_field = _first_field(Abc, ['x_studio_company_id', 'x_company_id'])
    active_field = _first_field(Abc, ['x_active', 'x_studio_active', 'active'])

    read_fields = [product_field]
    for f in [abcxyz_field, series_field, lifecycle_field]:
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

    try:
        rows = Abc.search(domain, order='write_date desc, id desc').read(read_fields)
    except Exception:
        return out

    for r in rows:
        pv = r.get(product_field)
        if isinstance(pv, (list, tuple)):
            pid = _safe_int(pv[0], 0)
        else:
            pid = _safe_int(pv, 0)
        if not pid or pid in out:
            continue
        out[pid] = {
            'abcxyz': _safe_text(r.get(abcxyz_field), 20).upper() if abcxyz_field else '',
            'series_type': _norm_txt(r.get(series_field), 40) if series_field else '',
            'lifecycle': _norm_txt(r.get(lifecycle_field), 40) if lifecycle_field else '',
        }

    return out


def _route_forecast_scope(abcxyz, series_type, lifecycle, mu_week):
    abc = _safe_text(abcxyz, 20).strip().upper()
    st = _norm_txt(series_type, 40)
    lc = _norm_txt(lifecycle, 40)
    mu = _safe_float(mu_week, 0.0)

    # Inferir series_type desde letra XYZ cuando no viene del modelo ABCXYZ.
    # X = demanda regular (smooth), Y = variable (erratic), Z = esporádica (lumpy).
    if not st and abc:
        xyz_letter = abc[-1]
        if xyz_letter == 'X':
            st = 'smooth'
        elif xyz_letter == 'Y':
            st = 'erratic'
        elif xyz_letter == 'Z':
            st = 'lumpy'

    # v3.13: AX smooth con threshold reducido (mu>=1) se evalua ANTES del floor global
    # para capturar productos de alta velocidad con demanda baja pero predecible.
    if (st == 'smooth') and (abc == 'AX') and (lc in ('mature', 'ramp_up')) and (mu >= 1.0):
        return 'Z1', 'core_hm_si', 'hm_si_core', 'A_smooth_core_ax'

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
SERVICE_DOWN_W_SHORT = float(CTX.get('service_down_w_short', SERVICE_DOWN_W_SHORT_DEFAULT))
SERVICE_DOWN_W_LONG = float(CTX.get('service_down_w_long', SERVICE_DOWN_W_LONG_DEFAULT))

PRICE_ADJUST_ENABLED = bool(CTX.get('price_adjust_enabled', PRICE_ADJUST_ENABLED_DEFAULT))
PRICE_EVENT_MODEL = str(CTX.get('price_event_model', PRICE_EVENT_MODEL_DEFAULT) or PRICE_EVENT_MODEL_DEFAULT)
PRICE_EVENT_HISTORY_WEEKS = int(CTX.get('price_event_history_weeks', PRICE_EVENT_HISTORY_WEEKS_DEFAULT))
PRICE_EVENT_RECENT_WEEKS = int(CTX.get('price_event_recent_weeks', PRICE_EVENT_RECENT_WEEKS_DEFAULT))
PRICE_FREQUENT_THRESHOLD = int(CTX.get('price_frequent_threshold', PRICE_FREQUENT_THRESHOLD_DEFAULT))
PRICE_MODERATE_THRESHOLD = int(CTX.get('price_moderate_threshold', PRICE_MODERATE_THRESHOLD_DEFAULT))
PRICE_RECENT_UNSTABLE_THRESHOLD = int(CTX.get('price_recent_unstable_threshold', PRICE_RECENT_UNSTABLE_THRESHOLD_DEFAULT))
PRICE_ELASTICITY = float(CTX.get('price_elasticity', PRICE_ELASTICITY_DEFAULT))
PRICE_ADJ_MIN_FACTOR = float(CTX.get('price_adj_min_factor', PRICE_ADJ_MIN_FACTOR_DEFAULT))
PRICE_ADJ_MAX_FACTOR = float(CTX.get('price_adj_max_factor', PRICE_ADJ_MAX_FACTOR_DEFAULT))
PRICE_ADJ_MIN_PRICE_RATIO_DELTA = float(CTX.get('price_adj_min_price_ratio_delta', PRICE_ADJ_MIN_PRICE_RATIO_DELTA_DEFAULT))
PRICE_DECAY_WEEKS = int(CTX.get('price_decay_weeks', PRICE_DECAY_WEEKS_DEFAULT))

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

        product_to_categ_l2 = {}
        if active_product_ids:
            categ_ids_used = list(set([cid for cid in product_to_categ.values() if cid]))
            if categ_ids_used:
                cat_records = ProductCateg.browse(categ_ids_used)
                cat_to_l2 = {}
                for c in cat_records:
                    try:
                        cat_to_l2[c.id] = _categ_l2_from_complete_name(c.complete_name)
                    except Exception:
                        cat_to_l2[c.id] = ''
                for pid, cid in product_to_categ.items():
                    product_to_categ_l2[pid] = cat_to_l2.get(cid, '')

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

                batch = []
                total_created = 0
                si_level_counts = {'local_categ': 0, 'categ_global': 0, 'global': 0}
                method_counts = {}

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

                price_ctx = _load_price_context(
                    product_ids_for_price, demand_weeks_list, date_to, product_to_categ_l2
                )
                price_segment_counts = {}
                total_adj_l2 = 0
                total_adj_default = 0
                total_adj_fallback = 0

                router_ctx = _load_forecast_router_context(product_ids_for_price)
                router_zone_counts = {}

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

                for team_id, product_id in local_pairs:
                    categ_id = product_to_categ.get(product_id)
                    if not product_id or product_id not in active_product_ids:
                        continue

                    wkmap = data.get((team_id, product_id)) or {}

                    base_vals = []
                    raw_vals = []
                    adjusted_vals = []
                    total_units = 0.0
                    total_units_adjusted = 0.0
                    total_revenue = 0.0
                    price_adjust_weeks = 0
                    price_adj_factor_sum = 0.0
                    price_adj_factor_max = 1.0
                    price_adj_factor_min = 1.0
                    price_elasticity_acc_sum = 0.0
                    price_elasticity_acc_n = 0

                    pctx = price_ctx.get(product_id, {})
                    price_segment = pctx.get('segment', 'stable_price')
                    price_segment_counts[price_segment] = price_segment_counts.get(price_segment, 0) + 1

                    total_adj_l2 += _safe_int(pctx.get('adj_l2'), 0)
                    total_adj_default += _safe_int(pctx.get('adj_default'), 0)
                    total_adj_fallback += _safe_int(pctx.get('adj_fallback'), 0)

                    base_vals_no_adj = []

                    # Per-product constants for fast SI lookup
                    si_sku_pid        = si_sku_raw.get(product_id, {})
                    si_c_dict         = si_categ_global.get(categ_id, {}) if categ_id else {}
                    si_lc_dict        = si_local_categ.get((team_id, categ_id), {}) if categ_id else {}
                    _uses_local_categ = bool(si_lc_dict)
                    n_years_pid = sku_n_years.get(product_id, 0)
                    alpha_pid   = SI_SKU_ADJ_ALPHA_HIGH if n_years_pid >= SI_MIN_YEARS_FOR_SKU else SI_SKU_ADJ_ALPHA_LOW
                    wf_dict     = pctx.get('week_factor') or {}

                    for wk, iso_w in zip(demand_weeks_list, demand_isoweeks):
                        row = wkmap.get(wk)
                        q_raw = _safe_float((row and row[1]) or 0.0, 0.0)
                        if q_raw < 0.0:
                            q_raw = 0.0
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

                        price_factor = 1.0
                        try:
                            price_factor = _safe_float(wf_dict.get(wk, 1.0), 1.0)
                        except Exception:
                            price_factor = 1.0
                        if price_factor <= 0.0:
                            price_factor = 1.0

                        q_adj = q_raw * price_factor
                        if abs(price_factor - 1.0) > 0.0001 and q_raw > 0.0:
                            price_adjust_weeks += 1
                            price_adj_factor_sum += price_factor
                            if price_factor > price_adj_factor_max:
                                price_adj_factor_max = price_factor
                            if price_factor < price_adj_factor_min:
                                price_adj_factor_min = price_factor
                            try:
                                pctx_events = pctx.get('events') or []
                                price_target = _safe_float(pctx.get('price_target'), 0.0)
                                ph = _price_at_week(pctx_events, wk)
                                if ph > 0.0 and price_target > 0.0:
                                    ratio = price_target / ph
                                    if abs(ratio - 1.0) > 0.001:
                                        elast_eff = (price_factor - 1.0) / (ratio - 1.0)
                                        price_elasticity_acc_sum += elast_eff
                                        price_elasticity_acc_n += 1
                            except Exception:
                                pass

                        q_base = q_adj / si_w if SI_ENABLED and si_w > 0.0 else q_adj
                        q_base_no_adj = q_raw / si_w if SI_ENABLED and si_w > 0.0 else q_raw

                        raw_vals.append(q_raw)
                        adjusted_vals.append(q_adj)
                        base_vals.append(q_base)
                        base_vals_no_adj.append(q_base_no_adj)
                        total_units += q_raw
                        total_units_adjusted += q_adj
                        total_revenue += r_raw

                    mu_base, sigma_base, demand_method = _calc_base_demand(
                        base_vals,
                        SERVICE_BASE_SHORT_WEEKS,
                        SERVICE_BASE_LONG_WEEKS,
                        SERVICE_RATIO_UP,
                        SERVICE_RATIO_HOLD,
                        SERVICE_DOWN_W_SHORT,
                        SERVICE_DOWN_W_LONG,
                    )

                    if price_adjust_weeks == 0:
                        mu_base_no_adj = mu_base
                    else:
                        mu_base_no_adj, _, _ = _calc_base_demand(
                            base_vals_no_adj,
                            SERVICE_BASE_SHORT_WEEKS,
                            SERVICE_BASE_LONG_WEEKS,
                            SERVICE_RATIO_UP,
                            SERVICE_RATIO_HOLD,
                            SERVICE_DOWN_W_SHORT,
                            SERVICE_DOWN_W_LONG,
                        )
                        if mu_base_no_adj < 0.0:
                            mu_base_no_adj = 0.0

                    if price_adjust_weeks > 0:
                        demand_method = (str(demand_method) + '|price_adj_v38')[:120]

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

                    mu_week_no_adj = mu_base_no_adj * si_next if SI_ENABLED else mu_base_no_adj
                    mu_week_price_delta = mu_week - mu_week_no_adj

                    rctx = router_ctx.get(product_id, {})
                    router_abcxyz = rctx.get('abcxyz', '')
                    router_series_type = rctx.get('series_type', '')
                    router_lifecycle = rctx.get('lifecycle', '')
                    if not router_series_type and router_abcxyz:
                        _xyz = router_abcxyz[-1]
                        if _xyz == 'X':   router_series_type = 'smooth'
                        elif _xyz == 'Y': router_series_type = 'erratic'
                        elif _xyz == 'Z': router_series_type = 'lumpy'
                    forecast_zone, forecast_scope, forecast_model_code, forecast_scope_reason = _route_forecast_scope(
                        router_abcxyz,
                        router_series_type,
                        router_lifecycle,
                        mu_week,
                    )
                    router_zone_counts[forecast_zone] = router_zone_counts.get(forecast_zone, 0) + 1

                    # ============================================================
                    # v3.17 — Correcciones de sobre-forecast (P1 + P3 + P6 ampliado)
                    # ============================================================

                    # P1: declining/dead nunca generan demanda — forzar cero
                    if router_lifecycle in ('declining', 'dead'):
                        mu_week = 0.0
                        sigma_week = 0.0

                    else:
                        # P3: zero-gate para Z4 sin actividad reciente
                        if forecast_zone == 'Z4' and router_lifecycle not in ('ramp_up',):
                            nz_recent = sum(1 for v in (base_vals or [])[-8:] if v > 0)
                            if nz_recent <= 1:
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
                                abc_last = router_abcxyz[-1:] if router_abcxyz else ''
                                is_ay_smooth_z2 = (
                                    router_abcxyz == 'AY'
                                    and router_series_type == 'smooth'
                                    and forecast_zone == 'Z2'
                                )
                                is_by_z3z4 = (
                                    router_abcxyz == 'BY'
                                    and forecast_zone in ('Z3', 'Z4')
                                )
                                is_cy_z4 = (
                                    router_abcxyz == 'CY'
                                    and forecast_zone == 'Z4'
                                )
                                if router_abcxyz == 'BZ':
                                    cap_val = max_obs * 0.8
                                    mu_week = min(mu_week, cap_val)
                                elif abc_last in ('Z',) or is_by_z3z4 or is_ay_smooth_z2 or is_cy_z4:
                                    cap_val = max_obs * 1.2
                                    mu_week = min(mu_week, cap_val)

                    # ============================================================
                    # Fin v3.17
                    # ============================================================

                    rec_name = 'HM-SI LOC%s PP%s' % (team_id, product_id)

                    vals = {}
                    if 'x_name' in fwd_fields:
                        vals['x_name'] = rec_name

                    _put_field(vals, fwd_fields, 'x_studio_product_id', product_id)
                    _put_field(vals, fwd_fields, 'x_studio_team_id', team_id)
                    _put_field(vals, fwd_fields, 'x_studio_categ_id', categ_id)
                    _put_field(vals, fwd_fields, 'x_studio_week_start', target_date)
                    _put_field(vals, fwd_fields, 'x_studio_mu_week', mu_week)
                    _put_field(vals, fwd_fields, 'x_studio_mu_week_pre_bias', mu_week)
                    _put_field(vals, fwd_fields, 'x_studio_sigma_week', sigma_week)
                    _put_field(vals, fwd_fields, 'x_studio_mu_base', mu_base)
                    _put_field(vals, fwd_fields, 'x_studio_sigma_base', sigma_base)
                    _put_field(vals, fwd_fields, 'x_studio_si_current', si_current)
                    _put_field(vals, fwd_fields, 'x_studio_si_next', si_next)
                    _put_si_level(vals, fwd_fields, si_next_level or '')
                    _put_field(vals, fwd_fields, 'x_studio_si_n_years', int(n_years_pid))

                    _put_field(vals, fwd_fields, 'x_studio_si_main_factor', si_main_factor)
                    _put_field(vals, fwd_fields, 'x_studio_si_sku_factor', si_sku_factor)

                    avg_price_factor = (price_adj_factor_sum / price_adjust_weeks) if price_adjust_weeks > 0 else 1.0
                    avg_price_elasticity = (price_elasticity_acc_sum / price_elasticity_acc_n) if price_elasticity_acc_n > 0 else PRICE_ELASTICITY
                    _put_field(vals, fwd_fields, 'x_studio_units_sold_adjusted', total_units_adjusted)
                    _put_field(vals, fwd_fields, 'x_studio_price_dynamics_segment', price_segment, 80)
                    _put_field(vals, fwd_fields, 'x_studio_price_events_104w', _safe_int(pctx.get('events_104w'), 0))
                    _put_field(vals, fwd_fields, 'x_studio_price_events_12w', _safe_int(pctx.get('events_recent'), 0))
                    _put_field(vals, fwd_fields, 'x_studio_price_current_eff', _safe_float(pctx.get('price_target'), 0.0))
                    _put_field(vals, fwd_fields, 'x_studio_price_adjust_weeks', price_adjust_weeks)
                    _put_field(vals, fwd_fields, 'x_studio_price_adj_factor_avg', avg_price_factor)
                    _put_field(vals, fwd_fields, 'x_studio_price_adjust_enabled', PRICE_ADJUST_ENABLED)
                    _put_field(vals, fwd_fields, 'x_studio_price_adj_factor_max', price_adj_factor_max)
                    _put_field(vals, fwd_fields, 'x_studio_price_adj_factor_min', price_adj_factor_min)
                    _put_field(vals, fwd_fields, 'x_studio_price_elasticity_used', avg_price_elasticity)
                    _put_field(vals, fwd_fields, 'x_studio_mu_week_price_delta', mu_week_price_delta)

                    _put_field(vals, fwd_fields, 'x_studio_forecast_zone', forecast_zone, 20)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_scope', forecast_scope, 60)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_model_code', forecast_model_code, 60)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_scope_reason', forecast_scope_reason, 120)

                    # v3.11 - inputs del router para auditoría y backtest
                    _put_field(vals, fwd_fields, 'x_studio_abcxyz', router_abcxyz, 10)
                    _put_field(vals, fwd_fields, 'x_studio_series_type', router_series_type, 20)
                    _put_field(vals, fwd_fields, 'x_studio_ciclo_de_vida', router_lifecycle, 40)

                    batch.append(vals)

                    if len(batch) >= BATCH_SIZE:
                        fwd_create(batch)
                        total_created += len(batch)
                        batch = []

                if batch:
                    fwd_create(batch)
                    total_created += len(batch)

                try:
                    log(
                        'HM_SI_WEEKLY v3.18 | purged=%s | created=%s | teams=%s | sku_local=%s'
                        ' | active_products=%s | hist=%s->%s | si_hist=%s | target_w=%s'
                        ' | si_lc=%s si_cat=%s si_global=%s'
                        ' | adj_L2=%s adj_DEFAULT=%s adj_FALLBACK=%s | decay_weeks=%s'
                        ' | price_segments=%s | router_zones=%s' % (
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
                            total_adj_l2,
                            total_adj_default,
                            total_adj_fallback,
                            PRICE_DECAY_WEEKS,
                            ','.join([str(k)+':'+str(v) for k, v in price_segment_counts.items()]),
                            ','.join([str(k)+':'+str(v) for k, v in router_zone_counts.items()]),
                        ),
                        level='info'
                    )
                except Exception:
                    pass

                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'HM_SI_WEEKLY v3.18',
                        'message': 'created=%s | sku_local=%s | zones=%s' % (
                            total_created,
                            len(local_pairs),
                            ','.join([str(k)+':'+str(v) for k, v in router_zone_counts.items()]),
                        ),
                        'sticky': True,
                        'type': 'success',
                    }
                }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))

