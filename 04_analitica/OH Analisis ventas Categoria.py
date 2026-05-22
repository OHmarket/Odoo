# ============================================================
# OH POS Week Category Fact — TY + LY + FACTOR ANUAL CATEGORIA
# v10 CATEGORY ANNUAL FACTOR:
#   - Mantiene la lógica original a nivel semana x sucursal x categoría
#   - NO baja a SKU
#   - Agrega/corrige factor categoría vs promedio semanal anual
#   - annual_avg_sales / annual_avg_units = promedio semanal del mismo año
#     ISO comercial, por sucursal x categoría
#   - season_factor_sales / season_factor_units = semana / promedio anual
#   - LY = semana - 364 días
#   - Soporta run_mode/date_from/date_to y también pos_week_start/pos_week_end
#   - x_name compatible con jsonb
# ============================================================

VERSION_ID = "POS_WEEK_CATEG_TYLY_v10_ANNUAL_FACTOR_CATEGORY"
TZ_NAME    = "America/Santiago"
LOCK_KEY   = 99013012

TEAM_IDS_FIXED = [18, 16, 12, 10, 9, 8, 7, 6, 5, 17, 13]

cr = env.cr
company = env.company
ctx = env.context

Fact = env['x_x_pos_week_sku_fact'].sudo().with_context(
    tracking_disable=True,
    mail_create_nosubscribe=True
)
TBL = Fact._table

def _as_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ('1','true','t','yes','y','si','sí','on'):
        return True
    if s in ('0','false','f','no','n','off',''):
        return False
    return default

def _col_exists(table, col):
    cr.execute("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name=%s AND column_name=%s
        LIMIT 1
    """, (table, col))
    return bool(cr.fetchone())

def _col_type(table, col):
    cr.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name=%s AND column_name=%s
        LIMIT 1
    """, (table, col))
    r = cr.fetchone()
    return (r[0] if r else None)

def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())

def _notify(title, message, typ='info', sticky=False):
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': title,
            'message': message,
            'type': typ,
            'sticky': sticky,
        }
    }

BUCKET  = float(ctx.get('pos_week_bucket') or 50.0)
DRY_RUN = _as_bool(ctx.get('dry_run'), _as_bool(ctx.get('pos_week_dry_run'), False))
DEBUG   = _as_bool(ctx.get('pos_week_debug'), False)

# Default seguro: en cron/rango borra solo el período recalculado.
# Si quieres reconstruir todo el modelo, pasar pos_week_purge_all=True.
PURGE_ALL_COMPANY = False if (ctx.get('pos_week_purge_all') is None) else _as_bool(ctx.get('pos_week_purge_all'), False)

# ------------------------------------------------------------
# Fechas:
# - Compatible con wrapper nuevo: run_mode/date_from/date_to/dry_run
# - Compatible con código original: pos_week_start/pos_week_end
# - Default: semana cerrada anterior lunes-domingo
# ------------------------------------------------------------
def _parse_date(s):
    if isinstance(s, datetime.date):
        return s
    return datetime.date.fromisoformat(str(s).strip()[:10])

def _factor_year(ws):
    # Año semanal por jueves: 2024-12-30 pertenece al año semanal 2025.
    return (ws + datetime.timedelta(days=3)).year

def _iso_year_start_week(y):
    return _week_start(datetime.date(y, 1, 4))

cr.execute("""
    SELECT ((now() AT TIME ZONE 'UTC') AT TIME ZONE %s)::date
""", (TZ_NAME,))
today_local = cr.fetchone()[0]
current_monday = _week_start(today_local)
last_closed_sunday = current_monday - datetime.timedelta(days=1)
last_closed_monday = current_monday - datetime.timedelta(days=7)

run_mode = str(ctx.get('run_mode') or '').strip().lower()
_start_raw = ctx.get('date_from') or ctx.get('pos_week_start')
_end_raw   = ctx.get('date_to') or ctx.get('pos_week_end')

if run_mode == 'last_closed':
    START_DATE = last_closed_monday
    END_DATE = last_closed_sunday
