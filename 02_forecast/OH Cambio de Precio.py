# ============================================================
# OH Price Weekly Snapshot — x_price_change_event (POS only)
# SQL-first | SOLO eventos reales | ALL PRODUCTS | WEEKLY INCREMENTAL
#
# Objetivo:
# - Procesar todos los productos vendibles con ventas POS
# - Detectar cambios reales de precio por régimen semanal
# - Guardar SOLO la primera semana del nuevo régimen
# - Recalcular solo una ventana móvil (no full rebuild)
#
# Lógica semanal:
# - END_DATE   = domingo de la última semana cerrada
# - START_DATE = 12 semanas hacia atrás (rebuild window)
# - CALC_START = START_DATE - 8 semanas (lookback técnico)
#
# Campos relevantes:
# - x_studio_base_price    = precio régimen anterior
# - x_studio_price_eff     = precio nuevo régimen
# - x_studio_week_price    = precio nuevo régimen
# - x_studio_delta_pct     = variación %
# - x_studio_direction     = Sube / Baja
# - x_studio_support_weeks = duración del régimen anterior
# ============================================================

TZ_NAME = 'America/Santiago'
LOCK_KEY = 99009414

RUN_ONLY_CLOSED_WEEKS = True
REBUILD_WEEKS = 12
LOOKBACK_WEEKS = 8

PRICE_BUCKET   = 50.0
MIN_UNITS_WEEK = 1.0
MIN_SALES_WEEK = 0.0

MIN_ABS_CHANGE = 50.0
MIN_PCT_CHANGE = 0.05

DRY_RUN = False
PURGE_EXISTING = True
BATCH = 1000

company = env.company
Ev = env['x_price_change_event'].sudo().with_context(
    tracking_disable=True,
    mail_create_nosubscribe=True
)

def _notify(t, m, typ='info', sticky=False):
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {'title': t, 'message': m, 'type': typ, 'sticky': sticky}
    }

# ------------------------------------------------------------
# Lock
# ------------------------------------------------------------
env.cr.execute("SELECT pg_try_advisory_lock(%s)", (int(LOCK_KEY),))
_locked = env.cr.fetchone()[0]

if not _locked:
    if env.context.get('from_cron'):
        raise Exception('Weekly Price Snapshot ALL: lock ocupado, abortado.')
    action = _notify('Weekly Price Snapshot ALL', 'Lock ocupado, abortado.', 'warning', False)
