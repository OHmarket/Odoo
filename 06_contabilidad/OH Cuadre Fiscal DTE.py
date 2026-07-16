# OH Cuadre Fiscal DTE v0.6  (ir.actions.server / account.move / safe_eval)
# Cada corrida: toma BATCH facturas de compra draft del mes con XML DTE; si el total
# no cuadra contra el <MntTotal> del DTE:
#   PASO 1  : aplica la posicion fiscal nativa (action_update_fpos_values, = boton
#             "Actualizar impuestos y cuentas").
#   PASO 1.5: arregla el precio PISADO de las lineas cuya qty coincide con el DTE
#             (pu = monto/qty * factor). Todo-o-nada via SAVEPOINT: solo persiste si
#             tras el fix la factura entera cuadra. La arreglada NO se postea en esta
#             corrida (queda draft) -> se postea la siguiente. Excluye el redondeo de
#             fraccion de pack (qty != DTE): ahi el precio ya es correcto (trampa UoM).
#   PASO 3  : postea (draft -> posted) las LIMPIAS = no tabaco + SKU + monto cuadra +
#             no duplicada + no arreglada-hoy. Si tras fpos+fix igual no cuadra, deja
#             una NOTA interna en el chatter (mail.mt_note, deduplicada) con el motivo.
# La clasificacion estructurada la sigue haciendo el detector (dueno de x_error_dte).
# Diseno/plan: proyectos/2026-07-05-cuadre-fiscal-dte/{diseno,plan}-paso15-fix-precio.md
#
# Flags:
#   DRY_RUN=True  -> no escribe nada (solo loguea la seleccion).
#   DRY_RUN=False, DO_POST=False -> aplica fpos y evalua, NO postea (muestra cuales postearia).
#   DRY_RUN=False, DO_POST=True  -> postea las limpias (<= MAX_POST por corrida).
#   BATCH -> facturas por corrida (subir p/ drenar backlog; cron steady-state ~10).
#
# Mecanismo fpos confirmado por SPIKE 2026-07-05 (variante A basta; show_update_fpos
# es solo visibilidad del boton en UI, el metodo recomputa igual). Diseno y validacion:
# proyectos/2026-07-05-cuadre-fiscal-dte/ (diseno.md, plan.md, helpers.py + tests).
#
# safe_eval: sin import (b64decode/datetime inyectados), .write()/metodo, retorno en action.
#
# PENDIENTE antes de cablear el cron de 30 min (Tarea 8):
#   marcador anti-clog para que las facturas "pegadas" (dif ILA ~ -69, falta_sku,
#   precio pisado) no ocupen el lote en cada corrida y no se re-evaluen sin cambio.

DRY_RUN = True         # v0.6: re-valida el PASO 1.5 en DRY; pasar a False tras revisar el log
DO_POST = True
BATCH = 10
MAX_POST = 20          # tope de posteos por corrida
TOL = 2.0              # tolerancia $ de cuadre amount_total vs MntTotal DTE (estricto)
PROV_TABACO = {'885029000'}   # BAT 88502900-0 (extensible)
LOCK_KEY = 99123055


# --- helpers puros (copiados de proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py, testeados) ---
def dte_mnt_total(xml):
    a = xml.find('<MntTotal>')
    if a == -1:
        return 0
    a += len('<MntTotal>')
    b = xml.find('</MntTotal>', a)
    if b == -1:
        return 0
    try:
        return int(round(float(xml[a:b].strip())))
    except (ValueError, TypeError):
        return 0


def _solo_digitos(s):
    r = ''
    for ch in (s or ''):
        if ch.isdigit():
            r += ch
    return r


FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por')


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def sku_ok(lines):
    for l in lines:
        if l['is_product'] and not l['has_product'] and not _es_flete(l['name']):
            return False
    return True


def es_tabaco(vat, prov_set):
    return _solo_digitos(vat) in prov_set


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def _num(t):
    try:
        return float(t)
    except Exception:
        return 0.0


def parse_items(xml):
    items = []
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        cod = ''
        ean = ''
        j = 0
        while True:
            ca = blk.find('<CdgItem>', j)
            if ca == -1:
                break
            cb = blk.find('</CdgItem>', ca)
            cblk = blk[ca:cb]
            tpo = _seg(cblk, '<TpoCodigo>', '</TpoCodigo>')
            vlr = _seg(cblk, '<VlrCodigo>', '</VlrCodigo>')
            if vlr:
                if 'EAN' in tpo.upper():
                    ean = vlr
                elif not cod:
                    cod = vlr
            j = cb
        items.append({
            'nombre': _seg(blk, '<NmbItem>', '</NmbItem>'),
            'codigo': cod, 'ean': ean,
            'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
            'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>')),
            'imp': _seg(blk, '<CodImpAdic>', '</CodImpAdic>'),
        })
        i = b
    return items


