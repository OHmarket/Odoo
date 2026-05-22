# ============================================================
# OH POS Venta Semanal por SKU — MODELO FINAL SIMPLE + BANDAS
# ------------------------------------------------------------
# Modelo destino: x_pos_week_sku_sale
# Grano:
#   company + team(local) + week_start + categ_id + product_id
#
# Campos base:
#   - x_studio_qty_sold     = SUM(pos_order_line.qty)
#   - x_studio_sales_gross  = SUM(pos_order_line.price_subtotal_incl)
#   - x_studio_week_start   = lunes de la semana local America/Santiago
#   - x_studio_week_end     = domingo de la semana local America/Santiago
#
# Campo principal nuevo, independiente de feriados:
#   REQUERIDO:
#   - x_studio_response_vs_category_pct  Float
#     = crecimiento SKU vs LY - crecimiento categoría vs LY
#   - x_studio_seasonal_band             Char o Selection
#     = banda estacional calculada desde ISO week
#
#   CAMPOS ACTUALES CONFIRMADOS EN MODELO:
#   - x_studio_iso_week                Integer
#   - x_studio_is_base_week            Boolean
#   - x_studio_seasonal_context        Char
#   - x_studio_holiday_in_band_key     Char
#   - x_studio_has_holiday             Boolean
#   - x_studio_holiday_days            Integer
#
#   CAMPOS OPCIONALES FUTUROS, si decides auditar más detalle:
#   - x_studio_sku_growth_qty_pct      Float
#   - x_studio_categ_growth_qty_pct    Float
#   - x_studio_qty_sold_ly             Float
#   - x_studio_categ_qty_sold          Float
#   - x_studio_categ_qty_sold_ly       Float
#   - x_studio_has_valid_ly_base       Boolean
#
#   OPCIONALES para respuesta en monto bruto:
#   - x_studio_response_gross_vs_category_pct Float
#   - x_studio_sku_growth_gross_pct           Float
#   - x_studio_categ_growth_gross_pct         Float
#   - x_studio_sales_gross_ly                 Float
#   - x_studio_categ_sales_gross              Float
#   - x_studio_categ_sales_gross_ly           Float
#
#   OPCIONAL compatibilidad versión anterior:
#   - x_studio_holiday_response_pct     Float
#
# Definición:
#   sku_growth_qty   = qty_sku_semana / qty_sku_semana_LY_364 - 1
#   categ_growth_qty = qty_categoria_semana / qty_categoria_semana_LY_364 - 1
#   response_vs_category = sku_growth_qty - categ_growth_qty
#
# Interpretación:
#   +0.20 = el SKU creció 20 puntos porcentuales más que su categoría.
#   -0.15 = el SKU creció 15 puntos porcentuales menos que su categoría.
#
# Este cálculo se hace para TODAS las semanas con base LY válida.
# Las bandas estacionales y feriados quedan como atributos de contexto
# para filtrar/explicar la respuesta del SKU.
# LY se compara con -364 días para conservar el mismo día de semana.
#
# Fuente feriados:
#   1) Contexto opcional: {'holiday_dates': ['2025-01-01', ...]}
#   2) Modelo por defecto: x_holiday_occurrence.x_studio_holiday_date
#   3) Relación esperada: x_holiday_occurrence.x_studio_holiday_id -> x_holiday_master
#   4) Desde x_holiday_master toma, si existen:
#      código, tipo de feriado e irrenunciable.
#   5) Contexto opcional: {'holiday_model': 'x_nombre_modelo'}
#
# SAFE_EVAL friendly — Odoo Server Action / Acción Planificada
# v11 incorpora estándar calendario OH para que todos los scripts semanales sean comparables.
# Mantiene compatibilidad safe_eval: sin lambdas, sin closures y sin nested functions.
# Requiere que datetime esté disponible en el contexto de Server Action.
# ============================================================

VERSION_ID = 'OH_POS_WEEK_SKU_SIMPLE_v12_COMBO_EXPLODE'
MODEL      = 'x_pos_week_sku_sale'
TZ_NAME    = 'America/Santiago'
LOCK_KEY   = 99022032

FILTERED_TEAM_IDS = [18, 16, 12, 10, 9, 8, 7, 6, 5, 17, 13, 11]
DEFAULT_RUN_MODE = 'range'
DEFAULT_FROM = '2025-01-01'

# ============================================================
# Estándar calendario OH para TODOS los scripts semanales
# ------------------------------------------------------------
# 1) Semana OH: lunes a domingo, siempre en hora local Chile.
# 2) week_start: lunes. week_end: domingo.
# 3) Comparación LY semanal: -364 días = 52 semanas exactas.
# 4) Bandas estacionales: se calculan desde ISO week de week_start.
# 5) Backfill: date_from se ajusta al lunes de su semana.
# 6) Semana ISO 53: se clasifica como FIN_ANIO.
# ============================================================
OH_WEEK_START_DOW = 0       # Python Monday
OH_WEEK_LENGTH_DAYS = 7
OH_LY_OFFSET_DAYS = 364
OH_CALENDAR_VERSION = 'OH_WEEK_MON_SUN_LY_364_v1'

