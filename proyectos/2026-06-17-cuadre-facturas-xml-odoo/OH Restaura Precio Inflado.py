# OH Restaura Precio Inflado v1.0  (ir.actions.server / safe_eval)
# Restaura el price_unit de las lineas infladas por el reproceso (2026-06-18):
# vincular product_id piso el precio -> setea price_subtotal = MontoItem del DTE.
# Verdad = DTE adjunto, cuadra por proveedor+folio.
#
# DRY_RUN=True -> CSV de preview, NO escribe.
# DRY_RUN=False -> escribe; posteadas: button_draft -> restaurar -> action_post.
# safe_eval: sin import (b64decode inyectado), string parse, .write(), defs top-level.

DRY_RUN = True
INCLUIR_POSTED = True

# (folio, vat) de las 13 infladas (DICALLA ya corregida, excluida)
TARGETS = [
    ('007088', '77659607'), ('007087', '77659607'), ('007086', '77659607'),
    ('007005', '77659607'),
    ('2368496', '76484106'), ('2368497', '76484106'), ('2368970', '76484106'),
    ('2368971', '76484106'), ('2368972', '76484106'), ('2368498', '76484106'),
    ('2376293', '76484106'),
    ('2293523', '79576940'), ('1809791', '76706610'),
]


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def _norm(s):
    return ' '.join((s or '').lower().split())


def detalle_monto(xml):
    out = {}
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
        m = _seg(blk, '<MontoItem>', '</MontoItem>')
        try:
            out[_norm(nmb)] = int(round(float(m)))
        except (ValueError, TypeError):
            pass
        i = b
    return out


Move = env['account.move']
prev = ['factura;state;linea;sub_actual;sub_correcto']
n_lin = 0
n_fac = 0
errores = []

for folio, vat in TARGETS:
    mv = Move.search([('move_type', '=', 'in_invoice'), ('name', '=', 'FAC ' + folio),
                      ('partner_id.vat', 'like', vat)], limit=1)
    if not mv or not mv.l10n_cl_dte_file:
        continue
    raw = mv.l10n_cl_dte_file.datas
    if not raw:
        continue
    det = detalle_monto(b64decode(raw).decode('latin-1', 'ignore'))

    fixes = []
    for l in mv.invoice_line_ids:
        if l.display_type != 'product':
            continue
        monto = det.get(_norm(l.name))
        if monto is None:
            continue
        qty = l.quantity or 1
        if l.price_subtotal > monto * 1.5:          # inflada material
            fixes.append((l, monto / qty, monto))
    if not fixes:
        continue

    if DRY_RUN:
        for l, pu, monto in fixes:
            prev.append('%s;%s;%s;%s;%s' % (mv.name, mv.state, (l.name or '')[:34],
                                            int(round(l.price_subtotal)), monto))
            n_lin += 1
        n_fac += 1
        continue

    # escribir
    try:
        was_posted = mv.state == 'posted'
        if was_posted:
            if not INCLUIR_POSTED:
                continue
            mv.button_draft()
        for l, pu, monto in fixes:
            l.write({'price_unit': pu, 'discount': 0})
            n_lin += 1
        if was_posted:
            mv.action_post()
        n_fac += 1
    except Exception as e:
        errores.append('%s: %s' % (mv.name, e))

log('restaura precio: facturas=%s lineas=%s dry=%s errores=%s' % (n_fac, n_lin, DRY_RUN, errores))

if DRY_RUN:
    att = env['ir.attachment'].create({
        'name': 'restaura_preview.csv',
        'raw': ('\n'.join(prev)).encode('utf-8-sig'),
        'mimetype': 'text/csv'})
    action = {'type': 'ir.actions.act_url',
              'url': '/web/content/%s?download=true' % att.id}
else:
    action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
        'title': 'Restaura precio inflado',
        'message': 'Restauradas %s lineas en %s facturas. Errores: %s' % (
            n_lin, n_fac, errores or 'ninguno'),
        'type': 'warning' if errores else 'success', 'sticky': True}}
