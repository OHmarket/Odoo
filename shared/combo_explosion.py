# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
combo_explosion — SQL para separar líneas de productos combo en sus componentes.

Contexto:
  Un combo de Odoo POS (v16+) genera una línea padre (tipo 'combo') y N líneas
  hijo con combo_parent_id = id de la línea padre. Los análisis de SKU deben
  excluir la línea padre y usar las líneas hijo, atribuyéndoles una fracción
  de la venta bruta del combo.

Estrategia de prorrateo:
  Cada hijo recibe la venta bruta proporcional a su price_subtotal_incl
  dentro del total del combo. Si todos los hijos tienen price=0, el prorrateo
  es uniforme (1/N).

Disponibilidad:
  combo_parent_id existe solo en Odoo v16+. Verificar con has_combo_parent()
  en sales_reader antes de usar estas funciones.
"""


def explode_combo_sql(team_ids, date_from, date_to, team_field="crm_team_id",
                      type_field="detailed_type", week_mode=True):
    """
    Retorna la query SQL de combo explosion lista para ejecutar con cr.execute().

    La query retorna filas con:
      team_id, product_id, period_start, qty_sold, sales_gross, line_type
      (line_type: 'standalone' o 'combo_child')

    Parámetros:
      team_ids: lista de int (IDs de equipos)
      date_from, date_to: datetime.date
      team_field: 'crm_team_id' o 'team_id'
      type_field: 'detailed_type' o 'type'
      week_mode: True = agrupar por semana, False = por mes

    Uso:
        sql, params = explode_combo_sql(team_ids=[18,16], date_from=d1, date_to=d2)
        cr.execute(sql, params)
        rows = cr.fetchall()
    """
    from datetime import timedelta

    if week_mode:
        period_expr = "date_trunc('week', po.date_order AT TIME ZONE 'America/Santiago')::date"
    else:
        period_expr = "date_trunc('month', po.date_order AT TIME ZONE 'America/Santiago')::date"

    team_ids_literal = ",".join(str(t) for t in team_ids)

    sql = """
    WITH base AS (
        SELECT
            pc.{team_field}             AS team_id,
            pol.id                      AS line_id,
            pol.order_id,
            pol.product_id,
            pol.combo_parent_id,
            pol.qty,
            pol.price_subtotal_incl     AS gross,
            pt.{type_field}             AS prod_type,
            {period_expr}               AS period_start
        FROM pos_order_line pol
        JOIN pos_order po     ON po.id = pol.order_id
        JOIN pos_session ps   ON ps.id = po.session_id
        JOIN pos_config pc    ON pc.id = ps.config_id
        JOIN product_product pp  ON pp.id = pol.product_id
        JOIN product_template pt ON pt.id = pp.product_tmpl_id
        WHERE po.state IN ('paid', 'invoiced', 'done')
          AND po.date_order >= %(date_from)s
          AND po.date_order < %(date_to_excl)s
          AND pc.{team_field} IN ({team_ids})
          AND pp.active = true
          AND pt.sale_ok = true
    ),

    -- Líneas standalone: no son hijo de combo y no son tipo combo/service
    standalone AS (
        SELECT
            team_id,
            product_id,
            period_start,
            SUM(qty)   AS qty_sold,
            SUM(gross) AS sales_gross,
            'standalone' AS line_type
        FROM base
        WHERE combo_parent_id IS NULL
          AND prod_type NOT IN ('service', 'combo')
        GROUP BY team_id, product_id, period_start
    ),

    -- Total bruto del combo por línea padre (para prorratear)
    combo_totals AS (
        SELECT
            combo_parent_id,
            SUM(gross) AS total_child_gross,
            COUNT(*)   AS child_count
        FROM base
        WHERE combo_parent_id IS NOT NULL
        GROUP BY combo_parent_id
    ),

    -- Líneas hijo: atribuyen fracción proporcional de la venta del padre
    combo_children AS (
        SELECT
            child.team_id,
            child.product_id,
            child.period_start,
            SUM(child.qty) AS qty_sold,
            -- Si el hijo tiene precio, prorratear por gross; sino, distribución uniforme
            SUM(
                CASE
                    WHEN ct.total_child_gross > 0
                    THEN parent.gross * (child.gross / ct.total_child_gross)
                    ELSE parent.gross / ct.child_count
                END
            ) AS sales_gross,
            'combo_child' AS line_type
        FROM base child
        JOIN base parent ON parent.line_id = child.combo_parent_id
        JOIN combo_totals ct ON ct.combo_parent_id = child.combo_parent_id
        WHERE child.combo_parent_id IS NOT NULL
        GROUP BY child.team_id, child.product_id, child.period_start
    )

    SELECT team_id, product_id, period_start, qty_sold, sales_gross, line_type
    FROM standalone
    UNION ALL
    SELECT team_id, product_id, period_start, qty_sold, sales_gross, line_type
    FROM combo_children
    ORDER BY team_id, product_id, period_start
    """.format(
        team_field=team_field,
        type_field=type_field,
        period_expr=period_expr,
        team_ids=team_ids_literal,
    )

    from datetime import timedelta
    params = {
        "date_from": date_from,
        "date_to_excl": date_to + timedelta(days=1),
    }

    return sql, params
