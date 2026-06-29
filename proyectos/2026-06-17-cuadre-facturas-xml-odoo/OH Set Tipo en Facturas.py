# OH Set Tipo en Facturas v1.0  (ir.actions.server / safe_eval)
# Llena x_studio_tipo_prov (campo PLANO en account.move) con el tipo del proveedor.
# Solo facturas de compra (in_invoice), por proveedor, en lotes -> NO toca 17M filas.
# Re-ejecutable (idempotente). Gentil: opcional acotar por fecha con DESDE.
#
# PRE-REQUISITO: crear en Studio el campo PLANO (no related) en account.move:
#   x_studio_tipo_prov  (Texto / Char)

DESDE = '2024-01-01'   # ajustar; '' = todas las de compra (mas pesado)

Part = env['res.partner']
Move = env['account.move']

base = [('move_type', '=', 'in_invoice')]
if DESDE:
    base = base + [('invoice_date', '>=', DESDE)]

proveedores = Part.search([('x_studio_tipo_proveedor', '!=', False)])
n_mov = 0
n_prov = 0
for p in proveedores:
    moves = Move.search(base + [('partner_id', '=', p.id)])
    if moves:
        moves.write({'x_studio_tipo_prov': p.x_studio_tipo_proveedor})
        n_mov += len(moves)
        n_prov += 1

log('tipo en facturas: %s proveedores, %s facturas (desde %s)' % (n_prov, n_mov, DESDE or 'inicio'))
action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
    'title': 'Tipo en facturas',
    'message': '%s facturas marcadas (%s proveedores), desde %s' % (n_mov, n_prov, DESDE or 'inicio'),
    'type': 'success', 'sticky': True}}
