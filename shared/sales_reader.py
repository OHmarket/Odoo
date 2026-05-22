# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
sales_reader — Lectura de ventas POS con detección dinámica de campos.

Maneja diferencias entre versiones de Odoo:
- pos.config: campo equipo es crm_team_id (v14+) o team_id (v13).
- product.template: tipo producto es detailed_type (v16+) o type (v13-v15).
- pos.order_line: combo_parent_id existe solo en v16+.

Uso típico:
    team_field = detect_team_field(env)
    type_field = detect_type_field(env)
    rows = fetch_pos_agg(cr, team_ids=[18, 16], date_from=d1, date_to=d2,
                         team_field=team_field, type_field=type_field)
"""

from datetime import date


# ---------------------------------------------------------------------------
# Detección dinámica de campos
# ---------------------------------------------------------------------------

def detect_team_field(env):
    """
    Detecta si pos.config usa crm_team_id (v14+) o team_id (v13).
    Retorna el nombre del campo que existe, o None si ninguno.
    """
    config_model = env["pos.config"]
    for fname in ("crm_team_id", "team_id"):
        if fname in config_model._fields:
            return fname
    return None


def detect_type_field(env):
    """
    Detecta si product.template usa detailed_type (v16+) o type (v13-v15).
    Retorna el nombre del campo que existe.
    """
    tmpl_model = env["product.template"]
    for fname in ("detailed_type", "type"):
        if fname in tmpl_model._fields:
            return fname
    return "type"


def has_combo_parent(cr):
    """
    Verifica si pos_order_line tiene la columna combo_parent_id (Odoo v16+).
    Consulta information_schema para evitar error si la columna no existe.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'pos_order_line'
          AND column_name = 'combo_parent_id'
        LIMIT 1
    """)
    return bool(cr.fetchone())


# ---------------------------------------------------------------------------
# Fetch POS agregado
# ---------------------------------------------------------------------------

def fetch_pos_agg(cr, team_ids, date_from, date_to, team_field="crm_team_id",
                  type_field="detailed_type", week_mode=True):
    """
    SQL agregado de ventas POS con combo explosion.

    Retorna lista de dicts:
      {team_id, product_id, period_start, qty_sold, sales_gross, orders_count}

    Parámetros:
      week_mode: True = agrupa por semana (lunes), False = agrupa por mes.
      team_field: 'crm_team_id' o 'team_id' según versión Odoo.
      type_field: 'detailed_type' o 'type' según versión Odoo.
    """
    # Detectar si existe combo_parent_id
    use_combo = has_combo_parent(cr)

    if week_mode:
        period_expr = "date_trunc('week', po.date_order AT TIME ZONE 'America/Santiago')::date"
    else:
        period_expr = "date_trunc('month', po.date_order AT TIME ZONE 'America/Santiago')::date"

    team_ids_sql = ",".join(str(t) for t in team_ids)

    if use_combo:
        # Standalone: líneas sin combo_parent_id y no de tipo combo/service
        standalone_filter = """
            AND pol.combo_parent_id IS NULL
            AND pt.{type_field} NOT IN ('service', 'combo')
        """.format(type_field=type_field)
        # Children: líneas hijo con combo_parent_id
        children_clause = """
            UNION ALL
            SELECT
                pc.{team_field} AS team_id,
                pol.product_id,
                {period_expr} AS period_start,
                pol.qty AS qty_sold,
                pol.price_subtotal_incl AS sales_gross,
                0 AS orders_count
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_session ps ON ps.id = po.session_id
            JOIN pos_config pc ON pc.id = ps.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE po.state IN ('paid', 'invoiced', 'done')
              AND po.date_order >= %(date_from)s
              AND po.date_order < %(date_to_excl)s
              AND pc.{team_field} IN ({team_ids})
              AND pol.combo_parent_id IS NOT NULL
        """.format(
            team_field=team_field,
            period_expr=period_expr,
            team_ids=team_ids_sql,
        )
    else:
        standalone_filter = ""
        children_clause = ""

    sql = """
        SELECT
            team_id,
            product_id,
            period_start,
            SUM(qty_sold)     AS qty_sold,
            SUM(sales_gross)  AS sales_gross,
            SUM(orders_count) AS orders_count
        FROM (
            SELECT
                pc.{team_field}        AS team_id,
                pol.product_id,
                {period_expr}          AS period_start,
                pol.qty                AS qty_sold,
                pol.price_subtotal_incl AS sales_gross,
                1                      AS orders_count
            FROM pos_order_line pol
            JOIN pos_order po ON po.id = pol.order_id
            JOIN pos_session ps ON ps.id = po.session_id
            JOIN pos_config pc ON pc.id = ps.config_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE po.state IN ('paid', 'invoiced', 'done')
              AND po.date_order >= %(date_from)s
              AND po.date_order < %(date_to_excl)s
              AND pc.{team_field} IN ({team_ids})
              AND pp.active = true
              AND pt.sale_ok = true
              {standalone_filter}
            {children_clause}
        ) sub
        GROUP BY team_id, product_id, period_start
        ORDER BY team_id, product_id, period_start
    """.format(
        team_field=team_field,
        period_expr=period_expr,
        team_ids=team_ids_sql,
        standalone_filter=standalone_filter,
        children_clause=children_clause,
    )

    from datetime import timedelta
    cr.execute(sql, {
        "date_from": date_from,
        "date_to_excl": date_to + timedelta(days=1),
    })
    cols = [d[0] for d in cr.description]
    return [dict(zip(cols, row)) for row in cr.fetchall()]
