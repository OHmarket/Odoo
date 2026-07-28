# OH Cuadre Fiscal DTE v0.7  (ir.actions.server / account.move / safe_eval)
#
# Automatiza el ciclo manual, por factura:
#     APLICAR posicion fiscal -> REVISAR -> GUARDAR -> siguiente
#
#   PASO 0   selecciona draft del mes con DTE, SIN hold vigente en x_error_dte,
#            ordenadas por id DESC (mas recientes primero). Cap MAX_MOVES.
#   PASO 1   aplica la posicion fiscal SIEMPRE (action_update_fpos_values),
#            no solo si ya descuadra.
#   PASO 1.5 arregla el precio PISADO de las lineas cuya qty coincide con el DTE.
#            Todo-o-nada via SAVEPOINT: solo persiste si tras el fix la factura
#            entera cuadra. Excluye el redondeo de fraccion de pack (trampa UoM).
#   PASO 2   REVISA: (a) lineas de MERCADERIA sin producto  (b) neto
#            (c) impuesto  (d) total  — los tres montos contra el DTE.
#   PASO 3   GUARDA (action_post) las limpias; a las demas les registra un hold
#            en x_error_dte con el motivo y sigue con la proxima.
#
# Diferencias con v0.6 (7 cambios, ver proyectos/2026-07-27-cuadre-dte-automatico/):
#   1. orden id DESC + excluye holds vigentes  (v0.6 ordenaba ASC -> arrancaba
#      por las mas viejas, que son las pegadas: 0 posteadas en 2 semanas)
#   2. BATCH -> MAX_MOVES (cap de COSTO, no de cola)
#   3. fpos SIEMPRE, no solo si delta > TOL (168 facturas nunca la recibian)
#   4. gate de 3 montos, no solo MntTotal (errores compensados pasaban)
#   5. motivo con ILA-origen ANTES del gate de montos (medido: 155 de 163
#      "estructura" eran en realidad ILA sin mapear; price_include mueve
#      neto E impuesto a la vez y disfraza el diagnostico)
#   6. sku_ok acotado a lineas de MERCADERIA (tipo_proveedor + cuenta 210230):
#      las de gasto son servicios legitimos sin SKU
#   7. registra el hold en x_error_dte (reusa el modelo del detector 1585)
#
# Baseline medido 2026-07-27 (diag_cuadre.py, read-only): de 314 draft,
#   117 cuadran hoy | 156 con ILA origen | 26 falta SKU real | 4 precio/impuesto
# Helpers validados offline: test_helpers.py, 15/15.
#
# safe_eval: sin import (b64decode inyectado), sin re, sin frozenset,
# loops planos (sin genexp dentro de def), .write() no obj.attr=,
# x_name required en el create de x_error_dte, retorno en action.

DRY_RUN = False         # primero True: lee el log y recien despues False
DO_POST = True
MAX_MOVES = 40         # facturas evaluadas por corrida (cap de costo)
MAX_POST = 20          # tope de posteos por corrida
TOL = 2.0              # tolerancia $ en CADA uno de los 3 montos
PROV_TABACO = {'885029000'}   # BAT 88502900-0 (IVA de margen cod 14: no esta en el XML)
LOCK_KEY = 99123055
FP_DEFAULT = 12        # posicion fiscal "Facturas de Compra"
MARCA_HOLD = 'cuadre v0.7:'   # firma de los holds propios (ver PASO 0)


# ============================================================================
# helpers puros — copiados de helpers.py (testeados, 15/15). No editar aqui:
# editar helpers.py, correr test_helpers.py y volver a pegar.
# ============================================================================

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


