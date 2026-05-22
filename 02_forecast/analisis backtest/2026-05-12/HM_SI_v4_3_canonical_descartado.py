# ============================================================
# HM SI Forecast — Motor canónico v4.3 (revert a 2 ciclos)
# ============================================================
# VERSION_ID = "FWD_v4_3_REVERT_2CICLOS"
#
# Cambio v4.3-revert (revierte el v4.3 con 3 ciclos):
#   DEMAND_HISTORY_MONTHS volvió a 24 (era 36) y DEMAND_WINDOW_WEEKS volvió
#   a 104 (era 156). La justificación teórica de Hyndman et al. para 3
#   ciclos es válida en datasets estacionarios, pero ignora que en retail
#   los años viejos pueden contaminar el modelo si hubo cambios
#   estructurales (mix, precios, locales, proveedores, política comercial).
#   Se prefiere ventana operativa más reciente y representativa.
#
#   La pregunta sobre qué tan estable es la señal (HW aplicado a SKUs
#   con 104 semanas pero pocos puntos con venta real) queda pendiente
#   para v4.4 (gate de señal por ciclo).
#
# Cambio v4.1 → v4.2:
#   1) DEMAND_WINDOW_WEEKS pasó de 52 a 104. Con 52 semanas,
#      _fc_holt_winters caía silenciosamente al fallback Holt doble
#      (porque n < 2*m=104) y nunca se activaba el componente seasonal S.
#      Crítico para retail Chile (verano alto, fiestas patrias, halloween,
#      fin de año). Ahora HW triple corre con 2 ciclos completos.
#   2) Fix de reporting: forecast_model_code ahora reporta honestamente
#      cuando un régimen HW cayó al fallback Holt doble por history corta.
#      Valor: 'holt_doble_fb_REG-X' en lugar de fingir 'hw_*'.
#
# Cambio v4.0 → v4.1:
#   REG-6 y REG-7 pasaron de Croston puro a SBA (Syntetos-Boylan 2005).
#   Croston tiene sesgo positivo demostrado de α/2; SBA lo corrige con
#   factor (1 - α/2). La protección contra stockout para productos C se
#   modela explícitamente en safety stock downstream (z_α × σ_h × √L),
#   no inflando el forecast point.
#
# Cambio respecto a v3.24:
#   Motor de forecast reescrito sobre la teoría establecida.
#   Cada SKU aplica el modelo canónico correspondiente a su régimen ABCXYZ.
#
#   Régimen → Modelo:
#     REG-0 (terminales)          → forecast = 0
#     REG-1/2/3 (smooth A/B/C)    → Holt-Winters triple (Winters 1960)
#     REG-4 (erratic)             → Holt-Winters triple α alto
#     REG-5 (lumpy A/B)           → SBA α=0.15 (Syntetos-Boylan 2005)
#     REG-6 (lumpy C)             → SBA α=0.10
#     REG-7 (intermittent)        → SBA α=0.05
#     REG-8 (seasonal)            → Holt-Winters triple γ dominante
#
#   Eliminado del v3.24:
#     - Router de zonas Z1-Z4 (reemplazado por régimen leído de ABCXYZ)
#     - Caps P1-P6 (precedencia REG-0 cubre dead/declining; resto se
#       controla por el cap natural del modelo canónico)
#     - SI custom (HW lo internaliza)
#     - Price adjustment (eventos → Fase 2 como outliers)
#     - PRICE_FACTOR_TABLE_L2 (idem)
#
#   Preservado del v3.24:
#     - Lock advisory + HARD_RESET + purge
#     - Query POS multi-team con combo handling
#     - Validación de schema x_hm_si_forecast
#     - Granularidad de salida: (team, product, target_week)
#     - Columnas que el backtest consume: mu_week, mu_week_pre_bias,
#       sigma_week, forecast_zone, abcxyz, series_type, ciclo_de_vida
#
#   Cambio de SEMANTICA en forecast_zone:
#     - Antes: Z1, Z2, Z3, Z4 (zonas del router viejo).
#     - Ahora: REG-0..REG-8 (los 9 regímenes canónicos).
#     - La columna sigue siendo "zone" por nombre, pero su contenido es
#       el régimen. Esto preserva el filtrado del backtest pero con la
#       nueva dimensión de segmentación.
#
#   Nueva columna escrita (redundante con forecast_zone, por claridad):
#     - x_studio_regimen (REG-0..REG-8)
#
#   TODO Fase 2:
#     - Detector de outliers Hampel (winsorización pre-modelo) para neutralizar
#       semanas con promo/quiebre/evento pasado
#     - Capa de ajuste post-forecast por eventos planificados futuros
#       (promos programadas, descuentos publicados) usando x_price_change_event
#
# Referencia: AGENTS.md → Referencias Canonicas → Forecast operativo.
# ============================================================

