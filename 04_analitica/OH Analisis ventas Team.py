# ============================================================
# OH Analisis Ventas Team - KPI mensual por sucursal (POS only)
# ============================================================
#
# Version activa: v13 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - KPI mensual por sucursal con combo-explode en unidades.
#   - Persiste en x_sales_month_team_kpi: ventas brutas, tickets,
#     unidades vendidas, ticket promedio, etc.
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Combos/sets explotan via combo_parent_id:
#       - Excluye service y combo/set standalone del conteo de unidades.
#       - Baja unidades del SET al SKU hijo real.
#       - Ventas brutas y tickets a nivel pedido (no cambian).
#   - SAFE_EVAL friendly. Requiere datetime en contexto Server Action.
#
# Contexto opcional:
#   run_mode:  "last_closed" | "range"   (default: "last_closed")
#   date_from: "YYYY-MM-DD"              (default: "2025-01-01")
#   date_to:   "YYYY-MM-DD"              (default: ultimo dia del mes cerrado)
#   team_ids:  [18,16,...]               (default: FILTERED_TEAM_IDS)
#   dry_run:   True/False                (default: False)
#
# Detalles, fixes historicos y esquema completo: ver CHANGELOG.md.
# ============================================================

VERSION_ID = "KPI_MONTH_TEAM_POSONLY_v13_COMBOEXPLODE_BACKFILL"

TZ_NAME    = "America/Santiago"
LOCK_KEY   = 99012026

FILTERED_TEAM_IDS = [18, 16, 12, 10, 9, 8, 7, 6, 5, 17, 13]
DEFAULT_FROM = '2025-01-01'

company = env.company
cr      = env.cr

Kpi = env['x_sales_month_team_kpi'].sudo().with_context(
    tracking_disable=True,
    mail_create_nosubscribe=True
)


# ============================================================
# Helpers generales
# ============================================================

def _notify(t, m, typ='info', sticky=False):
    return {
        'type': 'ir.actions.client', 'tag': 'display_notification',
        'params': {'title': t, 'message': m, 'type': typ, 'sticky': sticky}
    }


def _ctx_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return default if s == '' else s in ('1', 'true', 't', 'yes', 'y', 'si', 'sí', 'on')


def _to_int_list(val):
    if not val:
        return []
    try:
        return [int(x) for x in val]
    except TypeError:
        try:
            return [int(val)]
        except Exception:
            return []


def safe_div(a, b):
    return (a / b) if b else 0.0


# ============================================================
# Validación de campos del modelo
# ============================================================

REQUIRED_FIELDS = [
    'x_name',
    'x_studio_company_id',
    'x_studio_team_id',
    'x_studio_period_date',
    'x_studio_sales_gross',
    'x_studio_sales_gross_ly',
    'x_studio_tickets',
    'x_studio_tickets_ly',
    'x_studio_units',
    'x_studio_units_ly',
    'x_studio_atv',
    'x_studio_atv_ly',
    'x_studio_units_per_ticket',
    'x_studio_units_per_ticket_ly',
    'x_studio_yoy_sales_pct',
    'x_studio_yoy_tickets_pct',
    'x_studio_yoy_units_pct',
    'x_studio_yoy_atv_pct',
    'x_studio_avg_price_unit',
    'x_studio_avg_price_unit_ly',
    'x_studio_yoy_price_unit_pct',
    'x_studio_yoy_upt_pct',
    'x_studio_driver_code',
    'x_studio_color',
]

missing = [f for f in REQUIRED_FIELDS if f not in Kpi._fields]
if missing:
    raise ValueError("Faltan campos en x_sales_month_team_kpi: %s" % ", ".join(missing))

HAS_CURRENCY = ('x_studio_currency_id' in Kpi._fields)


# ============================================================
# Helpers de fechas
# ============================================================

def last_day_of_month(y, m):
    nxt = datetime.date(y + 1, 1, 1) if m == 12 else datetime.date(y, m + 1, 1)
    return (nxt - datetime.timedelta(days=1)).day


def month_start(d):
    return datetime.date(d.year, d.month, 1)


def month_end(d):
    return datetime.date(d.year, d.month, last_day_of_month(d.year, d.month))


def parse_date(s):
    if isinstance(s, datetime.date):
        return s
    return datetime.datetime.strptime(str(s)[:10], '%Y-%m-%d').date() if s else None


