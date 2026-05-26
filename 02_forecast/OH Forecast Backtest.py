# ============================================================
# OH Forecast Backtest - HM-SI vs Old Forecast vs Venta Real POS
# ============================================================
#
# Version activa: v11.1 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - Comparar forecast HM-SI vs forecast anterior contra venta real POS.
#   - Reporta por semana, sucursal, product.product y metodo.
#   - Persiste WAPE, BIAS, MAE, sub/over-forecast por dimension.
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Llave operativa unificada: product.product (no product_template).
#   - Venta real POS se agrupa por pp.id; ABCXYZ se carga directo desde
#     x_calculo_abc_xyz por product.product.
#   - _zone_code() acepta Z1-Z4 (HM-SI v3.x) y REG-0..REG-8 (HM-SI v4.x+).
#   - Lectura batch de x_hm_si_forecast: series_type, lifecycle, regimen,
#     forecast_model_code, mu_week_pre_bias.
#   - Modo multi-semana via BACKTEST_WEEKS + WEEK_OFFSET.
#   - No toca stock, compras, transferencias ni ordenes de compra.
#
# Detalles, fixes historicos y metricas de snapshots: ver CHANGELOG.md.
# ============================================================

VERSION_ID = 'OH_FORECAST_BACKTEST_RUNNER_v11_1_REGIMEN'

TZ_NAME = 'America/Santiago'
LOCK_KEY = 99009490

# ------------------------------------------------------------
# Configuración
# ------------------------------------------------------------
BACKTEST_MODEL_DEFAULT = 'x_forecast_backtest'
HM_SI_MODEL_DEFAULT = 'x_hm_si_forecast'
OLD_MODEL_DEFAULT = 'x_forecast_weekly_data'

HM_SI_ACTION_ID_DEFAULT = 1553
# OLD legacy (OH Forecast Semanal) eliminado el 2026-05-25: SA 1527 no existe
# y x_forecast_weekly_data tiene data residual sin refresh. Desactivado para
# evitar contaminacion en el backtest comparativo.
OLD_FORECAST_ACTION_ID_DEFAULT = 0
LOAD_EXISTING_OLD_WHEN_NO_ACTION_DEFAULT = False   # no cargar OLD existente
CREATE_HYBRID_ROWS_DEFAULT = False          # no crear filas hybrid
HYBRID_METHOD_CODE = 'hybrid_z12_hm_z34_old'
ZONE_MISSING = 'SIN_ZONA'
ZONES_ORDER = ['Z1', 'Z2', 'Z3', 'Z4']

# Modo multi-semana: BACKTEST_WEEKS controla cuántas semanas se procesan en una sola corrida.
# WEEK_OFFSET=0 → la semana más reciente cerrada es la última del rango.
# Con BACKTEST_WEEKS=4 y WEEK_OFFSET=0 procesa las 4 semanas cerradas más recientes.
# La purga borra todas las semanas del rango antes de insertar — idempotente.
TARGET_WEEK_STARTS_DEFAULT = []   # vacío = auto-detect desde WEEK_OFFSET
WEEK_OFFSET_DEFAULT = 0           # 0 = semana más reciente
BACKTEST_WEEKS_DEFAULT = 4        # 4 semanas por ejecución

FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
BATCH_SIZE = 800

ABC_MODEL = 'x_calculo_abc_xyz'


# ------------------------------------------------------------
# Helpers básicos
# ------------------------------------------------------------
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


def _safe_text(v, default=''):
    if v is None:
        return default
    try:
        return str(v)
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


def _field_exists(model_obj, fname):
    try:
        return bool(fname) and fname in (model_obj._fields or {})
    except Exception:
        return False


def _first_existing_field(model_obj, names):
    fields_map = model_obj._fields or {}
    for n in (names or []):
        if n in fields_map:
            return n
    return False


def _first_existing_field_or_label(model_obj, technical_names, label_names):
    fields_map = model_obj._fields or {}

    for n in (technical_names or []):
        if n in fields_map:
            return n

    wanted = []
    for x in (label_names or []):
        try:
            wanted.append(str(x or '').strip().lower())
        except Exception:
            pass

    if not wanted:
        return False

    for fname, field in fields_map.items():
        label = ''
        try:
            label = str(field.string or '').strip().lower()
        except Exception:
            label = ''
        if label and label in wanted:
            return fname

    return False


def _field_type(model_obj, fname):
    try:
        f = (model_obj._fields or {}).get(fname)
        if f:
            return f.type or ''
    except Exception:
        pass
    return ''


def _field_comodel(model_obj, fname):
    try:
        f = (model_obj._fields or {}).get(fname)
        if f and f.type == 'many2one':
            return f.comodel_name or ''
    except Exception:
        pass
    return ''


def _put_if_field(vals, model_obj, fname, value):
    if fname and _field_exists(model_obj, fname):
        vals[fname] = value


def _selection_keys(model_obj, fname):
    out = []
    try:
        field = (model_obj._fields or {}).get(fname)
        sel = field.selection or []
        if callable(sel):
            return out
        for ch in sel:
            try:
                out.append(str(ch[0]))
            except Exception:
                pass
    except Exception:
        pass
    return out


def _put_selection_safe(vals, model_obj, fname, code):
    if not fname or not _field_exists(model_obj, fname):
        return
    if code in (None, False, ''):
        return

    ftype = _field_type(model_obj, fname)
    if ftype != 'selection':
        vals[fname] = code
        return

    keys = _selection_keys(model_obj, fname)
    if (not keys) or (str(code) in keys):
        vals[fname] = code
        return

    alt_map = {
        'hm_si': ['hm-si', 'hmsi', 'HM-SI', 'HM_SI', 'HM SI', 'hm'],
        'old': ['old', 'OLD', 'anterior', 'previous', 'legacy'],
        'vendio_y_forecast': ['sold_and_forecast', 'venta_y_forecast'],
        'forecast_sin_venta': ['forecast_no_sale', 'forecast_sin_real'],
        'venta_sin_forecast': ['sale_no_forecast', 'venta_sin_pronostico'],
        'sin_movimiento': ['no_movement', 'sin_mov'],
        'critico': ['crítico', 'Critico', 'Crítico'],
        'alto': ['Alto'],
        'medio': ['Medio'],
        'bajo': ['Bajo'],
        'Z1': ['z1'],
        'Z2': ['z2'],
        'Z3': ['z3'],
        'Z4': ['z4'],
        'SIN_ZONA': ['sin_zona', 'no_zone'],
        'hybrid_z12_hm_z34_old': ['hybrid', 'hibrido', 'mixto'],
    }
    for alt in alt_map.get(str(code), []):
        if alt in keys:
            vals[fname] = alt
            return

    # Si la selección no tiene el valor, no escribimos para evitar error.
    return


def _selection_accepts(model_obj, fname, code):
    if not fname or not _field_exists(model_obj, fname):
        return False
    if _field_type(model_obj, fname) != 'selection':
        return True
    keys = _selection_keys(model_obj, fname)
    if not keys or str(code) in keys:
        return True
    if str(code) == HYBRID_METHOD_CODE:
        for alt in ['hybrid', 'hibrido', 'mixto']:
            if alt in keys:
                return True
    return False


def _zone_code(v):
    """Normaliza valor de zona/regimen. Acepta legacy Z1-Z4 y nuevo REG-0..REG-8.

    v4.3 motor HM-SI escribe REG-X en x_studio_forecast_zone (semantica
    cambio: la columna sigue llamandose 'zone' pero su contenido es el
    regimen canonico). Esta funcion preserva ese valor sin alterarlo.
    """
    txt = _safe_text(v, '').strip().upper()
    # Normalizar espacios pero NO guiones (REG-1 debe quedar como REG-1)
    txt = txt.replace(' ', '_')
    if txt in ('Z1', 'Z2', 'Z3', 'Z4'):
        return txt
    # Nuevo: aceptar REG-0..REG-8 tal cual
    if len(txt) == 5 and txt.startswith('REG-') and txt[4:].isdigit():
        return txt
    if txt in ('SIN_ZONA', 'NO_ZONE', 'NONE', 'FALSE', ''):
        return ZONE_MISSING
    return ZONE_MISSING


def _metric_bucket(metrics, method_code, zone_code):
    key = (method_code, zone_code)
    if key not in metrics:
        metrics[key] = {
            'n': 0,
            'real': 0.0,
            'forecast': 0.0,
            'abs_error': 0.0,
            'error': 0.0,
        }
    return metrics[key]


