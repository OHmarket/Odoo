# ============================================================
# OH Generacion de Documentos - Crea OCs y traslados desde Analisis Stock
# ============================================================
#
# Version activa: v1.6 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - Lee x_analisis_de_stock y crea documentos en Odoo:
#       - purchase.order (compra a proveedor) en estado Borrador/RFQ.
#       - stock.picking (traslados internos CD <-> sala) en Borrador.
#   - Filtros por gen_type: compra_sala / compra_bodega / envio_a_sala /
#     transferencia_interna_retiro.
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Modo adopcion: NO auto-confirma. Todo queda en Borrador para revision
#     humana (Compras + Bodega/Operaciones).
#   - Idempotencia por origin_key contra documentos no cancelados.
#   - Ejecuta el analisis de stock (action 1502) al inicio y exige snapshot
#     fresco posterior al inicio de la ejecucion.
#   - Compras en cajas (qty_a_pedir_cajas * MOQ). Traslados en unidades.
#   - Retorno a CD usa x_studio_qty_transferir + buy_action='retorno_a_cd'.
#   - Documentos borrador no entran a stock_pedido hasta ser confirmados.
#
# Detalles, fixes historicos y esquema completo: ver CHANGELOG.md.
# ============================================================

VERSION_ID = 'OH_SUPPLY_GENERATION_v1_6_BUDGET_RANK_ABCXYZ'

ACTION_STOCK_ANALYSIS_ID = 1502
CENTRAL_WAREHOUSE_ID     = 15
CENTRAL_TEAM_ID          = 26
LOCK_KEY                 = 99123041

# Si True, bloquea productos cuya UoM de compra sea igual a la UoM base.
# Si aún no están todas las UoM de compra/caja configuradas, cambia a False para probar.
STRICT_PURCHASE_UOM_BOX = True

# Bandas de ranking para los flags Top/Medio/Bajo, sobre x_studio_rank_abcxyz
# (1 = mejor margen acumulado; el numero CRECE al bajar la importancia).
#   Top   : rank 1..300
#   Medio : rank 301..800
#   Bajo  : rank 801..N (resto)
RANK_BAND_TOP_MAX    = 300
RANK_BAND_MEDIUM_MAX = 800

TEAM_WAREHOUSE_MAP_FALLBACK = {
    5:  1,
    6:  4,
    7:  2,
    8:  3,
    9:  16,
    10: 8,
    11: 5,
    12: 9,
    13: 10,
    16: 12,
    17: 14,
    18: 13,
}

rec = record
if not rec:
    raise UserError('No hay registro activo.')

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _safe_float(v, default=0.0):
    try:
        return float(v or 0.0)
    except Exception:
        return default

def _now_dt():
    # Odoo Datetime espera naive UTC.
    # SELECT now() devuelve timestamptz con timezone y falla en date_planned.
    env.cr.execute("SELECT (now() AT TIME ZONE 'UTC')")
    row = env.cr.fetchone()
    return row and row[0] or False

def _get_first_variant_from_tmpl(tmpl_id):
    return env['product.product'].sudo().search([('product_tmpl_id', '=', tmpl_id)], limit=1)

def _get_wh(wh_id):
    wh = env['stock.warehouse'].sudo().browse(wh_id)
    if not wh or not wh.exists():
        return False
    return wh

def _get_stock_loc_from_wh(wh_id):
    wh = _get_wh(wh_id)
    if not wh or not wh.lot_stock_id:
        return False
    return wh.lot_stock_id

def _get_in_type_from_wh(wh_id):
    wh = _get_wh(wh_id)
    if wh and wh.in_type_id:
        return wh.in_type_id
    return env['stock.picking.type'].sudo().search([('code', '=', 'incoming')], limit=1)

def _get_internal_type_from_wh(wh_id):
    pt = env['stock.picking.type'].sudo().search([
        ('warehouse_id', '=', wh_id),
        ('code', '=', 'internal')
    ], limit=1)
    if pt:
        return pt
    return env['stock.picking.type'].sudo().search([('code', '=', 'internal')], limit=1)

