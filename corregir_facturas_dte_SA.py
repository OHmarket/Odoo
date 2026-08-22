# -*- coding: utf-8 -*-
# OH Corregir Facturas DTE -- generado por skill corregir-facturas-dte
# Pegar en ir.actions.server, Modelo = account.move, safe_eval.
# Corre PRIMERO con DRY_RUN=True (solo loguea), luego False para aplicar.
# Por cada factura afectada: (1) re-aplica la posicion fiscal a cada linea
# (map_tax de supplier_taxes -> mapea el ILA correcto) y (2) cuadra el precio.
# NO re-vincula product_id (eso vuelve a pisar el precio). Solo facturas en draft.

DRY_RUN = True
FP_DEFAULT = 12  # "Facturas de Compra"

MOVES = [
    21331756,  # FAC 17197625
]
PRICE = {
    55796362: 44259.0,  # FAC 17197625 | 9065 Pall Mall Boost 10s
    55796367: 44259.0,  # FAC 17197625 | 9041 Pall Mall Click On 10s
}

msgs = []
for mid in MOVES:
    move = env['account.move'].browse(mid)
    if not move.exists() or move.state != 'draft':
        msgs.append('SKIP move %s: no existe o no esta en draft' % mid)
        continue
    fp = move.fiscal_position_id or env['account.fiscal.position'].browse(FP_DEFAULT)
    for line in move.invoice_line_ids:
        if line.display_type:
            continue
        vals = {}
        src = line.product_id.supplier_taxes_id
        if src:
            nuevo = fp.map_tax(src).ids
            if sorted(nuevo) != sorted(line.tax_ids.ids):
                vals['tax_ids'] = [(6, 0, nuevo)]
        if line.id in PRICE:
            vals['price_unit'] = PRICE[line.id]
            vals['discount'] = 0.0
        if not vals:
            continue
        if DRY_RUN:
            msgs.append('DRY %s L%s (%s): tax %s->%s pu=%s'
                        % (move.name, line.id, line.name[:24], line.tax_ids.ids,
                           vals.get('tax_ids'), vals.get('price_unit', '=')))
        else:
            line.write(vals)
            msgs.append('OK  %s L%s (%s)' % (move.name, line.id, line.name[:24]))

texto = '\n'.join(msgs) or 'nada que hacer'
log(texto)
action = {
    'type': 'ir.actions.client', 'tag': 'display_notification',
    'params': {'title': 'Corregir Facturas DTE (%s)' % ('DRY_RUN' if DRY_RUN else 'APLICADO'),
               'message': texto, 'sticky': True},
}