def iter_month_starts(dfrom, dto):
    cur, out = month_start(dfrom), []
    while cur <= dto:
        out.append(cur)
        cur = datetime.date(cur.year + 1, 1, 1) if cur.month == 12 else datetime.date(cur.year, cur.month + 1, 1)
    return out


# ============================================================
# KPI: color y driver
# ============================================================

AVG_DROP = -0.109  # -10.9 %


def perf_color(yoy_sales):
    if yoy_sales > 0.0:   return 4
    if yoy_sales <= AVG_DROP: return 1
    if yoy_sales <= -0.05:    return 2
    return 3


def _driver_raw(yoy_sales, yoy_tck, yoy_pu, yoy_upt):
    if yoy_sales > 0.0:
        return 'CROW'
    at, ap, au = abs(yoy_tck), abs(yoy_pu), abs(yoy_upt)
    mx = max(ap, au)
    if at > 1.2 * mx:   return 'TCK'
    mx2 = max(at, au)
    if ap > 1.2 * mx2:  return 'PRC'
    mx3 = max(at, ap)
    if au > 1.2 * mx3:  return 'UPT'
    return 'MIX'


_DRIVER_MAP = {'CROW': 'CROW', 'TCK': 'TCK', 'MIX': 'MIX', 'PRC': 'ATV', 'UPT': 'MIX'}


def driver_code(yoy_sales, yoy_tck, yoy_pu, yoy_upt):
    return _DRIVER_MAP.get(_driver_raw(yoy_sales, yoy_tck, yoy_pu, yoy_upt), 'MIX')


# ============================================================
# Detección dinámica de campos POS / product.template
# ============================================================

_pt_fields  = env['product.template'].sudo()._fields or {}
_pol_fields = env['pos.order.line']._fields or {}

HAS_COMBO_PARENT = bool(_pol_fields.get('combo_parent_id'))
DTYPE_SQL = 'pt.detailed_type' if _pt_fields.get('detailed_type') else 'pt.type'

# Detección dinámica: pos_config usa 'crm_team_id' (v16+) o 'team_id' (versiones anteriores)
_pc_fields  = env['pos.config'].sudo()._fields or {}
PC_TEAM_COL = 'crm_team_id' if _pc_fields.get('crm_team_id') else 'team_id'


# ============================================================
# SQL — única query para TY + LY en un solo viaje a la BD
# Recibe todos los períodos TY de una sola vez y devuelve
# filas para TY y LY juntos (discriminadas por is_ly).
# ============================================================

# --- variante con combo_parent_id ---
_SQL_COMBO = """
WITH
pos_orders AS (
    SELECT
        pc.__PC_TEAM_COL__                                                   AS team_id,
        ((o.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date        AS d,
        o.id                                                                  AS order_id,
        o.amount_total::numeric                                               AS order_total
    FROM pos_order o
    JOIN pos_session ps ON ps.id = o.session_id
    JOIN pos_config  pc ON pc.id = ps.config_id
    WHERE o.state IN ('paid','done','invoiced')
      AND o.company_id = %(company_id)s
      AND pc.__PC_TEAM_COL__ = ANY(%(team_ids)s)
      AND (
          ((o.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date
          BETWEEN %(global_from)s AND %(global_to)s
      )
),
base_lines AS (
    SELECT
        po.team_id,
        po.d,
        po.order_id,
        pol.combo_parent_id,
        COALESCE(pol.qty, 0.0)::numeric  AS qty,
        COALESCE(__DTYPE_SQL__, '')       AS dtype
    FROM pos_orders po
    JOIN pos_order_line  pol ON pol.order_id = po.order_id
    JOIN product_product pp  ON pp.id = pol.product_id
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE COALESCE(pol.qty, 0.0) > 0
),
standalone_units AS (
    SELECT team_id, d, order_id, SUM(qty)::numeric AS units
    FROM   base_lines
    WHERE  combo_parent_id IS NULL
      AND  dtype <> 'service'
      AND  dtype <> 'combo'
    GROUP BY team_id, d, order_id
),
combo_child_units AS (
    SELECT team_id, d, order_id, SUM(qty)::numeric AS units
    FROM   base_lines
    WHERE  combo_parent_id IS NOT NULL
      AND  dtype <> 'service'
    GROUP BY team_id, d, order_id
),
order_units AS (
    SELECT team_id, d, order_id, SUM(units)::numeric AS units
    FROM (
        SELECT team_id, d, order_id, units FROM standalone_units
        UNION ALL
        SELECT team_id, d, order_id, units FROM combo_child_units
    ) x
    GROUP BY team_id, d, order_id
),
src AS (
    SELECT
        po.team_id,
        date_trunc('month', po.d)::date          AS period_date,
        SUM(po.order_total)::numeric              AS sales_gross,
        COUNT(DISTINCT po.order_id)::int          AS tickets,
        COALESCE(SUM(ou.units), 0)::numeric       AS units
    FROM pos_orders po
    LEFT JOIN order_units ou
           ON ou.order_id = po.order_id
          AND ou.team_id  = po.team_id
          AND ou.d        = po.d
    GROUP BY po.team_id, date_trunc('month', po.d)::date
)
SELECT team_id, period_date, sales_gross, tickets, units
FROM   src
ORDER  BY period_date, team_id
""".replace('__DTYPE_SQL__', DTYPE_SQL)