def _set_summary(ok_bool, msg, snapshot_date, total_lines, total_amount):
    vals = {}
    if rec._fields.get('x_studio_prereq_ok'):
        vals['x_studio_prereq_ok'] = bool(ok_bool)
    if rec._fields.get('x_studio_prereq_message'):
        vals['x_studio_prereq_message'] = msg or ''
    if rec._fields.get('x_studio_stock_analysis_updated_on'):
        vals['x_studio_stock_analysis_updated_on'] = bool(ok_bool)
    if rec._fields.get('x_studio_snapshot_date') and snapshot_date:
        vals['x_studio_snapshot_date'] = snapshot_date
    if rec._fields.get('x_studio_total_selected_lines'):
        vals['x_studio_total_selected_lines'] = total_lines
    if rec._fields.get('x_studio_total_selected_amoun'):
        vals['x_studio_total_selected_amoun'] = total_amount
    if rec._fields.get('x_studio_generated_on') and ok_bool:
        vals['x_studio_generated_on'] = _now_dt()
    if vals:
        rec.write(vals)

def _any_group_selected():
    return bool(rec.x_studio_inc_top or rec.x_studio_inc_medium or rec.x_studio_inc_low)

def _selected_rank_domain():
    # Sub-dominio Odoo (OR de las bandas marcadas) sobre x_studio_rank_abcxyz.
    # Top=1..300, Medio=301..800, Bajo=801..N (resto). rank 1 = mejor margen.
    bands = []
    if rec.x_studio_inc_top:
        bands.append(['&', ('x_studio_rank_abcxyz', '>=', 1),
                           ('x_studio_rank_abcxyz', '<=', RANK_BAND_TOP_MAX)])
    if rec.x_studio_inc_medium:
        bands.append(['&', ('x_studio_rank_abcxyz', '>=', RANK_BAND_TOP_MAX + 1),
                           ('x_studio_rank_abcxyz', '<=', RANK_BAND_MEDIUM_MAX)])
    if rec.x_studio_inc_low:
        bands.append([('x_studio_rank_abcxyz', '>=', RANK_BAND_MEDIUM_MAX + 1)])
    # Combina las bandas con OR (notacion polaca: N-1 '|' al frente).
    dom = ['|'] * (len(bands) - 1) if len(bands) > 1 else []
    for b in bands:
        dom += b
    return dom

def _run_stock_analysis():
    act = env['ir.actions.server'].sudo().browse(ACTION_STOCK_ANALYSIS_ID)
    if not act or not act.exists():
        raise UserError('No existe la acción de análisis de stock. Ajusta ACTION_STOCK_ANALYSIS_ID.')
    act.run()

def _latest_snapshot_after(started_at):
    Anal = env['x_analisis_de_stock'].sudo()
    row = Anal.search(
        [
            ('x_studio_company_id', '=', env.company.id),
            ('write_date', '>=', started_at),
        ],
        order='write_date desc, id desc',
        limit=1
    )
    return row and row.x_studio_fecha_1 or False

def _build_origin_key(snapshot_date, gen_type):
    supplier_id = 0
    team_id = 0
    if rec.x_studio_supplier_id:
        supplier_id = rec.x_studio_supplier_id.id
    if rec.x_studio_team_id:
        team_id = rec.x_studio_team_id.id
    return 'SUPPLY|%s|%s|%s|%s|%s' % (
        rec.id,
        gen_type or '',
        supplier_id,
        team_id,
        snapshot_date,
    )

# ------------------------------------------------------------
# Lock
# ------------------------------------------------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
row = env.cr.fetchone()
locked = bool(row and row[0])

if not locked:
    raise UserError('Otro proceso de Supply Generation está ejecutándose. Reintenta.')

