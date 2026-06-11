# ============================================================
# OH Logistica de Refuerzo - Traslado CD -> sala SOLO para SKUs urgentes
# ============================================================
#
# Estado: EN DISEÑO (proyectos/2026-06-11-logistica-refuerzo). No productivo.
#
# Objetivo:
#   - Crear un stock.picking de REFUERZO (CD -> sala) en Borrador, acotado a los
#     SKUs en quiebre o cobertura critica de una sucursal, para despacho rapido.
#   - Es un subconjunto del 'envio_a_sala' normal: misma fuente (CD) y misma
#     cantidad (x_studio_qty_transferir), pero filtrado a urgencia.
#
# Criterio de inclusion (ver diseno.md seccion 7):
#   x_studio_team_id      == sucursal del formulario
#   x_studio_cover_label  in ('sin_stock', 'critico')   <- quiebre + critico
#   x_studio_buy_action   == 'transferir_desde_cd'       <- despachable hoy
#   x_studio_qty_transferir > 0
#
# Formato de guia: dirección (partner del warehouse destino), código + descripción
#   (default_code / display_name del producto) y cantidad (qty_transferir).
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

# Selector de días de cobertura al generar el documento.
#   El usuario elige el umbral en el formulario: el refuerzo incluye los SKU con
#   cobertura <= N días (el quiebre, cobertura 0, siempre entra).
#   Campo Studio en el formulario (Selection '3','5','7'... o Integer):
REFUERZO_DAYS_FIELD = 'x_studio_dias_cobertura_refuerzo'
REFUERZO_DAYS_DEFAULT = 5          # umbral si el campo está vacío
# Respaldo por etiqueta si el formulario NO tiene el campo selector todavía.
REFUERZO_COVER_LABELS = ['sin_stock', 'critico']

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
    # Lee el selector de días del formulario. Acepta Selection (str '5') o
    # Integer. Devuelve int de días, o None si el campo no existe en el modelo.
    if not rec._fields.get(REFUERZO_DAYS_FIELD):
        return None
    # safe_eval no expone getattr: se accede al campo por indexación del record.
    raw = rec[REFUERZO_DAYS_FIELD]
    if raw is False or raw is None or raw == '':
        return REFUERZO_DAYS_DEFAULT
    try:
        return int(float(raw))
    except Exception:
        return REFUERZO_DAYS_DEFAULT

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
    # 2) Filtrar refuerzo según el selector de días del formulario.
    #    Umbral N días -> incluye SKU con cobertura <= N días (cover_weeks*7).
    #    El quiebre (cover_weeks=0) siempre entra. Si el formulario aún no tiene
    #    el campo selector, se cae al filtro por etiqueta (sin_stock/critico).
    #    Siempre acotado a lo despachable desde el CD.
    # --------------------------------------------------------
    refuerzo_days = _selected_refuerzo_days()
    domain = [
        ('x_studio_company_id', '=', env.company.id),
        ('x_studio_fecha_1', '=', snapshot_date),
        ('x_studio_team_id', '=', team_id),
        ('x_studio_buy_action', '=', 'transferir_desde_cd'),
        ('x_studio_qty_transferir', '>', 0),
    ]
    if refuerzo_days is not None:
        # Umbral en semanas para comparar contra x_studio_cover_weeks (Float).
        domain.append(('x_studio_cover_weeks', '<=', refuerzo_days / 7.0))
        filtro_desc = 'cobertura <= %s días' % refuerzo_days
    else:
        domain.append(('x_studio_cover_label', 'in', REFUERZO_COVER_LABELS))
        filtro_desc = 'quiebre/crítico (sin selector de días)'
    rows = Anal.search(
        domain,
        order='x_studio_severity desc, x_studio_valor_reponer desc'
    )
    if not rows:
        _set_summary(False, 'No hay líneas de refuerzo (%s, despachable desde CD) para esta sucursal.' % filtro_desc, snapshot_date, 0, 0.0)
        raise UserError('No hay líneas de refuerzo (%s) para esta sucursal.' % filtro_desc)

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

    created_moves = 0
    total_amount = 0.0
    for r in rows:
        tmpl = r.x_studio_product_id
        tmpl_id = tmpl and tmpl.id or False
        if not tmpl_id:
            continue
        product = _get_first_variant_from_tmpl(tmpl_id)
        qty = _safe_float(r.x_studio_qty_transferir, 0.0)
        if not product or qty <= 0.0:
            continue
        # Días de cobertura para la guía: el motor guarda cobertura en SEMANAS
        # (x_studio_cover_weeks); días = semanas * 7. Se inyecta en el nombre del
        # move para que aparezca en la pantalla del documento y en la impresión.
        dias_cob = _safe_float(r.x_studio_cover_weeks, 0.0) * 7.0
        cover_label = r.x_studio_cover_label or ''
        move_name = '%s | Cobertura: %.1f días (%s)' % (
            product.display_name, dias_cob, cover_label or 's/dato')
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
        total_amount += _safe_float(r.x_studio_valor_reponer, 0.0)

    if created_moves == 0:
        picking.unlink()
        _set_summary(False, 'No se pudieron crear movimientos de refuerzo válidos.', snapshot_date, 0, 0.0)
        raise UserError('No se pudieron crear movimientos de refuerzo válidos.')

    # MODO ADOPCIÓN: no confirmar. Queda Borrador para revisión humana.
    msg = 'OK BORRADOR REFUERZO | %s | PICK=%s | moves=%s | filtro=%s | snapshot=%s' % (
        lote_name,
        picking.name or picking.id,
        created_moves,
        filtro_desc,
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