def dte_totales(xml):
    # {neto, exe, iva, otros, total}. `otros` suma TODOS los <ImptoReten>:
    # Odoo los acumula en amount_tax junto al IVA, el DTE los lleva aparte.
    # En una exenta (FNA) <MntNeto> viene vacio y el monto va en <MntExe>.
    tot = _seg(xml, '<Totales>', '</Totales>')
    otros = 0.0
    i = 0
    while True:
        a = xml.find('<ImptoReten>', i)
        if a == -1:
            break
        b = xml.find('</ImptoReten>', a)
        if b == -1:
            break
        otros += _num(_seg(xml[a:b], '<MontoImp>', '</MontoImp>'))
        i = b
    return {'neto': _num(_seg(tot, '<MntNeto>', '</MntNeto>')),
            'exe': _num(_seg(tot, '<MntExe>', '</MntExe>')),
            'iva': _num(_seg(tot, '<IVA>', '</IVA>')),
            'otros': otros,
            'total': _num(_seg(tot, '<MntTotal>', '</MntTotal>'))}


def cuadra_3(untaxed, tax, total, tot, tol):
    # (ok, dn, di, dt): cada d* True = ESE componente no cuadra.
    dn = abs(untaxed - (tot['neto'] + tot['exe'])) > tol
    di = abs(tax - (tot['iva'] + tot['otros'])) > tol
    dt = abs(total - tot['total']) > tol
    return ((not dn) and (not di) and (not dt), dn, di, dt)


# 'envio' agregado 2026-07-27 (ENVIO CHILEXPRESS). OJO: 'recargo' NO matchea
# 'RECARGAS' (recargas telefonicas = mercaderia que se vende), y esta bien asi.
FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por', 'envio')
TIPO_MERCADERIA = 'Mercaderia'
SRC_OC = (26, 28, 31, 33, 34)


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def exige_sku(name, tipo_prov):
    # Decide SOLO por tipo de proveedor. NO se mira la cuenta: la cuenta de
    # inventario (210230) sale de la categoria DEL PRODUCTO, asi que una linea
    # sin producto nunca puede estar ahi — cae al gasto (CMV). Condicionarla a
    # la cuenta era circular. Lo destapo la corrida real 2026-07-27:
    # action_update_fpos_values recomputa impuestos Y CUENTAS, las lineas sin
    # producto migraron a CMV y la regla se apagaba justo cuando hace falta
    # (13 de 59 lineas de mercaderia sin vincular se escapaban del bloqueo).
    if _es_flete(name):
        return False
    return tipo_prov == TIPO_MERCADERIA


def lineas_sin_sku(lineas, tipo_prov):
    out = []
    for l in lineas:
        if l['has_product']:
            continue
        if exige_sku(l['name'], tipo_prov):
            out.append(l)
    return out


def tiene_ila_origen(tax_ids):
    for t in tax_ids:
        if t in SRC_OC:
            return True
    return False


def unidad_ok(qty, uom_f, it, retail, std):
    # True / False / None (None = no verificable, no bloquea).
    # Una linea puede cuadrar en PLATA y aun asi entregar al stock la cantidad
    # equivocada, porque la UoM es un pack (FAC 10142151: 144 botellas donde el
    # DTE dice 12, a 1/12 del costo). El gate de 3 montos es ciego a eso.
    # Pero QtyItem NO siempre viene en unidades de stock: medido sobre 2.212
    # lineas, 63% de los DTE factura POR CAJA (y ahi Odoo esta BIEN). Comparar
    # qty*factor == QtyItem a secas daba 63% de falsos positivos.
    # Arbitro = PRECIO DE VENTA, no el costo: standard_price se deriva de estas
    # mismas compras (contaminado si el historico entro mal). Base economica:
    # el costo por unidad no puede superar el retail por unidad.
    # PROXY: lo correcto seria costo < retail*(1-margen) por categoria.
    if uom_f == 1 or not it['qty']:
        return True
    if abs(qty * uom_f - it['qty']) <= 0.01:
        return True
    pu = it['monto'] / it['qty']
    if retail:
        return pu > retail
    if std:
        return abs(pu / uom_f - std) < abs(pu - std)
    return None