HOLIDAY_DATE_FIELD = 'x_studio_holiday_date'
HOLIDAY_MODEL_DEFAULT = 'x_holiday_occurrence'
HOLIDAY_REF_FIELD = 'x_studio_holiday_id'
HOLIDAY_MODEL_CTX_KEY = 'holiday_model'
HOLIDAY_DATES_CTX_KEY = 'holiday_dates'

# ============================================================
# Bandas estacionales
# ------------------------------------------------------------
# Regla entregada por operación OH:
#   BASE: semanas normales
#   VERANO_BAJO / MEDIO / ALTO
#   FIESTAS_PATRIAS
#   HALLOWEEN
#   FIN_ANIO
#
# Nota: usamos semana ISO calculada sobre week_start.
# Semana 53, si aparece, queda como FIN_ANIO para no romper
# comparabilidad en años con semana ISO extra.
# ============================================================

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
    if int(iso_week or 0) == 53:
        return False
    return iso_week in _BASE_WEEKS_SET or iso_week not in _SEASONAL_BAND


def _seasonal_band(iso_week):
    if int(iso_week or 0) == 53:
        return 'FIN_ANIO'
    return _SEASONAL_BAND.get(iso_week, 'BASE')


# Candidatos porque Studio puede crear nombres técnicos distintos según etiqueta.
MASTER_CODE_FIELDS = [
    'x_studio_codigo',
    'x_studio_code',
    'x_code',
]
MASTER_TYPE_FIELDS = [
    'x_studio_tipo_de_feriado',
    'x_studio_holiday_type',
    'x_studio_type',
]
MASTER_IRRENUNCIABLE_FIELDS = [
    'x_studio_irrenunciable',
    'x_irrenunciable',
]
MASTER_ACTIVE_FIELDS = [
    'x_studio_active',
    'x_active',
    'active',
]

company = env.company
cr = env.cr

Fact = env[MODEL].sudo().with_context(
    tracking_disable=True,
    mail_create_nosubscribe=True,
    prefetch_fields=False,
)

# ============================================================
# Helpers
# ============================================================

def _notify(t, m, typ='info', sticky=False):
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {'title': t, 'message': m, 'type': typ, 'sticky': sticky},
    }


def _ctx_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return default if s == '' else s in ('1', 'true', 't', 'yes', 'y', 'si', 'sí', 'on')


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
    except TypeError:
        try:
            out.append(int(val))
        except Exception:
            pass
        return out


def safe_div(a, b):
    return (a / b) if b else 0.0


def parse_date(s):
    if isinstance(s, datetime.date):
        return s
    return datetime.datetime.strptime(str(s)[:10], '%Y-%m-%d').date() if s else None


def oh_week_start(d):
    # Semana OH: lunes a domingo. d.weekday(): lunes=0.
    return d - datetime.timedelta(days=d.weekday())


def oh_week_end(d):
    return oh_week_start(d) + datetime.timedelta(days=OH_WEEK_LENGTH_DAYS - 1)


def oh_ly_week_start(w_start):
    # LY comparable semanal: misma posición comercial, 52 semanas atrás.
    return w_start - datetime.timedelta(days=OH_LY_OFFSET_DAYS)


def oh_ly_week_end(w_end):
    return w_end - datetime.timedelta(days=OH_LY_OFFSET_DAYS)


def oh_iso_week_from_start(w_start):
    try:
        return int(w_start.isocalendar()[1])
    except Exception:
        return 0


# Alias para compatibilidad interna del script y para copiar el bloque
# a otros scripts sin romper nombres anteriores.
def week_start(d):
    return oh_week_start(d)


def week_end(d):
    return oh_week_end(d)


def iter_week_starts(dfrom, dto):
    cur = oh_week_start(dfrom)
    end = oh_week_start(dto)
    out = []
    while cur <= end:
        out.append(cur)
        cur = cur + datetime.timedelta(days=OH_WEEK_LENGTH_DAYS)
    return out

# ============================================================
# Validación de campos del modelo real creado en Studio
# ============================================================

REQUIRED_FIELDS = [
    'x_name',
    'x_studio_company_id',
    'x_studio_team_id',
    'x_studio_week_start',
    'x_studio_week_end',
    'x_studio_categ_id',
    'x_studio_product_id',
    'x_studio_qty_sold',
    'x_studio_sales_gross',
    'x_studio_response_vs_category_pct',
    'x_studio_seasonal_band',
]

missing = []
for f in REQUIRED_FIELDS:
    if f not in Fact._fields:
        missing.append(f)
if missing:
    raise ValueError('Faltan campos en %s: %s' % (MODEL, ', '.join(missing)))