else:
    try:
        # ------------------------------------------------------------
        # Fecha local en Chile vía SQL
        # ------------------------------------------------------------
        env.cr.execute("SELECT (now() AT TIME ZONE %s)::date", (TZ_NAME,))
        today_local = env.cr.fetchone()[0]

        # lunes=0 ... domingo=6
        weekday = today_local.weekday()
        this_monday = today_local - datetime.timedelta(days=weekday)

        if RUN_ONLY_CLOSED_WEEKS:
            END_DATE = this_monday - datetime.timedelta(days=1)  # domingo semana cerrada
        else:
            END_DATE = today_local

        START_DATE = this_monday - datetime.timedelta(weeks=int(REBUILD_WEEKS))
        CALC_START_DATE = START_DATE - datetime.timedelta(weeks=int(LOOKBACK_WEEKS))

        # ------------------------------------------------------------
        # Limpieza previa SOLO del rango objetivo
        # ------------------------------------------------------------
        if PURGE_EXISTING and (not DRY_RUN):
            env.cr.execute("""
                DELETE FROM x_price_change_event
                WHERE x_studio_company_id = %s
                  AND x_studio_period_start >= %s
                  AND x_studio_period_start <= %s
            """, (company.id, START_DATE, END_DATE))

        # ------------------------------------------------------------
        # Bounds UTC index-friendly
        # ------------------------------------------------------------
        env.cr.execute("""
            SELECT
              ((%s::date)::timestamp AT TIME ZONE %s)::timestamp AS utc_from,
              (((%s::date + 1)::timestamp) AT TIME ZONE %s)::timestamp AS utc_to
        """, (CALC_START_DATE, TZ_NAME, END_DATE, TZ_NAME))
        utc_from, utc_to = env.cr.fetchone()

        # ------------------------------------------------------------
        # Detectar columnas disponibles
        # ------------------------------------------------------------
        env.cr.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'pos_order_line'
              AND column_name = 'price_subtotal_incl'
            LIMIT 1
        """)
        has_incl = bool(env.cr.fetchone())
        sales_expr = "pol.price_subtotal_incl" if has_incl else "pol.price_subtotal"

        env.cr.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'product_template'
              AND column_name = 'available_in_pos'
            LIMIT 1
        """)
        has_available_in_pos = bool(env.cr.fetchone())

        env.cr.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'product_template'
              AND column_name = 'detailed_type'
            LIMIT 1
        """)
        has_detailed_type = bool(env.cr.fetchone())

        pos_clause = "AND pt.available_in_pos IS TRUE" if has_available_in_pos else ""
        type_clause = "AND COALESCE(pt.detailed_type, 'product') <> 'service'" if has_detailed_type else ""

        # ------------------------------------------------------------
        # SQL principal
        # ------------------------------------------------------------
        sql = """
            WITH base AS (
                SELECT
                    date_trunc('week', (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s))::date AS week_start,
                    pp.product_tmpl_id AS product_id,
                    pt.categ_id AS categ_id,
                    po.id AS order_id,
                    pol.qty::float AS qty,
                    ({sales_expr})::float AS sales,
                    (({sales_expr})::float / NULLIF(pol.qty, 0))::float AS unit_price
                FROM pos_order_line pol
                JOIN pos_order po        ON po.id = pol.order_id
                JOIN product_product pp  ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE po.company_id = %(company_id)s
                  AND po.state IN ('paid', 'invoiced', 'done')
                  AND po.date_order >= %(utc_from)s
                  AND po.date_order <  %(utc_to)s
                  AND pol.qty > 0
                  AND ({sales_expr})::float > 0
                  AND COALESCE(pt.sale_ok, FALSE) IS TRUE
                  {pos_clause}
                  {type_clause}
            ),
            bucket AS (
                SELECT
                    week_start,
                    product_id,
                    categ_id,
                    (floor((unit_price / %(bucket)s) + 0.5) * %(bucket)s)::float AS price_bucket,
                    SUM(qty)::float AS units_bucket,
                    SUM(sales)::float AS sales_bucket,
                    COUNT(*)::int AS lines_count,
                    COUNT(DISTINCT order_id)::int AS orders_count
                FROM base
                GROUP BY 1,2,3,4
            ),
            tot AS (
                SELECT
                    week_start,
                    product_id,
                    SUM(units_bucket)::float AS units_total,
                    SUM(sales_bucket)::float AS sales_total,
                    SUM(lines_count)::int AS lines_total,
                    SUM(orders_count)::int AS orders_total
                FROM bucket
                GROUP BY 1,2
            ),
            ranked AS (
                SELECT
                    b.week_start,
                    b.product_id,
                    b.categ_id,
                    b.price_bucket,
                    b.units_bucket,
                    b.sales_bucket,
                    b.lines_count,
                    b.orders_count,
                    t.units_total,
                    t.sales_total,
                    t.lines_total,
                    t.orders_total,
                    ROW_NUMBER() OVER (
                        PARTITION BY b.week_start, b.product_id
                        ORDER BY b.units_bucket DESC, b.sales_bucket DESC, b.price_bucket DESC
                    ) AS rn
                FROM bucket b
                JOIN tot t
                  ON t.week_start = b.week_start
                 AND t.product_id = b.product_id
            ),
            weekly AS (
                SELECT
                    week_start,
                    product_id,
                    MAX(categ_id) AS categ_id,
                    MAX(units_total) AS units_total,
                    MAX(sales_total) AS sales_total,
                    MAX(CASE WHEN rn = 1 THEN price_bucket END) AS week_price,
                    MAX(lines_total) AS lines_total,
                    MAX(orders_total) AS orders_total
                FROM ranked
                GROUP BY 1,2
                HAVING MAX(units_total) >= %(min_units)s
                   AND MAX(sales_total) >= %(min_sales)s
            ),
            weekly_norm AS (
                SELECT
                    week_start,
                    product_id,
                    categ_id,
                    units_total,
                    sales_total,
                    lines_total,
                    orders_total,
                    (floor((week_price / %(bucket)s) + 0.5) * %(bucket)s)::float AS week_price_50
                FROM weekly
            ),
            marks AS (
                SELECT
                    w.week_start,
                    w.product_id,
                    w.categ_id,
                    w.units_total,
                    w.sales_total,
                    w.lines_total,
                    w.orders_total,
                    w.week_price_50,
                    CASE
                        WHEN LAG(w.week_price_50) OVER (
                            PARTITION BY w.product_id
                            ORDER BY w.week_start
                        ) IS NULL THEN 1
                        WHEN LAG(w.week_price_50) OVER (
                            PARTITION BY w.product_id
                            ORDER BY w.week_start
                        ) <> w.week_price_50 THEN 1
                        ELSE 0
                    END AS regime_start_flag
                FROM weekly_norm w
            ),
            grp AS (
                SELECT
                    m.week_start,
                    m.product_id,
                    m.categ_id,
                    m.units_total,
                    m.sales_total,
                    m.lines_total,
                    m.orders_total,
                    m.week_price_50,
                    SUM(m.regime_start_flag) OVER (
                        PARTITION BY m.product_id
                        ORDER BY m.week_start
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS grp_id
                FROM marks m
            ),
            regimes AS (
                SELECT
                    product_id,
                    grp_id,
                    MIN(week_start) AS regime_start,
                    MAX(week_start) AS regime_end,
                    MAX(categ_id) AS categ_id,
                    MAX(week_price_50) AS regime_price,
                    COUNT(*)::int AS regime_weeks
                FROM grp
                GROUP BY product_id, grp_id
            ),
            regime_events AS (
                SELECT
                    cur.regime_start AS week_start,
                    cur.product_id,
                    cur.categ_id,
                    prev.regime_price::float AS base_price,
                    cur.regime_price::float AS price_eff,
                    ((cur.regime_price - prev.regime_price) / NULLIF(prev.regime_price, 0))::float AS delta_pct,
                    CASE
                        WHEN cur.regime_price > prev.regime_price THEN 'Sube'
                        WHEN cur.regime_price < prev.regime_price THEN 'Baja'
                        ELSE NULL
                    END AS direction,
                    prev.regime_weeks::int AS support_weeks
                FROM regimes cur
                JOIN regimes prev
                  ON prev.product_id = cur.product_id
                 AND prev.grp_id = cur.grp_id - 1
            ),
            final_events AS (
                SELECT
                    e.week_start,
                    e.product_id,
                    e.categ_id,
                    e.base_price,
                    e.price_eff,
                    e.delta_pct,
                    e.direction,
                    e.support_weeks,
                    w.units_total,
                    w.sales_total,
                    w.lines_total,
                    w.orders_total
                FROM regime_events e
                JOIN weekly_norm w
                  ON w.week_start = e.week_start
                 AND w.product_id = e.product_id
                WHERE e.week_start >= %(start_date)s
                  AND e.week_start <= %(end_date)s
                  AND ABS(e.price_eff - e.base_price) >= %(min_abs_change)s
                  AND ABS(e.delta_pct) >= %(min_pct_change)s
                  AND e.direction IS NOT NULL
            )
            SELECT
                week_start,
                product_id,
                categ_id,
                base_price,
                price_eff,
                delta_pct,
                direction,
                support_weeks,
                units_total,
                sales_total,
                lines_total,
                orders_total
            FROM final_events
            ORDER BY product_id, week_start
        """.format(
            sales_expr=sales_expr,
            pos_clause=pos_clause,
            type_clause=type_clause
        )

        env.cr.execute(sql, {
            'tz': TZ_NAME,
            'company_id': company.id,
            'utc_from': utc_from,
            'utc_to': utc_to,
            'start_date': START_DATE,
            'end_date': END_DATE,
            'bucket': float(PRICE_BUCKET),
            'min_units': float(MIN_UNITS_WEEK),
            'min_sales': float(MIN_SALES_WEEK),
            'min_abs_change': float(MIN_ABS_CHANGE),
            'min_pct_change': float(MIN_PCT_CHANGE),
        })
        rows = env.cr.fetchall()

        if not rows:
            msg = '0 eventos reales | window=%s..%s | calc_from=%s' % (
                START_DATE, END_DATE, CALC_START_DATE
            )

            if env.context.get('from_cron'):
                log(msg)
            action = _notify('Weekly Price Snapshot ALL', msg, 'warning', False)
        else:
            batch = []
            wrote = 0
            products_count = 0
            last_product_id = None
            step = float(PRICE_BUCKET) if PRICE_BUCKET else 50.0

            for row in rows:
                week_start = row[0]
                product_id = row[1]
                categ_id = row[2]
                base_price = row[3]
                price_eff = row[4]
                delta_pct = row[5]
                direction = row[6]
                support_weeks = row[7]
                units_total = row[8]
                sales_total = row[9]
                lines_total = row[10]
                orders_total = row[11]

                if product_id != last_product_id:
                    products_count += 1
                    last_product_id = product_id

                wp = float(price_eff or 0.0)
                wp50 = float(int((wp + (step / 2.0)) // step) * step)

                vals = {
                    'x_name': '%s | PT:%s | %s->%s' % (
                        week_start.isoformat(),
                        int(product_id),
                        int(base_price or 0.0),
                        int(price_eff or 0.0)
                    ),

                    'x_studio_company_id': company.id,
                    'x_studio_product_id': int(product_id),
                    'x_studio_categ_id': int(categ_id) if categ_id else False,

                    'x_studio_period_start': week_start,
                    'x_studio_week_price': float(wp50),

                    'x_studio_units': float(units_total or 0.0),
                    'x_studio_gross_sales': float(sales_total or 0.0),
                    'x_studio_lines_count': int(lines_total or 0),
                    'x_studio_orders_count': int(orders_total or 0),

                    'x_studio_delta_pct': float(delta_pct or 0.0),
                    'x_studio_direction': direction,
                    'x_studio_is_real_change': True,
                    'x_studio_support_weeks': int(support_weeks or 0),

                    'x_studio_base_price': float(base_price or 0.0),
                    'x_studio_price_eff': float(price_eff or 0.0),
                }

                batch.append(vals)

                if len(batch) >= int(BATCH):
                    if not DRY_RUN:
                        Ev.create(batch)
                    wrote += len(batch)
                    batch = []

            if batch:
                if not DRY_RUN:
                    Ev.create(batch)
                wrote += len(batch)

            msg = 'OK | products=%s | events=%s | wrote=%s | window=%s..%s | calc_from=%s | DRY_RUN=%s' % (
                int(products_count or 0),
                int(len(rows) or 0),
                int(wrote or 0),
                START_DATE,
                END_DATE,
                CALC_START_DATE,
                ('Y' if DRY_RUN else 'N')
            )

            if env.context.get('from_cron'):
                log(msg)

            action = _notify('Weekly Price Snapshot ALL', msg, 'success', False)

    except Exception as e:
        try:
            env.cr.rollback()
        except Exception:
            pass

        if env.context.get('from_cron'):
            raise Exception('Weekly Price Snapshot ALL ERROR: %s' % (str(e)[:300]))

        action = _notify(
            'Weekly Price Snapshot ALL',
            'ERROR: %s' % (str(e)[:180]),
            'danger',
            True
        )

    finally:
        env.cr.execute("SELECT pg_advisory_unlock(%s)", (int(LOCK_KEY),))