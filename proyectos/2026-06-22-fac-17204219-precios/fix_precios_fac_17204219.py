# Server Action (ir.actions.server, python_code / safe_eval)
# OH — Corrige precios pisados en borrador FAC 17204219 (BAT, tabaco)
#
# Problema: 3 lineas tienen price_unit = standard_price x factor UoM en vez del
# precio del DTE (bug "vincular product_id pisa el precio" + trampa UoM).
# Fix: re-asertar price_unit (y quantity, por la regla de no recompute) al valor DTE.
#
# NO toca el "otro impuesto" codigo 14 = 3.931 del DTE (pendiente decision contable).
# Solo opera si el move esta en borrador. Idempotente: si ya esta al precio DTE, no escribe.

FOLIO = 'FAC 17204219'

# default_code (INT1 del DTE)  ->  PrcItem correcto del DTE
DTE_PRICE = {
    '10209285': 31613.0,   # Pall Mall Azul 10s
    '10242376': 38726.0,   # Pall Mall Clic On XL20
    '10234321': 40993.0,   # Kent Neo B2K Azul 20
}

mv = env['account.move'].search([('name', '=', FOLIO), ('move_type', '=', 'in_invoice')], limit=1)
if not mv:
    raise UserError('No se encontro %s' % FOLIO)
if mv.state != 'draft':
    raise UserError('%s no esta en borrador (state=%s). Aborto.' % (FOLIO, mv.state))

cambios = []
for ln in mv.invoice_line_ids:
    code = ln.product_id.default_code or ''
    if code in DTE_PRICE:
        nuevo = DTE_PRICE[code]
        if float_compare(ln.price_unit, nuevo, precision_digits=2) != 0:
            ln.write({'price_unit': nuevo, 'quantity': ln.quantity})
            cambios.append('%s: %s -> %s' % (code, ln.price_unit, nuevo))

# refrescar totales calculados
mv.invalidate_recordset(['amount_untaxed', 'amount_tax', 'amount_total'])

msg = 'Lineas corregidas: %s | Neto=%s IVA=%s Total=%s (DTE: 323851 / 61533 / 389315 con otro imp. cod14=3931 pendiente)' % (
    (', '.join(cambios) if cambios else 'ninguna (ya estaban en precio DTE)'),
    mv.amount_untaxed, mv.amount_tax, mv.amount_total,
)
log(msg)
action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'FAC 17204219 — precios DTE',
        'message': msg,
        'type': 'success' if cambios else 'warning',
        'sticky': True,
    },
}