def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f


def price_fixes(odoo_lines, items):
    # Lineas a corregir por precio pisado -> [(line_id, pu_target)].
    # Excluye redondeo de fraccion de pack (qty != DTE) y flete. Ver diseno §6.
    if len(odoo_lines) != len(items) or not items:
        return []
    out = []
    for l, it in zip(odoo_lines, items):
        qty = l['quantity']
        if qty == 0:
            continue
        if abs(qty - it['qty']) > 0.001:
            continue
        if abs(l['price_subtotal'] - it['monto']) <= 1.0:
            continue
        if _es_flete(l['name']):
            continue
        out.append((l['id'], round((it['monto'] / qty) * l['factor'], 2)))
    return out


def motivo_no_cuadra(odoo_lines, items, delta):
    if len(odoo_lines) != len(items) or not items:
        return 'conteo_lineas'
    desc = []
    for l, it in zip(odoo_lines, items):
        if abs(l['price_subtotal'] - it['monto']) > 1.0:
            desc.append((l, it))
    if not desc:
        return 'residuo'
    todos_redondeo = True
    hay_flete = False
    for (l, it) in desc:
        if abs(l['quantity'] - it['qty']) <= 0.001:
            todos_redondeo = False
        if _es_flete(l['name']):
            hay_flete = True
    if todos_redondeo:
        return 'redondeo_uom'
    if hay_flete:
        return 'flete_descuadrado'
    return 'residuo'


def ultima_nota_cuadre(m):
    # Body de la nota [Cuadre DTE] mas reciente (o '' si no hay). Para el dedup.
    for msg in m.message_ids:
        body = msg.body or ''
        if '[Cuadre DTE]' in body:
            return body
    return ''


# --- lock (evita corridas solapadas del cron de 30 min) ---
env.cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    log('cuadre-fiscal: lock ocupado, salgo')
    action = {'type': 'ir.actions.act_window_close'}