def _accum_metric(metrics, method_code, zone_code, forecast_qty, real_qty):
    z = _zone_code(zone_code)
    if z == ZONE_MISSING:
        return
    m = _metric_bucket(metrics, method_code, z)
    fc = _safe_float(forecast_qty, 0.0)
    real = _safe_float(real_qty, 0.0)
    err = real - fc
    m['n'] += 1
    m['real'] += real
    m['forecast'] += fc
    m['abs_error'] += abs(err)
    m['error'] += err


def _metric_wmape(m):
    real = _safe_float((m or {}).get('real'), 0.0)
    ae = _safe_float((m or {}).get('abs_error'), 0.0)
    if real > 0.001:
        return ae / real
    if ae > 0.001:
        return 999.0
    return 0.0


def _metric_bias(m):
    real = _safe_float((m or {}).get('real'), 0.0)
    if real > 0.001:
        return _safe_float((m or {}).get('error'), 0.0) / real
    return 0.0


def _format_zone_metrics(metrics):
    parts = []
    method_labels = [
        ('hm_si', 'HM'),
        ('old', 'OLD'),
        (HYBRID_METHOD_CODE, 'HYB'),
    ]
    for z in ZONES_ORDER:
        z_parts = []
        for method_code, label in method_labels:
            m = metrics.get((method_code, z))
            if not m:
                continue
            wm = _metric_wmape(m)
            bs = _metric_bias(m)
            wm_txt = '999' if wm >= 999.0 else str(round(wm * 100.0, 1))
            z_parts.append('%s wm=%s%% b=%s%% r=%s f=%s n=%s' % (
                label,
                wm_txt,
                round(bs * 100.0, 1),
                round(_safe_float(m.get('real'), 0.0), 0),
                round(_safe_float(m.get('forecast'), 0.0), 0),
                _safe_int(m.get('n'), 0),
            ))
        if z_parts:
            parts.append('%s[%s]' % (z, '; '.join(z_parts)))
    return ' | '.join(parts)


def _normalize_product_to_variant_id(prod):
    if not prod:
        return False
    try:
        if prod._name == 'product.product':
            return prod.id
    except Exception:
        pass

    # Fallback legacy: si el forecast viejo trae product.template, se usa su primera variante.
    # Esto queda solo para comparar contra el modelo antiguo; la llave nueva debe ser product.product.
    try:
        if prod._name == 'product.template':
            try:
                if prod.product_variant_id:
                    return prod.product_variant_id.id
            except Exception:
                pass
            try:
                variants = prod.product_variant_ids
                if variants:
                    return variants[0].id
            except Exception:
                pass
    except Exception:
        pass

    return False


def _product_category_id_by_variant(product_id):
    if not product_id:
        return False
    try:
        prod = env['product.product'].sudo().browse(product_id)
        if prod and prod.exists():
            return prod.product_tmpl_id.categ_id.id or False
    except Exception:
        pass
    return False


def _variant_template_map(product_ids):
    out = {}
    ids = []
    for pid in (product_ids or []):
        pidi = _safe_int(pid, 0)
        if pidi:
            ids.append(pidi)
    ids = list(set(ids))
    if not ids:
        return out
    try:
        env.cr.execute("""
            SELECT pp.id, pp.product_tmpl_id
            FROM product_product pp
            WHERE pp.id IN %s
        """, (tuple(ids),))
        for pid, tmpl_id in env.cr.fetchall():
            out[_safe_int(pid)] = _safe_int(tmpl_id)
    except Exception:
        pass
    return out


def _series_type_from_metrics(cv2, density_pct, adi):
    den = _safe_float(density_pct, 0.0)
    cv2v = _safe_float(cv2, 999.0)
    adiv = _safe_float(adi, 999.0)
    if den < 0.05:
        return 'no_signal'
    if adiv >= 1.32 and cv2v >= 0.49:
        return 'lumpy'
    if adiv >= 1.32:
        return 'intermittent'
    if cv2v >= 0.49:
        return 'erratic'
    return 'smooth'


def _calc_adi_from_vals(qty_vals):
    intervals = []
    gap = 0
    for q in (qty_vals or []):
        qv = _safe_float(q, 0.0)
        if qv > 0.0:
            intervals.append(gap + 1)
            gap = 0
        else:
            gap += 1
    if not intervals:
        return 999.0
    return sum(intervals) / len(intervals)


