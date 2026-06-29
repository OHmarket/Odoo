# OH Reproceso Vinculacion SKU v1.0  (ir.actions.server / safe_eval)
# Re-vincula lineas de factura de compra SIN product_id a un producto existente,
# matcheando contra el <Detalle> del DTE por default_code y, si no, por EAN13.
# NO recalcula el asiento (solo escribe product_id).
#
# Perillas:
#   DRY_RUN = True  -> NO escribe; genera CSV de preview (que vincularia).
#   DRY_RUN = False -> escribe product_id (empieza con LIMIT chico).
#   LIMIT           -> cuantas lineas procesar por corrida.
#   DESDE           -> ventana de facturas.
#
# safe_eval: sin import/re; b64decode inyectado; defs a nivel modulo (sin closures).

DRY_RUN = True
LIMIT = 200
DESDE = '2026-06-01'
CUENTA_ALM = '210230'


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    if b == -1:
        return ''
    return s[a:b].strip()


def _norm(s):
    return ' '.join((s or '').lower().split())


def detalle_items(xml):
    out = []
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        nmb = _seg(blk, '<NmbItem>', '</NmbItem>')
        monto = _seg(blk, '<MontoItem>', '</MontoItem>')
        cods = []
        eans = []
        j = 0
        while True:
            ca = blk.find('<CdgItem>', j)
            if ca == -1:
                break
            cb = blk.find('</CdgItem>', ca)
            if cb == -1:
                break
            cblk = blk[ca:cb]
            tpo = _seg(cblk, '<TpoCodigo>', '</TpoCodigo>')
            vlr = _seg(cblk, '<VlrCodigo>', '</VlrCodigo>')
            if vlr:
                if tpo and 'EAN' in tpo.upper():
                    eans.append(vlr)
                else:
                    cods.append(vlr)
            j = cb
        mi = None
        try:
            mi = int(round(float(monto)))
        except (ValueError, TypeError):
            mi = None
        out.append({'nombre': _norm(nmb), 'monto': mi, 'cods': cods, 'eans': eans})
        i = b
    return out


def find_prod(cods, eans):
    P = env['product.product']
    for c in cods:
        p = P.search([('default_code', '=', c), ('active', 'in', [True, False])], limit=1)
        if p:
            return p
    for e in eans:
        p = P.search([('barcode', '=', e), ('active', 'in', [True, False])], limit=1)
        if p:
            return p
    return P


acc = env['account.account'].search([('code', '=', CUENTA_ALM)], limit=1)
acc_id = acc.id
moves = env['account.move'].search([
    ('move_type', '=', 'in_invoice'),
    ('invoice_date', '>=', DESDE),
    ('l10n_cl_dte_file', '!=', False)], order='invoice_date desc')

done = 0
escritas = 0
prev = ['factura;linea;match_por;codigo;producto']
for m in moves:
    if done >= LIMIT:
        break
    sin = [l for l in m.invoice_line_ids
           if l.display_type == 'product' and not l.product_id and l.account_id.id == acc_id]
    if not sin:
        continue
    raw = m.l10n_cl_dte_file.datas
    if not raw:
        continue
    xml = b64decode(raw).decode('latin-1', 'ignore')
    items = detalle_items(xml)
    by_name = {}
    amt_count = {}
    by_amt = {}
    for it in items:
        if it['nombre'] and it['nombre'] not in by_name:
            by_name[it['nombre']] = it
        if it['monto'] is not None:
            amt_count[it['monto']] = amt_count.get(it['monto'], 0) + 1
            by_amt[it['monto']] = it
    for l in sin:
        if done >= LIMIT:
            break
        modo = ''
        it = by_name.get(_norm(l.name))
        if it:
            modo = 'nombre'
        else:
            am = int(round(l.price_subtotal))
            if amt_count.get(am, 0) == 1:  # solo si el monto es unico en la factura
                it = by_amt.get(am)
                modo = 'monto'
        if not it:
            continue
        prod = find_prod(it['cods'], it['eans'])
        if not prod:
            continue
        done += 1
        prev.append('%s;%s;%s;%s;%s' % (
            m.name, (l.name or '')[:40], modo,
            (it['cods'][0] if it['cods'] else (it['eans'][0] if it['eans'] else '')),
            prod.default_code or prod.name))
        if not DRY_RUN:
            l.write({'product_id': prod.id})
            escritas += 1

log('reproceso SKU: procesadas=%s escritas=%s dry=%s' % (done, escritas, DRY_RUN))

if DRY_RUN:
    txt = '\n'.join(prev)
    att = env['ir.attachment'].create({
        'name': 'reproceso_preview.csv',
        'raw': txt.encode('utf-8-sig'),
        'mimetype': 'text/csv'})
    action = {'type': 'ir.actions.act_url',
              'url': '/web/content/%s?download=true' % att.id}
else:
    action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
        'title': 'Reproceso SKU',
        'message': 'Vinculadas %s lineas (de %s evaluadas)' % (escritas, done),
        'type': 'success', 'sticky': True}}
