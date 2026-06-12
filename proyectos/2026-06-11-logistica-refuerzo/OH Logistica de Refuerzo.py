# ============================================================
# OH Logistica de Refuerzo - Traslado CD -> sala SOLO para SKUs urgentes
# ============================================================
#
# Estado: EN DISEÑO (proyectos/2026-06-11-logistica-refuerzo). No productivo.
#
# Objetivo:
#   - Crear un stock.picking de REFUERZO (CD -> sala) en Borrador que lleve la
#     sala a N días EXTRA de cobertura (selector en el formulario), enviando solo
#     el faltante. Caso: logística central martes; refuerzo viernes para
#     cubrir sáb/dom/lun -> el operador elige esos días.
#
# Modelo order-up-to / base stock (R,S) — ver diseno.md sección 7:
#   demanda_diaria = x_studio_demanda_semanal / 7
#   objetivo_N     = demanda_diaria * N            (N = días seleccionados)
#   faltante       = objetivo_N - x_studio_stock_real        (físico en sala)
#   enviar         = min(max(0, faltante), x_studio_stock_central)  (tope CD)
#   qty            = round(enviar)
#
# Universo (decisiones cerradas con el usuario):
#   x_studio_team_id    == sucursal del formulario
#   x_studio_buy_action == 'transferir_desde_cd'   <- los que rutea el motor CD→sala
#
# Formato de guia: dirección (partner del warehouse destino), código + descripción
#   (default_code / display_name del producto) y cantidad (faltante a N días).
#
# Modo adopcion: NO auto-confirma. Queda Borrador para Bodega/Operaciones.
# Idempotencia por 'origin' (REFUERZO|...).
#
# Notas safe_eval (Odoo 17 Server Action):
#   - `datetime` disponible; `import`/`class`/comprehensions con closure prohibidos.
#   - `log(msg, level=...)` es funcion, no logger.
#   - Espejo del branch envio_a_sala de 03_stock/OH Generacion de Documentos.py.
# ============================================================

VERSION_ID = 'OH_LOGISTICA_REFUERZO_v0_1'

ACTION_STOCK_ANALYSIS_ID = 1502
CENTRAL_WAREHOUSE_ID     = 15
LOCK_KEY                 = 99123042   # distinto al de Supply Generation (99123041)

# Selector de días de cobertura al generar el documento (TARGET, no filtro).
#   El usuario elige cuántos días EXTRA cubrir. El refuerzo lleva cada SKU
#   (de los que van CD->sala) hasta esa cobertura, enviando solo el faltante:
#       demanda_diaria  = demanda_semanal / 7
#       objetivo_N      = demanda_diaria * N
#       faltante        = objetivo_N - stock_físico_sala
#       enviar          = min(max(0, faltante), stock_central)   <- tope CD
#   Caso típico: logística central martes; refuerzo viernes para cubrir
#   sáb/dom/lun -> se seleccionan esos días extra.
#   Campo Studio en el formulario (Selection '3','4','5'... o Integer):
REFUERZO_DAYS_FIELD = 'x_studio_dias_cobertura_refuerzo'
REFUERZO_DAYS_DEFAULT = 3          # días extra si el campo está vacío

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
# Helpers (espejo de OH Generacion de Documentos.py)
# ------------------------------------------------------------
def _safe_float(v, default=0.0):
    try:
        return float(v or 0.0)
    except Exception:
        return default

def _now_dt():
    # Odoo Datetime espera naive UTC.
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

def _get_internal_type_from_wh(wh_id):
    pt = env['stock.picking.type'].sudo().search([
        ('warehouse_id', '=', wh_id),
        ('code', '=', 'internal')
    ], limit=1)
    if pt:
        return pt
    return env['stock.picking.type'].sudo().search([('code', '=', 'internal')], limit=1)

def _wh_partner_id(wh_id):
    # Dirección de la sala destino para que imprima en la guía. Si el warehouse
    # no tiene partner configurado, retorna False (no bloquea el traslado).
    wh = _get_wh(wh_id)
    if wh and wh.partner_id:
        return wh.partner_id.id
    return False

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

