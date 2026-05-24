# -*- coding: utf-8 -*-
# ============================================================
# OH Flujo de Caja - Matriz diaria de cashflow
# ============================================================
#
# Version activa: v1.3 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - Genera matriz diaria de flujo de caja en x_cash_flow combinando:
#       1. Ventas POS reales (venta D -> caja D+1).
#       2. Presupuesto de venta futuro (x_presupuesto_de_venta).
#       3. Facturas de compra pendientes (fecha flujo = vencimiento).
#       4. Facturas de compra vencidas (fecha flujo = hoy - 1).
#       5. IVA estimado (IVA ventas - IVA compras, pago dia 20).
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Modelo destino: x_cash_flow.
#   - Lectura de presupuesto: x_presupuesto_de_venta.
#   - Ejecucion recomendada: diaria 06:00 via cron.
#   - NO incluye aun (deuda visible): bancos, arriendos, remuneraciones,
#     TGR, BAT.
#
# Detalles, fixes historicos y esquema completo: ver CHANGELOG.md.
# ============================================================

VERSION_ID = 'OH_CASH_FLOW_v1_3_FACTURAS_VENTA_IVA_SII_2026_04_30'

CASH_FLOW_MODEL = 'x_cash_flow'

# Presupuesto de venta real según modelo Studio
BUDGET_MODEL = 'x_presupuesto_de_venta'
BUDGET_DATE_FIELD = 'x_date_2025_eq'
BUDGET_AMOUNT_FIELD = 'x_studio_presupuesto_actualizado'
BUDGET_AMOUNT_FALLBACK_FIELD = 'x_proj_2025'
BUDGET_COMPANY_FIELD = 'x_company_id'
BUDGET_ACTIVE_FIELD = 'x_active'

HORIZON_DAYS = 90
TIMEZONE = 'America/Santiago'

ADVISORY_LOCK_ID = 2026043001


# =========================
# FUNCIONES AUXILIARES
# =========================

def pick_selection_value(Model, field_name, desired_values):
    """
    Devuelve el valor técnico real de una selección.
    Sirve para tolerar espacios accidentales, por ejemplo '01_sales '.
    """
    if field_name not in Model._fields:
        return desired_values[0]

    selection = Model._fields[field_name].selection

    for desired in desired_values:
        for item in selection:
            key = item[0]
            if str(key).strip() == desired:
                return key

    return desired_values[0]


def date_plus_days(date_value, days):
    env.cr.execute(
        """
        SELECT (%s::date + ((%s)::text || ' days')::interval)::date
        """,
        (str(date_value)[:10], days)
    )
    return env.cr.fetchone()[0]


def add_cash_line(vals_list, name, flow_date, section, source, state,
                  amount_in, amount_out, partner_id=False, invoice_id=False,
                  origin_model=False, origin_id=0, is_overdue=False):
    amount_in = amount_in or 0.0
    amount_out = amount_out or 0.0
    amount_net = amount_in - amount_out

    vals = {
        'x_name': name,
        'x_studio_flow_date': flow_date,
        'x_studio_section': section,
        'x_studio_source': source,
        'x_studio_state': state,
        'x_studio_amount_in': amount_in,
        'x_studio_amount_out': amount_out,
        'x_studio_amount_net': amount_net,
        'x_studio_is_overdue': is_overdue,
        'x_studio_origin_id': origin_id or 0,
    }

    if partner_id:
        vals['x_studio_partner_id'] = partner_id

    if invoice_id:
        vals['x_studio_invoice_id'] = invoice_id

    if origin_model:
        vals['x_studio_origin_model'] = origin_model

    if HAS_CURRENCY_FIELD:
        vals['x_studio_currency_id'] = COMPANY_CURRENCY_ID

    vals_list.append(vals)


# =========================
# INICIO CON LOCK
# =========================

env.cr.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
lock_ok = env.cr.fetchone()[0]