VERSION_ID = "FWD_v4_3_REVERT_2CICLOS"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009438


# ----------------------
# Parametros base
# ----------------------
FWD_MODEL_DEFAULT = 'x_hm_si_forecast'

HARD_RESET_DEFAULT = True
FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

DEMAND_HISTORY_MONTHS_DEFAULT = 24   # 2 anos. La ventana mas larga (3 anos)
                                     # contamina si hubo cambios estructurales
                                     # (mix, precios, locales, proveedores).
                                     # Se prefiere data reciente y representativa.
DEMAND_WINDOW_WEEKS_DEFAULT   = 104  # 2 ciclos completos. Minimo para que
                                     # _fc_holt_winters active componente seasonal
                                     # (n >= 2*m=104). Con 52 semanas caia al
                                     # fallback Holt doble silenciosamente.
BATCH_SIZE = 500

TARGET_WEEKS_AHEAD_DEFAULT = 1   # horizonte de forecast (h)
SEASONAL_PERIOD = 52              # weekly anual


# ============================================================
# Modelos canónicos de forecast — Python puro, sin dependencias
# ============================================================
# Holt (1957), Winters (1960), Croston (1972), Syntetos-Boylan (2005).
# Tests unitarios en analisis backtest/2026-05-12/_forecast_models.py
# reproducen casos canónicos del paper.
# ============================================================

def _fc_holt_doble(history, alpha=0.2, beta=0.1, h=1):
    """Holt linear exp smoothing (1957). Level + trend, sin seasonal."""
    n = len(history)
    if n == 0:
        return 0.0
    if n == 1:
        return max(0.0, float(history[0]))
    L = float(history[0])
    T = float(history[1] - history[0])
    for t in range(1, n):
        y = float(history[t])
        L_prev = L
        L = alpha * y + (1.0 - alpha) * (L + T)
        T = beta * (L - L_prev) + (1.0 - beta) * T
    f = L + h * T
    return max(0.0, f)


def _fc_holt_winters(history, m=52, alpha=0.2, beta=0.1, gamma=0.15, h=1):
    """Triple exp smoothing multiplicativo (Winters 1960).

    Fallback automático a Holt doble si len(history) < 2m.
    """
    n = len(history)
    if n < 2 * m:
        return _fc_holt_doble(history, alpha=alpha, beta=beta, h=h)

    L = sum(history[:m]) / m
    T = (sum(history[m:2*m]) / m - sum(history[:m]) / m) / m
    S = [(history[i] / L) if L > 0 else 1.0 for i in range(m)]

    for t in range(n):
        y = float(history[t])
        idx = t % m
        L_prev = L
        S_prev = S[idx] if S[idx] > 0 else 1.0
        L = alpha * (y / S_prev) + (1.0 - alpha) * (L + T)
        T = beta * (L - L_prev) + (1.0 - beta) * T
        S[idx] = (gamma * (y / L) + (1.0 - gamma) * S_prev) if L > 0 else S_prev

    idx_future = (n - 1 + h) % m
    f = (L + h * T) * S[idx_future]
    return max(0.0, f)