def uom_mal(pares):
    # True si alguna linea aporta al stock una cantidad distinta a la del DTE.
    # `pares` = salida de alinear(). Lo no verificable NO bloquea.
    for (l, it) in pares:
        if unidad_ok(l['quantity'], l['uom_f'], it, l['retail'], l['std']) is False:
            return True
    return False


def motivo(falta_sku, ila_origen, unidades_mal, dn, di, dt):
    # '' si esta OK. Orden: el ILA-origen ANTES del gate de montos (price_include
    # mueve neto E impuesto y disfraza el diagnostico), y las UNIDADES antes de
    # devolver '' (una factura puede cuadrar en plata y tener el stock 12x mal).
    # Valores de la seleccion ya existente en x_error_dte.
    if falta_sku:
        return 'codigo_no_vinculado'
    if ila_origen:
        return 'impuesto_mal_clasificado'
    if unidades_mal:
        return 'uom_no_cuadra'
    if dn and di:
        return 'linea_descuadrada'
    if dn:
        return 'precio'
    if di:
        return 'diferencia_impuesto'
    if dt:
        return 'linea_descuadrada'
    return ''


def _solo_digitos(s):
    r = ''
    for ch in (s or ''):
        if ch.isdigit():
            r += ch
    return r


def es_tabaco(vat, prov_set):
    return _solo_digitos(vat) in prov_set


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
        items.append({'nombre': _seg(blk, '<NmbItem>', '</NmbItem>'),
                      'codigo': cod, 'ean': ean,
                      'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
                      'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>'))})
        i = b
    return items


def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f


def alinear(odoo_lines, items):
    # Empareja lineas de Odoo con items del <Detalle>. Las lineas de
    # flete/recargo NO tienen item: el DTE las lleva como <DscRcgGlobal>, no
    # como <Detalle>. Por eso se descuentan ANTES de comparar los largos.
    # Verificado en FAC 10142151: 13 lineas vs 12 <Detalle>, y el DscRcgGlobal
    # de 77.520 es la linea RECARGO (MntNeto 2.000.646 = 1.923.126 + 77.520).
    # Antes se comparaba len(odoo_lines) != len(items) y se abortaba: toda
    # factura con recargo global quedaba sin fix de precio aunque fuera
    # reparable.
    # Dos intentos, en orden — el flete NO siempre es recargo global:
    #   1. tal cual, si los largos calzan. En FAC 000891 la linea DESPACHO SI
    #      es un <Detalle> (qty 1, monto 145.908) y son 7 vs 7: sacarla a
    #      ciegas rompia una factura que alineaba perfecto.
    #   2. descontando flete/recargo, para el caso <DscRcgGlobal> (FAC 10142151).
    # Devuelve [] si ninguno calza (no se adivina).
    if not items:
        return []
    if len(odoo_lines) == len(items):
        return list(zip(odoo_lines, items))
    prod = []
    for l in odoo_lines:
        if not _es_flete(l['name']):
            prod.append(l)
    if len(prod) != len(items):
        return []
    return list(zip(prod, items))


def price_fixes(odoo_lines, items):
    # [(line_id, pu_target)] por precio pisado. Excluye la fraccion de pack
    # (qty != QtyItem): ahi el price_unit YA es el correcto del DTE y
    # desviarlo contaminaria costo/WAC (trampa UoM).
    out = []
    for (l, it) in alinear(odoo_lines, items):
        qty = l['quantity']
        if qty == 0:
            continue
        if abs(qty - it['qty']) > 0.001:
            continue
        if abs(l['price_subtotal'] - it['monto']) <= 1.0:
            continue
        out.append((l['id'], round((it['monto'] / qty) * l['factor'], 2)))
    return out


# ============================================================================
# motor
# ============================================================================

env.cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    log('cuadre-fiscal v0.7: lock ocupado, salgo')
    action = {'type': 'ir.actions.act_window_close'}