if not lock_ok:
    raise UserError('El flujo de caja ya se está recalculando en otra ejecución.')

try:
    CashFlow = env[CASH_FLOW_MODEL]
    company = env.company
    COMPANY_ID = company.id
    COMPANY_CURRENCY_ID = company.currency_id.id

    HAS_CURRENCY_FIELD = 'x_studio_currency_id' in CashFlow._fields

    # =========================
    # VALORES TÉCNICOS REALES
    # =========================

    SECTION_SALES = pick_selection_value(CashFlow, 'x_studio_section', ['01_sales'])
    SECTION_SUPPLIERS = pick_selection_value(CashFlow, 'x_studio_section', ['02_suppliers'])
    SECTION_IVA = pick_selection_value(CashFlow, 'x_studio_section', ['03_iva'])

    SOURCE_POS = pick_selection_value(CashFlow, 'x_studio_source', ['pos_sales'])
    # Si agregas en Studio la opción técnica 'sales_invoice', se usará; si no existe, cae a 'pos_sales'.
    SOURCE_SALES_INVOICE = pick_selection_value(CashFlow, 'x_studio_source', ['sales_invoice', 'pos_sales'])
    SOURCE_BUDGET = pick_selection_value(CashFlow, 'x_studio_source', ['sales_budget'])
    SOURCE_PURCHASE = pick_selection_value(CashFlow, 'x_studio_source', ['purchase_invoice'])
    SOURCE_IVA = pick_selection_value(CashFlow, 'x_studio_source', ['iva_projection'])

    STATE_REAL = pick_selection_value(CashFlow, 'x_studio_state', ['Real'])
    STATE_PROJECTED = pick_selection_value(CashFlow, 'x_studio_state', ['Proyectado'])
    STATE_PENDING = pick_selection_value(CashFlow, 'x_studio_state', ['Pendiente'])
    STATE_OVERDUE = pick_selection_value(CashFlow, 'x_studio_state', ['Vencido'])

    ORIGIN_POS = pick_selection_value(CashFlow, 'x_studio_origin_model', ['pos.order'])
    ORIGIN_ACCOUNT_MOVE = pick_selection_value(CashFlow, 'x_studio_origin_model', ['account.move'])
    ORIGIN_BUDGET = pick_selection_value(CashFlow, 'x_studio_origin_model', ['x_presupuesto_de_venta'])

    AUTO_SOURCES = [
        SOURCE_POS,
        SOURCE_SALES_INVOICE,
        SOURCE_BUDGET,
        SOURCE_PURCHASE,
        SOURCE_IVA,
    ]

    # =========================
    # FECHAS BASE
    # =========================

    env.cr.execute(
        """
        WITH base AS (
            SELECT (now() AT TIME ZONE %s)::date AS today
        )
        SELECT
            today,
            (today - interval '1 day')::date AS yesterday,
            date_trunc('month', today)::date AS current_month_start,
            (date_trunc('month', today)::date + interval '1 month')::date AS next_month_start,
            (date_trunc('month', today)::date - interval '1 month')::date AS previous_month_start,
            (today + ((%s)::text || ' days')::interval)::date AS horizon_end,

            CASE
                WHEN EXTRACT(day FROM today)::int <= 20
                THEN (date_trunc('month', today)::date + interval '19 day')::date
                ELSE ((date_trunc('month', today)::date + interval '1 month') + interval '19 day')::date
            END AS iva_due_date,

            CASE
                WHEN EXTRACT(day FROM today)::int <= 20
                THEN (date_trunc('month', today)::date - interval '1 month')::date
                ELSE date_trunc('month', today)::date
            END AS iva_period_start,

            CASE
                WHEN EXTRACT(day FROM today)::int <= 20
                THEN date_trunc('month', today)::date
                ELSE (date_trunc('month', today)::date + interval '1 month')::date
            END AS iva_period_end
        FROM base
        """,
        (TIMEZONE, HORIZON_DAYS)
    )

    date_row = env.cr.fetchone()

    TODAY = date_row[0]
    YESTERDAY = date_row[1]
    CURRENT_MONTH_START = date_row[2]
    NEXT_MONTH_START = date_row[3]
    PREVIOUS_MONTH_START = date_row[4]
    HORIZON_END = date_row[5]
    IVA_DUE_DATE = date_row[6]
    IVA_PERIOD_START = date_row[7]
    IVA_PERIOD_END = date_row[8]

    vals_to_create = []

    count_pos = 0
    count_sales_invoice = 0
    count_budget = 0
    count_purchase = 0
    count_iva = 0
    skipped_budget_reason = ''

    # =========================
    # LIMPIAR LÍNEAS AUTOMÁTICAS
    # =========================

    old_lines = CashFlow.search([
        ('x_studio_source', 'in', AUTO_SOURCES),
    ])

    old_count = len(old_lines)

    if old_lines:
        old_lines.unlink()

    # =========================
    # 1) VENTAS POS REALES
    # Venta D entra a caja D+1
    # Se consideran ventas cerradas desde inicio de mes hasta ayer.
    # =========================

    if CURRENT_MONTH_START <= YESTERDAY:
        env.cr.execute(
            """
            SELECT
                sale_date,
                (sale_date + interval '1 day')::date AS flow_date,
                SUM(amount_total) AS amount_total
            FROM (
                SELECT
                    ((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %s)::date AS sale_date,
                    po.amount_total AS amount_total
                FROM pos_order po
                WHERE po.company_id = %s
                  AND po.state IN ('paid', 'done', 'invoiced')
                  AND po.date_order IS NOT NULL
            ) q
            WHERE sale_date >= %s
              AND sale_date <= %s
            GROUP BY sale_date
            ORDER BY sale_date
            """,
            (TIMEZONE, COMPANY_ID, CURRENT_MONTH_START, YESTERDAY)
        )

        pos_rows = env.cr.fetchall()

        for row in pos_rows:
            sale_date = row[0]
            flow_date = row[1]
            amount = float(row[2] or 0.0)

            if amount:
                name = 'Venta POS %s - entra %s' % (str(sale_date), str(flow_date))

                add_cash_line(
                    vals_to_create,
                    name,
                    flow_date,
                    SECTION_SALES,
                    SOURCE_POS,
                    STATE_REAL,
                    amount,
                    0.0,
                    False,
                    False,
                    ORIGIN_POS,
                    0,
                    False
                )

                count_pos += 1

    # =========================
    # 2) FACTURAS DE VENTA REALES NO POS
    # Factura D entra a caja D+1.
    # Objetivo: incluir ventas por factura electrónica (33) que no vienen desde POS.
    # Se excluyen boletas/resúmenes 39/41 para evitar duplicar POS.
    # Se intenta excluir facturas vinculadas a pos.order si la columna existe.
    # =========================

    env.cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'pos_order'
              AND column_name = 'account_move'
        )
        """
    )
    HAS_POS_ORDER_ACCOUNT_MOVE = env.cr.fetchone()[0]

    sales_invoice_sql = """
        SELECT
            invoice_date,
            (invoice_date + interval '1 day')::date AS flow_date,
            SUM(amount_signed) AS amount_total
        FROM (
            SELECT
                COALESCE(am.invoice_date, am.date)::date AS invoice_date,
                CASE
                    WHEN am.move_type = 'out_refund' THEN -ABS(am.amount_total_signed)
                    ELSE ABS(am.amount_total_signed)
                END AS amount_signed
            FROM account_move am
            LEFT JOIN l10n_latam_document_type dt ON dt.id = am.l10n_latam_document_type_id
            WHERE am.company_id = %s
              AND am.state = 'posted'
              AND am.move_type IN ('out_invoice', 'out_refund')
              AND COALESCE(am.invoice_date, am.date)::date >= %s
              AND COALESCE(am.invoice_date, am.date)::date <= %s
              AND COALESCE(dt.code, '') NOT IN ('39', '41')
    """

    sales_params = [COMPANY_ID, CURRENT_MONTH_START, YESTERDAY]

    if HAS_POS_ORDER_ACCOUNT_MOVE:
        sales_invoice_sql += """
              AND NOT EXISTS (
                  SELECT 1
                  FROM pos_order po
                  WHERE po.account_move = am.id
              )
        """

    sales_invoice_sql += """
        ) q
        GROUP BY invoice_date
        HAVING SUM(amount_signed) <> 0
        ORDER BY invoice_date
    """

    if CURRENT_MONTH_START <= YESTERDAY:
        env.cr.execute(sales_invoice_sql, tuple(sales_params))
        sales_invoice_rows = env.cr.fetchall()

        for row in sales_invoice_rows:
            invoice_date = row[0]
            flow_date = row[1]
            amount = float(row[2] or 0.0)

            if amount > 0:
                name = 'Facturas venta %s - entra %s' % (str(invoice_date), str(flow_date))
                add_cash_line(
                    vals_to_create,
                    name,
                    flow_date,
                    SECTION_SALES,
                    SOURCE_SALES_INVOICE,
                    STATE_REAL,
                    amount,
                    0.0,
                    False,
                    False,
                    ORIGIN_ACCOUNT_MOVE,
                    0,
                    False
                )
                count_sales_invoice += 1

            elif amount < 0:
                name = 'Notas crédito venta %s - descuenta %s' % (str(invoice_date), str(flow_date))
                add_cash_line(
                    vals_to_create,
                    name,
                    flow_date,
                    SECTION_SALES,
                    SOURCE_SALES_INVOICE,
                    STATE_REAL,
                    0.0,
                    abs(amount),
                    False,
                    False,
                    ORIGIN_ACCOUNT_MOVE,
                    0,
                    False
                )
                count_sales_invoice += 1


    # =========================
    # 3) PRESUPUESTO DE VENTA FUTURO
    # Presupuesto D entra a caja D+1
    # Desde hoy hasta horizonte.
    # Modelo: x_presupuesto_de_venta
    # Fecha: x_date_2025_eq
    # Monto principal: x_studio_presupuesto_actualizado
    # Monto respaldo: x_proj_2025
    # =========================

    budget_model_rec = env['ir.model'].search([('model', '=', BUDGET_MODEL)], limit=1)

    if budget_model_rec:
        Budget = env[BUDGET_MODEL]

        missing_budget_fields = []

        if BUDGET_DATE_FIELD not in Budget._fields:
            missing_budget_fields.append(BUDGET_DATE_FIELD)

        if BUDGET_AMOUNT_FIELD not in Budget._fields:
            missing_budget_fields.append(BUDGET_AMOUNT_FIELD)

        if missing_budget_fields:
            skipped_budget_reason = 'Presupuesto omitido. Faltan campos: %s' % ', '.join(missing_budget_fields)
        else:
            budget_domain = [
                (BUDGET_DATE_FIELD, '>=', TODAY),
                (BUDGET_DATE_FIELD, '<=', HORIZON_END),
            ]

            if BUDGET_ACTIVE_FIELD in Budget._fields:
                budget_domain.append((BUDGET_ACTIVE_FIELD, '=', True))

            if BUDGET_COMPANY_FIELD in Budget._fields:
                budget_domain.append((BUDGET_COMPANY_FIELD, '=', COMPANY_ID))

            budget_records = Budget.search(budget_domain)

            budget_by_day = {}

            for b in budget_records:
                budget_date_raw = b[BUDGET_DATE_FIELD]

                if not budget_date_raw:
                    continue

                budget_sale_date = str(budget_date_raw)[:10]
                amount = float(b[BUDGET_AMOUNT_FIELD] or 0.0)

                # Fallback si el presupuesto actualizado está en cero
                if amount == 0.0 and BUDGET_AMOUNT_FALLBACK_FIELD in Budget._fields:
                    amount = float(b[BUDGET_AMOUNT_FALLBACK_FIELD] or 0.0)

                if amount:
                    if budget_sale_date not in budget_by_day:
                        budget_by_day[budget_sale_date] = 0.0

                    budget_by_day[budget_sale_date] += amount

            for budget_sale_date in budget_by_day:
                amount = budget_by_day[budget_sale_date]

                if amount:
                    flow_date = date_plus_days(budget_sale_date, 1)

                    name = 'Presupuesto venta %s - entra %s' % (
                        str(budget_sale_date),
                        str(flow_date)
                    )

                    add_cash_line(
                        vals_to_create,
                        name,
                        flow_date,
                        SECTION_SALES,
                        SOURCE_BUDGET,
                        STATE_PROJECTED,
                        amount,
                        0.0,
                        False,
                        False,
                        ORIGIN_BUDGET,
                        0,
                        False
                    )

                    count_budget += 1
    else:
        skipped_budget_reason = 'Presupuesto omitido: no existe modelo %s.' % BUDGET_MODEL

    # =========================
    # 4) FACTURAS DE COMPRA PENDIENTES / VENCIDAS
    # Pendiente: fecha flujo = vencimiento
    # Vencida: fecha flujo = hoy - 1
    # =========================

    purchase_domain = [
        ('company_id', '=', COMPANY_ID),
        ('move_type', '=', 'in_invoice'),
        ('state', '=', 'posted'),
        ('payment_state', 'not in', ['paid', 'reversed']),
        ('amount_residual', '>', 0),
    ]

    purchase_invoices = env['account.move'].search(purchase_domain)

    for inv in purchase_invoices:
        amount = float(inv.amount_residual or 0.0)

        if amount <= 0:
            continue

        due_date = inv.invoice_date_due or inv.invoice_date or TODAY

        # Si no está vencida y queda fuera del horizonte, no se muestra todavía.
        if due_date >= TODAY and due_date > HORIZON_END:
            continue

        is_overdue = False

        if due_date < TODAY:
            flow_date = YESTERDAY
            state = STATE_OVERDUE
            is_overdue = True
        else:
            flow_date = due_date
            state = STATE_PENDING

        partner_name = ''
        partner_id = False

        if inv.partner_id:
            partner_name = inv.partner_id.display_name or ''
            partner_id = inv.partner_id.id

        doc_name = inv.name or inv.ref or ('ID %s' % inv.id)

        if partner_name:
            name = 'Proveedor %s - %s' % (partner_name, doc_name)
        else:
            name = 'Proveedor sin nombre - %s' % doc_name

        add_cash_line(
            vals_to_create,
            name,
            flow_date,
            SECTION_SUPPLIERS,
            SOURCE_PURCHASE,
            state,
            0.0,
            amount,
            partner_id,
            inv.id,
            ORIGIN_ACCOUNT_MOVE,
            inv.id,
            is_overdue
        )

        count_purchase += 1

    # =========================
    # 5) IVA ESTIMADO SEGÚN CRITERIO SII / F29 OPERATIVO
    # Pago proyectado: día 20.
    #
    # Regla validada:
    #   IVA a pagar = IVA débito ventas - IVA crédito compras
    #
    # Criterio:
    #   Ventas:
    #       Facturas / boletas suman IVA débito.
    #       Notas de crédito de venta restan IVA débito.
    #       Asientos POS se consideran solo si el diario es de ventas.
    #
    #   Compras:
    #       Facturas de compra suman IVA crédito recuperable.
    #       Notas de crédito de compra restan IVA crédito recuperable.
    #       IVA no recuperable / uso común NO se usa como crédito.
    #
    # Nota:
    #   Este cálculo busca calzar con el resumen SII/F29 operativo:
    #       Ventas abril: IVA débito generado.
    #       Compras abril: solo IVA crédito recuperable.
    #       Diferencia: egreso el 20 del mes siguiente.
    # =========================

    env.cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'account_move'
              AND column_name = 'l10n_latam_document_type_id'
        )
        """
    )
    HAS_LATAM_DOC_TYPE = env.cr.fetchone()[0]

    if HAS_LATAM_DOC_TYPE:
        iva_sql = """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN am.move_type IN ('out_invoice', 'out_receipt')
                            THEN ABS(aml.balance)
                        WHEN am.move_type = 'out_refund'
                            THEN -ABS(aml.balance)
                        WHEN am.move_type = 'entry'
                             AND aj.type = 'sale'
                             AND aml.balance < 0
                            THEN -aml.balance
                        ELSE 0
                    END
                ), 0) AS iva_debito_ventas,

                COALESCE(SUM(
                    CASE
                        WHEN am.move_type IN ('in_invoice', 'in_receipt')
                             AND NOT (
                                 LOWER(COALESCE(tax.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso común%%'
                             )
                            THEN ABS(aml.balance)
                        WHEN am.move_type = 'in_refund'
                             AND NOT (
                                 LOWER(COALESCE(tax.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso común%%'
                             )
                            THEN -ABS(aml.balance)
                        ELSE 0
                    END
                ), 0) AS iva_credito_compras,

                COALESCE(SUM(
                    CASE
                        WHEN am.move_type IN ('in_invoice', 'in_receipt', 'in_refund')
                             AND (
                                 LOWER(COALESCE(tax.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso común%%'
                             )
                            THEN
                                CASE
                                    WHEN am.move_type = 'in_refund' THEN -ABS(aml.balance)
                                    ELSE ABS(aml.balance)
                                END
                        ELSE 0
                    END
                ), 0) AS iva_no_recuperable_excluido

            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_tax tax ON tax.id = aml.tax_line_id
            JOIN account_journal aj ON aj.id = am.journal_id
            JOIN account_account aa ON aa.id = aml.account_id
            LEFT JOIN l10n_latam_document_type dt ON dt.id = am.l10n_latam_document_type_id
            WHERE am.company_id = %s
              AND am.state = 'posted'
              AND aml.tax_line_id IS NOT NULL
              AND COALESCE(am.invoice_date, am.date) >= %s
              AND COALESCE(am.invoice_date, am.date) < %s
              AND tax.amount_type = 'percent'
              AND ROUND(ABS(tax.amount)::numeric, 2) = 19.00
              AND (
                    am.move_type IN ('out_invoice', 'out_receipt', 'out_refund', 'in_invoice', 'in_receipt', 'in_refund')
                    OR (
                        am.move_type = 'entry'
                        AND aj.type = 'sale'
                        AND COALESCE(dt.code, '') IN ('39', '41', '33', '61')
                    )
              )
        """
    else:
        iva_sql = """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN am.move_type IN ('out_invoice', 'out_receipt')
                            THEN ABS(aml.balance)
                        WHEN am.move_type = 'out_refund'
                            THEN -ABS(aml.balance)
                        WHEN am.move_type = 'entry'
                             AND aj.type = 'sale'
                             AND aml.balance < 0
                            THEN -aml.balance
                        ELSE 0
                    END
                ), 0) AS iva_debito_ventas,

                COALESCE(SUM(
                    CASE
                        WHEN am.move_type IN ('in_invoice', 'in_receipt')
                             AND NOT (
                                 LOWER(COALESCE(tax.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso común%%'
                             )
                            THEN ABS(aml.balance)
                        WHEN am.move_type = 'in_refund'
                             AND NOT (
                                 LOWER(COALESCE(tax.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso común%%'
                             )
                            THEN -ABS(aml.balance)
                        ELSE 0
                    END
                ), 0) AS iva_credito_compras,

                COALESCE(SUM(
                    CASE
                        WHEN am.move_type IN ('in_invoice', 'in_receipt', 'in_refund')
                             AND (
                                 LOWER(COALESCE(tax.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(tax.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aa.name::text, '')) LIKE '%%uso común%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no recuper%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%no-rec%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso com%%'
                                 OR LOWER(COALESCE(aml.name::text, '')) LIKE '%%uso común%%'
                             )
                            THEN
                                CASE
                                    WHEN am.move_type = 'in_refund' THEN -ABS(aml.balance)
                                    ELSE ABS(aml.balance)
                                END
                        ELSE 0
                    END
                ), 0) AS iva_no_recuperable_excluido

            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_tax tax ON tax.id = aml.tax_line_id
            JOIN account_journal aj ON aj.id = am.journal_id
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE am.company_id = %s
              AND am.state = 'posted'
              AND aml.tax_line_id IS NOT NULL
              AND COALESCE(am.invoice_date, am.date) >= %s
              AND COALESCE(am.invoice_date, am.date) < %s
              AND tax.amount_type = 'percent'
              AND ROUND(ABS(tax.amount)::numeric, 2) = 19.00
              AND (
                    am.move_type IN ('out_invoice', 'out_receipt', 'out_refund', 'in_invoice', 'in_receipt', 'in_refund')
                    OR (
                        am.move_type = 'entry'
                        AND aj.type = 'sale'
                    )
              )
        """

    env.cr.execute(iva_sql, (COMPANY_ID, IVA_PERIOD_START, IVA_PERIOD_END))
    iva_row = env.cr.fetchone()

    iva_debito_ventas = float(iva_row[0] or 0.0)
    iva_credito_compras = float(iva_row[1] or 0.0)
    iva_no_recuperable_excluido = float(iva_row[2] or 0.0)

    iva_to_pay = round(iva_debito_ventas - iva_credito_compras)

    if iva_to_pay > 0:
        iva_period_label = str(IVA_PERIOD_START)[:7]

        name = 'IVA estimado %s - debito %.0f / credito recuperable %.0f / no rec excl %.0f' % (
            iva_period_label,
            iva_debito_ventas,
            iva_credito_compras,
            iva_no_recuperable_excluido
        )

        iva_state = STATE_PROJECTED
        iva_flow_date = IVA_DUE_DATE
        iva_is_overdue = False

        if IVA_DUE_DATE < TODAY:
            iva_state = STATE_OVERDUE
            iva_flow_date = YESTERDAY
            iva_is_overdue = True

        add_cash_line(
            vals_to_create,
            name,
            iva_flow_date,
            SECTION_IVA,
            SOURCE_IVA,
            iva_state,
            0.0,
            iva_to_pay,
            False,
            False,
            ORIGIN_ACCOUNT_MOVE,
            0,
            iva_is_overdue
        )

        count_iva += 1

    elif iva_to_pay < 0:
        pass

    # =========================
    # CREAR LÍNEAS
    # =========================

    created_count = 0

    if vals_to_create:
        CashFlow.create(vals_to_create)
        created_count = len(vals_to_create)

    # =========================
    # MENSAJE FINAL
    # =========================

    message = (
        'Flujo de caja actualizado. '
        'Eliminadas: %s | Creadas: %s | '
        'POS: %s | Facturas venta: %s | Presupuesto: %s | Proveedores: %s | IVA: %s'
    ) % (
        old_count,
        created_count,
        count_pos,
        count_sales_invoice,
        count_budget,
        count_purchase,
        count_iva,
    )

    if skipped_budget_reason:
        message = message + ' | ' + skipped_budget_reason

    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'Flujo de caja',
            'message': message,
            'sticky': False,
            'type': 'success',
        }
    }

finally:
    env.cr.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