def _selected_refuerzo_days():
    # Días EXTRA a cubrir (target). Lee el selector del formulario; acepta
    # Selection (str '4') o Integer. Si el campo no existe o está vacío, usa
    # REFUERZO_DAYS_DEFAULT. safe_eval no expone getattr -> indexar el record.
    if not rec._fields.get(REFUERZO_DAYS_FIELD):
        return REFUERZO_DAYS_DEFAULT
    raw = rec[REFUERZO_DAYS_FIELD]
    if raw is False or raw is None or raw == '':
        return REFUERZO_DAYS_DEFAULT
    try:
        n = int(float(raw))
    except Exception:
        return REFUERZO_DAYS_DEFAULT
    return n if n > 0 else REFUERZO_DAYS_DEFAULT

def _build_origin_key(snapshot_date):
    team_id = 0
    if rec.x_studio_team_id:
        team_id = rec.x_studio_team_id.id
    return 'REFUERZO|%s|%s|%s' % (rec.id, team_id, snapshot_date)

# ------------------------------------------------------------
# Lock
# ------------------------------------------------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
row = env.cr.fetchone()
locked = bool(row and row[0])
if not locked:
    raise UserError('Otro proceso de Logística de Refuerzo está ejecutándose. Reintenta.')

try:
    # --------------------------------------------------------
    # Validaciones del formulario
    # --------------------------------------------------------
    lote_name = (rec.x_name or '').strip()
    if not lote_name:
        raise UserError('Debes completar Nombre del Lote. Ej: REFUERZO - Panguipulli 790.')

    if not rec.x_studio_team_id:
        raise UserError('Sucursal es obligatoria para el refuerzo.')

    team_id = rec.x_studio_team_id.id
    dst_wh_id = TEAM_WAREHOUSE_MAP_FALLBACK.get(team_id)
    if not dst_wh_id:
        raise UserError('No existe warehouse mapeado para la sucursal seleccionada.')

    # --------------------------------------------------------
    # 1) Recalcular análisis de stock y exigir snapshot fresco
    # --------------------------------------------------------
    started_at = _now_dt()
    _run_stock_analysis()
    snapshot_date = _latest_snapshot_after(started_at)
    if not snapshot_date:
        _set_summary(False, 'Análisis de Stock no generó snapshot fresco. Revisar acción 1502.', False, 0, 0.0)
        raise UserError('Análisis de Stock no generó snapshot fresco. Revisar acción 1502.')

    Anal = env['x_analisis_de_stock'].sudo()

    # --------------------------------------------------------
    # 2) Universo: SKU que el motor rutea CD -> sala para esta sucursal.
    #    La CANTIDAD se recalcula a N días (sección 4); por eso NO se filtra por
    #    qty_transferir ni por cover_label: el selector es TARGET, no umbral.
    # --------------------------------------------------------
    refuerzo_days = _selected_refuerzo_days()
    filtro_desc = 'refuerzo a %s días extra (CD→sala)' % refuerzo_days
    domain = [
        ('x_studio_company_id', '=', env.company.id),
        ('x_studio_fecha_1', '=', snapshot_date),
        ('x_studio_team_id', '=', team_id),
        ('x_studio_buy_action', '=', 'transferir_desde_cd'),
    ]
    rows = Anal.search(
        domain,
        order='x_studio_severity desc, x_studio_valor_reponer desc'
    )
    if not rows:
        _set_summary(False, 'No hay SKU ruteados CD→sala para esta sucursal (%s).' % filtro_desc, snapshot_date, 0, 0.0)
        raise UserError('No hay SKU ruteados CD→sala para esta sucursal.')

    # --------------------------------------------------------
    # 3) Crear picking CD -> sala en Borrador
    # --------------------------------------------------------
    src_loc = _get_stock_loc_from_wh(CENTRAL_WAREHOUSE_ID)
    dst_loc = _get_stock_loc_from_wh(dst_wh_id)
    if not src_loc:
        raise UserError('No se encontró ubicación de stock origen (CD).')
    if not dst_loc:
        raise UserError('No se encontró ubicación de stock destino (sala).')

    internal_type = _get_internal_type_from_wh(CENTRAL_WAREHOUSE_ID)
    if not internal_type:
        raise UserError('No se encontró picking type interno.')

    origin_key = _build_origin_key(snapshot_date)
    existing_picking = env['stock.picking'].sudo().search([
        ('origin', '=', origin_key),
        ('state', '!=', 'cancel'),
    ], limit=1)
    if existing_picking:
        _set_summary(False, 'Ya existe refuerzo no cancelado para esta solicitud.', snapshot_date, 0, 0.0)
        raise UserError('Ya existe un refuerzo no cancelado generado para esta solicitud.')

    pick_vals = {
        'picking_type_id': internal_type.id,
        'location_id': src_loc.id,
        'location_dest_id': dst_loc.id,
        'origin': origin_key,
        'company_id': env.company.id,
    }
    # Dirección de la sala destino para la guía (si el warehouse la tiene).
    dst_partner_id = _wh_partner_id(dst_wh_id)
    if dst_partner_id:
        pick_vals['partner_id'] = dst_partner_id

    picking = env['stock.picking'].sudo().create(pick_vals)

    # Política order-up-to (base stock): llevar la sala a N días de cobertura,
    # enviar solo el faltante, topado por lo que hay en el CD.
    created_moves = 0
    total_amount = 0.0
    skipped_cero = 0      # faltante <= 0 (la sala ya cubre N días)
    skipped_sincd = 0     # faltante > 0 pero CD sin stock
    for r in rows:
        tmpl = r.x_studio_product_id
        tmpl_id = tmpl and tmpl.id or False
        if not tmpl_id:
            continue
        product = _get_first_variant_from_tmpl(tmpl_id)
        if not product:
            continue

        demanda_semanal = _safe_float(r.x_studio_demanda_semanal, 0.0)
        demanda_diaria  = demanda_semanal / 7.0
        objetivo_n      = demanda_diaria * refuerzo_days        # target a N días
        stock_sala      = _safe_float(r.x_studio_stock_real, 0.0)  # físico en sala
        stock_cd        = _safe_float(r.x_studio_stock_central, 0.0)

        faltante = objetivo_n - stock_sala
        if faltante <= 0.0:
            skipped_cero += 1
            continue
        # Tope por stock disponible en el CD.
        enviar = faltante if faltante <= stock_cd else stock_cd
        # Redondeo a unidades enteras (no se despachan fracciones).
        qty = int(enviar + 0.5)
        if qty <= 0:
            if stock_cd <= 0.0:
                skipped_sincd += 1
            else:
                skipped_cero += 1
            continue

        # Días de cobertura ACTUAL para la guía (motor guarda semanas).
        dias_cob_actual = _safe_float(r.x_studio_cover_weeks, 0.0) * 7.0
        cover_label = r.x_studio_cover_label or 's/dato'
        move_name = '%s | Cob. actual: %.1f d → refuerzo a %s d (%s)' % (
            product.display_name, dias_cob_actual, refuerzo_days, cover_label)
        move_vals = {
            'name': move_name,
            'company_id': env.company.id,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': src_loc.id,
            'location_dest_id': dst_loc.id,
            'picking_id': picking.id,
        }
        # description_picking es la columna "Descripción" que imprime la guía.
        if 'description_picking' in env['stock.move']._fields:
            move_vals['description_picking'] = move_name
        env['stock.move'].sudo().create(move_vals)
        created_moves += 1
        # Valoriza el envío real (unidades * precio compra cash unitario).
        total_amount += qty * _safe_float(r.x_studio_purchase_price_cash_unit, 0.0)

    if created_moves == 0:
        picking.unlink()
        _set_summary(False, 'Sin faltante para %s: la sala ya cubre N días (%s) o el CD no tiene stock (%s).' % (filtro_desc, skipped_cero, skipped_sincd), snapshot_date, 0, 0.0)
        raise UserError('No hay faltante a reforzar (ya cubierto: %s, sin stock CD: %s).' % (skipped_cero, skipped_sincd))

    # MODO ADOPCIÓN: no confirmar. Queda Borrador para revisión humana.
    msg = 'OK BORRADOR REFUERZO | %s | PICK=%s | moves=%s | %s | ya_cubiertos=%s | sin_cd=%s | snapshot=%s' % (
        lote_name,
        picking.name or picking.id,
        created_moves,
        filtro_desc,
        skipped_cero,
        skipped_sincd,
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
            'title': 'Logística de Refuerzo',
            'message': 'Refuerzo borrador generado: %s (%s líneas)' % (picking.name or '', created_moves),
            'type': 'success',
            'sticky': False,
        }
    }

finally:
    env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