elif _start_raw:
    START_DATE = _parse_date(_start_raw)
    END_DATE = _parse_date(_end_raw) if _end_raw else last_closed_sunday
else:
    START_DATE = last_closed_monday
    END_DATE = last_closed_sunday

if END_DATE > last_closed_sunday:
    END_DATE = last_closed_sunday

START_WEEK = _week_start(START_DATE)
END_WEEK   = _week_start(END_DATE)

# Para LY necesitamos semana -364; para factor anual necesitamos al menos
# desde la semana 1 del año semanal actual hasta END_WEEK.
LY_START_WEEK = START_WEEK - datetime.timedelta(days=364)
ANNUAL_START_WEEK = _iso_year_start_week(_factor_year(START_WEEK))
HIST_START_WEEK = LY_START_WEEK if LY_START_WEEK < ANNUAL_START_WEEK else ANNUAL_START_WEEK

TEAM_IDS = ctx.get('pos_week_team_ids') or TEAM_IDS_FIXED
team_ids_t = tuple(int(x) for x in TEAM_IDS)

req = [
    'x_name',
    'x_studio_company_id','x_studio_team_id','x_studio_week_start',
    'x_studio_categ_id','x_studio_cluster_desc',
    'x_studio_units','x_studio_sales','x_studio_orders_count','x_studio_lines_count',
    'x_studio_week_price','x_studio_avg_price_unit',
    'x_studio_units_ly','x_studio_sales_ly','x_studio_orders_count_ly','x_studio_lines_count_ly',
    'x_studio_week_price_ly','x_studio_avg_price_unit_ly',
    'x_studio_var_orders_pct','x_studio_var_sales_pct','x_studio_var_units_pct',
    'x_studio_annual_avg_units','x_studio_annual_avg_sales',
    'x_studio_season_factor_units','x_studio_season_factor_sales',
    'x_studio_support_weeks_52w',
]
missing = [f for f in req if f not in Fact._fields]
if missing:
    raise Exception("Faltan campos en %s: %s" % (Fact._name, ", ".join(missing)))

has_incl = _col_exists('pos_order_line', 'price_subtotal_incl')
sales_expr = "pol.price_subtotal_incl" if has_incl else "pol.price_subtotal"

has_combo_parent = _col_exists('pos_order_line', 'combo_parent_id')

pt_fields = env['product.template']._fields or {}
dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

xname_is_jsonb = (_col_type(TBL, 'x_name') == 'jsonb')
LANG = (ctx.get('lang') or env.user.lang or 'es_CL')

cr.execute("""
    SELECT
      (((%s::date)::timestamp AT TIME ZONE %s) AT TIME ZONE 'UTC')::timestamp AS utc_from_src,
      ((((%s::date + 1)::timestamp) AT TIME ZONE %s) AT TIME ZONE 'UTC')::timestamp AS utc_to_src
""", (HIST_START_WEEK, TZ_NAME, END_DATE, TZ_NAME))
utc_from_src, utc_to_src = cr.fetchone()

cr.execute("SELECT pg_try_advisory_lock(%s)", (int(LOCK_KEY),))
if not cr.fetchone()[0]:
    raise Exception("Lock ocupado (%s)" % LOCK_KEY)