def _quarter_abs(d):
    return d.year * 4 + ((d.month - 1) // 3) + 1


def _infer_lifecycle_simple(u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7, p_q8, local_volatility_high):
    u_rest = u_q1 + u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7
    u8 = u_q0 + u_rest
    if u8 <= 0.0:
        return 'dead'
    if p_q8 <= 2 and u_q1 <= 0.0:
        return 'intermittent'
    if u_q0 > 0.0 and u_rest <= 0.0:
        return 'new'
    if u_q0 <= 0.0 and (u_q1 + u_q2 + u_q3) > 0.0:
        return 'declining'
    if local_volatility_high and p_q8 <= 5:
        return 'seasonal'
    if u_q0 > 0.0 and u_q1 <= 0.0 and (u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7) > 0.0:
        return 'ramp_up'
    return 'mature'


def _seasonal_band_for_week(iso_week):
    w = _safe_int(iso_week, 0)
    if w in [1]:
        return 'VERANO_BAJO'
    if w in [2, 3, 4, 9]:
        return 'VERANO_MEDIO'
    if w in [5, 6, 7, 8]:
        return 'VERANO_ALTO'
    if w == 38:
        return 'FIESTAS_PATRIAS'
    if w == 44:
        return 'HALLOWEEN'
    if w in [49, 50, 51, 52]:
        return 'FIN_ANIO'
    return 'BASE'


# ------------------------------------------------------------
# Contexto
# ------------------------------------------------------------
CTX = env.context or {}

BACKTEST_MODEL = str(CTX.get('backtest_model', BACKTEST_MODEL_DEFAULT) or BACKTEST_MODEL_DEFAULT)
HM_SI_MODEL = str(CTX.get('hm_si_model', HM_SI_MODEL_DEFAULT) or HM_SI_MODEL_DEFAULT)
OLD_MODEL = str(CTX.get('old_model', OLD_MODEL_DEFAULT) or OLD_MODEL_DEFAULT)

HM_SI_ACTION_ID = _safe_int(CTX.get('hm_si_action_id', HM_SI_ACTION_ID_DEFAULT), HM_SI_ACTION_ID_DEFAULT)

# Propaga el flag de normalizacion de demanda al HM-SI Action invocado.
# Default TRUE durante el backtest comparativo (no productivo). Para desactivar
# temporalmente, pasar context use_demand_normalization=False.
USE_DEMAND_NORMALIZATION = bool(CTX.get('use_demand_normalization', True))
OLD_FORECAST_ACTION_ID = _safe_int(CTX.get('old_forecast_action_id', OLD_FORECAST_ACTION_ID_DEFAULT), OLD_FORECAST_ACTION_ID_DEFAULT)
LOAD_EXISTING_OLD_WHEN_NO_ACTION = bool(CTX.get('load_existing_old_when_no_action', LOAD_EXISTING_OLD_WHEN_NO_ACTION_DEFAULT))
CREATE_HYBRID_ROWS = bool(CTX.get('create_hybrid_rows', CREATE_HYBRID_ROWS_DEFAULT))
BACKTEST_WEEKS = _safe_int(CTX.get('backtest_weeks', BACKTEST_WEEKS_DEFAULT), BACKTEST_WEEKS_DEFAULT)
WEEK_OFFSET = _safe_int(CTX.get('week_offset', WEEK_OFFSET_DEFAULT), WEEK_OFFSET_DEFAULT)

TEAM_IDS = _to_int_list(CTX.get('team_ids'))
if not TEAM_IDS:
    TEAM_IDS = list(FILTERED_TEAM_IDS_DEFAULT)

company = env.company

Backtest = env[BACKTEST_MODEL].sudo()
HmModel = env[HM_SI_MODEL].sudo()
OldModel = env[OLD_MODEL].sudo()


# ------------------------------------------------------------
# Resolver campos Backtest
# ------------------------------------------------------------
BT_NAME = _first_existing_field(Backtest, ['x_name', 'name'])
BT_WEEK = _first_existing_field(Backtest, ['x_studio_target_week_start', 'x_studio_week_start', 'x_week_start', 'x_studio_period_start'])
BT_CUTOFF = _first_existing_field(Backtest, ['x_studio_forecast_cutoff', 'x_studio_cutoff_date', 'x_studio_date_to'])
BT_PRODUCT = _first_existing_field(Backtest, ['x_studio_product_id', 'x_product_id', 'x_studio_producto'])
BT_TEAM = _first_existing_field(Backtest, ['x_studio_team_id', 'x_team_id', 'x_studio_sucursal', 'x_studio_local_id', 'x_studio_local'])
BT_METHOD = _first_existing_field(Backtest, ['x_studio_method', 'x_studio_metodo', 'x_studio_forecast_method'])
BT_FORECAST = _first_existing_field(Backtest, ['x_studio_forecast_qty', 'x_studio_mu_week', 'x_studio_demanda_estimada', 'x_studio_demanda_semanal'])
BT_MU_PRE_BIAS = _first_existing_field(Backtest, ['x_studio_mu_week_pre_bias', 'x_studio_forecast_pre_bias', 'x_studio_mu_pre_bias', 'x_studio_demanda_pre_bias'])
BT_REAL = _first_existing_field(Backtest, ['x_studio_real_qty', 'x_studio_demanda_real', 'x_studio_venta_real', 'x_studio_units_real'])
BT_ERROR = _first_existing_field(Backtest, ['x_studio_error_qty', 'x_studio_error'])
BT_ABS_ERROR = _first_existing_field(Backtest, ['x_studio_abs_error_qty', 'x_studio_abs_error', 'x_studio_error_abs'])
BT_APE = _first_existing_field(Backtest, ['x_studio_ape', 'x_studio_error_pct'])
BT_BIAS = _first_existing_field(Backtest, ['x_studio_bias_pct', 'x_studio_bias'])
BT_SIGMA = _first_existing_field(Backtest, ['x_studio_sigma_week', 'x_studio_sigma'])
BT_COMPANY = _first_existing_field(Backtest, ['x_studio_company_id', 'x_company_id', 'x_studio_compania'])
BT_CATEG = _first_existing_field(Backtest, ['x_studio_categ_id', 'x_studio_categoria', 'x_studio_category_id'])
BT_VALID = _first_existing_field(Backtest, ['x_studio_valid_for_error', 'x_studio_valid'])
BT_BUCKET = _first_existing_field(Backtest, ['x_studio_error_bucket', 'x_studio_bucket', 'x_studio_estado_error', 'x_studio_tipo_error'])

BT_SERIES_TYPE = _first_existing_field(Backtest, ['x_studio_series_type', 'x_series_type'])
BT_LIFECYCLE = _first_existing_field(Backtest, ['x_studio_ciclo_de_vida', 'x_studio_lifecycle', 'x_lifecycle'])
BT_ABCXYZ = _first_existing_field(Backtest, ['x_studio_abcxyz', 'x_studio_abc_xyz', 'x_abcxyz'])
BT_ABC = _first_existing_field(Backtest, ['x_studio_abc', 'x_abc'])
BT_XYZ = _first_existing_field(Backtest, ['x_studio_xyz', 'x_xyz'])
BT_IMPORTANCE = _first_existing_field(Backtest, ['x_studio_importancia', 'x_studio_importance', 'x_importancia'])
BT_RANK_ABCXYZ = _first_existing_field(Backtest, ['x_studio_rank_abcxyz', 'x_studio_rank', 'x_rank_abcxyz'])
BT_CV2 = _first_existing_field(Backtest, ['x_studio_cv2', 'x_cv2'])
BT_FORECAST_ZONE = _first_existing_field(Backtest, ['x_studio_forecast_zone', 'x_studio_z_segment', 'x_studio_zona_forecast', 'x_forecast_zone'])

# v4.3 motor canonico: regimen + model_code (best-effort, si no existen los campos se omiten).
BT_REGIMEN = _first_existing_field(Backtest, ['x_studio_regimen', 'x_regimen'])
BT_FORECAST_MODEL_CODE = _first_existing_field(Backtest, ['x_studio_forecast_model_code', 'x_forecast_model_code'])

# Campos opcionales para medir sesgo por dinamica de precio del forecast HM-SI v3.6.
BT_PRICE_SEGMENT = _first_existing_field(Backtest, ['x_studio_price_dynamics_segment', 'x_studio_price_segment'])

required_bt = []
if not BT_WEEK:
    required_bt.append('semana objetivo')
if not BT_PRODUCT:
    required_bt.append('producto')
if not BT_TEAM:
    required_bt.append('local/equipo')
if not BT_FORECAST:
    required_bt.append('forecast qty')
if not BT_REAL:
    required_bt.append('real qty')

# Validación de llave: backtest debe guardar product.product.
if BT_PRODUCT and _field_type(Backtest, BT_PRODUCT) == 'many2one':
    _bt_prod_comodel = _field_comodel(Backtest, BT_PRODUCT)
    if _bt_prod_comodel and _bt_prod_comodel != 'product.product':
        required_bt.append('producto debe apuntar a product.product; hoy apunta a %s' % _bt_prod_comodel)


# ------------------------------------------------------------
# Resolver campos forecast HM-SI
# ------------------------------------------------------------
HM_WEEK = _first_existing_field(HmModel, ['x_studio_week_start', 'x_studio_target_week_start', 'x_week_start'])
HM_PRODUCT = _first_existing_field(HmModel, ['x_studio_product_id', 'x_product_id', 'x_studio_producto'])
HM_TEAM = _first_existing_field(HmModel, ['x_studio_team_id', 'x_team_id', 'x_studio_sucursal'])
HM_MU = _first_existing_field(HmModel, ['x_studio_mu_week', 'x_studio_demanda_estimada', 'x_studio_forecast_qty'])
HM_MU_PRE_BIAS = _first_existing_field(HmModel, ['x_studio_mu_week_pre_bias', 'x_studio_mu_week_v38_pre_bias', 'x_studio_forecast_pre_bias', 'x_studio_mu_pre_bias'])
HM_SIGMA = _first_existing_field(HmModel, ['x_studio_sigma_week', 'x_studio_sigma'])
HM_CATEG = _first_existing_field(HmModel, ['x_studio_categ_id', 'x_studio_categoria'])
HM_ZONE = _first_existing_field(HmModel, ['x_studio_forecast_zone', 'x_studio_z_segment', 'x_studio_zona_forecast', 'x_forecast_zone'])
# v4.3 motor canonico: regimen y model_code escritos por HM-SI v4.3-revert+.
HM_REGIMEN = _first_existing_field(HmModel, ['x_studio_regimen', 'x_regimen'])
HM_MODEL_CODE = _first_existing_field(HmModel, ['x_studio_forecast_model_code', 'x_forecast_model_code'])


# ------------------------------------------------------------
# Resolver campos forecast anterior
# ------------------------------------------------------------
OLD_WEEK = _first_existing_field(OldModel, ['x_studio_week_start', 'x_studio_fecha_de_corte', 'x_studio_fecha_corte', 'x_studio_cutoff_date', 'x_studio_date_to', 'x_studio_target_week_start', 'x_week_start', 'x_studio_period_start'])
OLD_PRODUCT = _first_existing_field(OldModel, ['x_studio_product_id', 'x_product_id', 'x_studio_producto'])
OLD_TEAM = _first_existing_field(OldModel, ['x_studio_local', 'x_studio_team_id', 'x_team_id', 'x_studio_sucursal'])
OLD_MU = _first_existing_field(OldModel, ['x_studio_mu_week', 'x_studio_demanda_semanal_ajustada', 'x_studio_demanda_ajustada', 'x_studio_demanda_semanal', 'x_studio_forecast_qty', 'x_studio_demanda_estimada', 'x_studio_demanda_estimada_entera'])
OLD_SIGMA = _first_existing_field(OldModel, ['x_studio_sigma_week', 'x_studio_desviacion_semanal', 'x_studio_sigma'])
OLD_CATEG = _first_existing_field(OldModel, ['x_studio_categ_id', 'x_studio_categoria'])

OLD_SERIES_TYPE = _first_existing_field_or_label(OldModel, ['x_studio_series_type', 'x_series_type'], ['Tipo de Serie', 'series_type', 'Series Type'])
OLD_LIFECYCLE = _first_existing_field_or_label(OldModel, ['x_studio_ciclo_de_vida', 'x_studio_lifecycle', 'x_ciclo_de_vida'], ['ciclo_de_vida', 'Ciclo de Vida', 'Ciclo de vida', 'lifecycle'])
OLD_SEASONAL_BAND = _first_existing_field_or_label(OldModel, ['x_studio_banda_actual', 'x_studio_seasonal_band', 'x_banda_actual'], ['banda_actual', 'Banda actual', 'Banda Actual', 'seasonal_band'])
OLD_CV2 = _first_existing_field_or_label(OldModel, ['x_studio_cv2', 'x_cv2'], ['cv2', 'CV2', 'CV²'])
OLD_CV_ALL = _first_existing_field_or_label(OldModel, ['x_studio_cv_all', 'x_studio_cv', 'x_cv_all', 'x_cv'], ['cv_all', 'CV all', 'CV'])
OLD_ADI = _first_existing_field_or_label(OldModel, ['x_studio_adi', 'x_adi'], ['adi', 'ADI'])
OLD_DENSITY = _first_existing_field_or_label(OldModel, ['x_studio_density_pct', 'x_density_pct'], ['density_pct', 'Densidad', 'Densidad de venta'])


# ------------------------------------------------------------
# Lock
# ------------------------------------------------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
locked = env.cr.fetchone()[0]

if required_bt:
    if locked:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'Forecast Backtest',
            'message': 'Faltan campos mínimos en %s: %s' % (BACKTEST_MODEL, ', '.join(required_bt)),
            'type': 'danger',
            'sticky': True,
        }
    }

