# ============================================================
# LEGACY - Reemplazado por Script 5 (HM-SI Forecast v3.35) el 2026-05-13.
# NO ejecutar en produccion. Script 3 ahora lee directo de
# x_hm_si_forecast (motor HM-SI) + Odoo nativo (product_supplierinfo,
# product_template.uom_po_id) para los metadatos de compra.
# Conservado como referencia historica de share_of_pool, price_event
# detector legacy, supplier maps, _SEASONAL_BAND, density/adi.
# Para reactivar: deshabilitar primero el cron de S5 sobre x_hm_si_forecast
# y revertir cambios en `3- OH Analisis de Stock.py` (FWD_MODEL y FWD_TEAM_FIELD).
# ============================================================

# VERSION_ID = "FWD_v3_0_5_XYZ_LOCAL"
#
# Patch sobre v3.0.4:
#   - Calcula XYZ_LOCAL por team con el MISMO metodo del XYZ global (archivo 1):
#     una sola pasada CV simple = sigma/mu sobre la serie local del team
#     (qty_all_vals), umbrales 0.45 / 0.90, min_active_weeks alineado al global.
#   - Escribe x_studio_xyz_local, x_studio_xyz_local_source, x_studio_active_weeks_local.
#   - Reintroduce lectura PARCIAL de x_calculo_abc_xyz: solo el campo abcxyz a
#     nivel global (team_id IS NULL) para heredar la letra XYZ del producto a
#     xyz_local cuando el calculo local cae a fallback. Esto preserva trazabilidad
#     (siempre hay un valor en xyz_local) sin reintroducir dependencia del ABC.
#   - ABC para politica de servicio sigue siendo lectura de Stock (archivo 3).
#     Solo la variabilidad XYZ se localiza por sucursal para corregir la asimetria
#     Z (global) x sigma (local) que sub o sobre-stockeaba SKUs cuyo comportamiento
#     local difiere del global.
#
# Patch v3.0.4 (mantenido):
#   - Forecast queda como motor de DEMANDA LOCAL.
#   - Mantiene calculo LOCAL de mu_week y sigma_week, share_of_pool, etc.
#
# Contrato:
#   Forecast entrega a Stock (modelo x_forecast_weekly_data):
#     product_id, local, week_start, mu_week, sigma_week, lead_weeks, moq,
#     supplier_id, share_of_pool, diagnosticos de senal,
#     xyz_local + xyz_local_source + active_weeks_local (nuevo en v3.0.5).
#   ABC global lo sigue leyendo Stock directo desde x_calculo_abc_xyz.
#
# Campos Studio requeridos en x_forecast_weekly_data para v3.0.5:
#   x_studio_xyz_local          Selection: X / Y / Z (vacio solo si tampoco hay
#                                 XYZ global heredado)
#   x_studio_xyz_local_source   Selection: local / global
#                                 - local : se uso la clasificacion local del team
#                                 - global: se heredo el XYZ global del producto
#                                           (sea por falta de historia local o
#                                           porque el calculo local quedo vacio)
#   x_studio_active_weeks_local Integer

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009435
GLOBAL_TEAM_NAME = 'General OH'


# ----------------------
# Parámetros
# ----------------------
XYZ_BASE_WEEKS_DEFAULT = 26      # semanas BASE target para cálculo μ/σ
XYZ_WEEKS_DEFAULT      = 26      # ventana calendario mínima (fallback)
HISTORY_MONTHS_DEFAULT = 24

LOCAL_CV_HIGH_THRESHOLD = 0.90  # Solo diagnóstico/lifecycle local; NO define XYZ oficial

HARD_RESET_DEFAULT = True

MIN_ACTIVE_WEEKS_DEFAULT = 4
MIN_MU_WEEK_DEFAULT      = 0.2

BATCH_SIZE = 500

FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

# ----------------------
# Parámetros trend / cash anchor
# ----------------------
MU_TREND_R2_MIN     = 0.15
MU_TREND_EXTRAP_CAP = 0.40
MU_TREND_F8V8_CAP   = 1.30
MU_TREND_F8V8_FLOOR = 0.77
MU_TREND_N_MIN      = 8
MU_TREND_SLOPE_CAP  = 0.05

# ----------------------
# Parámetros service demand (BASE short vs BASE long)
# ----------------------
SERVICE_BASE_SHORT_WEEKS_DEFAULT = 6
SERVICE_BASE_LONG_WEEKS_DEFAULT  = 16
SERVICE_RATIO_UP_DEFAULT         = 1.15
SERVICE_RATIO_HOLD_DEFAULT       = 0.90
SERVICE_DOWN_W_SHORT_DEFAULT     = 0.70
SERVICE_DOWN_W_LONG_DEFAULT      = 0.30

# ----------------------
# Parametros XYZ local por team
# ----------------------
# Clasificacion XYZ derivada de la serie local (qty_all_vals) del team usando
# el MISMO metodo del XYZ global (archivo 1): una sola pasada con CV simple
# sobre la ventana completa. Si active_weeks_local < MIN, xyz_local queda vacio
# y el consumidor (archivo 3) cae al XYZ global (source='global'). Umbrales
# identicos al global.
XYZ_LOCAL_MIN_WEEKS_DEFAULT   = 4     # alineado con MIN_ACTIVE_WEEKS del global
XYZ_LOCAL_T1_DEFAULT          = 0.45  # umbral X/Y del global
XYZ_LOCAL_T2_DEFAULT          = 0.90  # umbral Y/Z del global

# ----------------------
# Parámetros price event correction
# ----------------------
PRICE_EVENT_ENABLE_DEFAULT          = True
PRICE_EVENT_LOOKBACK_WEEKS_DEFAULT  = 12
PRICE_EVENT_PRE_BASE_WEEKS_DEFAULT  = 4
PRICE_EVENT_POST_BASE_WEEKS_DEFAULT = 4
PRICE_EVENT_MIN_WEEKS_DEFAULT       = 2
PRICE_EVENT_SIGNAL_UP_DEFAULT       = 1.08
PRICE_EVENT_SIGNAL_DOWN_DEFAULT     = 0.92
PRICE_EVENT_CAP_UP_DEFAULT          = 1.25
PRICE_EVENT_FLOOR_DOWN_DEFAULT      = 0.80

# ----------------------
# Bandas estacionales
# ----------------------
_SEASONAL_BAND = {}
for _w in list(range(10, 38)) + list(range(39, 44)) + list(range(45, 49)):
    _SEASONAL_BAND[_w] = 'BASE'
_SEASONAL_BAND[1] = 'VERANO_BAJO'
for _w in [2, 3, 4, 9]:
    _SEASONAL_BAND[_w] = 'VERANO_MEDIO'
for _w in [5, 6, 7, 8]:
    _SEASONAL_BAND[_w] = 'VERANO_ALTO'
_SEASONAL_BAND[38] = 'FIESTAS_PATRIAS'
_SEASONAL_BAND[44] = 'HALLOWEEN'
for _w in [49, 50, 51, 52]:
    _SEASONAL_BAND[_w] = 'FIN_ANIO'

_BASE_WEEKS_SET = set()
for _w_num, _w_band in _SEASONAL_BAND.items():
    if _w_band == 'BASE':
        _BASE_WEEKS_SET.add(_w_num)


def _is_base_week(iso_week):
    return iso_week in _BASE_WEEKS_SET or iso_week not in _SEASONAL_BAND


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



def _m2o_id(v):
    if not v:
        return False
    if isinstance(v, (list, tuple)):
        return _safe_int(v[0]) if v else False
    return _safe_int(v)