HAS_CURRENCY = 'x_studio_currency_id' in Fact._fields
HAS_RESPONSE_FIELD = 'x_studio_response_vs_category_pct' in Fact._fields
HAS_SEASONAL_BAND = 'x_studio_seasonal_band' in Fact._fields
HAS_ISO_WEEK = 'x_studio_iso_week' in Fact._fields
HAS_IS_BASE_WEEK = 'x_studio_is_base_week' in Fact._fields
HAS_SEASONAL_CONTEXT = 'x_studio_seasonal_context' in Fact._fields
HAS_HOLIDAY_IN_BAND_KEY = 'x_studio_holiday_in_band_key' in Fact._fields
HAS_LY_WEEK_START = 'x_studio_ly_week_start' in Fact._fields
HAS_LY_WEEK_END = 'x_studio_ly_week_end' in Fact._fields
HAS_CALENDAR_VERSION = 'x_studio_calendar_version' in Fact._fields
HAS_HOLIDAY_RESPONSE_OLD = 'x_studio_holiday_response_pct' in Fact._fields
HAS_HAS_VALID_LY_BASE = 'x_studio_has_valid_ly_base' in Fact._fields
HAS_RESPONSE_GROSS = 'x_studio_response_gross_vs_category_pct' in Fact._fields
HAS_SKU_GROSS_GROWTH = 'x_studio_sku_growth_gross_pct' in Fact._fields
HAS_CATEG_GROSS_GROWTH = 'x_studio_categ_growth_gross_pct' in Fact._fields
HAS_SALES_GROSS_LY = 'x_studio_sales_gross_ly' in Fact._fields
HAS_CATEG_SALES_GROSS = 'x_studio_categ_sales_gross' in Fact._fields
HAS_CATEG_SALES_GROSS_LY = 'x_studio_categ_sales_gross_ly' in Fact._fields
HAS_HAS_HOLIDAY = 'x_studio_has_holiday' in Fact._fields
HAS_HOLIDAY_DAYS = 'x_studio_holiday_days' in Fact._fields
HAS_SKU_GROWTH = 'x_studio_sku_growth_qty_pct' in Fact._fields
HAS_CATEG_GROWTH = 'x_studio_categ_growth_qty_pct' in Fact._fields
HAS_QTY_LY = 'x_studio_qty_sold_ly' in Fact._fields
HAS_CATEG_QTY = 'x_studio_categ_qty_sold' in Fact._fields
HAS_CATEG_QTY_LY = 'x_studio_categ_qty_sold_ly' in Fact._fields
HAS_HOLIDAY_NAMES = 'x_studio_holiday_names' in Fact._fields
HAS_HOLIDAY_CODES = 'x_studio_holiday_codes' in Fact._fields
HAS_HOLIDAY_TYPES = 'x_studio_holiday_types' in Fact._fields
HAS_HAS_IRRENUNCIABLE = 'x_studio_has_irrenunciable' in Fact._fields
HAS_IRRENUNCIABLE_DAYS = 'x_studio_irrenunciable_days' in Fact._fields
HAS_SOURCE_VERSION = 'x_studio_source_version' in Fact._fields
HAS_COMBO_EXPLOSION_FIELD = 'x_studio_has_combo_explosion' in Fact._fields

# ============================================================
# Detección dinámica Odoo POS
# ============================================================

_pt_fields  = env['product.template'].sudo()._fields or {}
_pol_fields = env['pos.order.line'].sudo()._fields or {}
_pc_fields  = env['pos.config'].sudo()._fields or {}

DTYPE_SQL = 'pt.detailed_type' if _pt_fields.get('detailed_type') else 'pt.type'
HAS_COMBO_PARENT = bool(_pol_fields.get('combo_parent_id'))

if _pc_fields.get('crm_team_id'):
    PC_TEAM_COL = 'crm_team_id'
elif _pc_fields.get('team_id'):
    PC_TEAM_COL = 'team_id'
else:
    raise ValueError('pos.config no tiene crm_team_id ni team_id para identificar local')

PRICE_GROSS_SQL = 'pol.price_subtotal_incl' if _pol_fields.get('price_subtotal_incl') else 'pol.price_subtotal'