else:
    HOY = datetime.date.today()
    DESDE = HOY.replace(day=1).isoformat()
    if HOY.month == 12:
        _fin = datetime.date(HOY.year + 1, 1, 1)
    else:
        _fin = datetime.date(HOY.year, HOY.month + 1, 1)
    HASTA = (_fin - datetime.timedelta(days=1)).isoformat()

    # PASO 0 — seleccion: primeras BATCH draft del mes con DTE (sin filtrar por
    # descuadre: las que ya cuadran tambien hay que postearlas; fpos se aplica solo si hace falta).
    universo = env['account.move'].search([
        ('move_type', '=', 'in_invoice'), ('state', '=', 'draft'),
        ('invoice_date', '>=', DESDE), ('invoice_date', '<=', HASTA),
        ('l10n_cl_dte_file', '!=', False)], order='id')

    lote = []
    for m in universo:
        if len(lote) >= BATCH:
            break
        if not m.l10n_cl_dte_file.datas:
            continue
        xml = b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore')
        total_dte = dte_mnt_total(xml)
        delta = round(m.amount_total - total_dte, 2)
        lote.append((m, total_dte, delta))

    msgs = ['=== Cuadre Fiscal DTE (dry=%s post=%s) mes=%s..%s ==='
            % (DRY_RUN, DO_POST, DESDE, HASTA),
            'universo=%d  lote=%d' % (len(universo), len(lote))]
    # catalogo de impuestos de compra (para el factor price_include del fix de precio)
    _taxes = env['account.tax'].search([('type_tax_use', '=', 'purchase')])
    tax_by_id = {}
    for t in _taxes:
        tax_by_id[t.id] = {'price_include': t.price_include, 'amount': t.amount}
    posteadas = 0
    for (m, td, d0) in lote:
        lineas = [{'is_product': l.display_type == 'product',
                   'has_product': bool(l.product_id),
                   'name': l.name or ''} for l in m.invoice_line_ids]
        if es_tabaco(m.partner_id.vat, PROV_TABACO):
            msgs.append('  %s SKIP tabaco' % m.name); continue
        if not sku_ok(lineas):
            msgs.append('  %s SKIP falta_sku' % m.name); continue
        # PASO 1: aplicar posicion fiscal SOLO si descuadra (variante A; SPIKE 2026-07-05)
        delta = round(m.amount_total - td, 2)
        ms = 0.0
        if abs(delta) > TOL and not DRY_RUN:
            t0 = datetime.datetime.now()
            m.action_update_fpos_values()
            ms = (datetime.datetime.now() - t0).total_seconds() * 1000
            delta = round(m.amount_total - td, 2)   # post-fpos
        # PASO 1.5: fix de precio pisado (todo-o-nada via savepoint). NO postea esta corrida.
        fixed_now = False
        items = []
        ol = []
        if abs(delta) > TOL:
            xmlm = b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore')
            items = parse_items(xmlm)
            prod_lines = m.invoice_line_ids.filtered(
                lambda x: x.display_type == 'product').sorted(lambda x: (x.sequence, x.id))
            ol = [{'id': l.id, 'name': l.name or '', 'quantity': l.quantity,
                   'price_subtotal': l.price_subtotal,
                   'factor': _factor(l.tax_ids.ids, tax_by_id)} for l in prod_lines]
            fixes = price_fixes(ol, items)
            if fixes:
                by_id = {l.id: l for l in prod_lines}
                env.flush_all()                        # persiste la fpos ANTES del savepoint
                env.cr.execute("SAVEPOINT cuadre_fix")  # (asi el ROLLBACK solo revierte el precio)
                for (lid, pu) in fixes:
                    by_id[lid].write({'price_unit': pu, 'discount': 0.0})
                env.flush_all()                        # empuja los writes de precio a SQL
                new_delta = round(m.amount_total - td, 2)
                if abs(new_delta) <= TOL:
                    # el fix cuadraria la factura
                    if DRY_RUN:
                        env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_fix")
                        m.invalidate_recordset()
                        msgs.append('  %s FIX %d linea(s) -> cuadraria new_delta=%+d [DRY]'
                                    % (m.name, len(fixes), new_delta))
                    else:
                        env.cr.execute("RELEASE SAVEPOINT cuadre_fix")
                        delta = new_delta
                        msgs.append('  %s FIX precio %d linea(s) -> cuadra, queda draft'
                                    % (m.name, len(fixes)))
                    fixed_now = True   # no cae al PASO 3 (evita el "NO cuadra residuo" enganoso)
                else:
                    env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_fix")
                    m.invalidate_recordset()
                    msgs.append('  %s FIX %d linea(s) -> NO cuadra new_delta=%+d%s'
                                % (m.name, len(fixes), new_delta, ' [DRY]' if DRY_RUN else ''))
        if fixed_now:
            continue   # arreglada hoy: se postea la corrida siguiente
        # PASO 3: gate de posteo
        if abs(delta) > TOL:
            motivo = motivo_no_cuadra(ol, items, delta)
            nota = '[Cuadre DTE] no cuadra %+d vs DTE. Motivo: %s' % (delta, motivo)
            if not DRY_RUN and nota not in ultima_nota_cuadre(m):
                m.message_post(body=nota, subtype_xmlid='mail.mt_note')
            msgs.append('  %s NO cuadra delta=%+d motivo=%s%s'
                        % (m.name, delta, motivo, ' [DRY]' if DRY_RUN else '')); continue
        dup = env['account.move'].search_count([
            ('move_type', '=', 'in_invoice'), ('partner_id', '=', m.partner_id.id),
            ('name', '=', m.name), ('state', 'in', ['draft', 'posted']),
            ('id', '!=', m.id)])
        if dup:
            msgs.append('  %s NO duplicada (%d copias)' % (m.name, dup)); continue
        if posteadas >= MAX_POST:
            msgs.append('  %s LISTA (tope %d)' % (m.name, MAX_POST)); continue
        if not DRY_RUN and DO_POST:
            m.action_post()
            posteadas += 1
            msgs.append('  %s POSTEADA (%.0f ms)' % (m.name, ms))
        else:
            msgs.append('  %s postearia (%.0f ms)%s'
                        % (m.name, ms, ' [DRY]' if DRY_RUN else ' [DO_POST=False]'))

    msgs.append('RESUMEN lote=%d posteadas=%d dry=%s post=%s'
                % (len(lote), posteadas, DRY_RUN, DO_POST))
    log('\n'.join(msgs))
    env.cr.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    action = {'type': 'ir.actions.act_window_close'}