def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def _week_range(dfrom, dto):
    start = _week_start(dfrom)
    end   = _week_start(dto)
    weeks = []
    cur   = start
    while cur <= end:
        weeks.append(cur)
        cur += datetime.timedelta(weeks=1)
    return weeks or [start]


def _quarter_abs(d):
    return d.year * 4 + ((d.month - 1) // 3) + 1


def _infer_lifecycle(u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7, p_q8, local_volatility_high):
    u_rest = u_q1 + u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7
    u8     = u_q0 + u_rest
    if u8 <= 0:
        return 'dead'
    if p_q8 <= 2 and u_q1 <= 0:
        return 'intermittent'
    if u_q0 > 0 and u_rest <= 0:
        return 'new'
    if u_q0 <= 0 and (u_q1 + u_q2 + u_q3) > 0:
        return 'declining'
    if local_volatility_high and p_q8 <= 5:
        return 'seasonal'
    if u_q0 > 0 and u_q1 <= 0 and (u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7) > 0:
        return 'ramp_up'
    return 'mature'


def _calc_adi(qty_vals):
    intervals = []
    gap = 0
    for q in (qty_vals or []):
        if q > 0:
            intervals.append(gap + 1)
            gap = 0
        else:
            gap += 1
    if not intervals:
        return 999.0
    return sum(intervals) / len(intervals)


def _series_type(cv, density_pct, adi):
    den   = _safe_float(density_pct, 0.0)
    cv_v  = _safe_float(cv, 999.0)
    adi_v = _safe_float(adi, 999.0)
    if den < 0.05:
        return 'no_signal'
    cv2 = cv_v * cv_v
    if adi_v >= 1.32 and cv2 >= 0.49:
        return 'lumpy'
    if adi_v >= 1.32:
        return 'intermittent'
    if cv2 >= 0.49:
        return 'erratic'
    return 'smooth'


def _avg_std(vals):
    n = len(vals or [])
    if n <= 0:
        return 0.0, 0.0
    _sum = 0.0
    _sq  = 0.0
    for _v in vals:
        _x = _safe_float(_v, 0.0)
        _sum += _x
        _sq  += _x * _x
    mu = _sum / n
    var = (_sq / n) - mu * mu
    if var < 0.0:
        var = 0.0
    return mu, (var ** 0.5)


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


def _calc_mu_trend(qty_base_vals, n_base_weeks, ciclo_de_vida,
                   r2_min, extrap_cap, f8v8_cap, f8v8_floor, n_min, slope_cap):
    n = n_base_weeks
    if n < 4:
        return None, 'fallback_sin_historia'

    xm    = (n - 1) / 2.0
    _sum  = 0.0
    ss_xy = 0.0
    ss_xx = 0.0
    for _i in range(n):
        _q   = qty_base_vals[_i]
        _sum += _q
        _dx  = _i - xm
        ss_xy += _dx * _q
        ss_xx += _dx * _dx

    mu_sma = _sum / n

    if ciclo_de_vida == 'dead':
        return mu_sma, 'sma_dead'
    if ss_xx <= 0:
        return mu_sma, 'sma_ss_zero'

    b1 = ss_xy / ss_xx
    b0 = mu_sma - b1 * xm

    ss_res = 0.0
    ss_tot = 0.0
    for _i in range(n):
        _q    = qty_base_vals[_i]
        _pred = b0 + b1 * _i
        _err  = _q - _pred
        ss_res += _err * _err
        _d    = _q - mu_sma
        ss_tot += _d * _d

    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    if r2 < 0.0:
        r2 = 0.0

    _f8v8_mu     = None
    _f8v8_factor = None
    _f8v8_f_raw  = None
    _f8v8_status = None
    if n >= n_min:
        _sum_rec = 0.0
        for _q in qty_base_vals[-8:]:
            _sum_rec += _q
        _sma_rec = _sum_rec / 8.0
        _sum_ant = 0.0
        for _q in qty_base_vals[-16:-8]:
            _sum_ant += _q
        _sma_ant = _sum_ant / 8.0
        if _sma_ant > 0:
            _f8v8_f_raw  = _sma_rec / _sma_ant
            _f8v8_factor = (f8v8_floor if _f8v8_f_raw < f8v8_floor
                            else f8v8_cap if _f8v8_f_raw > f8v8_cap
                            else _f8v8_f_raw)
            _f8v8_mu     = mu_sma * _f8v8_factor
            _f8v8_status = 'capped' if abs(_f8v8_factor - _f8v8_f_raw) > 0.001 else 'ok'

    _extrap_mu  = b0 + b1 * n
    if _extrap_mu < 0.0:
        _extrap_mu = 0.0
    _cap_hi = mu_sma * (1.0 + extrap_cap)
    _cap_lo = mu_sma * (1.0 - extrap_cap)
    if _cap_lo < 0.0:
        _cap_lo = 0.0
    if _extrap_mu < _cap_lo:
        _extrap_adj = _cap_lo
        _extrap_st  = 'capped'
    elif _extrap_mu > _cap_hi:
        _extrap_adj = _cap_hi
        _extrap_st  = 'capped'
    else:
        _extrap_adj = _extrap_mu
        _extrap_st  = 'ok'

    if ciclo_de_vida == 'declining':
        if r2 >= r2_min and b1 < 0:
            pend_rel = abs(b1) / mu_sma if mu_sma > 0 else 0.0
            if pend_rel > slope_cap:
                return mu_sma, 'sma_declining_slope_guard_' + str(round(pend_rel * 100, 1)) + 'pct'
            return _extrap_adj, 'linreg_declining_' + _extrap_st + '_R2=' + str(round(r2, 2)) + '_b1=' + str(round(b1, 3))
        return mu_sma, 'sma_declining_R2=' + str(round(r2, 2))

    if r2 >= r2_min:
        if b1 < 0:
            pend_rel = abs(b1) / mu_sma if mu_sma > 0 else 0.0
            if pend_rel > slope_cap:
                if _f8v8_mu is not None:
                    return _f8v8_mu, 'f8v8_slope_guard_' + _f8v8_status + '_' + str(round(pend_rel * 100, 1)) + 'pct_f=' + str(round(_f8v8_factor, 3))
                return mu_sma, 'sma_slope_guard_' + str(round(pend_rel * 100, 1)) + 'pct'
        return _extrap_adj, 'linreg_' + _extrap_st + '_R2=' + str(round(r2, 2)) + '_b1=' + str(round(b1, 3))

    if _f8v8_mu is not None:
        return _f8v8_mu, 'f8v8_' + _f8v8_status + '_f=' + str(round(_f8v8_factor, 3)) + '_raw=' + str(round(_f8v8_f_raw, 3))

    return mu_sma, 'sma_puro_R2=' + str(round(r2, 2))


# ----------------------
# Context
# ----------------------
CTX = env.context or {}

HARD_RESET       = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
XYZ_BASE_WEEKS   = int(CTX.get('xyz_base_weeks', XYZ_BASE_WEEKS_DEFAULT))
XYZ_WEEKS        = int(CTX.get('xyz_weeks', XYZ_WEEKS_DEFAULT))
HIST_MONTHS      = int(CTX.get('history_months', HISTORY_MONTHS_DEFAULT))
MIN_ACTIVE_WEEKS = int(CTX.get('min_active_weeks', MIN_ACTIVE_WEEKS_DEFAULT))
MIN_MU_WEEK      = float(CTX.get('min_mu_week', MIN_MU_WEEK_DEFAULT))

SERVICE_BASE_SHORT_WEEKS = int(CTX.get('service_base_short_weeks', SERVICE_BASE_SHORT_WEEKS_DEFAULT))
SERVICE_BASE_LONG_WEEKS  = int(CTX.get('service_base_long_weeks',  SERVICE_BASE_LONG_WEEKS_DEFAULT))
SERVICE_RATIO_UP         = float(CTX.get('service_ratio_up',       SERVICE_RATIO_UP_DEFAULT))
SERVICE_RATIO_HOLD       = float(CTX.get('service_ratio_hold',     SERVICE_RATIO_HOLD_DEFAULT))
SERVICE_DOWN_W_SHORT     = float(CTX.get('service_down_w_short',   SERVICE_DOWN_W_SHORT_DEFAULT))
SERVICE_DOWN_W_LONG      = float(CTX.get('service_down_w_long',    SERVICE_DOWN_W_LONG_DEFAULT))

XYZ_LOCAL_MIN_WEEKS = int(CTX.get('xyz_local_min_weeks', XYZ_LOCAL_MIN_WEEKS_DEFAULT))
XYZ_LOCAL_T1 = float(CTX.get('xyz_local_t1', XYZ_LOCAL_T1_DEFAULT))
XYZ_LOCAL_T2 = float(CTX.get('xyz_local_t2', XYZ_LOCAL_T2_DEFAULT))

PRICE_EVENT_ENABLE          = bool(CTX.get('price_event_enable', PRICE_EVENT_ENABLE_DEFAULT))
PRICE_EVENT_LOOKBACK_WEEKS  = int(CTX.get('price_event_lookback_weeks',  PRICE_EVENT_LOOKBACK_WEEKS_DEFAULT))
PRICE_EVENT_PRE_BASE_WEEKS  = int(CTX.get('price_event_pre_base_weeks',  PRICE_EVENT_PRE_BASE_WEEKS_DEFAULT))
PRICE_EVENT_POST_BASE_WEEKS = int(CTX.get('price_event_post_base_weeks', PRICE_EVENT_POST_BASE_WEEKS_DEFAULT))
PRICE_EVENT_MIN_WEEKS       = int(CTX.get('price_event_min_weeks', PRICE_EVENT_MIN_WEEKS_DEFAULT))
PRICE_EVENT_SIGNAL_UP       = float(CTX.get('price_event_signal_up',   PRICE_EVENT_SIGNAL_UP_DEFAULT))
PRICE_EVENT_SIGNAL_DOWN     = float(CTX.get('price_event_signal_down', PRICE_EVENT_SIGNAL_DOWN_DEFAULT))
PRICE_EVENT_CAP_UP          = float(CTX.get('price_event_cap_up',      PRICE_EVENT_CAP_UP_DEFAULT))
PRICE_EVENT_FLOOR_DOWN      = float(CTX.get('price_event_floor_down',  PRICE_EVENT_FLOOR_DOWN_DEFAULT))
TEAM_IDS                    = _to_int_list(CTX.get('team_ids'))
if not TEAM_IDS:
    TEAM_IDS = list(FILTERED_TEAM_IDS_DEFAULT)

company     = env.company
FWD         = env['x_forecast_weekly_data'].sudo()
ProductTmpl = env['product.template'].sudo()
fwd_fields  = FWD._fields or {}
pt_fields   = ProductTmpl._fields or {}

# v3.0.5: validar campos Studio nuevos para XYZ local. Si faltan, los datos
# de xyz_local NO se persisten (filtrados silenciosamente en el write batched).
# El resto del forecast sigue funcionando; solo se pierde info de variabilidad.
_xyz_local_required = (
    'x_studio_xyz_local',
    'x_studio_xyz_local_source',
    'x_studio_active_weeks_local',
)
_xyz_local_missing = [f for f in _xyz_local_required if f not in fwd_fields]

global_team = env['crm.team'].sudo().search([('name', '=', GLOBAL_TEAM_NAME)], limit=1)
GLOBAL_TEAM_ID = global_team.id if global_team else False

# ----------------------
# Lock
# ----------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
locked = env.cr.fetchone()[0]

if not locked:
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'FWD LOCAL',
            'message': 'Otro proceso FWD LOCAL está ejecutándose. Reintenta.',
            'type': 'warning',
            'sticky': False,
        }
    }