if HAS_COMBO_PARENT:
    SQL_POS = ("""
WITH base AS (
    SELECT
        pol.id AS line_id,
        pol.combo_parent_id AS combo_parent_id,
        pc.__PC_TEAM_COL__ AS team_id,
        (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date) AS local_date,
        pp.id AS product_id,
        pt.categ_id AS categ_id,
        __DTYPE_SQL__ AS dtype,
        COALESCE(pol.qty, 0.0)::numeric AS qty,
        COALESCE(__PRICE_GROSS_SQL__, 0.0)::numeric AS line_gross
    FROM pos_order_line pol
    JOIN pos_order po        ON po.id = pol.order_id
    JOIN pos_session ps      ON ps.id = po.session_id
    JOIN pos_config pc       ON pc.id = ps.config_id
    JOIN product_product pp  ON pp.id = pol.product_id
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE po.company_id = %(company_id)s
      AND po.state IN ('paid', 'done', 'invoiced')
      AND pc.__PC_TEAM_COL__ = ANY(%(team_ids)s)
      AND (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date) >= %(date_from)s::date
      AND (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date) <= %(date_to)s::date
      AND COALESCE(__DTYPE_SQL__, '') <> 'service'
), standalone AS (
    SELECT
        b.team_id,
        b.local_date,
        b.product_id,
        b.categ_id,
        SUM(b.qty)::numeric AS qty_sold,
        SUM(b.line_gross)::numeric AS sales_gross
    FROM base b
    WHERE b.combo_parent_id IS NULL
      AND COALESCE(b.dtype, '') <> 'combo'
    GROUP BY b.team_id, b.local_date, b.product_id, b.categ_id
), combo_child_pre AS (
    SELECT
        c.team_id,
        c.local_date,
        c.product_id,
        c.categ_id,
        c.qty,
        c.line_gross AS child_gross,
        p.line_gross AS parent_gross,
        c.combo_parent_id,
        CASE
            WHEN ABS(COALESCE(c.line_gross, 0.0)) > 0.00001
                THEN ABS(COALESCE(c.line_gross, 0.0))
            WHEN COALESCE(c.qty, 0.0) > 0
                THEN COALESCE(c.qty, 0.0)
            ELSE 0.0
        END AS weight_value
    FROM base c
    JOIN base p ON p.line_id = c.combo_parent_id
    WHERE c.combo_parent_id IS NOT NULL
      AND COALESCE(c.dtype, '') <> 'service'
), combo_parent_stats AS (
    SELECT
        combo_parent_id,
        SUM(weight_value)::numeric AS weight_sum,
        COUNT(*)::numeric AS child_count,
        SUM(CASE WHEN ABS(COALESCE(child_gross, 0.0)) > 0.00001 THEN 1 ELSE 0 END)::numeric AS priced_child_count
    FROM combo_child_pre
    GROUP BY combo_parent_id
), combo_children AS (
    SELECT
        c.team_id,
        c.local_date,
        c.product_id,
        c.categ_id,
        SUM(c.qty)::numeric AS qty_sold,
        SUM(
            CASE
                WHEN s.priced_child_count > 0 THEN c.child_gross
                WHEN ABS(COALESCE(c.parent_gross, 0.0)) <= 0.00001 THEN 0.0
                WHEN COALESCE(s.weight_sum, 0.0) > 0.00001 THEN c.parent_gross * (c.weight_value / s.weight_sum)
                WHEN COALESCE(s.child_count, 0.0) > 0.0 THEN c.parent_gross * (1.0 / s.child_count)
                ELSE 0.0
            END
        )::numeric AS sales_gross
    FROM combo_child_pre c
    JOIN combo_parent_stats s ON s.combo_parent_id = c.combo_parent_id
    GROUP BY c.team_id, c.local_date, c.product_id, c.categ_id
), src AS (
    SELECT team_id, local_date, product_id, categ_id, qty_sold, sales_gross FROM standalone
    UNION ALL
    SELECT team_id, local_date, product_id, categ_id, qty_sold, sales_gross FROM combo_children
), wk AS (
    SELECT
        team_id,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day'))::date AS week_start,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day') + INTERVAL '6 day')::date AS week_end,
        categ_id,
        product_id,
        SUM(qty_sold)::numeric AS qty_sold,
        SUM(sales_gross)::numeric AS sales_gross
    FROM src
    GROUP BY
        team_id,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day'))::date,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day') + INTERVAL '6 day')::date,
        categ_id,
        product_id
)
SELECT
    team_id,
    week_start,
    week_end,
    categ_id,
    product_id,
    qty_sold,
    sales_gross
FROM wk
ORDER BY week_start, team_id, categ_id, product_id
""").replace('__PC_TEAM_COL__', PC_TEAM_COL) \
        .replace('__DTYPE_SQL__', DTYPE_SQL) \
        .replace('__PRICE_GROSS_SQL__', PRICE_GROSS_SQL)
else:
    SQL_POS = ("""
WITH src AS (
    SELECT
        pc.__PC_TEAM_COL__ AS team_id,
        (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date) AS local_date,
        pp.id AS product_id,
        pt.categ_id AS categ_id,
        SUM(COALESCE(pol.qty, 0.0))::numeric AS qty_sold,
        SUM(COALESCE(__PRICE_GROSS_SQL__, 0.0))::numeric AS sales_gross
    FROM pos_order_line pol
    JOIN pos_order po        ON po.id = pol.order_id
    JOIN pos_session ps      ON ps.id = po.session_id
    JOIN pos_config pc       ON pc.id = ps.config_id
    JOIN product_product pp  ON pp.id = pol.product_id
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE po.company_id = %(company_id)s
      AND po.state IN ('paid', 'done', 'invoiced')
      AND pc.__PC_TEAM_COL__ = ANY(%(team_ids)s)
      AND (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date) >= %(date_from)s::date
      AND (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date) <= %(date_to)s::date
      AND COALESCE(__DTYPE_SQL__, '') <> 'service'
      AND COALESCE(__DTYPE_SQL__, '') <> 'combo'
    GROUP BY
        pc.__PC_TEAM_COL__,
        (((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date),
        pp.id,
        pt.categ_id
), wk AS (
    SELECT
        team_id,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day'))::date AS week_start,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day') + INTERVAL '6 day')::date AS week_end,
        categ_id,
        product_id,
        SUM(qty_sold)::numeric AS qty_sold,
        SUM(sales_gross)::numeric AS sales_gross
    FROM src
    GROUP BY
        team_id,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day'))::date,
        (local_date - ((EXTRACT(ISODOW FROM local_date)::int - 1) * INTERVAL '1 day') + INTERVAL '6 day')::date,
        categ_id,
        product_id
)
SELECT
    team_id,
    week_start,
    week_end,
    categ_id,
    product_id,
    qty_sold,
    sales_gross
FROM wk
ORDER BY week_start, team_id, categ_id, product_id
""").replace('__PC_TEAM_COL__', PC_TEAM_COL) \
        .replace('__DTYPE_SQL__', DTYPE_SQL) \
        .replace('__PRICE_GROSS_SQL__', PRICE_GROSS_SQL)