def _fc_croston(history, alpha=0.1, h=1):
    """Croston (1972). Demanda intermitente: z (size) / p (interval)."""
    n = len(history)
    if n == 0:
        return 0.0
    z = None
    p = None
    q = 0
    for t in range(n):
        y = float(history[t])
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


def _fc_sba(history, alpha=0.1, h=1):
    """Syntetos-Boylan Approximation (2005). Croston corregido por sesgo."""
    base = _fc_croston(history, alpha=alpha, h=h)
    return (1.0 - alpha / 2.0) * base


def _fc_dispatch(regimen, history, m=52, h=1):
    """Selecciona modelo canónico según régimen ABCXYZ.

    Returns (forecast, model_code) donde model_code es identificador
    HONESTO del modelo realmente aplicado. Si el régimen pide HW pero
    len(history) < 2*m, reporta 'holt_doble_fb_<REGIMEN>' para que el
    backtest sepa que el componente seasonal no se activó.
    """
    if regimen == 'REG-0' or not history:
        return 0.0, 'no_forecast'

    # Regimenes que requieren HW triple (necesitan 2 ciclos para inicializar S).
    hw_regimes = ('REG-1', 'REG-2', 'REG-3', 'REG-4', 'REG-8')
    n = len(history)
    if regimen in hw_regimes and n < 2 * m:
        # Fallback explícito a Holt doble con reporting honesto.
        forecast = _fc_holt_doble(history, alpha=0.20, beta=0.10, h=h)
        return forecast, 'holt_doble_fb_' + regimen

    if regimen == 'REG-1':
        return _fc_holt_winters(history, m=m, alpha=0.20, beta=0.10, gamma=0.15, h=h), 'hw_a020_b010_g015'
    if regimen == 'REG-2':
        return _fc_holt_winters(history, m=m, alpha=0.25, beta=0.10, gamma=0.15, h=h), 'hw_a025_b010_g015'
    if regimen == 'REG-3':
        return _fc_holt_winters(history, m=m, alpha=0.30, beta=0.10, gamma=0.10, h=h), 'hw_a030_b010_g010'
    if regimen == 'REG-4':
        return _fc_holt_winters(history, m=m, alpha=0.40, beta=0.10, gamma=0.15, h=h), 'hw_a040_b010_g015'
    if regimen == 'REG-5':
        return _fc_sba(history, alpha=0.15, h=h), 'sba_a015'
    if regimen == 'REG-6':
        return _fc_sba(history, alpha=0.10, h=h), 'sba_a010'
    if regimen == 'REG-7':
        return _fc_sba(history, alpha=0.05, h=h), 'sba_a005'
    if regimen == 'REG-8':
        return _fc_holt_winters(history, m=m, alpha=0.20, beta=0.05, gamma=0.30, h=h), 'hw_seasonal_a020_g030'
    return _fc_holt_doble(history, alpha=0.20, beta=0.10, h=h), 'holt_doble_fallback'


# ----------------------
# Helpers básicos
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


def _norm_txt(v, maxlen=80):
    return _safe_text(v, maxlen).strip().lower()


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
# Lectura ABCXYZ — incluye régimen v19.x
# ----------------------
def _load_forecast_router_context(product_ids):
    """Lee atributos de clasificación desde x_calculo_abc_xyz.

    Returns dict {product_id: {'abcxyz', 'series_type', 'lifecycle', 'regimen'}}.
    Compatible con modelos viejos (regimen vacío si el campo no existe → fallback
    en el dispatcher).
    """
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
    regimen_field = _first_field(Abc, ['x_studio_regimen', 'x_regimen'])
    company_field = _first_field(Abc, ['x_studio_company_id', 'x_company_id'])
    active_field = _first_field(Abc, ['x_active', 'x_studio_active', 'active'])

    read_fields = [product_field]
    for f in [abcxyz_field, series_field, lifecycle_field, regimen_field]:
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
            'regimen': _safe_text(r.get(regimen_field), 10) if regimen_field else '',
        }
    return out