# --- variante sin combo_parent_id ---
_SQL_PLAIN = """
WITH
pos_orders AS (
    SELECT
        pc.__PC_TEAM_COL__                                                   AS team_id,
        ((o.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date        AS d,
        o.id                                                                  AS order_id,
        o.amount_total::numeric                                               AS order_total
    FROM pos_order o
    JOIN pos_session ps ON ps.id = o.session_id
    JOIN pos_config  pc ON pc.id = ps.config_id
    WHERE o.state IN ('paid','done','invoiced')
      AND o.company_id = %(company_id)s
      AND pc.__PC_TEAM_COL__ = ANY(%(team_ids)s)
      AND (
          ((o.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s)::date
          BETWEEN %(global_from)s AND %(global_to)s
      )
),
order_units AS (
    SELECT
        po.order_id,
        SUM(pol.qty)::numeric AS units
    FROM pos_orders po
    JOIN pos_order_line  pol ON pol.order_id = po.order_id
    JOIN product_product pp  ON pp.id = pol.product_id
    JOIN product_template pt ON pt.id = pp.product_tmpl_id
    WHERE pol.qty > 0
      AND COALESCE(__DTYPE_SQL__, '') <> 'service'
      AND COALESCE(__DTYPE_SQL__, '') <> 'combo'
    GROUP BY po.order_id
),
src AS (
    SELECT
        po.team_id,
        date_trunc('month', po.d)::date          AS period_date,
        SUM(po.order_total)::numeric              AS sales_gross,
        COUNT(DISTINCT po.order_id)::int          AS tickets,
        COALESCE(SUM(ou.units), 0)::numeric       AS units
    FROM pos_orders po
    LEFT JOIN order_units ou ON ou.order_id = po.order_id
    GROUP BY po.team_id, date_trunc('month', po.d)::date
)
SELECT team_id, period_date, sales_gross, tickets, units
FROM   src
ORDER  BY period_date, team_id
""".replace('__DTYPE_SQL__', DTYPE_SQL)

SQL_POS = (
    (_SQL_COMBO if HAS_COMBO_PARENT else _SQL_PLAIN)
    .replace('__DTYPE_SQL__', DTYPE_SQL)
    .replace('__PC_TEAM_COL__', PC_TEAM_COL)
)


# ============================================================
# Fetch ÚNICO para todos los períodos TY + sus LY
# ============================================================

def fetch_all_periods(periods, team_ids):
    """
    Recibe lista de month_start TY.
    Calcula el rango global TY y LY, hace UNA sola query SQL
    y devuelve dict {(team_id, period_date): (sales, tickets, units)}.
    """
    if not periods:
        return {}

    ty_min = periods[0]
    ty_max = month_end(periods[-1])

    # Rango LY: todos los meses equivalentes del año anterior
    ly_min = datetime.date(ty_min.year - 1, ty_min.month, 1)
    ly_max = datetime.date(
        ty_max.year - 1,
        ty_max.month,
        last_day_of_month(ty_max.year - 1, ty_max.month)
    )

    # Un solo viaje a la BD cubre TY y LY completos
    global_from = ly_min
    global_to   = ty_max

    cr.execute(SQL_POS, {
        'tz':          TZ_NAME,
        'company_id':  company.id,
        'team_ids':    team_ids,
        'global_from': global_from,
        'global_to':   global_to,
    })

    result = {}
    team_set = set(team_ids)
    for team_id, period_date, sales_gross, tickets, units in cr.fetchall():
        tid = int(team_id or 0)
        if tid not in team_set:
            continue
        result[(tid, period_date)] = (
            float(sales_gross or 0.0),
            int(tickets   or 0),
            float(units   or 0.0),
        )
    return result