try:
    # --------------------------------------------------------
    # Validaciones del formulario
    # --------------------------------------------------------
    lote_name = (rec.x_name or '').strip()
    if not lote_name:
        raise UserError('Debes completar Nombre del Lote. Ej: GEN Compra Sala - CCU - Panguipulli 790.')

    gen_type = rec.x_studio_generation_type or False
    if not gen_type:
        raise UserError('Falta Operación.')

    if not _any_group_selected():
        raise UserError('Debes marcar al menos un grupo: Top, Medio o Bajo.')

    if gen_type in ('compra_sala', 'compra_bodega') and not rec.x_studio_supplier_id:
        raise UserError('Proveedor es obligatorio para compras.')

    if gen_type in ('compra_sala', 'envio_a_sala', 'transferencia_interna_retiro') and not rec.x_studio_team_id:
        raise UserError('Sucursal es obligatoria para esta operación.')

    # --------------------------------------------------------
    # 1) Recalcular análisis de stock al inicio
    # --------------------------------------------------------
    started_at = _now_dt()
    _run_stock_analysis()

    # --------------------------------------------------------
    # 2) Exigir snapshot fresco creado/modificado después del inicio
    # --------------------------------------------------------
    snapshot_date = _latest_snapshot_after(started_at)
    if not snapshot_date:
        _set_summary(False, 'Análisis de Stock no generó snapshot fresco. Revisar acción 1502.', False, 0, 0.0)
        raise UserError('Análisis de Stock no generó snapshot fresco. Revisar acción 1502.')

    Anal = env['x_analisis_de_stock'].sudo()

    domain = [
        ('x_studio_company_id', '=', env.company.id),
        ('x_studio_fecha_1', '=', snapshot_date),
    ]
    # Universo por banda de ranking (flags Top/Medio/Bajo => rank_abcxyz).
    domain += _selected_rank_domain()

    total_amount = 0.0
    selected_rows = []
    origin_key = _build_origin_key(snapshot_date, gen_type)

    # --------------------------------------------------------
    # 3) Compras: compra_sala / compra_bodega
    # --------------------------------------------------------
    if gen_type in ('compra_sala', 'compra_bodega'):
        supplier_id = rec.x_studio_supplier_id.id

        if gen_type == 'compra_sala':
            team_id = rec.x_studio_team_id.id
            dest_wh_id = TEAM_WAREHOUSE_MAP_FALLBACK.get(team_id)
            if not dest_wh_id:
                raise UserError('No existe warehouse mapeado para la sucursal seleccionada.')

            domain += [
                ('x_studio_team_id', '=', team_id),
                ('x_studio_proveedor_id', '=', supplier_id),
                ('x_studio_buy_action', '=', 'reponer_ahora'),
                ('x_studio_qty_a_pedir_cajas', '>', 0),
            ]

        else:
            dest_wh_id = CENTRAL_WAREHOUSE_ID
            domain += [
                ('x_studio_team_id', '=', CENTRAL_TEAM_ID),
                ('x_studio_proveedor_id', '=', supplier_id),
                ('x_studio_buy_action', '=', 'compra_cd'),
                ('x_studio_qty_a_pedir_cajas', '>', 0),
            ]

        # Prioridad unica para compras (sala y CD): ranking de margen de la
        # segmentacion, x_studio_rank_abcxyz. rank 1 = mayor margen acumulado
        # (el mejor) y el numero CRECE a medida que el SKU importa menos, asi
        # que ASC = mejor primero (NO desc). Desempate por valor de orden
        # ascendente (mas barato primero).
        order = 'x_studio_rank_abcxyz asc, x_studio_valor_orden_compra asc'

        rows = Anal.search(domain, order=order)

        if not rows:
            _set_summary(False, 'No hay líneas elegibles para compra.', snapshot_date, 0, 0.0)
            raise UserError('No hay líneas elegibles para compra.')

        # Presupuesto: recorre rank_abcxyz de 1 hacia N (mejor margen primero) y
        # acumula hasta topar el monto total. Si una linea no cabe en el saldo,
        # se salta y se sigue con la siguiente (mas abajo en rank) hasta agotar
        # el presupuesto. Aplica igual a compra_sala y compra_bodega.
        if rec.x_studio_use_budget and _safe_float(rec.x_studio_budget_amount, 0.0) > 0.0:
            budget = _safe_float(rec.x_studio_budget_amount, 0.0)
            for r in rows:
                line_amount = _safe_float(r.x_studio_valor_orden_compra, 0.0)
                if total_amount + line_amount <= budget:
                    selected_rows.append(r)
                    total_amount += line_amount
        else:
            selected_rows = rows
            for r in rows:
                total_amount += _safe_float(r.x_studio_valor_orden_compra, 0.0)

        if not selected_rows:
            _set_summary(False, 'No quedaron líneas luego de aplicar presupuesto.', snapshot_date, 0, 0.0)
            raise UserError('No quedaron líneas luego de aplicar presupuesto.')

        existing_po = env['purchase.order'].sudo().search([
            ('origin', '=', origin_key),
            ('state', '!=', 'cancel'),
        ], limit=1)
        if existing_po:
            _set_summary(False, 'Ya existe RFQ/OC no cancelada para esta solicitud.', snapshot_date, 0, 0.0)
            raise UserError('Ya existe una RFQ/OC no cancelada generada para esta solicitud.')

        in_type = _get_in_type_from_wh(dest_wh_id)
        po_vals = {
            'partner_id': supplier_id,
            'origin': origin_key,
        }
        if in_type:
            po_vals['picking_type_id'] = in_type.id

        po = env['purchase.order'].sudo().create(po_vals)

        created_lines = 0
        skipped = []

        for r in selected_rows:
            tmpl = r.x_studio_product_id
            tmpl_id = tmpl and tmpl.id or False
            if not tmpl_id:
                skipped.append('sin_template')
                continue

            product = _get_first_variant_from_tmpl(tmpl_id)
            if not product:
                skipped.append('tmpl_%s_sin_variante' % tmpl_id)
                continue

            qty_boxes = _safe_float(r.x_studio_qty_a_pedir_cajas, 0.0)
            moq = _safe_float(r.x_studio_moq, 0.0)
            unit_price = _safe_float(r.x_studio_purchase_price_cash_unit, 0.0)

            if qty_boxes <= 0.0:
                continue
            if moq <= 0.0:
                skipped.append('%s_moq_0' % (product.default_code or product.id))
                continue

            uom_po = product.uom_po_id or product.uom_id
            if not uom_po:
                skipped.append('%s_sin_uom_po' % (product.default_code or product.id))
                continue

            if STRICT_PURCHASE_UOM_BOX:
                if (not product.uom_po_id) or (product.uom_po_id.id == product.uom_id.id):
                    skipped.append('%s_uom_compra_no_caja' % (product.default_code or product.id))
                    continue

            # Compra en cajas:
            # qty = cajas
            # price_unit = precio por caja = precio unitario * moq
            price_box = unit_price * moq

            env['purchase.order.line'].sudo().create({
                'order_id': po.id,
                'product_id': product.id,
                'name': product.display_name,
                'product_qty': qty_boxes,
                'product_uom': uom_po.id,
                'price_unit': price_box,
                'date_planned': _now_dt(),
            })
            created_lines += 1

        if created_lines == 0:
            po.unlink()
            _set_summary(False, 'No se crearon líneas de compra. Revisa UoM compra/caja, MOQ y productos omitidos: %s' % (', '.join(skipped[:10])), snapshot_date, 0, 0.0)
            raise UserError('No se pudieron crear líneas de compra válidas. Revisa UoM compra/caja y MOQ.')

        # MODO ADOPCIÓN:
        # No confirmar automáticamente. La OC queda como RFQ/Borrador.
        # Importante: mientras esté en borrador, normalmente NO entra a stock_pedido.
        # po.button_confirm()

        msg = 'OK BORRADOR | %s | RFQ=%s | lineas=%s | snapshot=%s' % (
            lote_name,
            po.name or po.id,
            created_lines,
            snapshot_date,
        )
        if skipped:
            msg += ' | omitidas=%s' % (', '.join(skipped[:10]))

        _set_summary(True, msg, snapshot_date, created_lines, total_amount)

        write_vals = {}
        if rec._fields.get('x_studio_generated_docs_count'):
            write_vals['x_studio_generated_docs_count'] = 1
        if rec._fields.get('x_studio_origin_key'):
            write_vals['x_studio_origin_key'] = origin_key
        if write_vals:
            rec.write(write_vals)

        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Supply Generation',
                'message': 'RFQ borrador generada: %s' % (po.name or ''),
                'type': 'success',
                'sticky': False,
            }
        }

    # --------------------------------------------------------
    # 4) Traslados: envio_a_sala / transferencia_interna_retiro
    # --------------------------------------------------------
    elif gen_type in ('envio_a_sala', 'transferencia_interna_retiro'):
        team_id = rec.x_studio_team_id.id
        local_wh_id = TEAM_WAREHOUSE_MAP_FALLBACK.get(team_id)
        if not local_wh_id:
            raise UserError('No existe warehouse mapeado para la sucursal seleccionada.')

        if gen_type == 'envio_a_sala':
            # CD -> Local
            src_wh_id = CENTRAL_WAREHOUSE_ID
            dst_wh_id = local_wh_id
            # Filtra por la ACCION (buy_action), no por supply_source.
            # supply_source='transferir_desde_cd' es la politica estatica ("si
            # falta, traer del CD") y queda seteada incluso en filas de retorno
            # (ver OH Analisis de Stock.py: RETURN_TO_CD usa el mismo
            # qty_transferir + supply_source SAFE). Filtrar por supply_source
            # barria filas retorno_a_cd y compra_cd y las enviaba al reves.
            # La accion de enviar CD->sala es buy_action='transferir_desde_cd'.
            domain += [
                ('x_studio_team_id', '=', team_id),
                ('x_studio_buy_action', '=', 'transferir_desde_cd'),
                ('x_studio_qty_transferir', '>', 0),
            ]
        else:
            # Local -> CD
            # Regla operativa: retorno a CD usa la misma cantidad de traslado.
            src_wh_id = local_wh_id
            dst_wh_id = CENTRAL_WAREHOUSE_ID
            domain += [
                ('x_studio_team_id', '=', team_id),
                ('x_studio_buy_action', '=', 'retorno_a_cd'),
                ('x_studio_qty_transferir', '>', 0),
            ]

        rows = Anal.search(
            domain,
            order='x_studio_severity desc, x_studio_valor_reponer desc'
        )

        if not rows:
            _set_summary(False, 'No hay líneas elegibles para traslado.', snapshot_date, 0, 0.0)
            raise UserError('No hay líneas elegibles para traslado.')

        selected_rows = rows

        src_loc = _get_stock_loc_from_wh(src_wh_id)
        dst_loc = _get_stock_loc_from_wh(dst_wh_id)
        if not src_loc:
            raise UserError('No se encontró ubicación de stock origen.')
        if not dst_loc:
            raise UserError('No se encontró ubicación de stock destino.')

        internal_type = _get_internal_type_from_wh(src_wh_id)
        if not internal_type:
            raise UserError('No se encontró picking type interno.')

        existing_picking = env['stock.picking'].sudo().search([
            ('origin', '=', origin_key),
            ('state', '!=', 'cancel'),
        ], limit=1)
        if existing_picking:
            _set_summary(False, 'Ya existe traslado no cancelado para esta solicitud.', snapshot_date, 0, 0.0)
            raise UserError('Ya existe un traslado no cancelado generado para esta solicitud.')

        picking = env['stock.picking'].sudo().create({
            'picking_type_id': internal_type.id,
            'location_id': src_loc.id,
            'location_dest_id': dst_loc.id,
            'origin': origin_key,
            'company_id': env.company.id,
        })

        created_moves = 0
        for r in selected_rows:
            tmpl = r.x_studio_product_id
            tmpl_id = tmpl and tmpl.id or False
            if not tmpl_id:
                continue

            product = _get_first_variant_from_tmpl(tmpl_id)
            # Envío a sala y retorno a CD usan x_studio_qty_transferir.
            qty = _safe_float(r.x_studio_qty_transferir, 0.0)

            if not product or qty <= 0.0:
                continue

            env['stock.move'].sudo().create({
                'name': product.display_name,
                'company_id': env.company.id,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'location_id': src_loc.id,
                'location_dest_id': dst_loc.id,
                'picking_id': picking.id,
            })
            created_moves += 1
            total_amount += _safe_float(r.x_studio_valor_reponer, 0.0)

        if created_moves == 0:
            picking.unlink()
            _set_summary(False, 'No se pudieron crear movimientos válidos.', snapshot_date, 0, 0.0)
            raise UserError('No se pudieron crear movimientos válidos.')

        # MODO ADOPCIÓN:
        # No confirmar automáticamente. El traslado queda en Borrador.
        # picking.action_confirm()

        msg = 'OK BORRADOR | %s | PICK=%s | moves=%s | snapshot=%s' % (
            lote_name,
            picking.name or picking.id,
            created_moves,
            snapshot_date,
        )
        _set_summary(True, msg, snapshot_date, created_moves, total_amount)

        write_vals = {}
        if rec._fields.get('x_studio_generated_docs_count'):
            write_vals['x_studio_generated_docs_count'] = 1
        if rec._fields.get('x_studio_origin_key'):
            write_vals['x_studio_origin_key'] = origin_key
        if write_vals:
            rec.write(write_vals)

        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Supply Generation',
                'message': 'Traslado borrador generado: %s' % (picking.name or ''),
                'type': 'success',
                'sticky': False,
            }
        }

    else:
        raise UserError('Operación no soportada: %s' % (gen_type,))

finally:
    env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