def _fallback_regimen(abcxyz, series_type, lifecycle):
    """Asigna régimen cuando ABCXYZ no lo escribió. Misma lógica que en
    1- OH Calculo ABCXYZ.py _assign_regimen(). Garantiza que HM-SI funcione
    aunque ABCXYZ esté en versión vieja.
    """
    abc_letter = (abcxyz or '')[:1].upper()
    s = (series_type or '').strip().lower()
    c = (lifecycle or '').strip().lower()
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
        return 'REG-5' if abc_letter in ('A', 'B') else 'REG-6'
    if s in ('intermittent', 'no_signal'):
        return 'REG-7'
    return 'REG-0'


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
TARGET_WEEKS_AHEAD = int(CTX.get('target_weeks_ahead', TARGET_WEEKS_AHEAD_DEFAULT))

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
            'title': 'HM_SI_WEEKLY v4.3',
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
            'title': 'HM_SI_WEEKLY v4.3',
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

        if not active_product_ids:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'HM_SI_WEEKLY v4.3',
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
                        'title': 'HM_SI_WEEKLY v4.3',
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
                    'history_from': history_from,
                    'date_to': date_to,
                    'tz': TZ_NAME,
                }
                if TEAM_IDS:
                    params['team_ids'] = TEAM_IDS

                env.cr.execute(sql_sales, params)

                data = {}
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
                    team_ids_found.add(team_i)
                    key = (team_i, pid)
                    data.setdefault(key, {})
                    row = data[key].get(wk)
                    if row:
                        row[0] += r
                        row[1] += q
                    else:
                        data[key][wk] = [r, q]

                local_pairs = sorted(data.keys())

                # ----------------------
                # Cargar régimen + atributos de ABCXYZ
                # ----------------------
                product_ids_used = list(set([p for _, p in local_pairs]))
                router_ctx = _load_forecast_router_context(product_ids_used)

                # ----------------------
                # Setup loop principal
                # ----------------------
                batch = []
                total_created = 0
                regimen_counts = {}
                model_counts = {}

                fwd_create = FWD.with_context(
                    tracking_disable=True,
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                    mail_notrack=True,
                ).create

                target_date = _week_start(date_to) + datetime.timedelta(weeks=max(TARGET_WEEKS_AHEAD, 1))

                for team_id, product_id in local_pairs:
                    categ_id = product_to_categ.get(product_id)
                    if not product_id or product_id not in active_product_ids:
                        continue

                    wkmap = data.get((team_id, product_id)) or {}

                    # Construir history ordenada por fecha (oldest first) sobre la ventana de demanda.
                    qty_history = []
                    total_units = 0.0
                    total_revenue = 0.0
                    for wk in demand_weeks_list:
                        row = wkmap.get(wk)
                        q = _safe_float((row and row[1]) or 0.0, 0.0)
                        if q < 0.0:
                            q = 0.0
                        r = _safe_float((row and row[0]) or 0.0, 0.0)
                        qty_history.append(q)
                        total_units += q
                        total_revenue += r

                    # Recuperar atributos de ABCXYZ; fallback si la corrida de ABCXYZ
                    # es v18 (sin campo regimen).
                    rctx = router_ctx.get(product_id, {})
                    abcxyz = rctx.get('abcxyz', '')
                    series_type = rctx.get('series_type', '')
                    lifecycle = rctx.get('lifecycle', '')
                    regimen = rctx.get('regimen', '') or _fallback_regimen(abcxyz, series_type, lifecycle)

                    regimen_counts[regimen] = regimen_counts.get(regimen, 0) + 1

                    # Forecast canónico según régimen.
                    forecast_value, model_code = _fc_dispatch(
                        regimen,
                        qty_history,
                        m=SEASONAL_PERIOD,
                        h=TARGET_WEEKS_AHEAD,
                    )
                    model_counts[model_code] = model_counts.get(model_code, 0) + 1

                    mu_week = max(0.0, _safe_float(forecast_value, 0.0))

                    # sigma como std de la historia (Brown 1959); sirve para safety stock
                    # downstream, no para el forecast point.
                    _, sigma_week = _avg_std(qty_history)

                    rec_name = 'HM-SI LOC%s PP%s' % (team_id, product_id)

                    vals = {}
                    if 'x_name' in fwd_fields:
                        vals['x_name'] = rec_name

                    _put_field(vals, fwd_fields, 'x_studio_product_id', product_id)
                    _put_field(vals, fwd_fields, 'x_studio_team_id', team_id)
                    _put_field(vals, fwd_fields, 'x_studio_categ_id', categ_id)
                    _put_field(vals, fwd_fields, 'x_studio_week_start', target_date)

                    # Forecast point: backtest lee mu_week como predicción
                    _put_field(vals, fwd_fields, 'x_studio_mu_week', mu_week)
                    # pre_bias = mu_week porque ya no hay clamps P1-P6 que difieran
                    _put_field(vals, fwd_fields, 'x_studio_mu_week_pre_bias', mu_week)
                    _put_field(vals, fwd_fields, 'x_studio_sigma_week', sigma_week)

                    # Columnas legacy del v3.24 mantenidas para compatibilidad con backtest.
                    # mu_base = mu_week (ya no hay desestacionalización previa).
                    _put_field(vals, fwd_fields, 'x_studio_mu_base', mu_week)
                    _put_field(vals, fwd_fields, 'x_studio_sigma_base', sigma_week)
                    # SI integrado en el modelo canónico → exposición neutra.
                    _put_field(vals, fwd_fields, 'x_studio_si_current', 1.0)
                    _put_field(vals, fwd_fields, 'x_studio_si_next', 1.0)
                    _put_field(vals, fwd_fields, 'x_studio_si_n_years', 0)

                    # Atributos de clasificación (críticos para backtest analizar por regimen).
                    # forecast_zone ahora lleva el régimen (REG-0..REG-8) — los 9 valores nuevos
                    # reemplazan las viejas zonas Z1-Z4. Es la dimensión de segmentación del modelo.
                    _put_field(vals, fwd_fields, 'x_studio_forecast_zone', regimen, 10)
                    _put_field(vals, fwd_fields, 'x_studio_regimen', regimen, 10)
                    _put_field(vals, fwd_fields, 'x_studio_forecast_model_code', model_code, 60)
                    _put_field(vals, fwd_fields, 'x_studio_abcxyz', abcxyz, 10)
                    _put_field(vals, fwd_fields, 'x_studio_series_type', series_type, 20)
                    _put_field(vals, fwd_fields, 'x_studio_ciclo_de_vida', lifecycle, 40)

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
                        'HM_SI_WEEKLY v4.3 | purged=%s | created=%s | teams=%s | sku_local=%s'
                        ' | active_products=%s | hist=%s->%s'
                        ' | regimen=%s | model=%s' % (
                            purge_count,
                            total_created,
                            len(team_ids_found),
                            len(local_pairs),
                            len(active_product_ids),
                            history_from,
                            date_to,
                            ','.join([str(k)+':'+str(v) for k, v in sorted(regimen_counts.items())]),
                            ','.join([str(k)+':'+str(v) for k, v in sorted(model_counts.items())]),
                        ),
                        level='info'
                    )
                except Exception:
                    pass

                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'HM_SI_WEEKLY v4.3',
                        'message': 'created=%s | sku_local=%s | regimen=%s' % (
                            total_created,
                            len(local_pairs),
                            ','.join([str(k)+':'+str(v) for k, v in sorted(regimen_counts.items())]),
                        ),
                        'sticky': True,
                        'type': 'success',
                    }
                }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))