else:
    try:
        purge_count = 0
        if HARD_RESET:
            if TEAM_IDS:
                old_domain = [('x_studio_local', 'in', TEAM_IDS)]
            else:
                old_domain = [('x_studio_local', '!=', False)]
                if GLOBAL_TEAM_ID:
                    old_domain.append(('x_studio_local', '!=', GLOBAL_TEAM_ID))
            old = FWD.search(old_domain)
            purge_count = len(old)
            if old:
                old.unlink()

        env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
        today_local = env.cr.fetchone()[0]

        _current_week_start = _week_start(today_local)
        _last_closed_week_end = _current_week_start - datetime.timedelta(days=1)

        date_to_ctx = CTX.get('date_to')
        if date_to_ctx:
            try:
                _dt_raw = datetime.datetime.fromisoformat(str(date_to_ctx)).date()
                date_to = _week_start(_dt_raw) + datetime.timedelta(days=6)
                if date_to >= _current_week_start:
                    date_to = _last_closed_week_end
            except Exception:
                date_to = _last_closed_week_end
        else:
            date_to = _last_closed_week_end

        env.cr.execute(
            "SELECT (date_trunc('month', %s::date)::date - (%s || ' months')::interval)::date",
            (date_to, HIST_MONTHS)
        )
        history_from = env.cr.fetchone()[0]

        xyz_from_min    = date_to - datetime.timedelta(weeks=XYZ_WEEKS)
        _week_start_dto = _week_start(date_to)
        _base_count     = 0
        _cur            = _week_start_dto + datetime.timedelta(weeks=1)
        _xyz_from_dyn   = _week_start_dto
        while _base_count < XYZ_BASE_WEEKS:
            _cur = _cur - datetime.timedelta(weeks=1)
            if _cur < history_from:
                break
            if _is_base_week(_cur.isocalendar()[1]):
                _base_count += 1
            _xyz_from_dyn = _cur

        xyz_from       = min(xyz_from_min, _xyz_from_dyn)
        xyz_weeks_list = _week_range(xyz_from, date_to)
        all_weeks_list = _week_range(history_from, date_to)

        q_now_abs = _quarter_abs(date_to)

        _week_to_q_offset = {}
        for _wk in all_weeks_list:
            _off = q_now_abs - _quarter_abs(_wk)
            if 0 <= _off <= 7:
                _week_to_q_offset[_wk] = _off

        _xyz_base_week_dates = set()
        for _wk in xyz_weeks_list:
            if _is_base_week(_wk.isocalendar()[1]):
                _xyz_base_week_dates.add(_wk)

        master_domain  = [('sale_ok', '=', True), ('active', '=', True)]
        combo_tmpl_ids = set()

        if pt_fields.get('detailed_type'):
            combo_tmpl_ids = set(ProductTmpl.search([
                ('sale_ok', '=', True), ('active', '=', True),
                ('detailed_type', '=', 'combo'),
            ]).ids)
            master_domain.append(('detailed_type', 'not in', ['service', 'combo']))
        elif pt_fields.get('type'):
            master_domain.append(('type', '!=', 'service'))

        active_tmpl_ids = set(ProductTmpl.search(master_domain).ids)
        all_tmpl_ids    = list(active_tmpl_ids)

        if not all_tmpl_ids:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'FWD LOCAL',
                    'message': 'No hay productos activos/vendibles.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        else:
            tmpl_tuple = tuple(all_tmpl_ids)

            env.cr.execute("""
                SELECT DISTINCT ON (pp.product_tmpl_id)
                    pp.product_tmpl_id,
                    pp.id AS product_id,
                    pt.categ_id
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE pp.product_tmpl_id IN %s
                  AND pp.active = TRUE
                ORDER BY pp.product_tmpl_id, pp.id
            """, (tmpl_tuple,))
            tmpl_to_variant = {}
            tmpl_to_categ   = {}
            for tmpl_id, pp_id, categ_id in env.cr.fetchall():
                tmpl_to_variant[tmpl_id] = pp_id
                tmpl_to_categ[tmpl_id]   = categ_id

            # Forecast no lee ABC/XYZ. Clasificación queda fuera de este modelo.

            dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

            pc_fields = env['pos.config']._fields or {}
            team_col_sql = None
            try:
                _f = pc_fields.get('crm_team_id')
                if _f and (_f.type == 'many2one') and (_f.comodel_name == 'crm.team'):
                    team_col_sql = 'pc.crm_team_id'
            except Exception:
                team_col_sql = team_col_sql
            if not team_col_sql:
                try:
                    _f = pc_fields.get('team_id')
                    if _f and (_f.type == 'many2one') and (_f.comodel_name == 'crm.team'):
                        team_col_sql = 'pc.team_id'
                except Exception:
                    team_col_sql = team_col_sql

            if not team_col_sql:
                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'FWD LOCAL',
                        'message': 'No se encontró crm_team_id/team_id válido en pos.config.',
                        'type': 'danger',
                        'sticky': True,
                    }
                }
            else:
                team_filter_sql = ''
                if TEAM_IDS:
                    team_filter_sql = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '

                sql_sales = f"""
                WITH base AS (
                    SELECT
                        {team_col_sql} AS team_id,
                        pol.id AS line_id,
                        pol.combo_parent_id,
                        pt.id AS tmpl_id,
                        {dtype_sql} AS dtype,
                        date_trunc('week',
                            po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s
                        )::date AS week,
                        COALESCE(pol.qty, 0.0)            AS qty,
                        COALESCE(pol.price_subtotal, 0.0) AS line_rev
                    FROM pos_order_line pol
                    JOIN pos_order po        ON po.id  = pol.order_id
                    LEFT JOIN pos_session ps ON ps.id = po.session_id
                    LEFT JOIN pos_config pc  ON pc.id = ps.config_id
                    JOIN product_product pp  ON pp.id  = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE po.company_id = %(company_id)s
                      AND po.state IN ('paid','done','invoiced')
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(history_from)s
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                      AND pt.sale_ok = TRUE
                      AND pt.active  = TRUE
                      AND {team_col_sql} IS NOT NULL
                      {team_filter_sql}
                ),
                standalone AS (
                    SELECT team_id, tmpl_id, week,
                           SUM(line_rev) AS net_revenue,
                           SUM(qty)      AS units
                    FROM base
                    WHERE combo_parent_id IS NULL
                      AND COALESCE(dtype,'') NOT IN ('combo','service')
                    GROUP BY 1,2,3
                ),
                combo_child_pre AS (
                    SELECT c.team_id, c.line_id, c.combo_parent_id,
                           c.tmpl_id, c.week, c.qty,
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
                ),
                combo_parent_stats AS (
                    SELECT team_id, combo_parent_id,
                           SUM(weight_value) AS weight_sum,
                           COUNT(*) AS child_count,
                           SUM(CASE WHEN ABS(child_rev) > 0.00001 THEN 1 ELSE 0 END) AS priced_child_count
                    FROM combo_child_pre GROUP BY 1,2
                ),
                combo_children AS (
                    SELECT c.team_id, c.tmpl_id, c.week,
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
                    JOIN combo_parent_stats s ON s.combo_parent_id = c.combo_parent_id AND s.team_id = c.team_id
                    GROUP BY 1,2,3
                )
                SELECT team_id, tmpl_id, week,
                       SUM(net_revenue) AS net_revenue,
                       SUM(units)       AS units
                FROM (SELECT * FROM standalone UNION ALL SELECT * FROM combo_children) su
                GROUP BY 1,2,3
                """

                _sql_params = {
                    'company_id':   company.id,
                    'history_from': history_from,
                    'date_to':      date_to,
                    'tz':           TZ_NAME,
                }
                if TEAM_IDS:
                    _sql_params['team_ids'] = TEAM_IDS

                env.cr.execute(sql_sales, _sql_params)

                data = {}
                team_ids_found = set()
                for team_id, tmpl_id, wk, rev, qty in env.cr.fetchall():
                    team_i = _safe_int(team_id)
                    tid = _safe_int(tmpl_id)
                    if (not team_i) or (tid not in active_tmpl_ids):
                        continue
                    team_ids_found.add(team_i)
                    key = (team_i, tid)
                    if key not in data:
                        data[key] = {}
                    w = data[key].get(wk)
                    if w:
                        w[0] += _safe_float(rev)
                        w[1] += _safe_float(qty)
                    else:
                        data[key][wk] = [_safe_float(rev), _safe_float(qty)]

                local_pairs = sorted(data.keys())

                if not local_pairs:
                    action = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': 'FWD LOCAL',
                            'message': 'No hay ventas POS con sucursal en el rango.',
                            'type': 'warning',
                            'sticky': False,
                        }
                    }

                _iso_week_today = date_to.isocalendar()[1]
                _banda_today    = _SEASONAL_BAND.get(_iso_week_today, 'BASE')

                supplier_lead_map    = {}
                supplier_moq_map     = {}
                supplier_partner_map = {}
                uom_po_factor_map    = {}

                try:
                    env.cr.execute("""
                        SELECT DISTINCT ON (si.product_tmpl_id)
                            si.product_tmpl_id,
                            COALESCE(si.delay,   7.0) AS lead_days,
                            COALESCE(si.min_qty, 1.0) AS min_qty,
                            si.partner_id              AS partner_id
                        FROM product_supplierinfo si
                        WHERE (si.company_id IS NULL OR si.company_id = %s)
                          AND si.product_tmpl_id IS NOT NULL
                        ORDER BY si.product_tmpl_id, si.sequence, si.min_qty, si.id
                    """, (company.id,))
                    for _tid, _lead_days, _min_qty, _partner_id in env.cr.fetchall():
                        _tid_i  = _safe_int(_tid)
                        _lead_w = max(_safe_float(_lead_days, 7.0) / 7.0, 0.5)
                        supplier_lead_map[_tid_i]    = _lead_w
                        supplier_moq_map[_tid_i]     = max(_safe_float(_min_qty, 1.0), 1.0)
                        supplier_partner_map[_tid_i] = _safe_int(_partner_id, 0) or False
                except Exception:
                    pass

                env.cr.execute("""
                    SELECT pt.id,
                           COALESCE(uu.uom_type, 'reference') AS uom_type,
                           COALESCE(uu.factor, 1.0)           AS uom_factor
                    FROM product_template pt
                    LEFT JOIN uom_uom uu ON uu.id = pt.uom_po_id
                    WHERE pt.id IN %s
                """, (tmpl_tuple,))
                for _tid, _uom_type, _uom_factor in env.cr.fetchall():
                    _f = _safe_float(_uom_factor, 1.0)
                    if _uom_type == 'bigger' and _f > 0.0 and _f < 1.0:
                        _moq_from_uom = round(1.0 / _f)
                    elif _uom_type == 'bigger' and _f >= 1.0:
                        _moq_from_uom = round(_f)
                    else:
                        _moq_from_uom = 1
                    uom_po_factor_map[_safe_int(_tid)] = float(_moq_from_uom) if _moq_from_uom > 1 else 1.0

                # Stock global solo para contexto / compatibilidad de basis.
                # share_of_pool LOCAL se calcula aparte por team.
                stock_physical_map   = {}
                stock_basis_map      = {}
                variant_stock_map    = {}
                single_comp_pool_rels = []

                env.cr.execute("""
                    SELECT pp.id, pp.product_tmpl_id,
                           SUM(COALESCE(sq.quantity,0.0) - COALESCE(sq.reserved_quantity,0.0))
                    FROM stock_quant sq
                    JOIN stock_location sl ON sl.id = sq.location_id
                    JOIN product_product pp ON pp.id = sq.product_id
                    WHERE sl.usage = 'internal' AND sq.company_id = %s
                    GROUP BY pp.id, pp.product_tmpl_id
                    HAVING ABS(SUM(COALESCE(sq.quantity,0.0) - COALESCE(sq.reserved_quantity,0.0))) > 0.00001
                """, (company.id,))
                for _ppid, _tid, _sq in env.cr.fetchall():
                    _ppid_i = _safe_int(_ppid)
                    _tid_i  = _safe_int(_tid)
                    _qty    = _safe_float(_sq, 0.0)
                    if _tid_i not in active_tmpl_ids:
                        continue
                    variant_stock_map[_ppid_i] = _qty
                    stock_physical_map[_tid_i] = stock_physical_map.get(_tid_i, 0.0) + _qty
                    stock_basis_map[_tid_i]    = 'direct'

                try:
                    Bom = env['mrp.bom'].sudo()
                    bom_fields = Bom._fields or {}
                    bom_domain = [('type', '=', 'phantom')]
                    if bom_fields.get('active'):
                        bom_domain.append(('active', '=', True))
                    if bom_fields.get('company_id'):
                        bom_domain += ['|', ('company_id', '=', False), ('company_id', '=', company.id)]

                    selected_bom = {}
                    for bom in Bom.search(bom_domain, order='sequence, id'):
                        _tmpl_id = (bom.product_tmpl_id.id if bom.product_tmpl_id
                                    else (bom.product_id.product_tmpl_id.id if bom.product_id else False))
                        if not _tmpl_id or _tmpl_id not in active_tmpl_ids or _tmpl_id in selected_bom:
                            continue
                        selected_bom[_tmpl_id] = bom

                    for _tmpl_id, bom in selected_bom.items():
                        _bom_qty   = max(_safe_float(bom.product_qty, 1.0), 0.001)
                        _min_kits  = None
                        _valid     = 0
                        for line in bom.bom_line_ids:
                            comp     = line.product_id
                            comp_qty = _safe_float(line.product_qty, 0.0)
                            if not comp or comp_qty <= 0.0:
                                continue
                            _valid += 1
                            kits = (variant_stock_map.get(comp.id, 0.0) / comp_qty) * _bom_qty
                            if _min_kits is None or kits < _min_kits:
                                _min_kits = kits
                        if _valid <= 0:
                            continue
                        stock_basis_map[_tmpl_id] = 'kit_phantom'
                        if _valid == 1:
                            _line0 = bom.bom_line_ids[:1]
                            if _line0:
                                _comp0    = _line0[0].product_id
                                _cq0      = _safe_float(_line0[0].product_qty, 0.0)
                                if _comp0 and _cq0 > 0.0:
                                    _child_tmpl = _comp0.product_tmpl_id.id
                                    _factor     = _cq0 / _bom_qty
                                    if _child_tmpl and _factor > 0.0:
                                        single_comp_pool_rels.append({
                                            'parent_tmpl_id': _tmpl_id,
                                            'child_tmpl_id':  _child_tmpl,
                                            'factor_to_base': _factor,
                                        })
                    
                except Exception:
                    pass

                # -------------------------------------------------
                # SHARE OF POOL LOCAL (PATCH)
                # -------------------------------------------------
                # Default por fila: 1.0
                share_of_pool_map_local = {}
                stock_basis_map_local   = {}
                for _team_id, _tmpl_id in local_pairs:
                    share_of_pool_map_local[(_team_id, _tmpl_id)] = 1.0
                    stock_basis_map_local[(_team_id, _tmpl_id)] = stock_basis_map.get(_tmpl_id, 'direct')

                # Lógica histórica: SOLO pool compartido 1-componente.
                # A diferencia de v3.0.1, aquí se calcula por sucursal.
                if single_comp_pool_rels:
                    for _rel in single_comp_pool_rels:
                        _parent = _rel['parent_tmpl_id']
                        _child  = _rel['child_tmpl_id']
                        _factor = _safe_float(_rel.get('factor_to_base'), 0.0)
                        if _factor <= 0.0:
                            continue

                        for _team_id in team_ids_found:
                            _pw = data.get((_team_id, _parent)) or {}
                            _cw = data.get((_team_id, _child))  or {}

                            # No hay mezcla en esa sucursal
                            if (not _pw) and (not _cw):
                                continue

                            _peq = 0.0
                            _ceq = 0.0
                            for _wk in xyz_weeks_list:
                                _pr = _pw.get(_wk)
                                _cr = _cw.get(_wk)
                                if _pr:
                                    _peq += _safe_float(_pr[1], 0.0) * _factor
                                if _cr:
                                    _ceq += _safe_float(_cr[1], 0.0)

                            _teq = _peq + _ceq
                            if _teq <= 0.0:
                                continue

                            _sp = max(min(_peq / _teq, 1.0), 0.0)
                            _sc = max(min(_ceq / _teq, 1.0), 0.0)

                            share_of_pool_map_local[(_team_id, _parent)] = _sp
                            share_of_pool_map_local[(_team_id, _child)]  = _sc
                            stock_basis_map_local[(_team_id, _parent)]   = 'shared_pool_mix'
                            stock_basis_map_local[(_team_id, _child)]    = 'shared_pool_mix'

                price_event_map = {}
                if PRICE_EVENT_ENABLE:
                    try:
                        _px_from = _week_start(date_to) - datetime.timedelta(weeks=PRICE_EVENT_LOOKBACK_WEEKS)
                        env.cr.execute("""
                            SELECT DISTINCT ON (x_studio_product_id)
                                x_studio_product_id,
                                x_studio_period_start,
                                x_studio_direction,
                                x_studio_delta_pct,
                                x_studio_support_weeks
                            FROM x_price_change_event
                            WHERE x_studio_company_id = %s
                              AND COALESCE(x_studio_is_real_change, FALSE) IS TRUE
                              AND x_studio_product_id IN %s
                              AND x_studio_period_start >= %s
                              AND x_studio_period_start <= %s
                            ORDER BY x_studio_product_id, x_studio_period_start DESC, id DESC
                        """, (company.id, tmpl_tuple, _px_from, date_to))
                        for _tid, _evt_week, _evt_dir, _evt_dpct, _evt_support in env.cr.fetchall():
                            price_event_map[_safe_int(_tid)] = {
                                'event_week': _evt_week,
                                'direction': _evt_dir or '',
                                'delta_pct': _safe_float(_evt_dpct, 0.0),
                                'support_weeks': _safe_int(_evt_support, 0),
                                'flag': True,
                            }
                    except Exception:
                        price_event_map = {}

                pt_create_date_map = {}
                env.cr.execute("""
                    SELECT pt.id,
                           (pt.create_date AT TIME ZONE 'UTC' AT TIME ZONE %s)::date
                    FROM product_template pt
                    WHERE pt.id IN %s
                """, (TZ_NAME, tmpl_tuple))
                for _tid, _cdt in env.cr.fetchall():
                    pt_create_date_map[_safe_int(_tid)] = _cdt or False

                # v3.0.5: lectura del XYZ global desde x_calculo_abc_xyz para
                # heredarlo a xyz_local cuando el calculo local cae a fallback.
                # El ABCXYZ del producto es global (una fila por SKU, sin team).
                # Usa ORM para tolerar columnas Studio inexistentes en otras
                # instancias y savepoint para que cualquier error no aborte la
                # transaccion principal del forecast.
                xyz_global_by_tmpl = {}
                env.cr.execute('SAVEPOINT xyz_global_lookup')
                try:
                    Abc = env['x_calculo_abc_xyz'].sudo()
                    abc_fields_map = Abc._fields or {}
                    abc_domain = []
                    if abc_fields_map.get('x_studio_company_id'):
                        abc_domain.append(('x_studio_company_id', '=', company.id))
                    # Solo filtra por team si la columna existe Y el archivo 1
                    # poblara filas por team en el futuro. Hoy todas las filas
                    # son globales (team_id=False), pero el filtro defensivo
                    # garantiza que tomamos solo las globales si llegara a haber
                    # filas por team mas adelante.
                    if abc_fields_map.get('x_studio_team_id'):
                        abc_domain.append(('x_studio_team_id', '=', False))

                    # Invertir tmpl_to_variant: pp_id -> tmpl_id
                    _variant_to_tmpl = {pp: tid for tid, pp in tmpl_to_variant.items()}

                    abc_records = Abc.search(abc_domain).read([
                        'x_studio_product_id',
                        'x_studio_abcxyz',
                    ])
                    for _r in abc_records:
                        _pp_field = _r.get('x_studio_product_id')
                        if not _pp_field:
                            continue
                        _pp_id = _pp_field[0] if isinstance(_pp_field, (list, tuple)) else _pp_field
                        _tmpl_id = _variant_to_tmpl.get(_safe_int(_pp_id))
                        if not _tmpl_id:
                            continue
                        _s = (_r.get('x_studio_abcxyz') or '').strip().upper()
                        if len(_s) == 2 and _s[1] in ('X', 'Y', 'Z'):
                            xyz_global_by_tmpl[_tmpl_id] = _s[1]
                    env.cr.execute('RELEASE SAVEPOINT xyz_global_lookup')
                except Exception:
                    env.cr.execute('ROLLBACK TO SAVEPOINT xyz_global_lookup')
                    xyz_global_by_tmpl = {}

                batch         = []
                total_created = 0
                service_short_count = 0
                service_long_count  = 0
                service_blend_count = 0
                service_fallback_count = 0
                price_event_adj_count = 0
                pool_local_adj_count  = 0
                # v3.0.5: contadores distribucion XYZ local por team
                # 'global' = cayo al fallback global (sin datos o calculo vacio)
                xyz_local_counts = {'X': 0, 'Y': 0, 'Z': 0, 'global': 0}

                for _k, _v in share_of_pool_map_local.items():
                    if abs(_safe_float(_v, 1.0) - 1.0) > 0.0001:
                        pool_local_adj_count += 1

                _fwd_create = FWD.with_context(
                    tracking_disable=True,
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                    mail_notrack=True,
                ).create

                for team_id, tmpl_id in local_pairs:
                    pp_id    = tmpl_to_variant.get(tmpl_id)
                    categ_id = tmpl_to_categ.get(tmpl_id)
                    if not pp_id:
                        continue

                    wkmap = data.get((team_id, tmpl_id)) or {}
                    create_date_local = pt_create_date_map.get(tmpl_id) or date_to

                    first_sale_week = None
                    for wk0 in all_weeks_list:
                        row0 = wkmap.get(wk0)
                        if row0 and (row0[1] > 0.0 or abs(row0[0]) > 0.00001):
                            first_sale_week = wk0
                            break

                    age_anchor = create_date_local
                    if first_sale_week and first_sale_week < age_anchor:
                        age_anchor = first_sale_week

                    age_days  = (date_to - age_anchor).days if age_anchor else 0
                    age_weeks = max(age_days // 7 + 1, 1)

                    sum_qty_base = 0.0
                    sum_sq_base  = 0.0
                    sum_qty_all  = 0.0
                    sum_sq_all   = 0.0
                    active_wks   = 0
                    qty_base_vals = []
                    qty_all_vals  = []
                    n_base_weeks  = 0
                    total_units_xyz = 0.0
                    total_rev_xyz   = 0.0
                    orders_count    = 0

                    weeks_for_xyz = max(min(XYZ_WEEKS, age_weeks), 1)

                    for wk in xyz_weeks_list:
                        row = wkmap.get(wk)
                        q   = row[1] if row else 0.0
                        r   = row[0] if row else 0.0
                        qty_all_vals.append(q)
                        sum_qty_all     += q
                        sum_sq_all      += q * q
                        total_units_xyz += q
                        total_rev_xyz   += r
                        if q > 0:
                            active_wks   += 1
                            orders_count += 1
                        if wk in _xyz_base_week_dates:
                            qty_base_vals.append(q)
                            sum_qty_base += q
                            sum_sq_base  += q * q
                            n_base_weeks += 1

                    if n_base_weeks >= 4:
                        mu_sma_base = sum_qty_base / n_base_weeks
                        var_base    = (sum_sq_base / n_base_weeks) - mu_sma_base * mu_sma_base
                        if var_base < 0.0:
                            var_base = 0.0
                    else:
                        mu_sma_base = sum_qty_all / weeks_for_xyz if weeks_for_xyz > 0 else 0.0
                        var_base    = ((sum_sq_all / weeks_for_xyz) - mu_sma_base * mu_sma_base
                                       if weeks_for_xyz > 0 else 0.0)
                        if var_base < 0.0:
                            var_base = 0.0

                    sigma_base = var_base ** 0.5

                    avg_all = sum_qty_all / weeks_for_xyz if weeks_for_xyz > 0 else 0.0
                    var_all = ((sum_sq_all / weeks_for_xyz) - avg_all * avg_all
                               if weeks_for_xyz > 0 else 0.0)
                    if var_all < 0.0:
                        var_all = 0.0
                    std_all     = var_all ** 0.5
                    avg_nonzero = (total_units_xyz / active_wks) if active_wks > 0 else 0.0
                    cv_base     = (sigma_base / mu_sma_base) if mu_sma_base > 0 else 999.0
                    cv_all      = (std_all / avg_all) if avg_all > 0 else 999.0

                    # XYZ local: mismo metodo que el global (archivo 1) pero sobre la
                    # serie del team (qty_all_vals). Una sola pasada CV simple.
                    # Si active_wks < MIN o el calculo queda vacio, se hereda el XYZ
                    # global del producto (segunda letra de su abcxyz) y se marca
                    # source='global' para trazabilidad. Si el global tampoco existe,
                    # xyz_local queda vacio y archivo 3 fuerza CZ (regla anti-blanco).
                    _global_xyz_for_sku = xyz_global_by_tmpl.get(tmpl_id, '')
                    if active_wks < XYZ_LOCAL_MIN_WEEKS:
                        xyz_local        = _global_xyz_for_sku
                        xyz_local_source = 'global'
                    else:
                        _xyz_calc = _xyz_from_serie(qty_all_vals, XYZ_LOCAL_T1, XYZ_LOCAL_T2)
                        if _xyz_calc:
                            xyz_local        = _xyz_calc
                            xyz_local_source = 'local'
                        else:
                            xyz_local        = _global_xyz_for_sku
                            xyz_local_source = 'global'
                    if xyz_local in ('X', 'Y', 'Z'):
                        xyz_local_counts[xyz_local] += 1
                    else:
                        xyz_local_counts['global'] += 1

                    # Volatilidad local solo para diagnóstico/lifecycle.
                    # No se escribe ABC/XYZ en Forecast.
                    if mu_sma_base < MIN_MU_WEEK or active_wks < MIN_ACTIVE_WEEKS:
                        local_volatility_high = True
                    elif cv_base > LOCAL_CV_HIGH_THRESHOLD:
                        local_volatility_high = True
                    else:
                        local_volatility_high = False

                    _u_q = [0.0] * 8
                    for _wk, _row in wkmap.items():
                        _qty_val = _safe_float(_row[1], 0.0)
                        if _qty_val > 0.0:
                            _off = _week_to_q_offset.get(_wk)
                            if _off is not None:
                                _u_q[_off] += _qty_val

                    _p_q8 = 0
                    for _u in _u_q:
                        if _u > 0.0:
                            _p_q8 += 1

                    ciclo_pre = _infer_lifecycle(
                        _u_q[0], _u_q[1], _u_q[2], _u_q[3],
                        _u_q[4], _u_q[5], _u_q[6], _u_q[7],
                        _p_q8, local_volatility_high
                    )

                    _use_base = n_base_weeks >= 4
                    _mu_adj_cash, _trend_method_cash = _calc_mu_trend(
                        qty_base_vals if _use_base else qty_all_vals,
                        n_base_weeks  if _use_base else weeks_for_xyz,
                        ciclo_pre,
                        MU_TREND_R2_MIN,
                        MU_TREND_EXTRAP_CAP,
                        MU_TREND_F8V8_CAP,
                        MU_TREND_F8V8_FLOOR,
                        MU_TREND_N_MIN,
                        MU_TREND_SLOPE_CAP,
                    )
                    mu_week_cash    = _mu_adj_cash if _mu_adj_cash is not None else mu_sma_base
                    sigma_week_cash = sigma_base

                    sma_base_6       = 0.0
                    sigma_base_6     = 0.0
                    sma_base_16      = 0.0
                    sigma_base_16    = 0.0
                    ratio_base_6_16  = 0.0

                    mu_week_service    = mu_week_cash
                    sigma_week_service = sigma_week_cash
                    mu_service_method  = 'cash_fallback|' + (_trend_method_cash or '')

                    if n_base_weeks >= SERVICE_BASE_LONG_WEEKS:
                        _short_vals = qty_base_vals[-SERVICE_BASE_SHORT_WEEKS:]
                        _long_vals  = qty_base_vals[-SERVICE_BASE_LONG_WEEKS:]

                        sma_base_6,  sigma_base_6  = _avg_std(_short_vals)
                        sma_base_16, sigma_base_16 = _avg_std(_long_vals)

                        if sma_base_16 > 0.0:
                            ratio_base_6_16 = sma_base_6 / sma_base_16
                        else:
                            ratio_base_6_16 = 9.99 if sma_base_6 > 0.0 else 1.0

                        if ratio_base_6_16 >= SERVICE_RATIO_UP:
                            mu_week_service    = sma_base_6
                            sigma_week_service = sigma_base_6
                            mu_service_method  = (
                                'svc_sma6_base'
                                + '|ratio=' + str(round(ratio_base_6_16, 3))
                                + '|sma6=' + str(round(sma_base_6, 3))
                                + '|sma16=' + str(round(sma_base_16, 3))
                                + '|cash=' + str(round(mu_week_cash, 3))
                            )
                            service_short_count += 1
                        elif ratio_base_6_16 >= SERVICE_RATIO_HOLD:
                            mu_week_service    = sma_base_16
                            sigma_week_service = sigma_base_16
                            mu_service_method  = (
                                'svc_sma16_base'
                                + '|ratio=' + str(round(ratio_base_6_16, 3))
                                + '|sma6=' + str(round(sma_base_6, 3))
                                + '|sma16=' + str(round(sma_base_16, 3))
                                + '|cash=' + str(round(mu_week_cash, 3))
                            )
                            service_long_count += 1
                        else:
                            mu_week_service    = (SERVICE_DOWN_W_SHORT * sma_base_6) + (SERVICE_DOWN_W_LONG * sma_base_16)
                            sigma_week_service = (SERVICE_DOWN_W_SHORT * sigma_base_6) + (SERVICE_DOWN_W_LONG * sigma_base_16)
                            mu_service_method  = (
                                'svc_blend_down_base'
                                + '|ratio=' + str(round(ratio_base_6_16, 3))
                                + '|sma6=' + str(round(sma_base_6, 3))
                                + '|sma16=' + str(round(sma_base_16, 3))
                                + '|cash=' + str(round(mu_week_cash, 3))
                            )
                            service_blend_count += 1
                    else:
                        service_fallback_count += 1

                    _px = price_event_map.get(tmpl_id) if PRICE_EVENT_ENABLE else False
                    price_event_flag = bool(_px)
                    price_event_date = (_px.get('event_week') if _px else False) or False
                    price_direction  = (_px.get('direction') if _px else '') or False
                    price_delta_pct  = (_px.get('delta_pct') if _px else 0.0) or 0.0
                    price_support_weeks = (_px.get('support_weeks') if _px else 0) or 0
                    if _px:
                        _evt_week = _px.get('event_week')
                        _evt_dir  = _px.get('direction') or ''
                        if _evt_week:
                            _pre_vals = []
                            _post_vals = []
                            for _wk in all_weeks_list:
                                if not _is_base_week(_wk.isocalendar()[1]):
                                    continue
                                _row = wkmap.get(_wk)
                                _qv = _safe_float((_row and _row[1]) or 0.0, 0.0)
                                if _wk < _evt_week:
                                    _pre_vals.append(_qv)
                                else:
                                    _post_vals.append(_qv)

                            if len(_pre_vals) > PRICE_EVENT_PRE_BASE_WEEKS:
                                _pre_vals = _pre_vals[-PRICE_EVENT_PRE_BASE_WEEKS:]
                            if len(_post_vals) > PRICE_EVENT_POST_BASE_WEEKS:
                                _post_vals = _post_vals[:PRICE_EVENT_POST_BASE_WEEKS]

                            _pre_n = len(_pre_vals)
                            _post_n = len(_post_vals)

                            if _pre_n >= PRICE_EVENT_MIN_WEEKS and _post_n >= PRICE_EVENT_MIN_WEEKS:
                                _pre_mu, _pre_sigma = _avg_std(_pre_vals)
                                _post_mu, _post_sigma = _avg_std(_post_vals)

                                if _pre_mu > 0.0:
                                    _post_pre_ratio = _post_mu / _pre_mu
                                else:
                                    _post_pre_ratio = 9.99 if _post_mu > 0.0 else 1.0

                                _apply_px = False
                                _mu_px = mu_week_service
                                _sigma_px = sigma_week_service
                                _px_tag = ''

                                if _evt_dir == 'Baja':
                                    if _post_pre_ratio >= PRICE_EVENT_SIGNAL_UP and _post_mu > (mu_week_service * 1.03):
                                        _mu_px = min(_post_mu, mu_week_service * PRICE_EVENT_CAP_UP) if mu_week_service > 0.0 else _post_mu
                                        _sigma_px = _post_sigma if _post_sigma > 0.0 else sigma_week_service
                                        _apply_px = True
                                        _px_tag = 'pxevt_baja'
                                elif _evt_dir == 'Sube':
                                    if _post_pre_ratio <= PRICE_EVENT_SIGNAL_DOWN and _post_mu < (mu_week_service * 0.97):
                                        _mu_px = max(_post_mu, mu_week_service * PRICE_EVENT_FLOOR_DOWN) if mu_week_service > 0.0 else _post_mu
                                        _sigma_px = _post_sigma if _post_sigma > 0.0 else sigma_week_service
                                        _apply_px = True
                                        _px_tag = 'pxevt_sube'

                                if _apply_px:
                                    mu_week_service = _mu_px
                                    sigma_week_service = _sigma_px
                                    mu_service_method = (
                                        mu_service_method
                                        + '|' + _px_tag
                                        + '|wk=' + str(_evt_week)
                                        + '|pre=' + str(round(_pre_mu, 3))
                                        + '|post=' + str(round(_post_mu, 3))
                                        + '|r=' + str(round(_post_pre_ratio, 3))
                                    )
                                    price_event_adj_count += 1

                    mu_week    = mu_week_service
                    sigma_week = sigma_week_service

                    total_wks_hist   = 0
                    nonzero_wks_hist = 0
                    last_sale_wk     = None

                    for _wk in all_weeks_list:
                        row = wkmap.get(_wk)
                        total_wks_hist += 1
                        if row and row[1] > 0:
                            nonzero_wks_hist += 1
                            last_sale_wk = _wk

                    weeks_since_last = ((_week_start(date_to) - last_sale_wk).days // 7) if last_sale_wk else total_wks_hist
                    density_pct  = (nonzero_wks_hist / total_wks_hist) if total_wks_hist > 0 else 0.0
                    adi_val      = _calc_adi(qty_all_vals)
                    stype        = _series_type(cv_base, density_pct, adi_val)
                    signal_score = density_pct * (_p_q8 / 8.0)

                    _uom_po_factor  = uom_po_factor_map.get(tmpl_id, 1.0)
                    _supplier_moq   = supplier_moq_map.get(tmpl_id, 1.0)
                    _lead_weeks_sku = supplier_lead_map.get(tmpl_id, 1.0)
                    _moq_sku        = max(_uom_po_factor, _supplier_moq)
                    _share_of_pool  = share_of_pool_map_local.get((team_id, tmpl_id), 1.0)
                    _supplier_id    = supplier_partner_map.get(tmpl_id, False)
                    _stock_basis    = stock_basis_map_local.get((team_id, tmpl_id), stock_basis_map.get(tmpl_id, 'direct'))

                    rec_name = 'FWD·LOC%s·PT%s' % (team_id, tmpl_id)

                    vals = {
                        'x_name':                         rec_name,
                        'x_studio_product_id':            pp_id,
                        'x_studio_local':                 team_id,
                        'x_studio_categ_id':              categ_id,
                        'x_studio_mu_week':               mu_week,
                        'x_studio_sigma_week':            sigma_week,
                        'x_studio_avg_units_all':         avg_all,
                        'x_studio_avg_units_nonzero':     avg_nonzero,
                        'x_studio_std_units_all':         std_all,
                        'x_studio_cv_all':                cv_all,
                        'x_studio_cv2':                   cv_base * cv_base,
                        'x_studio_ciclo_de_vida':         ciclo_pre,
                        'x_studio_mu_trend_method':       (mu_service_method or '')[:120],
                        'x_studio_n_base_weeks':          n_base_weeks if _use_base else weeks_for_xyz,
                        'x_studio_units_sold':            total_units_xyz,
                        'x_studio_sales_amount':          total_rev_xyz,
                        'x_studio_orders_count':          float(orders_count),
                        'x_studio_series_weeks_total':    total_wks_hist,
                        'x_studio_series_weeks_nonzero':  float(nonzero_wks_hist),
                        'x_studio_weeks_since_last_sale': weeks_since_last,
                        'x_studio_last_sale_week':        last_sale_wk or False,
                        'x_studio_density_pct':           density_pct,
                        'x_studio_adi':                   adi_val,
                        'x_studio_series_type':           stype,
                        'x_studio_signal_score':          signal_score,
                        'x_studio_week_start':            date_to,
                        'x_studio_lead_weeks':            _lead_weeks_sku,
                        'x_studio_moq':                   _moq_sku,
                        'x_studio_share_of_pool':         _share_of_pool,
                        'x_studio_banda_actual':          _banda_today,
                        'x_studio_supplier_id':           _supplier_id,
                        'x_studio_price_event_flag':      price_event_flag,
                        'x_studio_price_event_date':      price_event_date,
                        'x_studio_price_direction':       price_direction,
                        'x_studio_price_delta_pct':       price_delta_pct,
                        'x_studio_price_support_weeks':   int(price_support_weeks or 0),
                        # XYZ local por team (mismo metodo que el global, una sola pasada)
                        'x_studio_xyz_local':             xyz_local,
                        'x_studio_xyz_local_source':      xyz_local_source,
                        'x_studio_active_weeks_local':    int(active_wks),
                    }

                    if 'x_studio_stock_basis' in fwd_fields:
                        vals['x_studio_stock_basis'] = _stock_basis

                    vals = {k: v for k, v in vals.items() if k in fwd_fields or k == 'x_name'}
                    batch.append(vals)

                    if len(batch) >= BATCH_SIZE:
                        _fwd_create(batch)
                        total_created += len(batch)
                        batch = []

                if batch:
                    _fwd_create(batch)
                    total_created += len(batch)

                try:
                    log(
                        'FWD v3.0.4 LOCAL DEMAND ONLY | purged=%s | created=%s'
                        ' | teams=%s | sku_local=%s | hist=%s→%s | xyz_base_weeks=%s | xyz_cal_weeks=%s'
                        ' | svc6=%s | svc16=%s | svcblend=%s | svcfallback=%s | pxadj=%s | pool_local=%s' % (
                            purge_count, total_created,
                            len(team_ids_found),
                            len(local_pairs),
                            history_from, date_to,
                            XYZ_BASE_WEEKS,
                            len(xyz_weeks_list),
                            service_short_count,
                            service_long_count,
                            service_blend_count,
                            service_fallback_count,
                            price_event_adj_count,
                            pool_local_adj_count,
                        ),
                        level='info'
                    )
                except Exception:
                    pass

                _base_sorted = sorted(_xyz_base_week_dates)
                _xyz_missing_msg = (
                    ' | xyz_local_missing=' + ','.join(_xyz_local_missing)
                ) if _xyz_local_missing else ''
                _debug_msg = (
                    'date_to=%s | xyz_from=%s | cal_weeks=%s | base_weeks=%s'
                    ' | base_1=%s | base_last=%s'
                    ' | svc6=%s | svc16=%s | blend=%s | fb=%s | px=%s | pool=%s'
                    ' | xyz_local: X=%s Y=%s Z=%s global=%s%s'
                ) % (
                    date_to,
                    xyz_from,
                    len(xyz_weeks_list),
                    len(_base_sorted),
                    str(_base_sorted[0]) if _base_sorted else 'none',
                    str(_base_sorted[-1]) if _base_sorted else 'none',
                    service_short_count,
                    service_long_count,
                    service_blend_count,
                    service_fallback_count,
                    price_event_adj_count,
                    pool_local_adj_count,
                    xyz_local_counts['X'],
                    xyz_local_counts['Y'],
                    xyz_local_counts['Z'],
                    xyz_local_counts['global'],
                    _xyz_missing_msg,
                )

                # Si faltan campos Studio para xyz_local, escalar a warning visible.
                _notif_type = 'danger' if _xyz_local_missing else 'warning'

                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'FWD v3.0.5 XYZ_LOCAL',
                        'message': _debug_msg,
                        'sticky': True,
                        'type': _notif_type,
                    }
                }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))