elif not locked:
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'Forecast Backtest',
            'message': 'Otro backtest está ejecutándose.',
            'type': 'warning',
            'sticky': False,
        }
    }

else:
    try:
        # --------------------------------------------------------
        # Fechas base
        # --------------------------------------------------------
        env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
        today_local = env.cr.fetchone()[0]
        current_week_start = _week_start(today_local)

        target_weeks = []
        target_week_starts_ctx = CTX.get('target_week_starts', TARGET_WEEK_STARTS_DEFAULT)

        if target_week_starts_ctx:
            for ds in target_week_starts_ctx:
                try:
                    d = datetime.datetime.fromisoformat(str(ds)).date()
                    target_weeks.append(_week_start(d))
                except Exception:
                    pass

        if not target_weeks:
            # WEEK_OFFSET desplaza el punto de partida: 0=semana más reciente cerrada.
            base_week = current_week_start - datetime.timedelta(weeks=1 + WEEK_OFFSET)
            i = BACKTEST_WEEKS - 1
            while i >= 0:
                target_weeks.append(base_week - datetime.timedelta(weeks=i))
                i -= 1

        _seen_w = {}
        _clean_weeks = []
        for w in target_weeks:
            if w not in _seen_w:
                _seen_w[w] = True
                _clean_weeks.append(w)
        target_weeks = _clean_weeks

        # --------------------------------------------------------
        # Detectar team en POS
        # --------------------------------------------------------
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
                    'title': 'Forecast Backtest',
                    'message': 'No se encontró crm_team_id/team_id válido en pos.config.',
                    'type': 'danger',
                    'sticky': True,
                }
            }

        else:
            forecast_warnings = []
            if not HM_WEEK or not HM_PRODUCT or not HM_TEAM or not HM_MU:
                forecast_warnings.append('HM-SI campos incompletos')
            if not HM_ZONE:
                forecast_warnings.append('HM-SI sin forecast_zone')
            if not BT_FORECAST_ZONE:
                forecast_warnings.append('Backtest sin campo forecast_zone')
            if not BT_MU_PRE_BIAS:
                forecast_warnings.append('Backtest sin campo mu_week_pre_bias')
            if not HM_MU_PRE_BIAS:
                forecast_warnings.append('HM-SI sin campo mu_week_pre_bias')

            if (OLD_FORECAST_ACTION_ID and OLD_FORECAST_ACTION_ID > 0) or LOAD_EXISTING_OLD_WHEN_NO_ACTION:
                if not OLD_WEEK or not OLD_PRODUCT or not OLD_TEAM or not OLD_MU:
                    forecast_warnings.append('OLD campos incompletos')
            hybrid_rows_enabled = bool(CREATE_HYBRID_ROWS)
            if hybrid_rows_enabled and not BT_METHOD:
                hybrid_rows_enabled = False
                forecast_warnings.append('hybrid no persistido: sin campo metodo')
            elif hybrid_rows_enabled and BT_METHOD and not _selection_accepts(Backtest, BT_METHOD, HYBRID_METHOD_CODE):
                hybrid_rows_enabled = False
                forecast_warnings.append('hybrid no persistido: falta selection')

            # ----------------------------------------------------
            # Purga backtest de semanas objetivo
            # ----------------------------------------------------
            purge_domain = []
            if BT_WEEK and target_weeks:
                purge_domain.append((BT_WEEK, 'in', target_weeks))
            if BT_COMPANY:
                purge_domain.append((BT_COMPANY, '=', company.id))

            purge_count = 0
            if purge_domain:
                old_bt = Backtest.search(purge_domain)
                purge_count = len(old_bt)
                if old_bt:
                    old_bt.unlink()

            # ----------------------------------------------------
            # Función: venta real POS por semana, llave product.product
            # ----------------------------------------------------
            def _load_real_sales(real_from, real_to):
                team_filter_sql = ''
                params = {
                    'company_id': company.id,
                    'date_from': real_from,
                    'date_to': real_to,
                    'tz': TZ_NAME,
                }

                if TEAM_IDS:
                    team_filter_sql = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '
                    params['team_ids'] = TEAM_IDS

                pt_fields = env['product.template']._fields or {}
                dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

                sql = """
                    WITH base AS (
                        SELECT
                            {team_col} AS team_id,
                            pol.id AS line_id,
                            pol.combo_parent_id,
                            pp.id AS product_id,
                            {dtype_sql} AS dtype,
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
                          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(date_from)s
                          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                          AND pp.active = TRUE
                          AND pt.sale_ok = TRUE
                          AND pt.active = TRUE
                          AND {team_col} IS NOT NULL
                          {team_filter}
                    ),
                    standalone AS (
                        SELECT team_id, product_id, SUM(qty) AS units
                        FROM base
                        WHERE combo_parent_id IS NULL
                          AND COALESCE(dtype,'') NOT IN ('combo','service')
                        GROUP BY 1,2
                    ),
                    combo_children AS (
                        SELECT c.team_id, c.product_id, SUM(c.qty) AS units
                        FROM base c
                        JOIN base p ON p.line_id = c.combo_parent_id
                        WHERE c.combo_parent_id IS NOT NULL
                          AND COALESCE(c.dtype,'') <> 'service'
                        GROUP BY 1,2
                    )
                    SELECT team_id, product_id, SUM(units) AS units
                    FROM (
                        SELECT * FROM standalone
                        UNION ALL
                        SELECT * FROM combo_children
                    ) su
                    GROUP BY 1,2
                """.format(
                    team_col=team_col_sql,
                    dtype_sql=dtype_sql,
                    team_filter=team_filter_sql,
                )

                env.cr.execute(sql, params)
                out = {}
                for team_id, product_id, qty in env.cr.fetchall():
                    tid = _safe_int(team_id)
                    pid = _safe_int(product_id)
                    if not tid or not pid:
                        continue
                    q = _safe_float(qty, 0.0)
                    if q < 0.0:
                        q = 0.0
                    key = (tid, pid)
                    out[key] = out.get(key, 0.0) + q
                return out

            def _load_real_sales_batched(date_from_all, date_to_all):
                team_filter_sql = ''
                params = {
                    'company_id': company.id,
                    'date_from': date_from_all,
                    'date_to': date_to_all,
                    'tz': TZ_NAME,
                }
                if TEAM_IDS:
                    team_filter_sql = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '
                    params['team_ids'] = TEAM_IDS

                pt_fields = env['product.template']._fields or {}
                dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

                sql = """
                    WITH base AS (
                        SELECT
                            {team_col} AS team_id,
                            pol.id AS line_id,
                            pol.combo_parent_id,
                            pp.id AS product_id,
                            {dtype_sql} AS dtype,
                            date_trunc('week', po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS week,
                            COALESCE(pol.qty, 0.0) AS qty
                        FROM pos_order_line pol
                        JOIN pos_order po ON po.id = pol.order_id
                        LEFT JOIN pos_session ps ON ps.id = po.session_id
                        LEFT JOIN pos_config pc ON pc.id = ps.config_id
                        JOIN product_product pp ON pp.id = pol.product_id
                        JOIN product_template pt ON pt.id = pp.product_tmpl_id
                        WHERE po.company_id = %(company_id)s
                          AND po.state IN ('paid','done','invoiced')
                          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(date_from)s
                          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                          AND pp.active = TRUE
                          AND pt.sale_ok = TRUE
                          AND pt.active = TRUE
                          AND {team_col} IS NOT NULL
                          {team_filter}
                    ),
                    standalone AS (
                        SELECT team_id, product_id, week, SUM(qty) AS units
                        FROM base
                        WHERE combo_parent_id IS NULL
                          AND COALESCE(dtype,'') NOT IN ('combo','service')
                        GROUP BY 1,2,3
                    ),
                    combo_children AS (
                        SELECT c.team_id, c.product_id, c.week, SUM(c.qty) AS units
                        FROM base c
                        JOIN base p ON p.line_id = c.combo_parent_id
                        WHERE c.combo_parent_id IS NOT NULL
                          AND COALESCE(c.dtype,'') <> 'service'
                        GROUP BY 1,2,3
                    )
                    SELECT team_id, product_id, week, SUM(units) AS units
                    FROM (
                        SELECT * FROM standalone
                        UNION ALL
                        SELECT * FROM combo_children
                    ) su
                    GROUP BY 1,2,3
                """.format(
                    team_col=team_col_sql,
                    dtype_sql=dtype_sql,
                    team_filter=team_filter_sql,
                )

                env.cr.execute(sql, params)
                out = {}
                for team_id, product_id, week, qty in env.cr.fetchall():
                    tid = _safe_int(team_id)
                    pid = _safe_int(product_id)
                    if not tid or not pid or not week:
                        continue
                    q = _safe_float(qty, 0.0)
                    if q < 0.0:
                        q = 0.0
                    week_map = out.setdefault(week, {})
                    key = (tid, pid)
                    week_map[key] = week_map.get(key, 0.0) + q
                return out

            # ----------------------------------------------------
            # Función: ejecutar acción forecast
            # ----------------------------------------------------
            def _run_forecast_action(action_id, cutoff_date):
                if not action_id or action_id <= 0:
                    return False
                act = env['ir.actions.server'].sudo().browse(action_id)
                if not act or not act.exists():
                    return False
                ctx2 = dict(env.context or {})
                ctx2.update({
                    'date_to': str(cutoff_date),
                    'hard_reset': True,
                    'team_ids': TEAM_IDS,
                    'use_demand_normalization': USE_DEMAND_NORMALIZATION,
                })
                act.with_context(ctx2).run()
                return True

            # ----------------------------------------------------
            # Función: leer forecast desde un modelo
            # ----------------------------------------------------
            def _load_forecast_rows(model_obj, week_field, product_field, team_field, mu_field, sigma_field, categ_field, lookup_week):
                out = {}
                sigma_out = {}
                categ_out = {}
                meta_out = {}

                if not week_field or not product_field or not team_field or not mu_field:
                    return out, sigma_out, categ_out, meta_out

                # Campo opcional presente en HM-SI v3.6 para medir sesgo por dinamica de precio.
                # Modelo backtest actual: solo x_studio_price_dynamics_segment.
                price_segment_field = _first_existing_field(model_obj, ['x_studio_price_dynamics_segment', 'x_studio_price_segment'])
                pre_bias_field = _first_existing_field(model_obj, ['x_studio_mu_week_pre_bias', 'x_studio_mu_week_v38_pre_bias', 'x_studio_forecast_pre_bias', 'x_studio_mu_pre_bias'])
                zone_field = _first_existing_field(model_obj, ['x_studio_forecast_zone', 'x_studio_z_segment', 'x_studio_zona_forecast', 'x_forecast_zone'])
                series_type_field  = _first_existing_field(model_obj, ['x_studio_series_type'])
                lifecycle_hm_field = _first_existing_field(model_obj, ['x_studio_ciclo_de_vida'])
                # v4.3 motor canonico: regimen y model_code escritos por HM-SI v4.3-revert+.
                regimen_field = _first_existing_field(model_obj, ['x_studio_regimen', 'x_regimen'])
                model_code_field = _first_existing_field(model_obj, ['x_studio_forecast_model_code', 'x_forecast_model_code'])

                domain = [(week_field, '=', lookup_week)]
                if team_field and TEAM_IDS:
                    domain.append((team_field, 'in', TEAM_IDS))

                rows = model_obj.search(domain)
                for rec in rows:
                    try:
                        team_rec = rec[team_field]
                        team_id = team_rec.id if team_rec else False
                    except Exception:
                        team_id = False

                    try:
                        prod_rec = rec[product_field]
                    except Exception:
                        prod_rec = False

                    variant_id = _normalize_product_to_variant_id(prod_rec)
                    if not team_id or not variant_id:
                        continue

                    try:
                        mu = _safe_float(rec[mu_field], 0.0)
                    except Exception:
                        mu = 0.0
                    if mu < 0.0:
                        mu = 0.0

                    key = (team_id, variant_id)
                    out[key] = out.get(key, 0.0) + mu

                    if sigma_field:
                        try:
                            sig = _safe_float(rec[sigma_field], 0.0)
                        except Exception:
                            sig = 0.0
                        if sig < 0.0:
                            sig = 0.0
                        sigma_out[key] = sigma_out.get(key, 0.0) + sig

                    if categ_field:
                        try:
                            c = rec[categ_field]
                            if c:
                                categ_out[key] = c.id
                        except Exception:
                            pass
                    else:
                        cat_id = _product_category_id_by_variant(variant_id)
                        if cat_id:
                            categ_out[key] = cat_id

                    meta = meta_out.get(key, {})
                    if pre_bias_field:
                        try:
                            pre_bias_val = _safe_float(rec[pre_bias_field], 0.0)
                        except Exception:
                            pre_bias_val = 0.0
                        if pre_bias_val < 0.0:
                            pre_bias_val = 0.0
                        meta['mu_week_pre_bias'] = _safe_float(meta.get('mu_week_pre_bias'), 0.0) + pre_bias_val
                    if price_segment_field:
                        try:
                            val = rec[price_segment_field]
                            if val not in (None, False, ''):
                                meta['price_segment'] = val
                        except Exception:
                            pass
                    if zone_field:
                        try:
                            zval = _zone_code(rec[zone_field])
                            if zval:
                                meta['forecast_zone'] = zval
                        except Exception:
                            pass
                    if series_type_field:
                        try:
                            sv = rec[series_type_field]
                            if sv not in (None, False, ''):
                                meta['series_type'] = sv
                        except Exception:
                            pass
                    if lifecycle_hm_field:
                        try:
                            lv = rec[lifecycle_hm_field]
                            if lv not in (None, False, ''):
                                meta['lifecycle'] = lv
                        except Exception:
                            pass
                    if regimen_field:
                        try:
                            rv = rec[regimen_field]
                            if rv not in (None, False, ''):
                                meta['regimen'] = _safe_text(rv, 10)
                        except Exception:
                            pass
                    if model_code_field:
                        try:
                            mv = rec[model_code_field]
                            if mv not in (None, False, ''):
                                meta['forecast_model_code'] = _safe_text(mv, 60)
                        except Exception:
                            pass
                    if meta:
                        meta_out[key] = meta

                return out, sigma_out, categ_out, meta_out

            # ----------------------------------------------------
            # Función: leer señales del forecast viejo
            # ----------------------------------------------------
            def _load_old_segment_rows(lookup_week):
                series_out = {}
                lifecycle_out = {}
                band_out = {}
                cv2_out = {}

                if not OLD_WEEK or not OLD_PRODUCT or not OLD_TEAM:
                    return series_out, lifecycle_out, band_out, cv2_out

                domain = [(OLD_WEEK, '=', lookup_week)]
                if TEAM_IDS:
                    domain.append((OLD_TEAM, 'in', TEAM_IDS))

                rows = OldModel.search(domain)
                for rec in rows:
                    try:
                        team_rec = rec[OLD_TEAM]
                        team_id = team_rec.id if team_rec else False
                    except Exception:
                        team_id = False

                    try:
                        prod_rec = rec[OLD_PRODUCT]
                    except Exception:
                        prod_rec = False

                    variant_id = _normalize_product_to_variant_id(prod_rec)
                    if not team_id or not variant_id:
                        continue

                    key = (team_id, variant_id)

                    cv2_val = None
                    if OLD_CV2:
                        try:
                            cv2_val = _safe_float(rec[OLD_CV2], 0.0)
                        except Exception:
                            cv2_val = None

                    if cv2_val is None and OLD_CV_ALL:
                        try:
                            cv = _safe_float(rec[OLD_CV_ALL], 0.0)
                            cv2_val = cv * cv
                        except Exception:
                            cv2_val = None

                    if cv2_val is not None:
                        if cv2_val < 0.0:
                            cv2_val = 0.0
                        cv2_out[key] = cv2_val

                    density_val = None
                    if OLD_DENSITY:
                        try:
                            density_val = _safe_float(rec[OLD_DENSITY], 0.0)
                        except Exception:
                            density_val = None

                    adi_val = None
                    if OLD_ADI:
                        try:
                            adi_val = _safe_float(rec[OLD_ADI], 999.0)
                        except Exception:
                            adi_val = None

                    st_val = False
                    if OLD_SERIES_TYPE:
                        try:
                            val = rec[OLD_SERIES_TYPE]
                            if val not in (None, False, ''):
                                st_val = val
                        except Exception:
                            st_val = False

                    if not st_val and cv2_val is not None and density_val is not None and adi_val is not None:
                        st_val = _series_type_from_metrics(cv2_val, density_val, adi_val)

                    if st_val not in (None, False, ''):
                        series_out[key] = st_val

                    if OLD_LIFECYCLE:
                        try:
                            val = rec[OLD_LIFECYCLE]
                            if val not in (None, False, ''):
                                lifecycle_out[key] = val
                        except Exception:
                            pass

                    if OLD_SEASONAL_BAND:
                        try:
                            val = rec[OLD_SEASONAL_BAND]
                            if val not in (None, False, ''):
                                band_out[key] = val
                        except Exception:
                            pass

                return series_out, lifecycle_out, band_out, cv2_out

            # ----------------------------------------------------
            # Función: calcular señales de serie desde POS, llave product.product
            # ----------------------------------------------------
            def _load_computed_segment_rows_from_pos(lookup_week):
                series_out = {}
                lifecycle_out = {}
                band_out = {}
                cv2_out = {}

                try:
                    _band = _seasonal_band_for_week(lookup_week.isocalendar()[1])
                except Exception:
                    _band = 'BASE'

                try:
                    env.cr.execute(
                        "SELECT (date_trunc('month', %s::date)::date - interval '24 months')::date",
                        (lookup_week,)
                    )
                    history_from_seg = env.cr.fetchone()[0]
                except Exception:
                    history_from_seg = _week_start(lookup_week) - datetime.timedelta(weeks=104)

                xyz_from_seg = _week_start(lookup_week) - datetime.timedelta(weeks=25)
                if xyz_from_seg < history_from_seg:
                    xyz_from_seg = history_from_seg

                xyz_weeks_seg = _week_range(xyz_from_seg, lookup_week)
                all_weeks_seg = _week_range(history_from_seg, lookup_week)

                q_now_abs = _quarter_abs(lookup_week)
                week_to_q_offset = {}
                for wk in all_weeks_seg:
                    off = q_now_abs - _quarter_abs(wk)
                    if 0 <= off <= 7:
                        week_to_q_offset[wk] = off

                team_filter_sql = ''
                params = {
                    'company_id': company.id,
                    'history_from': history_from_seg,
                    'date_to': lookup_week,
                    'tz': TZ_NAME,
                }
                if TEAM_IDS:
                    team_filter_sql = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '
                    params['team_ids'] = TEAM_IDS

                pt_fields_seg = env['product.template']._fields or {}
                dtype_sql_seg = 'pt.detailed_type' if pt_fields_seg.get('detailed_type') else 'pt.type'

                sql_seg = """
                    WITH base AS (
                        SELECT
                            {team_col} AS team_id,
                            pol.id AS line_id,
                            pol.combo_parent_id,
                            pp.id AS product_id,
                            {dtype_sql} AS dtype,
                            date_trunc('week', po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS week,
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
                          AND {team_col} IS NOT NULL
                          {team_filter}
                    ),
                    standalone AS (
                        SELECT team_id, product_id, week, SUM(qty) AS units
                        FROM base
                        WHERE combo_parent_id IS NULL
                          AND COALESCE(dtype,'') NOT IN ('combo','service')
                        GROUP BY 1,2,3
                    ),
                    combo_children AS (
                        SELECT c.team_id, c.product_id, c.week, SUM(c.qty) AS units
                        FROM base c
                        JOIN base p ON p.line_id = c.combo_parent_id
                        WHERE c.combo_parent_id IS NOT NULL
                          AND COALESCE(c.dtype,'') <> 'service'
                        GROUP BY 1,2,3
                    )
                    SELECT team_id, product_id, week, SUM(units) AS units
                    FROM (
                        SELECT * FROM standalone
                        UNION ALL
                        SELECT * FROM combo_children
                    ) su
                    GROUP BY 1,2,3
                """.format(
                    team_col=team_col_sql,
                    dtype_sql=dtype_sql_seg,
                    team_filter=team_filter_sql,
                )

                env.cr.execute(sql_seg, params)
                raw = env.cr.fetchall()

                data_seg = {}
                for team_id, product_id, wk, qty in raw:
                    ti = _safe_int(team_id)
                    pi = _safe_int(product_id)
                    if not ti or not pi:
                        continue
                    key = (ti, pi)
                    if key not in data_seg:
                        data_seg[key] = {}
                    qv = _safe_float(qty, 0.0)
                    if qv < 0.0:
                        qv = 0.0
                    data_seg[key][wk] = data_seg[key].get(wk, 0.0) + qv

                total_weeks_hist = len(all_weeks_seg)
                total_weeks_xyz = len(xyz_weeks_seg)
                if total_weeks_xyz <= 0:
                    total_weeks_xyz = 1

                for key, wkmap in data_seg.items():
                    qty_vals = []
                    sum_q = 0.0
                    sum_sq = 0.0
                    active_wks = 0
                    for wk in xyz_weeks_seg:
                        qv = _safe_float(wkmap.get(wk, 0.0), 0.0)
                        if qv < 0.0:
                            qv = 0.0
                        qty_vals.append(qv)
                        sum_q += qv
                        sum_sq += qv * qv
                        if qv > 0.0:
                            active_wks += 1

                    mu = sum_q / total_weeks_xyz
                    var = (sum_sq / total_weeks_xyz) - (mu * mu)
                    if var < 0.0:
                        var = 0.0
                    sigma = var ** 0.5
                    cv = (sigma / mu) if mu > 0.0 else 999.0
                    cv2 = cv * cv

                    nonzero_hist = 0
                    u_q = [0.0] * 8
                    for wk in all_weeks_seg:
                        qh = _safe_float(wkmap.get(wk, 0.0), 0.0)
                        if qh > 0.0:
                            nonzero_hist += 1
                            off = week_to_q_offset.get(wk)
                            if off is not None:
                                u_q[off] += qh

                    density = (float(nonzero_hist) / float(total_weeks_hist)) if total_weeks_hist > 0 else 0.0
                    adi = _calc_adi_from_vals(qty_vals)
                    stype = _series_type_from_metrics(cv2, density, adi)

                    p_q8 = 0
                    for uq in u_q:
                        if uq > 0.0:
                            p_q8 += 1

                    local_vol_high = bool(mu < 0.2 or active_wks < 4 or cv > 0.90)
                    lifecycle = _infer_lifecycle_simple(
                        u_q[0], u_q[1], u_q[2], u_q[3],
                        u_q[4], u_q[5], u_q[6], u_q[7],
                        p_q8, local_vol_high
                    )

                    series_out[key] = stype
                    lifecycle_out[key] = lifecycle
                    band_out[key] = _band
                    cv2_out[key] = cv2

                return series_out, lifecycle_out, band_out, cv2_out

            # ----------------------------------------------------
            # Función: leer ABCXYZ por product.product desde x_calculo_abc_xyz
            # ----------------------------------------------------
            def _load_abcxyz_map(product_ids):
                out = {}
                product_ids_clean = []
                for pid in (product_ids or []):
                    pidi = _safe_int(pid, 0)
                    if pidi:
                        product_ids_clean.append(pidi)
                product_ids_clean = list(set(product_ids_clean))
                if not product_ids_clean:
                    return out

                try:
                    AbcModel = env[ABC_MODEL].sudo()
                except Exception:
                    return out

                abc_fields = AbcModel._fields or {}
                product_field = 'x_studio_product_id' if 'x_studio_product_id' in abc_fields else False
                abcxyz_field = 'x_studio_abcxyz' if 'x_studio_abcxyz' in abc_fields else False
                company_field = 'x_studio_company_id' if 'x_studio_company_id' in abc_fields else False
                active_field = 'x_active' if 'x_active' in abc_fields else False

                if not product_field or not abcxyz_field:
                    return out

                product_comodel = ''
                try:
                    product_comodel = abc_fields[product_field].comodel_name or ''
                except Exception:
                    product_comodel = ''

                domain = []
                variant_to_tmpl = {}
                tmpl_to_variants = {}

                if product_comodel == 'product.product':
                    domain = [(product_field, 'in', product_ids_clean)]
                elif product_comodel == 'product.template':
                    # Fallback legacy. La arquitectura objetivo es product.product.
                    variant_to_tmpl = _variant_template_map(product_ids_clean)
                    tmpl_ids = list(set([v for v in variant_to_tmpl.values() if v]))
                    if not tmpl_ids:
                        return out
                    for vid, tid in variant_to_tmpl.items():
                        if tid not in tmpl_to_variants:
                            tmpl_to_variants[tid] = []
                        tmpl_to_variants[tid].append(vid)
                    domain = [(product_field, 'in', tmpl_ids)]
                else:
                    return out

                if company_field:
                    domain.append((company_field, '=', company.id))
                if active_field:
                    domain.append((active_field, '=', True))

                abc_field = 'x_studio_abc' if 'x_studio_abc' in abc_fields else False
                xyz_field = 'x_studio_xyz' if 'x_studio_xyz' in abc_fields else False
                lifecycle_field = 'x_studio_ciclo_de_vida' if 'x_studio_ciclo_de_vida' in abc_fields else False
                importance_field = 'x_studio_importancia' if 'x_studio_importancia' in abc_fields else False
                rank_field = 'x_studio_rank_abcxyz' if 'x_studio_rank_abcxyz' in abc_fields else False
                categ_field = 'x_studio_categ_id' if 'x_studio_categ_id' in abc_fields else False

                try:
                    recs = AbcModel.search(domain, order='write_date desc, id desc')
                except Exception:
                    return out

                seen = {}
                for rec in recs:
                    try:
                        pval = rec[product_field]
                        rid = pval.id if pval else False
                    except Exception:
                        rid = False
                    if not rid:
                        continue

                    variant_ids = []
                    if product_comodel == 'product.product':
                        variant_ids = [_safe_int(rid)]
                    else:
                        variant_ids = tmpl_to_variants.get(_safe_int(rid), [])

                    try:
                        abcxyz_val = rec[abcxyz_field]
                    except Exception:
                        abcxyz_val = False
                    if abcxyz_val in (None, False, ''):
                        continue

                    info = {'abcxyz': abcxyz_val}

                    if abc_field:
                        try:
                            info['abc'] = rec[abc_field]
                        except Exception:
                            pass
                    if xyz_field:
                        try:
                            info['xyz'] = rec[xyz_field]
                        except Exception:
                            pass
                    if lifecycle_field:
                        try:
                            info['lifecycle'] = rec[lifecycle_field]
                        except Exception:
                            pass
                    if importance_field:
                        try:
                            info['importance'] = rec[importance_field]
                        except Exception:
                            pass
                    if rank_field:
                        try:
                            info['rank'] = _safe_int(rec[rank_field], 0)
                        except Exception:
                            pass
                    if categ_field:
                        try:
                            c = rec[categ_field]
                            info['categ_id'] = c.id if c else False
                        except Exception:
                            pass

                    for vid in variant_ids:
                        if not vid or vid in seen:
                            continue
                        seen[vid] = True
                        out[vid] = dict(info)

                return out

            # ----------------------------------------------------
            # Loop principal
            # ----------------------------------------------------
            rows_to_create = []
            total_created = 0
            weeks_done = 0
            methods_done = {}
            hm_total_forecast = 0.0
            hm_total_pre_bias = 0.0
            old_total_forecast = 0.0
            hybrid_total_forecast = 0.0
            real_total_all = 0.0
            abc_loaded_rows = 0
            abc_missing_rows = 0
            zone_metrics = {}
            zone_missing_rows = {}

            _real_from_all = target_weeks[0]
            _real_to_all   = target_weeks[-1] + datetime.timedelta(days=6)
            all_real_map = _load_real_sales_batched(_real_from_all, _real_to_all)

            for target_week_start in target_weeks:
                cutoff_date = target_week_start - datetime.timedelta(days=1)
                real_from = target_week_start
                real_to = target_week_start + datetime.timedelta(days=6)

                real_map = all_real_map.get(target_week_start, {})

                series_map = {}
                lifecycle_map = {}
                seasonal_band_map = {}
                cv2_map = {}

                methods = []
                hm_forecast = {}
                hm_sigma = {}
                hm_categ = {}
                hm_meta = {}
                old_forecast = {}
                old_sigma = {}
                old_categ = {}
                old_meta = {}
                hm_zone_map = {}

                if not forecast_warnings or 'HM-SI campos incompletos' not in forecast_warnings:
                    _run_forecast_action(HM_SI_ACTION_ID, cutoff_date)
                    hm_forecast, hm_sigma, hm_categ, hm_meta = _load_forecast_rows(
                        HmModel, HM_WEEK, HM_PRODUCT, HM_TEAM, HM_MU, HM_SIGMA, HM_CATEG, target_week_start
                    )
                    for _k, _meta in hm_meta.items():
                        z = _zone_code((_meta or {}).get('forecast_zone', ZONE_MISSING))
                        if z != ZONE_MISSING:
                            hm_zone_map[_k] = z
                    methods.append(('hm_si', hm_forecast, hm_sigma, hm_categ, hm_meta, True))
                    for _k, _v in hm_forecast.items():
                        hm_total_forecast += _safe_float(_v, 0.0)
                        hm_total_pre_bias += _safe_float((hm_meta.get(_k, {}) or {}).get('mu_week_pre_bias', _v), 0.0)

                if (OLD_FORECAST_ACTION_ID and OLD_FORECAST_ACTION_ID > 0) or LOAD_EXISTING_OLD_WHEN_NO_ACTION:
                    if 'OLD campos incompletos' not in forecast_warnings:
                        if OLD_FORECAST_ACTION_ID and OLD_FORECAST_ACTION_ID > 0:
                            _run_forecast_action(OLD_FORECAST_ACTION_ID, cutoff_date)
                        old_forecast, old_sigma, old_categ, old_meta = _load_forecast_rows(
                            OldModel, OLD_WEEK, OLD_PRODUCT, OLD_TEAM, OLD_MU, OLD_SIGMA, OLD_CATEG, cutoff_date
                        )
                        methods.append(('old', old_forecast, old_sigma, old_categ, old_meta, True))
                        for _v in old_forecast.values():
                            old_total_forecast += _safe_float(_v, 0.0)

                        series_map, lifecycle_map, seasonal_band_map, cv2_map = _load_old_segment_rows(cutoff_date)

                for _k, _m in hm_meta.items():
                    if not series_map.get(_k):
                        st = (_m or {}).get('series_type')
                        if st:
                            series_map[_k] = st
                    if not lifecycle_map.get(_k):
                        lc = (_m or {}).get('lifecycle')
                        if lc:
                            lifecycle_map[_k] = lc

                _real_week_sum = 0.0
                for _v in real_map.values():
                    _real_week_sum += _safe_float(_v, 0.0)
                real_total_all += _real_week_sum

                if hm_forecast and old_forecast:
                    hybrid_forecast = {}
                    hybrid_sigma = {}
                    hybrid_categ = {}
                    hybrid_meta = {}
                    hybrid_keys = {}
                    for _k in real_map.keys():
                        hybrid_keys[_k] = True
                    for _k in hm_forecast.keys():
                        hybrid_keys[_k] = True
                    for _k in old_forecast.keys():
                        hybrid_keys[_k] = True

                    for _k in hybrid_keys.keys():
                        z = _zone_code(hm_zone_map.get(_k, ZONE_MISSING))
                        if z in ('Z1', 'Z2'):
                            hybrid_forecast[_k] = _safe_float(hm_forecast.get(_k, 0.0), 0.0)
                            hybrid_sigma[_k] = _safe_float(hm_sigma.get(_k, 0.0), 0.0)
                            hybrid_categ[_k] = hm_categ.get(_k, False) or old_categ.get(_k, False)
                            hybrid_meta[_k] = {'forecast_zone': z, 'hybrid_source': 'hm_si'}
                        elif z in ('Z3', 'Z4'):
                            hybrid_forecast[_k] = _safe_float(old_forecast.get(_k, 0.0), 0.0)
                            hybrid_sigma[_k] = _safe_float(old_sigma.get(_k, 0.0), 0.0)
                            hybrid_categ[_k] = old_categ.get(_k, False) or hm_categ.get(_k, False)
                            hybrid_meta[_k] = {'forecast_zone': z, 'hybrid_source': 'old'}

                    if hybrid_forecast:
                        methods.append((HYBRID_METHOD_CODE, hybrid_forecast, hybrid_sigma, hybrid_categ, hybrid_meta, hybrid_rows_enabled))
                        for _v in hybrid_forecast.values():
                            hybrid_total_forecast += _safe_float(_v, 0.0)

                _abc_pids = list(set(
                    k[1] for k in list(hm_forecast.keys()) + list(old_forecast.keys()) + list(real_map.keys())
                ))
                abcxyz_map = _load_abcxyz_map(_abc_pids)

                for method_code, forecast_map, sigma_map, categ_map, meta_map, create_method_rows in methods:
                    methods_done[method_code] = methods_done.get(method_code, 0) + 1

                    all_keys = {}
                    for k in forecast_map.keys():
                        all_keys[k] = True
                    for k in real_map.keys():
                        all_keys[k] = True

                    for key in all_keys.keys():
                        team_id = key[0]
                        product_id = key[1]

                        forecast_qty = _safe_float(forecast_map.get(key, 0.0), 0.0)
                        real_qty = _safe_float(real_map.get(key, 0.0), 0.0)
                        sigma_qty = _safe_float(sigma_map.get(key, 0.0), 0.0)
                        price_meta = meta_map.get(key, {}) if meta_map else {}
                        forecast_pre_bias_qty = forecast_qty
                        if method_code == 'hm_si':
                            forecast_pre_bias_qty = _safe_float(price_meta.get('mu_week_pre_bias', forecast_qty), forecast_qty)
                            if forecast_pre_bias_qty < 0.0:
                                forecast_pre_bias_qty = 0.0
                        forecast_zone = _zone_code(hm_zone_map.get(key, ZONE_MISSING))
                        if forecast_zone == ZONE_MISSING and method_code == 'hm_si':
                            forecast_zone = _zone_code(price_meta.get('forecast_zone', ZONE_MISSING))
                        if forecast_zone == ZONE_MISSING:
                            zone_missing_rows[method_code] = zone_missing_rows.get(method_code, 0) + 1

                        error_qty = real_qty - forecast_qty
                        abs_error_qty = abs(error_qty)
                        _accum_metric(zone_metrics, method_code, forecast_zone, forecast_qty, real_qty)

                        if real_qty > 0.0:
                            ape = abs_error_qty / real_qty
                            bias = error_qty / real_qty
                            valid_for_error = True
                        else:
                            ape = 0.0
                            bias = 0.0
                            valid_for_error = False

                        if forecast_qty > 0.0 and real_qty > 0.0:
                            bucket = 'vendio_y_forecast'
                        elif forecast_qty > 0.0 and real_qty <= 0.0:
                            bucket = 'forecast_sin_venta'
                        elif forecast_qty <= 0.0 and real_qty > 0.0:
                            bucket = 'venta_sin_forecast'
                        else:
                            bucket = 'sin_movimiento'

                        rec_name = '%s | %s | T%s | P%s' % (method_code, target_week_start, team_id, product_id)

                        vals = {}
                        _put_if_field(vals, Backtest, BT_NAME, rec_name)
                        _put_if_field(vals, Backtest, BT_WEEK, target_week_start)
                        _put_if_field(vals, Backtest, BT_CUTOFF, cutoff_date)
                        _put_if_field(vals, Backtest, BT_PRODUCT, product_id)
                        _put_if_field(vals, Backtest, BT_TEAM, team_id)
                        _put_selection_safe(vals, Backtest, BT_METHOD, method_code)

                        _put_if_field(vals, Backtest, BT_FORECAST, forecast_qty)
                        if method_code == 'hm_si':
                            _put_if_field(vals, Backtest, BT_MU_PRE_BIAS, forecast_pre_bias_qty)
                        _put_if_field(vals, Backtest, BT_REAL, real_qty)
                        _put_if_field(vals, Backtest, BT_ERROR, error_qty)
                        _put_if_field(vals, Backtest, BT_ABS_ERROR, abs_error_qty)
                        _put_if_field(vals, Backtest, BT_APE, ape)
                        _put_if_field(vals, Backtest, BT_BIAS, bias)
                        _put_if_field(vals, Backtest, BT_SIGMA, sigma_qty)

                        if BT_COMPANY:
                            vals[BT_COMPANY] = company.id

                        abc_info = abcxyz_map.get(product_id) or {}
                        if create_method_rows:
                            if abc_info.get('abcxyz'):
                                abc_loaded_rows += 1
                            else:
                                abc_missing_rows += 1

                        if BT_CATEG:
                            categ_id = categ_map.get(key, False)
                            if not categ_id:
                                categ_id = abc_info.get('categ_id', False)
                            if not categ_id:
                                categ_id = _product_category_id_by_variant(product_id)
                            vals[BT_CATEG] = categ_id or False

                        if BT_SERIES_TYPE:
                            _put_selection_safe(vals, Backtest, BT_SERIES_TYPE, series_map.get(key, False))

                        if BT_LIFECYCLE:
                            # Preferimos ciclo de vida global ABCXYZ si existe; si no, fallback local calculado.
                            _put_selection_safe(vals, Backtest, BT_LIFECYCLE, abc_info.get('lifecycle') or lifecycle_map.get(key, False))

                        if BT_ABCXYZ:
                            _put_selection_safe(vals, Backtest, BT_ABCXYZ, abc_info.get('abcxyz', False))
                        if BT_ABC:
                            _put_selection_safe(vals, Backtest, BT_ABC, abc_info.get('abc', False))
                        if BT_XYZ:
                            _put_selection_safe(vals, Backtest, BT_XYZ, abc_info.get('xyz', False))
                        if BT_IMPORTANCE:
                            _put_selection_safe(vals, Backtest, BT_IMPORTANCE, abc_info.get('importance', False))
                        if BT_RANK_ABCXYZ:
                            rank_val = abc_info.get('rank', 0)
                            if rank_val:
                                _put_if_field(vals, Backtest, BT_RANK_ABCXYZ, rank_val)

                        if BT_CV2:
                            _put_if_field(vals, Backtest, BT_CV2, cv2_map.get(key, 0.0))

                        if BT_PRICE_SEGMENT:
                            _put_selection_safe(vals, Backtest, BT_PRICE_SEGMENT, price_meta.get('price_segment', False))

                        if BT_FORECAST_ZONE:
                            _put_selection_safe(vals, Backtest, BT_FORECAST_ZONE, forecast_zone)

                        # v11.1: regimen y model_code leidos de HM-SI v4.3+.
                        # Solo se persisten para method_code='hm_si' (otros metodos
                        # como old/hybrid no tienen regimen aplicable).
                        if method_code == 'hm_si':
                            if BT_REGIMEN:
                                _regimen_val = price_meta.get('regimen', '')
                                if _regimen_val:
                                    _put_selection_safe(vals, Backtest, BT_REGIMEN, _regimen_val)
                            if BT_FORECAST_MODEL_CODE:
                                _mc_val = _safe_text(price_meta.get('forecast_model_code', ''), 60)
                                if _mc_val:
                                    _put_if_field(vals, Backtest, BT_FORECAST_MODEL_CODE, _mc_val)

                        if BT_VALID:
                            vals[BT_VALID] = valid_for_error

                        if BT_BUCKET:
                            _put_selection_safe(vals, Backtest, BT_BUCKET, bucket)

                        if create_method_rows:
                            rows_to_create.append(vals)

                        if create_method_rows and len(rows_to_create) >= BATCH_SIZE:
                            Backtest.create(rows_to_create)
                            total_created += len(rows_to_create)
                            rows_to_create = []

                weeks_done += 1

            if rows_to_create:
                Backtest.create(rows_to_create)
                total_created += len(rows_to_create)
                rows_to_create = []

            zone_summary = _format_zone_metrics(zone_metrics)
            zone_missing_summary = ','.join([str(k) + ':' + str(v) for k, v in zone_missing_rows.items()])

            try:
                log(
                    '%s | purged=%s | weeks=%s | created=%s | methods=%s | teams=%s | hm_fcst=%s | hm_pre_bias=%s | old_fcst=%s | hybrid_fcst=%s | real_sum=%s | abc_loaded=%s | abc_missing=%s | zone_missing=%s | zone_metrics=%s | warnings=%s' % (
                        VERSION_ID,
                        purge_count,
                        weeks_done,
                        total_created,
                        ','.join(methods_done.keys()),
                        len(TEAM_IDS),
                        round(hm_total_forecast, 2),
                        round(hm_total_pre_bias, 2),
                        round(old_total_forecast, 2),
                        round(hybrid_total_forecast, 2),
                        round(real_total_all, 2),
                        abc_loaded_rows,
                        abc_missing_rows,
                        zone_missing_summary,
                        zone_summary,
                        ','.join(forecast_warnings),
                    ),
                    level='info'
                )
            except Exception:
                pass

            msg = 'Backtest creado: semanas=%s | filas=%s | metodos=%s | HM=%s | HMpre=%s | OLD=%s | HYB=%s | Real=%s | ABC cargado=%s | ABC faltante=%s' % (
                weeks_done,
                total_created,
                ','.join(methods_done.keys()),
                round(hm_total_forecast, 0),
                round(hm_total_pre_bias, 0),
                round(old_total_forecast, 0),
                round(hybrid_total_forecast, 0),
                round(real_total_all, 0),
                abc_loaded_rows,
                abc_missing_rows,
            )
            if zone_summary:
                msg += ' | Z: ' + zone_summary[:900]
            if zone_missing_summary:
                msg += ' | SIN_ZONA: ' + zone_missing_summary
            if forecast_warnings:
                msg += ' | WARN: ' + ','.join(forecast_warnings)

            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Forecast Backtest v10.4 pre-bias',
                    'message': msg,
                    'type': 'success' if not forecast_warnings else 'warning',
                    'sticky': True,
                }
            }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