# ============================================================
# Construcción de registros para todos los períodos
# ============================================================

def build_all_vals(periods, team_ids, data_map):
    """
    Genera la lista completa de dicts a insertar sin I/O adicional.
    """
    currency_id = company.currency_id.id if HAS_CURRENCY else None
    all_vals = []

    for period_date in periods:
        ty_y  = period_date.year
        ly_period = datetime.date(ty_y - 1, period_date.month, 1)

        for tid in team_ids:
            sales,    tck,    unt    = data_map.get((tid, period_date), (0.0, 0, 0.0))
            ly_sales, ly_tck, ly_unt = data_map.get((tid, ly_period),  (0.0, 0, 0.0))

            tck_f    = float(tck)
            ly_tck_f = float(ly_tck)

            atv    = safe_div(sales,    tck_f)
            atv_ly = safe_div(ly_sales, ly_tck_f)
            upt    = safe_div(unt,      tck_f)
            upt_ly = safe_div(ly_unt,   ly_tck_f)
            pu     = safe_div(sales,    unt)
            pu_ly  = safe_div(ly_sales, ly_unt)

            yoy_sales = safe_div(sales,    ly_sales)    - 1.0 if ly_sales    else 0.0
            yoy_tck   = safe_div(tck_f,    ly_tck_f)   - 1.0 if ly_tck      else 0.0
            yoy_units = safe_div(unt,      ly_unt)      - 1.0 if ly_unt      else 0.0
            yoy_atv   = safe_div(atv,      atv_ly)      - 1.0 if atv_ly      else 0.0
            yoy_pu    = safe_div(pu,        pu_ly)      - 1.0 if pu_ly       else 0.0
            yoy_upt   = safe_div(upt,       upt_ly)     - 1.0 if upt_ly      else 0.0

            vals = {
                'x_name':                       "%s | %s | team=%s" % (VERSION_ID, str(period_date), tid),
                'x_studio_company_id':           company.id,
                'x_studio_team_id':              tid,
                'x_studio_period_date':          period_date,
                'x_studio_sales_gross':          sales,
                'x_studio_sales_gross_ly':       ly_sales,
                'x_studio_tickets':              tck,
                'x_studio_tickets_ly':           ly_tck,
                'x_studio_units':                unt,
                'x_studio_units_ly':             ly_unt,
                'x_studio_atv':                  atv,
                'x_studio_atv_ly':               atv_ly,
                'x_studio_units_per_ticket':     upt,
                'x_studio_units_per_ticket_ly':  upt_ly,
                'x_studio_avg_price_unit':       pu,
                'x_studio_avg_price_unit_ly':    pu_ly,
                'x_studio_yoy_price_unit_pct':   yoy_pu,
                'x_studio_yoy_upt_pct':          yoy_upt,
                'x_studio_yoy_sales_pct':        yoy_sales,
                'x_studio_yoy_tickets_pct':      yoy_tck,
                'x_studio_yoy_units_pct':        yoy_units,
                'x_studio_yoy_atv_pct':          yoy_atv,
                'x_studio_driver_code':          driver_code(yoy_sales, yoy_tck, yoy_pu, yoy_upt),
                'x_studio_color':                perf_color(yoy_sales),
            }
            if HAS_CURRENCY:
                vals['x_studio_currency_id'] = currency_id
            all_vals.append(vals)

    return all_vals


# ============================================================
# Delete masivo con SQL directo (evita ORM browse innecesario)
# ============================================================

def delete_periods_sql(periods, team_ids):
    """
    Borra en una sola query todos los registros de los períodos
    indicados para los equipos dados.

    DECISIÓN TÉCNICA: se usa SQL directo en vez de ORM search+unlink
    para evitar el overhead de browse y los hooks de tracking, dado que
    x_sales_month_team_kpi es un modelo Studio de métricas puras sin
    lógica de negocio ni listeners relevantes en unlink. Si en el futuro
    se agregan triggers ORM sobre este modelo, se debe volver a unlink().
    """
    cr.execute("""
        DELETE FROM x_sales_month_team_kpi
        WHERE x_studio_company_id = %s
          AND x_studio_team_id    = ANY(%s)
          AND x_studio_period_date = ANY(%s)
    """, (
        company.id,
        team_ids,
        [p for p in periods],
    ))
    return cr.rowcount