# ============================================================
# Feriados
# ============================================================

def _detect_holiday_model(ctx):
    explicit_model = str(ctx.get(HOLIDAY_MODEL_CTX_KEY) or '').strip()
    if explicit_model:
        try:
            env[explicit_model]
            return explicit_model
        except Exception:
            return False

    # Modelo confirmado por archivo holiday_occurrence (x_holiday_occurrence).
    try:
        env[HOLIDAY_MODEL_DEFAULT]
        if HOLIDAY_DATE_FIELD in env[HOLIDAY_MODEL_DEFAULT].sudo()._fields:
            return HOLIDAY_MODEL_DEFAULT
    except Exception:
        pass

    # Detecta cualquier modelo Studio que tenga x_studio_holiday_date.
    # Excluye el modelo destino para evitar falsos positivos futuros.
    try:
        cr.execute("""
            SELECT m.model
            FROM ir_model_fields f
            JOIN ir_model m ON m.id = f.model_id
            WHERE f.name = %s
              AND m.model <> %s
            ORDER BY m.model
        """, (HOLIDAY_DATE_FIELD, MODEL))
        rows = cr.fetchall()
        for r in rows:
            model_name = r[0]
            try:
                env[model_name]
                return model_name
            except Exception:
                pass
    except Exception:
        return False
    return False


def _first_existing_field(model, candidates):
    try:
        fields = model.sudo()._fields or {}
    except Exception:
        fields = {}
    for fname in candidates:
        if fname in fields:
            return fname
    return False


def _is_active_record(rec):
    for fname in MASTER_ACTIVE_FIELDS:
        try:
            if fname in rec._fields:
                return bool(rec[fname])
        except Exception:
            pass
    return True


def _empty_holiday_info():
    return {
        'days': 0,
        'irrenunciable_days': 0,
        'names': [],
        'codes': [],
        'types': [],
    }


def _add_unique(lst, val):
    if val in (None, False, ''):
        return
    s = str(val)
    if s not in lst:
        lst.append(s)


def _holiday_week_counts(dfrom, dto, ctx):
    """
    SAFE_EVAL: no usa funciones internas ni closures.

    Devuelve:
      info_by_week = {
        week_start: {
          days,
          irrenunciable_days,
          names[],
          codes[],
          types[]
        }
      }

    Usa x_holiday_occurrence como calendario de fechas y, si existe
    x_studio_holiday_id, enriquece con x_holiday_master.
    """
    info_by_week = {}

    # 1) Fechas manuales vía contexto, útil para pruebas rápidas.
    manual_dates = ctx.get(HOLIDAY_DATES_CTX_KEY)
    if manual_dates:
        try:
            for ds in manual_dates:
                hd = parse_date(ds)
                if hd and hd >= dfrom and hd <= dto:
                    ws = week_start(hd)
                    if ws not in info_by_week:
                        info_by_week[ws] = _empty_holiday_info()
                    inf = info_by_week[ws]
                    inf['days'] += 1
                    _add_unique(inf['names'], 'manual')
        except Exception:
            pass

    # 2) Modelo de feriados, si existe.
    model_name = _detect_holiday_model(ctx)
    if model_name:
        try:
            H = env[model_name].sudo()
            if HOLIDAY_DATE_FIELD in H._fields:
                dom = [(HOLIDAY_DATE_FIELD, '>=', dfrom), (HOLIDAY_DATE_FIELD, '<=', dto)]
                if 'x_studio_active' in H._fields:
                    dom.append(('x_studio_active', '=', True))
                elif 'x_active' in H._fields:
                    dom.append(('x_active', '=', True))
                elif 'active' in H._fields:
                    dom.append(('active', '=', True))

                recs = H.search(dom)

                for h in recs:
                    hd = h[HOLIDAY_DATE_FIELD]
                    if not hd:
                        continue
                    if not isinstance(hd, datetime.date):
                        hd = parse_date(hd)
                    if not hd:
                        continue

                    ws = week_start(hd)
                    if ws not in info_by_week:
                        info_by_week[ws] = _empty_holiday_info()
                    inf = info_by_week[ws]
                    inf['days'] += 1

                    # Nombre base: display_name del occurrence.
                    try:
                        _add_unique(inf['names'], h.display_name)
                    except Exception:
                        pass

                    # Enriquecimiento desde holiday master.
                    master = False
                    try:
                        if HOLIDAY_REF_FIELD in H._fields:
                            master = h[HOLIDAY_REF_FIELD]
                    except Exception:
                        master = False

                    if master:
                        try:
                            if _is_active_record(master):
                                # Reemplaza/agrega nombre más limpio desde master si existe.
                                try:
                                    _add_unique(inf['names'], master.display_name)
                                except Exception:
                                    pass

                                code_field = _first_existing_field(master, MASTER_CODE_FIELDS)
                                type_field = _first_existing_field(master, MASTER_TYPE_FIELDS)
                                irr_field = _first_existing_field(master, MASTER_IRRENUNCIABLE_FIELDS)

                                if code_field:
                                    try:
                                        _add_unique(inf['codes'], master[code_field])
                                    except Exception:
                                        pass
                                if type_field:
                                    try:
                                        _add_unique(inf['types'], master[type_field])
                                    except Exception:
                                        pass
                                if irr_field:
                                    try:
                                        if bool(master[irr_field]):
                                            inf['irrenunciable_days'] += 1
                                    except Exception:
                                        pass
                        except Exception:
                            pass

        except Exception:
            pass

    return info_by_week, model_name or 'manual/none'