else:
    HOY = datetime.date.today()
    DESDE = HOY.replace(day=1).isoformat()
    if HOY.month == 12:
        _fin = datetime.date(HOY.year + 1, 1, 1)
    else:
        _fin = datetime.date(HOY.year, HOY.month + 1, 1)
    HASTA = (_fin - datetime.timedelta(days=1)).isoformat()

    # --- holds vigentes: la factura sale de la cola hasta que alguien la toque.
    # Solo bloquean los holds que dejo ESTE motor (marca MARCA_HOLD en la
    # sugerencia). Los del detector 1585 son informativos y NO deben bloquear:
    # 245 de ellos son 'impuesto_mal_clasificado', que es justo lo que este SA
    # resuelve al aplicar la fpos — respetarlos seria auto-bloquearse.
    # 'draft' tampoco bloquea (solo significa "pendiente de postear").
    holds = {}
    for h in env['x_error_dte'].search([('x_studio_estado', '=', 'pendiente'),
                                        ('x_studio_tipo_error', '!=', 'draft'),
                                        ('x_studio_sugerencia', 'like', MARCA_HOLD)]):
        if not h.x_studio_factura:
            continue
        mid = h.x_studio_factura.id
        f = h.x_studio_fecha_check
        if f and (mid not in holds or f > holds[mid]):
            holds[mid] = f

    # --- catalogo de impuestos de compra (factor price_include del fix de precio)
    tax_by_id = {}
    for t in env['account.tax'].search([('type_tax_use', '=', 'purchase')]):
        tax_by_id[t.id] = {'price_include': t.price_include, 'amount': t.amount}

    # --- tabaco: se excluye del UNIVERSO, no se saltea dentro del lote.
    # Es inposteable por diseno (el IVA de margen cod 14 lo calcula Odoo, no
    # esta en el XML, asi que el gate de 3 montos no puede validarlo). Salteandolo
    # dentro del lote consumia cupo en CADA corrida: medido 2026-07-27, 62 draft
    # de BAT en el mes y 10 de las 40 del primer lote. Mismo clog que curamos.
    tabaco_ids = []
    for p in env['res.partner'].search([('supplier_rank', '>', 0)]):
        if es_tabaco(p.vat, PROV_TABACO):
            tabaco_ids.append(p.id)

    dom_base = [('move_type', '=', 'in_invoice'), ('state', '=', 'draft'),
                ('invoice_date', '>=', DESDE), ('invoice_date', '<=', HASTA),
                ('l10n_cl_dte_file', '!=', False)]
    n_tabaco = env['account.move'].search_count(
        dom_base + [('partner_id', 'in', tabaco_ids)])

    # --- PASO 0: universo, mas RECIENTES primero
    universo = env['account.move'].search(
        dom_base + [('partner_id', 'not in', tabaco_ids)], order='id desc')

    lote = []
    en_hold = 0
    for m in universo:
        if len(lote) >= MAX_MOVES:
            break
        if not m.l10n_cl_dte_file.datas:
            continue
        # re-entrada: si el move o alguna linea cambio despues del hold, vuelve.
        fh = holds.get(m.id)
        if fh:
            ult = m.write_date
            for l in m.invoice_line_ids:
                if l.write_date and l.write_date > ult:
                    ult = l.write_date
            if ult <= fh:
                en_hold += 1
                continue
        lote.append(m)

    msgs = ['=== OH Cuadre Fiscal DTE v0.7 (dry=%s post=%s) mes=%s..%s ==='
            % (DRY_RUN, DO_POST, DESDE, HASTA),
            'universo=%d  en_hold=%d  lote=%d  (tabaco excluido=%d, revision manual)'
            % (len(universo), en_hold, len(lote), n_tabaco)]
    posteadas = 0
    por_motivo = {}

    for m in lote:
        tipo_prov = m.partner_id.x_studio_tipo_proveedor or ''
        xml = b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore')
        tot = dte_totales(xml)

        if es_tabaco(m.partner_id.vat, PROV_TABACO):
            msgs.append('  %-16s SKIP tabaco' % m.name)
            por_motivo['tabaco'] = por_motivo.get('tabaco', 0) + 1
            continue

        # --- PASO 1: aplicar posicion fiscal SIEMPRE
        ms = 0.0
        if not DRY_RUN:
            t0 = datetime.datetime.now()
            m.action_update_fpos_values()
            ms = (datetime.datetime.now() - t0).total_seconds() * 1000

        prod_lines = m.invoice_line_ids.filtered(
            lambda x: x.display_type == 'product').sorted(lambda x: (x.sequence, x.id))
        lineas = []
        ila = False
        for l in prod_lines:
            # OJO: 'factor' es el del price_include (fix de precio) y 'uom_f' el
            # de la unidad de medida (gate de unidades). No confundirlos.
            lineas.append({'id': l.id, 'name': l.name or '',
                           'has_product': bool(l.product_id),
                           'quantity': l.quantity,
                           'price_subtotal': l.price_subtotal,
                           'factor': _factor(l.tax_ids.ids, tax_by_id),
                           'uom_f': l.product_uom_id.factor_inv or 1.0,
                           'retail': l.product_id.list_price or 0.0,
                           'std': l.product_id.standard_price or 0.0})
            if tiene_ila_origen(l.tax_ids.ids):
                ila = True

        # --- PASO 1.5: fix de precio pisado (todo-o-nada via savepoint)
        ok, dn, di, dt = cuadra_3(m.amount_untaxed, m.amount_tax, m.amount_total, tot, TOL)
        items = parse_items(xml)
        if not ok and not ila:
            fixes = price_fixes(lineas, items)
            if fixes:
                by_id = {}
                for l in prod_lines:
                    by_id[l.id] = l
                env.flush_all()                          # persiste la fpos ANTES del savepoint
                env.cr.execute("SAVEPOINT cuadre_fix")   # el ROLLBACK revierte solo el precio
                for (lid, pu) in fixes:
                    by_id[lid].write({'price_unit': pu, 'discount': 0.0})
                env.flush_all()
                ok2, dn2, di2, dt2 = cuadra_3(m.amount_untaxed, m.amount_tax,
                                              m.amount_total, tot, TOL)
                if ok2 and not DRY_RUN:
                    env.cr.execute("RELEASE SAVEPOINT cuadre_fix")
                    # v0.6 dejaba la arreglada en draft para postearla en la
                    # corrida siguiente. Aca se postea en la MISMA pasada: el
                    # savepoint ya re-verifico los 3 montos antes de persistir,
                    # asi que diferirla solo agrega una vuelta.
                    ok, dn, di, dt = ok2, dn2, di2, dt2
                    msgs.append('  %-16s FIX precio %d linea(s) -> cuadra'
                                % (m.name, len(fixes)))
                else:
                    env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_fix")
                    m.invalidate_recordset()
                    msgs.append('  %-16s FIX %d linea(s) -> %s%s'
                                % (m.name, len(fixes),
                                   'cuadraria' if ok2 else 'NO cuadra',
                                   ' [DRY]' if DRY_RUN else ''))

        # --- PASO 2: REVISAR (SKU / unidades / los 3 montos)
        faltan = lineas_sin_sku(lineas, tipo_prov)
        pares = alinear(lineas, items)
        umal = uom_mal(pares)
        if not pares:
            # sin alineacion el gate de unidades no puede opinar y NO bloquea.
            # Se deja visible: silenciarlo haria pasar por "verificado" algo que
            # no se verifico (medido: ~3% de las facturas).
            msgs.append('  %-16s (unidades no verificables: no alinea con el DTE)' % m.name)
        mt = motivo(len(faltan) > 0, ila, umal, dn, di, dt)

        # --- PASO 3: GUARDAR o apartar
        if not mt:
            dup = env['account.move'].search_count([
                ('move_type', '=', 'in_invoice'), ('partner_id', '=', m.partner_id.id),
                ('name', '=', m.name), ('state', 'in', ['draft', 'posted']),
                ('id', '!=', m.id)])
            if dup:
                mt = 'duplicado'
            elif posteadas >= MAX_POST:
                msgs.append('  %-16s LISTA (tope %d)' % (m.name, MAX_POST))
                continue
            elif not DRY_RUN and DO_POST:
                m.action_post()
                posteadas += 1
                msgs.append('  %-16s POSTEADA (fpos %.0f ms)' % (m.name, ms))
                continue
            else:
                posteadas += 1
                msgs.append('  %-16s postearia%s'
                            % (m.name, ' [DRY]' if DRY_RUN else ' [DO_POST=False]'))
                continue

        por_motivo[mt] = por_motivo.get(mt, 0) + 1
        det = '%s%s%s' % ('N' if dn else '.', 'I' if di else '.', 'T' if dt else '.')
        msgs.append('  %-16s %-26s %s  delta=%+d'
                    % (m.name, mt, det, round(m.amount_total - tot['total'])))
        # detalle accionable de las lineas sin vincular (codigo del DTE por posicion)
        for l in faltan:
            cod = ''
            for k, ln in enumerate(lineas):
                if ln['id'] == l['id'] and k < len(items):
                    cod = items[k]['codigo']
            # cod vacio = el DTE de ese proveedor no manda <CdgItem> (verificado
            # en FAC 003666 y FAC 000087: Detalle=5/1 con CdgItem=0)
            msgs.append('      - sin vincular: %-34s cod_DTE=%s'
                        % (l['name'][:34], cod or '(el DTE no trae codigo)'))

        # --- hold en x_error_dte (dedup por factura+tipo)
        if not DRY_RUN:
            # El sello va DESPUES de procesar esta factura, con flush previo.
            # Si se sella al inicio del loop, la escritura de la propia fpos
            # (PASO 1) deja write_date > fecha_check y la regla de re-entrada
            # lee eso como "alguien la toco": el motor invalida su propio hold
            # y la factura vuelve a la cola en cada corrida. Diagnosticado
            # 2026-07-27 (dos corridas reales seguidas con en_hold=0).
            env.flush_all()
            ahora = datetime.datetime.now()
            lid = faltan[0]['id'] if faltan else False
            key = '%s:%s:%s' % (m.name, mt, lid or '')
            prev = env['x_error_dte'].search([('x_studio_factura', '=', m.id),
                                              ('x_studio_tipo_error', '=', mt),
                                              ('x_studio_estado', '=', 'pendiente')], limit=1)
            vals = {'x_name': key,
                    'x_studio_factura': m.id,
                    'x_studio_proveedor': m.partner_id.id,
                    'x_studio_tipo_error': mt,
                    'x_studio_estado': 'pendiente',
                    'x_studio_fecha_check': ahora,
                    'x_studio_monto_riesgo': abs(m.amount_total - tot['total']),
                    'x_studio_sugerencia': '%s %s (%s)' % (MARCA_HOLD, mt, det)}
            if lid:
                vals['x_studio_line_id'] = lid
            if prev:
                prev.write(vals)
            else:
                env['x_error_dte'].create(vals)

    resumen = []
    for k in sorted(por_motivo):
        resumen.append('%s=%d' % (k, por_motivo[k]))
    msgs.append('RESUMEN lote=%d posteadas=%d | %s'
                % (len(lote), posteadas, ' '.join(resumen) or 'sin apartadas'))
    texto = '\n'.join(msgs)
    log(texto)
    env.cr.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    action = {
        'type': 'ir.actions.client', 'tag': 'display_notification',
        'params': {'title': 'Cuadre Fiscal DTE v0.7 (%s)' % ('DRY_RUN' if DRY_RUN else 'APLICADO'),
                   'message': texto, 'sticky': True},
    }