# ============================================================
# Punto de entrada principal (backfill completo en una sola pasada)
# ============================================================

def rebuild_periods(periods, team_ids, dry_run=False):
    """
    Procesa TODOS los períodos en una sola query SQL y una sola
    operación de create masiva — en vez de un loop por mes.
    """
    data_map  = fetch_all_periods(periods, team_ids)
    all_vals  = build_all_vals(periods, team_ids, data_map)

    if dry_run:
        return {
            'periods':    len(periods),
            'teams':      len(team_ids),
            'to_create':  len(all_vals),
            'rows_in_db': len(data_map),
        }

    deleted = delete_periods_sql(periods, team_ids)

    BATCH = 500
    for i in range(0, len(all_vals), BATCH):
        Kpi.create(all_vals[i:i + BATCH])

    return {
        'periods':   len(periods),
        'teams':     len(team_ids),
        'deleted':   deleted,
        'created':   len(all_vals),
    }


# ============================================================
# EJECUCIÓN con advisory lock
# ============================================================

# --- intentar lock con autocommit para que el unlock sobreviva
# cualquier rollback de la transacción principal ---
cr.execute("SELECT pg_try_advisory_lock(%s)", (int(LOCK_KEY),))
_locked = cr.fetchone()[0]

if not _locked:
    action = _notify('KPI Mensual POS', 'Lock ocupado — ejecución abortada.', 'warning', False)
else:
    _unlock_needed = True
    try:
        # Fecha local
        cr.execute(
            "SELECT (now() AT TIME ZONE 'UTC' AT TIME ZONE %s)::date",
            (TZ_NAME,)
        )
        today_local       = cr.fetchone()[0]
        first_this_month  = datetime.date(today_local.year, today_local.month, 1)
        last_closed_start = month_start(first_this_month - datetime.timedelta(days=1))

        ctx      = dict(env.context or {})
        run_mode = str(ctx.get('run_mode') or 'last_closed').strip().lower()
        dry_run  = _ctx_bool(ctx.get('dry_run'), False)

        team_ids = _to_int_list(ctx.get('team_ids')) or list(FILTERED_TEAM_IDS)
        if not team_ids:
            raise ValueError('team_ids vacío')

        # Validar que los team_ids existen en la BD (sin filtrar active:
        # equipos inactivos hoy pueden tener datos históricos válidos)
        cr.execute(
            "SELECT id FROM crm_team WHERE id = ANY(%s)",
            (team_ids,)
        )
        valid_team_ids = [r[0] for r in cr.fetchall()]
        invalid = set(team_ids) - set(valid_team_ids)
        if invalid:
            raise ValueError('team_ids no encontrados en crm_team: %s' % sorted(invalid))
        team_ids = valid_team_ids

        if run_mode == 'last_closed':
            periods = [last_closed_start]
        else:
            dfrom = parse_date(ctx.get('date_from') or DEFAULT_FROM)
            dto   = parse_date(ctx.get('date_to') or month_end(last_closed_start))
            if not dfrom or not dto:
                raise ValueError('date_from/date_to inválidos')
            if dfrom > dto:
                raise ValueError('date_from > date_to')
            periods = iter_month_starts(month_start(dfrom), month_start(dto))

        if not periods:
            raise ValueError('No hay períodos para recalcular')

        result = rebuild_periods(periods, team_ids, dry_run=dry_run)

        action = _notify(
            'KPI Mensual POS',
            'OK | mode=%s | months=%s | from=%s | to=%s | teams=%s | combo=%s | dry=%s | deleted=%s | created=%s' % (
                run_mode,
                result['periods'],
                periods[0].isoformat(),
                periods[-1].isoformat(),
                len(team_ids),
                'yes' if HAS_COMBO_PARENT else 'no',
                'yes' if dry_run else 'no',
                result.get('deleted', '–'),
                result.get('created', result.get('to_create', '–')),
            ),
            'success', False
        )

    except Exception as e:
        # NO hacemos cr.rollback() — el framework de Odoo maneja
        # la transacción; un rollback manual aquí puede dejar el
        # cursor en estado inválido.
        action = _notify('KPI Mensual POS', 'ERROR: %s' % str(e)[:300], 'danger', True)

    finally:
        if _unlock_needed:
            # Ejecutar unlock fuera de la transacción principal
            # para que sobreviva incluso si hubo error arriba.
            try:
                cr.execute("SELECT pg_advisory_unlock(%s)", (int(LOCK_KEY),))
            except Exception:
                pass