# ============================================================
# Fetch / build / delete / create
# ============================================================

def fetch_rows(dfrom, dto, team_ids):
    cr.execute(SQL_POS, {
        'tz': TZ_NAME,
        'company_id': company.id,
        'team_ids': team_ids,
        'date_from': dfrom,
        'date_to': dto,
    })
    return cr.fetchall()


def build_maps(rows):
    sku_map = {}
    cat_qty_map = {}
    cat_gross_map = {}

    for row in rows:
        team_id, w_start, w_end, categ_id, product_id, qty_sold, sales_gross = row
        tid = int(team_id or 0)
        cid = int(categ_id or 0) if categ_id else False
        pid = int(product_id or 0)
        qty = float(qty_sold or 0.0)
        gross = float(sales_gross or 0.0)

        sku_key = (tid, w_start, cid, pid)
        sku_map[sku_key] = {
            'week_end': w_end,
            'qty': qty,
            'gross': gross,
        }

        cat_key = (tid, w_start, cid)
        cat_qty_map[cat_key] = cat_qty_map.get(cat_key, 0.0) + qty
        cat_gross_map[cat_key] = cat_gross_map.get(cat_key, 0.0) + gross

    return sku_map, cat_qty_map, cat_gross_map


def build_vals(rows_global, dfrom, dto, holiday_info_by_week):
    vals_list = []
    currency_id = company.currency_id.id if HAS_CURRENCY else False

    sku_map, cat_qty_map, cat_gross_map = build_maps(rows_global)

    for row in rows_global:
        team_id, w_start, w_end, categ_id, product_id, qty_sold, sales_gross = row

        # Solo se crean filas para el rango objetivo actual.
        # Las filas LY solo alimentan el cálculo.
        if w_start < dfrom or w_start > dto:
            continue

        tid = int(team_id or 0)
        cid = int(categ_id or 0) if categ_id else False
        pid = int(product_id or 0)
        qty = float(qty_sold or 0.0)
        gross = float(sales_gross or 0.0)

        ly_week = oh_ly_week_start(w_start)
        sku_ly = sku_map.get((tid, ly_week, cid, pid), {'qty': 0.0, 'gross': 0.0})

        cat_key_ty = (tid, w_start, cid)
        cat_key_ly = (tid, ly_week, cid)
        cat_qty_ty = float(cat_qty_map.get(cat_key_ty, 0.0) or 0.0)
        cat_qty_ly = float(cat_qty_map.get(cat_key_ly, 0.0) or 0.0)
        cat_gross_ty = float(cat_gross_map.get(cat_key_ty, 0.0) or 0.0)
        cat_gross_ly = float(cat_gross_map.get(cat_key_ly, 0.0) or 0.0)

        sku_qty_ly = float(sku_ly.get('qty', 0.0) or 0.0)
        sku_gross_ly = float(sku_ly.get('gross', 0.0) or 0.0)

        has_valid_qty_ly_base = bool(sku_qty_ly and cat_qty_ly)
        has_valid_gross_ly_base = bool(sku_gross_ly and cat_gross_ly)

        sku_growth_qty = (safe_div(qty, sku_qty_ly) - 1.0) if sku_qty_ly else 0.0
        categ_growth_qty = (safe_div(cat_qty_ty, cat_qty_ly) - 1.0) if cat_qty_ly else 0.0
        sku_growth_gross = (safe_div(gross, sku_gross_ly) - 1.0) if sku_gross_ly else 0.0
        categ_growth_gross = (safe_div(cat_gross_ty, cat_gross_ly) - 1.0) if cat_gross_ly else 0.0

        response_vs_category = (sku_growth_qty - categ_growth_qty) if has_valid_qty_ly_base else 0.0
        response_gross_vs_category = (sku_growth_gross - categ_growth_gross) if has_valid_gross_ly_base else 0.0

        # Banda estacional desde semana ISO. Esta capa es independiente
        # del feriado: toda semana queda clasificada en una banda.
        iso_week = oh_iso_week_from_start(w_start)
        seasonal_band = _seasonal_band(iso_week)
        is_base_week = _is_base_week(iso_week)

        holiday_info = holiday_info_by_week.get(w_start, _empty_holiday_info())
        holiday_days = int(holiday_info.get('days', 0) or 0)
        irrenunciable_days = int(holiday_info.get('irrenunciable_days', 0) or 0)
        has_holiday = bool(holiday_days > 0)
        has_irrenunciable = bool(irrenunciable_days > 0)
        holiday_names = ', '.join(holiday_info.get('names', []) or [])
        holiday_codes = ', '.join(holiday_info.get('codes', []) or [])
        holiday_types = ', '.join(holiday_info.get('types', []) or [])

        seasonal_context = seasonal_band + ('|FERIADO' if has_holiday else '|SIN_FERIADO')
        if has_holiday:
            holiday_in_band_key = seasonal_band + '|' + (holiday_codes or holiday_names or 'FERIADO')
        else:
            holiday_in_band_key = seasonal_band + '|SIN_FERIADO'

        # Compatibilidad con versión anterior:
        # el campo antiguo de feriado solo se llena en semanas con feriado.
        holiday_response = response_vs_category if (has_holiday and has_valid_qty_ly_base) else 0.0

        vals = {
            'x_name': '%s | %s | local=%s | sku=%s' % (
                VERSION_ID,
                str(w_start),
                tid,
                pid,
            ),
            'x_studio_company_id': company.id,
            'x_studio_team_id': tid,
            'x_studio_week_start': w_start,
            'x_studio_week_end': w_end,
            'x_studio_categ_id': cid or False,
            'x_studio_product_id': pid,
            'x_studio_qty_sold': qty,
            'x_studio_sales_gross': gross,
            'x_studio_response_vs_category_pct': response_vs_category,
            'x_studio_seasonal_band': seasonal_band,
        }

        if HAS_CURRENCY:
            vals['x_studio_currency_id'] = currency_id
        if HAS_ISO_WEEK:
            vals['x_studio_iso_week'] = iso_week
        if HAS_IS_BASE_WEEK:
            vals['x_studio_is_base_week'] = is_base_week
        if HAS_SEASONAL_CONTEXT:
            vals['x_studio_seasonal_context'] = seasonal_context
        if HAS_HOLIDAY_IN_BAND_KEY:
            vals['x_studio_holiday_in_band_key'] = holiday_in_band_key
        if HAS_LY_WEEK_START:
            vals['x_studio_ly_week_start'] = ly_week
        if HAS_LY_WEEK_END:
            vals['x_studio_ly_week_end'] = oh_ly_week_end(w_end)
        if HAS_CALENDAR_VERSION:
            vals['x_studio_calendar_version'] = OH_CALENDAR_VERSION
        if HAS_HOLIDAY_RESPONSE_OLD:
            vals['x_studio_holiday_response_pct'] = holiday_response
        if HAS_HAS_VALID_LY_BASE:
            vals['x_studio_has_valid_ly_base'] = has_valid_qty_ly_base
        if HAS_RESPONSE_GROSS:
            vals['x_studio_response_gross_vs_category_pct'] = response_gross_vs_category
        if HAS_SKU_GROSS_GROWTH:
            vals['x_studio_sku_growth_gross_pct'] = sku_growth_gross
        if HAS_CATEG_GROSS_GROWTH:
            vals['x_studio_categ_growth_gross_pct'] = categ_growth_gross
        if HAS_SALES_GROSS_LY:
            vals['x_studio_sales_gross_ly'] = sku_gross_ly
        if HAS_CATEG_SALES_GROSS:
            vals['x_studio_categ_sales_gross'] = cat_gross_ty
        if HAS_CATEG_SALES_GROSS_LY:
            vals['x_studio_categ_sales_gross_ly'] = cat_gross_ly
        if HAS_HAS_HOLIDAY:
            vals['x_studio_has_holiday'] = has_holiday
        if HAS_HOLIDAY_DAYS:
            vals['x_studio_holiday_days'] = holiday_days
        if HAS_SKU_GROWTH:
            vals['x_studio_sku_growth_qty_pct'] = sku_growth_qty
        if HAS_CATEG_GROWTH:
            vals['x_studio_categ_growth_qty_pct'] = categ_growth_qty
        if HAS_QTY_LY:
            vals['x_studio_qty_sold_ly'] = sku_qty_ly
        if HAS_CATEG_QTY:
            vals['x_studio_categ_qty_sold'] = cat_qty_ty
        if HAS_CATEG_QTY_LY:
            vals['x_studio_categ_qty_sold_ly'] = cat_qty_ly
        if HAS_HOLIDAY_NAMES:
            vals['x_studio_holiday_names'] = holiday_names
        if HAS_HOLIDAY_CODES:
            vals['x_studio_holiday_codes'] = holiday_codes
        if HAS_HOLIDAY_TYPES:
            vals['x_studio_holiday_types'] = holiday_types
        if HAS_HAS_IRRENUNCIABLE:
            vals['x_studio_has_irrenunciable'] = has_irrenunciable
        if HAS_IRRENUNCIABLE_DAYS:
            vals['x_studio_irrenunciable_days'] = irrenunciable_days
        if HAS_SOURCE_VERSION:
            vals['x_studio_source_version'] = VERSION_ID
        if HAS_COMBO_EXPLOSION_FIELD:
            vals['x_studio_has_combo_explosion'] = bool(HAS_COMBO_PARENT)

        vals_list.append(vals)

    return vals_list