try:
    purged = 0

    if DRY_RUN:
        action = _notify(
            'POS Week Categ TY/LY + Factor Anual',
            'DRY_RUN OK | nivel=categoria | source=%s | %s..%s | source_from=%s | combo_parent=%s | purge_all=%s' % (
                'manual' if (_start_raw and _end_raw) else 'auto_prev_week',
                START_WEEK, END_WEEK, HIST_START_WEEK,
                int(has_combo_parent), int(PURGE_ALL_COMPANY)
            ),
            'success',
            False
        )
    else:
        if PURGE_ALL_COMPANY:
            cr.execute("DELETE FROM %s WHERE x_studio_company_id = %%s" % TBL, (company.id,))
            purged = cr.rowcount or 0
        else:
            cr.execute("""
                DELETE FROM {tbl}
                WHERE x_studio_company_id = %s
                  AND x_studio_week_start >= %s
                  AND x_studio_week_start <= %s
                  AND x_studio_team_id IN %s
            """.format(tbl=TBL), (company.id, START_WEEK, END_WEEK, team_ids_t))
            purged = cr.rowcount or 0
        cr.commit()

        name_txt = "(%(version_id)s || ' | ' || e.week_start::text || ' | team=' || e.team_id::text || ' | categ=' || e.categ_id::text)"
        if xname_is_jsonb:
            xname_sql = "jsonb_build_object(%(lang)s::text, {name_txt})".format(name_txt=name_txt)
        else:
            xname_sql = name_txt

        insert_cols = [
            'x_name','x_studio_company_id','x_studio_team_id','x_studio_week_start',
            'x_studio_categ_id','x_studio_cluster_desc',
            'x_studio_units','x_studio_sales','x_studio_orders_count','x_studio_lines_count',
            'x_studio_week_price','x_studio_avg_price_unit',
            'x_studio_units_ly','x_studio_sales_ly','x_studio_orders_count_ly','x_studio_lines_count_ly',
            'x_studio_week_price_ly','x_studio_avg_price_unit_ly',
            'x_studio_var_orders_pct','x_studio_var_sales_pct','x_studio_var_units_pct',
            'x_studio_annual_avg_units','x_studio_annual_avg_sales',
            'x_studio_season_factor_units','x_studio_season_factor_sales',
            'x_studio_support_weeks_52w',
            'create_uid', 'create_date', 'write_uid', 'write_date'
        ]

        select_cols = [
            xname_sql + " AS x_name",
            "%(company_id)s AS x_studio_company_id",
            "e.team_id AS x_studio_team_id",
            "e.week_start AS x_studio_week_start",
            "e.categ_id AS x_studio_categ_id",
            "''::text AS x_studio_cluster_desc",
            "e.units_total AS x_studio_units",
            "e.sales_total AS x_studio_sales",
            "e.orders_total AS x_studio_orders_count",
            "e.lines_total AS x_studio_lines_count",
            "COALESCE(e.week_price, 0)::int AS x_studio_week_price",
            "CASE WHEN e.units_total > 0 THEN (e.sales_total / e.units_total) ELSE 0 END AS x_studio_avg_price_unit",
            "COALESCE(ly.units_total, 0)::float AS x_studio_units_ly",
            "COALESCE(ly.sales_total, 0)::float AS x_studio_sales_ly",
            "COALESCE(ly.orders_total, 0)::int AS x_studio_orders_count_ly",
            "COALESCE(ly.lines_total, 0)::int AS x_studio_lines_count_ly",
            "COALESCE(ly.week_price, 0)::int AS x_studio_week_price_ly",
            "CASE WHEN COALESCE(ly.units_total,0) > 0 THEN (ly.sales_total / ly.units_total) ELSE 0 END AS x_studio_avg_price_unit_ly",
            "CASE WHEN COALESCE(ly.orders_total,0) > 0 THEN (e.orders_total::float / ly.orders_total) - 1 ELSE 0 END AS x_studio_var_orders_pct",
            "CASE WHEN COALESCE(ly.sales_total,0) > 0 THEN (e.sales_total / ly.sales_total) - 1 ELSE 0 END AS x_studio_var_sales_pct",
            "CASE WHEN COALESCE(ly.units_total,0) > 0 THEN (e.units_total / ly.units_total) - 1 ELSE 0 END AS x_studio_var_units_pct",
            "COALESCE(e.annual_avg_units_prev52, 0) AS x_studio_annual_avg_units",
            "COALESCE(e.annual_avg_sales_prev52, 0) AS x_studio_annual_avg_sales",
            "CASE WHEN COALESCE(e.annual_avg_units_prev52,0) > 0 THEN (e.units_total / e.annual_avg_units_prev52) ELSE 1 END AS x_studio_season_factor_units",
            "CASE WHEN COALESCE(e.annual_avg_sales_prev52,0) > 0 THEN (e.sales_total / e.annual_avg_sales_prev52) ELSE 1 END AS x_studio_season_factor_sales",
            "COALESCE(e.support_weeks_prev52, 0) AS x_studio_support_weeks_52w",
            "%(uid)s AS create_uid",
            "(now() AT TIME ZONE 'UTC') AS create_date",
            "%(uid)s AS write_uid",
            "(now() AT TIME ZONE 'UTC') AS write_date"
        ]

        if has_combo_parent:
            sql = """
                INSERT INTO {tbl}
                ({insert_cols})

                WITH
                src_orders AS (
                    SELECT
                        o.id AS order_id,
                        o.crm_team_id AS team_id,
                        (o.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s) AS dt_local
                    FROM pos_order o
                    WHERE o.state IN ('paid','done','invoiced')
                      AND o.company_id = %(company_id)s
                      AND o.crm_team_id IN %(team_ids)s
                      AND o.date_order >= %(utc_from_src)s
                      AND o.date_order <  %(utc_to_src)s
                ),
                base AS (
                    SELECT
                        pol.id AS line_id,
                        pol.combo_parent_id AS combo_parent_id,
                        date_trunc('week', so.dt_local)::date AS week_start,
                        so.team_id,
                        so.order_id,
                        pt.categ_id AS categ_id,
                        COALESCE(pol.qty, 0.0)::float AS qty,
                        COALESCE({sales_expr}, 0.0)::float AS line_rev,
                        COALESCE({dtype_sql}, '') AS dtype
                    FROM src_orders so
                    JOIN pos_order_line pol ON pol.order_id = so.order_id
                    JOIN product_product pp ON pp.id = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE COALESCE(pol.qty, 0.0) > 0
                      AND date_trunc('week', so.dt_local)::date >= %(hist_start_week)s
                      AND date_trunc('week', so.dt_local)::date <= %(end_week)s
                ),
                standalone AS (
                    SELECT
                        b.week_start, b.team_id, b.order_id, b.categ_id,
                        b.qty,
                        b.line_rev AS sales,
                        CASE WHEN b.qty > 0 THEN (b.line_rev / b.qty) ELSE 0 END AS unit_price
                    FROM base b
                    WHERE b.combo_parent_id IS NULL
                      AND b.dtype <> 'service'
                      AND b.dtype <> 'combo'
                      AND b.line_rev > 0
                ),
                combo_child_pre AS (
                    SELECT
                        c.line_id,
                        c.combo_parent_id AS combo_parent_id,
                        c.week_start, c.team_id, c.order_id, c.categ_id,
                        c.qty,
                        c.line_rev AS child_rev,
                        p.line_rev AS parent_rev,
                        CASE
                            WHEN ABS(COALESCE(c.line_rev, 0.0)) > 0.00001 THEN ABS(COALESCE(c.line_rev, 0.0))
                            WHEN COALESCE(c.qty, 0.0) > 0 THEN COALESCE(c.qty, 0.0)
                            ELSE 0.0
                        END AS weight_value
                    FROM base c
                    JOIN base p
                      ON p.line_id = c.combo_parent_id
                    WHERE c.combo_parent_id IS NOT NULL
                      AND c.dtype <> 'service'
                ),
                combo_parent_stats AS (
                    SELECT
                        combo_parent_id,
                        SUM(weight_value) AS weight_sum,
                        COUNT(*) AS child_count,
                        SUM(CASE WHEN ABS(child_rev) > 0.00001 THEN 1 ELSE 0 END) AS priced_child_count
                    FROM combo_child_pre
                    GROUP BY 1
                ),
                combo_children AS (
                    SELECT
                        c.week_start, c.team_id, c.order_id, c.categ_id,
                        c.qty,
                        CASE
                            WHEN s.priced_child_count > 0 THEN c.child_rev
                            WHEN ABS(c.parent_rev) <= 0.00001 THEN 0.0
                            WHEN COALESCE(s.weight_sum, 0.0) > 0.00001 THEN c.parent_rev * (c.weight_value / s.weight_sum)
                            WHEN COALESCE(s.child_count, 0) > 0 THEN c.parent_rev * (1.0 / s.child_count)
                            ELSE 0.0
                        END AS sales
                    FROM combo_child_pre c
                    JOIN combo_parent_stats s
                      ON s.combo_parent_id = c.combo_parent_id
                ),
                sales_union AS (
                    SELECT
                        week_start, team_id, order_id, categ_id,
                        qty, sales,
                        CASE WHEN qty > 0 THEN (sales / qty) ELSE 0 END AS unit_price
                    FROM standalone
                    UNION ALL
                    SELECT
                        week_start, team_id, order_id, categ_id,
                        qty, sales,
                        CASE WHEN qty > 0 THEN (sales / qty) ELSE 0 END AS unit_price
                    FROM combo_children
                    WHERE sales > 0
                ),
                agg AS (
                    SELECT
                        week_start, team_id, categ_id,
                        SUM(qty)::float AS units_total,
                        SUM(sales)::float AS sales_total,
                        COUNT(*)::int AS lines_total,
                        COUNT(DISTINCT order_id)::int AS orders_total
                    FROM sales_union
                    GROUP BY 1,2,3
                ),
                bucket AS (
                    SELECT
                        week_start, team_id, categ_id,
                        (floor((unit_price / %(bucket)s) + 0.5) * %(bucket)s)::float AS price_bucket,
                        SUM(qty)::float AS units_bucket,
                        SUM(sales)::float AS sales_bucket
                    FROM sales_union
                    GROUP BY 1,2,3,4
                ),
                ranked AS (
                    SELECT
                        b.week_start, b.team_id, b.categ_id, b.price_bucket,
                        ROW_NUMBER() OVER (
                            PARTITION BY b.week_start, b.team_id, b.categ_id
                            ORDER BY b.units_bucket DESC, b.sales_bucket DESC
                        ) AS rn
                    FROM bucket b
                ),
                team_categ AS (
                    SELECT DISTINCT team_id, categ_id
                    FROM agg
                    WHERE categ_id IS NOT NULL
                ),
                weeks AS (
                    SELECT generate_series(%(hist_start_week)s::date, %(end_week)s::date, interval '7 days')::date AS week_start
                ),
                spine AS (
                    SELECT
                        w.week_start,
                        tc.team_id,
                        tc.categ_id
                    FROM weeks w
                    CROSS JOIN team_categ tc
                ),
                filled AS (
                    SELECT
                        s.week_start,
                        s.team_id,
                        s.categ_id,
                        COALESCE(a.units_total, 0)::float AS units_total,
                        COALESCE(a.sales_total, 0)::float AS sales_total,
                        COALESCE(a.orders_total, 0)::int AS orders_total,
                        COALESCE(a.lines_total, 0)::int AS lines_total,
                        COALESCE(r.price_bucket, 0)::float AS week_price
                    FROM spine s
                    LEFT JOIN agg a
                      ON a.week_start = s.week_start
                     AND a.team_id = s.team_id
                     AND a.categ_id = s.categ_id
                    LEFT JOIN ranked r
                      ON r.week_start = s.week_start
                     AND r.team_id = s.team_id
                     AND r.categ_id = s.categ_id
                     AND r.rn = 1
                ),
                enriched AS (
                    SELECT
                        f.*,
                        EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int AS factor_year,
                        COUNT(*) OVER (
                            PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                        )::int AS support_weeks_prev52,
                        CASE
                            WHEN COUNT(*) OVER (
                                PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                            ) > 0
                            THEN (
                                SUM(f.units_total) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                ) /
                                COUNT(*) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                )
                            )::float
                            ELSE 0
                        END AS annual_avg_units_prev52,
                        CASE
                            WHEN COUNT(*) OVER (
                                PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                            ) > 0
                            THEN (
                                SUM(f.sales_total) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                ) /
                                COUNT(*) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                )
                            )::float
                            ELSE 0
                        END AS annual_avg_sales_prev52
                    FROM filled f
                )

                SELECT
                    {select_cols}
                FROM enriched e
                LEFT JOIN enriched ly
                  ON ly.team_id = e.team_id
                 AND ly.categ_id = e.categ_id
                 AND ly.week_start = (e.week_start - interval '364 days')::date
                WHERE e.week_start >= %(start_week)s
                  AND e.week_start <= %(end_week)s
            """.format(
                tbl=TBL,
                insert_cols=",\n             ".join(insert_cols),
                select_cols=",\n                ".join(select_cols),
                sales_expr=sales_expr,
                dtype_sql=dtype_sql
            )
        else:
            sql = """
                INSERT INTO {tbl}
                ({insert_cols})

                WITH
                src_orders AS (
                    SELECT
                        o.id AS order_id,
                        o.crm_team_id AS team_id,
                        (o.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s) AS dt_local
                    FROM pos_order o
                    WHERE o.state IN ('paid','done','invoiced')
                      AND o.company_id = %(company_id)s
                      AND o.crm_team_id IN %(team_ids)s
                      AND o.date_order >= %(utc_from_src)s
                      AND o.date_order <  %(utc_to_src)s
                ),
                base AS (
                    SELECT
                        date_trunc('week', so.dt_local)::date AS week_start,
                        so.team_id,
                        so.order_id,
                        pt.categ_id AS categ_id,
                        COALESCE(pol.qty, 0.0)::float AS qty,
                        COALESCE({sales_expr}, 0.0)::float AS sales,
                        CASE WHEN COALESCE(pol.qty,0.0) > 0 THEN (COALESCE({sales_expr},0.0) / pol.qty) ELSE 0 END AS unit_price
                    FROM src_orders so
                    JOIN pos_order_line pol ON pol.order_id = so.order_id
                    JOIN product_product pp ON pp.id = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE COALESCE(pol.qty, 0.0) > 0
                      AND COALESCE({sales_expr}, 0.0) > 0
                      AND COALESCE({dtype_sql}, '') <> 'service'
                      AND COALESCE({dtype_sql}, '') <> 'combo'
                      AND date_trunc('week', so.dt_local)::date >= %(hist_start_week)s
                      AND date_trunc('week', so.dt_local)::date <= %(end_week)s
                ),
                agg AS (
                    SELECT
                        week_start, team_id, categ_id,
                        SUM(qty)::float AS units_total,
                        SUM(sales)::float AS sales_total,
                        COUNT(*)::int AS lines_total,
                        COUNT(DISTINCT order_id)::int AS orders_total
                    FROM base
                    GROUP BY 1,2,3
                ),
                bucket AS (
                    SELECT
                        week_start, team_id, categ_id,
                        (floor((unit_price / %(bucket)s) + 0.5) * %(bucket)s)::float AS price_bucket,
                        SUM(qty)::float AS units_bucket,
                        SUM(sales)::float AS sales_bucket
                    FROM base
                    GROUP BY 1,2,3,4
                ),
                ranked AS (
                    SELECT
                        b.week_start, b.team_id, b.categ_id, b.price_bucket,
                        ROW_NUMBER() OVER (
                            PARTITION BY b.week_start, b.team_id, b.categ_id
                            ORDER BY b.units_bucket DESC, b.sales_bucket DESC
                        ) AS rn
                    FROM bucket b
                ),
                team_categ AS (
                    SELECT DISTINCT team_id, categ_id
                    FROM agg
                    WHERE categ_id IS NOT NULL
                ),
                weeks AS (
                    SELECT generate_series(%(hist_start_week)s::date, %(end_week)s::date, interval '7 days')::date AS week_start
                ),
                spine AS (
                    SELECT
                        w.week_start,
                        tc.team_id,
                        tc.categ_id
                    FROM weeks w
                    CROSS JOIN team_categ tc
                ),
                filled AS (
                    SELECT
                        s.week_start,
                        s.team_id,
                        s.categ_id,
                        COALESCE(a.units_total, 0)::float AS units_total,
                        COALESCE(a.sales_total, 0)::float AS sales_total,
                        COALESCE(a.orders_total, 0)::int AS orders_total,
                        COALESCE(a.lines_total, 0)::int AS lines_total,
                        COALESCE(r.price_bucket, 0)::float AS week_price
                    FROM spine s
                    LEFT JOIN agg a
                      ON a.week_start = s.week_start
                     AND a.team_id = s.team_id
                     AND a.categ_id = s.categ_id
                    LEFT JOIN ranked r
                      ON r.week_start = s.week_start
                     AND r.team_id = s.team_id
                     AND r.categ_id = s.categ_id
                     AND r.rn = 1
                ),
                enriched AS (
                    SELECT
                        f.*,
                        EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int AS factor_year,
                        COUNT(*) OVER (
                            PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                        )::int AS support_weeks_prev52,
                        CASE
                            WHEN COUNT(*) OVER (
                                PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                            ) > 0
                            THEN (
                                SUM(f.units_total) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                ) /
                                COUNT(*) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                )
                            )::float
                            ELSE 0
                        END AS annual_avg_units_prev52,
                        CASE
                            WHEN COUNT(*) OVER (
                                PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                            ) > 0
                            THEN (
                                SUM(f.sales_total) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                ) /
                                COUNT(*) OVER (
                                    PARTITION BY f.team_id, f.categ_id, EXTRACT(YEAR FROM (f.week_start + interval '3 days'))::int
                                )
                            )::float
                            ELSE 0
                        END AS annual_avg_sales_prev52
                    FROM filled f
                )

                SELECT
                    {select_cols}
                FROM enriched e
                LEFT JOIN enriched ly
                  ON ly.team_id = e.team_id
                 AND ly.categ_id = e.categ_id
                 AND ly.week_start = (e.week_start - interval '364 days')::date
                WHERE e.week_start >= %(start_week)s
                  AND e.week_start <= %(end_week)s
            """.format(
                tbl=TBL,
                insert_cols=",\n             ".join(insert_cols),
                select_cols=",\n                ".join(select_cols),
                sales_expr=sales_expr,
                dtype_sql=dtype_sql
            )

        params = {
            'tz': TZ_NAME,
            'company_id': company.id,
            'team_ids': team_ids_t,
            'utc_from_src': utc_from_src,
            'utc_to_src': utc_to_src,
            'hist_start_week': HIST_START_WEEK,
            'start_week': START_WEEK,
            'end_week': END_WEEK,
            'bucket': float(BUCKET),
            'uid': env.uid,
            'version_id': VERSION_ID,
            'lang': LANG,
        }

        cr.execute("SAVEPOINT pos_week_fact_sp")
        try:
            cr.execute(sql, params)
            inserted = cr.rowcount or 0
            cr.execute("RELEASE SAVEPOINT pos_week_fact_sp")
        except Exception:
            try:
                cr.execute("ROLLBACK TO SAVEPOINT pos_week_fact_sp")
            except Exception:
                pass
            raise

        cr.commit()

        cr.execute("""
            SELECT
              COUNT(*)::int AS n,
              SUM(CASE WHEN COALESCE(x_studio_sales_ly,0) > 0 THEN 1 ELSE 0 END)::int AS n_ly
            FROM {tbl}
            WHERE x_studio_company_id = %s
        """.format(tbl=TBL), (company.id,))
        n_all, n_ly = cr.fetchone()

        action = _notify(
            'POS Week Categ TY/LY + Factor Anual',
            'OK %s | nivel=categoria | %s..%s | purged=%s | inserted=%s | rows=%s | rows_with_LY=%s | incl=%s | combo_parent=%s | purge_all=%s | source_from=%s | xname_jsonb=%s' % (
                VERSION_ID,
                START_WEEK, END_WEEK,
                purged, inserted, n_all, n_ly,
                int(has_incl), int(has_combo_parent), int(PURGE_ALL_COMPANY),
                HIST_START_WEEK, int(xname_is_jsonb)
            ),
            'success',
            False
        )

finally:
    try:
        cr.execute("SELECT pg_advisory_unlock(%s)", (int(LOCK_KEY),))
    except Exception:
        try:
            cr.rollback()
            cr.execute("SELECT pg_advisory_unlock(%s)", (int(LOCK_KEY),))
        except Exception:
            pass