def delete_weeks_sql(weeks, team_ids):
    if not weeks:
        return 0
    sql = """
        DELETE FROM %s
        WHERE x_studio_company_id = %%s
          AND x_studio_team_id = ANY(%%s)
          AND x_studio_week_start = ANY(%%s)
    """ % Fact._table
    cr.execute(sql, (company.id, team_ids, weeks))
    return cr.rowcount


def rebuild(dfrom, dto, team_ids, dry_run=False, ctx=None):
    if ctx is None:
        ctx = {}

    weeks = iter_week_starts(dfrom, dto)

    # Necesitamos LY para calcular respuesta vs categoría.
    # La fecha de inicio global usa el estándar OH: -364 días.
    global_from = oh_ly_week_start(dfrom)
    global_to = dto

    rows_global = fetch_rows(global_from, global_to, team_ids)
    holiday_info_by_week, holiday_source = _holiday_week_counts(dfrom, dto, ctx)
    vals = build_vals(rows_global, dfrom, dto, holiday_info_by_week)

    if dry_run:
        return {
            'weeks': len(weeks),
            'rows_sql_global': len(rows_global),
            'holiday_weeks': len(holiday_info_by_week),
            'holiday_source': holiday_source,
            'deleted': 0,
            'created': 0,
            'to_create': len(vals),
        }

    deleted = delete_weeks_sql(weeks, team_ids)

    BATCH = 500
    for i in range(0, len(vals), BATCH):
        Fact.create(vals[i:i + BATCH])

    return {
        'weeks': len(weeks),
        'rows_sql_global': len(rows_global),
        'holiday_weeks': len(holiday_info_by_week),
        'holiday_source': holiday_source,
        'deleted': deleted,
        'created': len(vals),
        'to_create': len(vals),
    }

# ============================================================
# Ejecución con advisory lock
# ============================================================

cr.execute('SELECT pg_try_advisory_lock(%s)', (int(LOCK_KEY),))
_locked = cr.fetchone()[0]

if not _locked:
    action = _notify('POS Semana SKU', 'Lock ocupado — ejecución abortada.', 'warning', False)
else:
    _unlock_needed = True
    try:
        cr.execute("SELECT (now() AT TIME ZONE 'UTC' AT TIME ZONE %s)::date", (TZ_NAME,))
        today_local = cr.fetchone()[0]

        current_week_start = oh_week_start(today_local)
        last_closed_start = current_week_start - datetime.timedelta(days=OH_WEEK_LENGTH_DAYS)
        last_closed_end = last_closed_start + datetime.timedelta(days=OH_WEEK_LENGTH_DAYS - 1)

        ctx = dict(env.context or {})
        run_mode = str(ctx.get('run_mode') or DEFAULT_RUN_MODE).strip().lower()
        dry_run = _ctx_bool(ctx.get('dry_run'), False)

        team_ids = _to_int_list(ctx.get('team_ids')) or list(FILTERED_TEAM_IDS)
        if not team_ids:
            raise ValueError('team_ids vacío')

        cr.execute('SELECT id FROM crm_team WHERE id = ANY(%s)', (team_ids,))
        valid_team_ids = []
        for r in cr.fetchall():
            valid_team_ids.append(r[0])
        invalid = set(team_ids) - set(valid_team_ids)
        if invalid:
            raise ValueError('team_ids no encontrados en crm_team: %s' % sorted(invalid))
        team_ids = valid_team_ids

        if run_mode == 'last_closed':
            dfrom = last_closed_start
            dto = last_closed_end
        else:
            raw_from = parse_date(ctx.get('date_from') or DEFAULT_FROM)
            raw_to = parse_date(ctx.get('date_to') or last_closed_end)
            if not raw_from or not raw_to:
                raise ValueError('date_from/date_to inválidos')
            if raw_from > raw_to:
                raise ValueError('date_from > date_to')
            dfrom = oh_week_start(raw_from)
            dto = oh_week_end(raw_to)

        result = rebuild(dfrom, dto, team_ids, dry_run=dry_run, ctx=ctx)

        action = _notify(
            'POS Semana SKU',
            'OK | mode=%s | from=%s | to=%s | weeks=%s | teams=%s | rows_global=%s | holiday_weeks=%s | holiday_source=%s | seasonal_bands=yes | dry=%s | deleted=%s | created=%s | combo_explode=%s | calendar=%s' % (
                run_mode,
                dfrom.isoformat(),
                dto.isoformat(),
                result['weeks'],
                len(team_ids),
                result['rows_sql_global'],
                result['holiday_weeks'],
                result['holiday_source'],
                'yes' if dry_run else 'no',
                result['deleted'],
                result['created'] or result['to_create'],
                'yes' if HAS_COMBO_PARENT else 'no',
                OH_CALENDAR_VERSION,
            ),
            'success',
            False,
        )

    except Exception as e:
        action = _notify('POS Semana SKU', 'ERROR: %s' % str(e)[:300], 'danger', True)

    finally:
        if _unlock_needed:
            try:
                cr.execute('SELECT pg_advisory_unlock(%s)', (int(LOCK_KEY),))
            except Exception:
                pass
