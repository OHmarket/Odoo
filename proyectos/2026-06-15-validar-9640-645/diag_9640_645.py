# DIAG read-only: valida cantidad recomendada SKU 9640 -> team 8 (Panguipulli 645)
# y la fila CD (team 26). No escribe nada.
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# 1) Resolver product.product por default_code = '9640'
prods = odoo.search_read(
    'product.product',
    domain=[('default_code', '=', '9640')],
    fields=['id', 'default_code', 'name', 'product_tmpl_id', 'uom_id', 'barcode'],
)
print('=== product.product default_code=9640 ===')
for p in prods:
    print(p)

if not prods:
    print('NO product con default_code=9640. Probar barcode / name_search.')
    sys.exit(0)

pids = [p['id'] for p in prods]

# 2) Analisis de stock para esos product ids, team 8 (sala) y 26 (CD)
fields = [
    'x_studio_product_id', 'x_studio_team_id', 'x_studio_buy_action',
    'x_studio_stock_real', 'x_studio_stock_effective', 'x_studio_stock_proyectado',
    'x_studio_stock_pedido_transfer', 'x_studio_stock_pedido_compra',
    'x_studio_demanda_semanal', 'x_studio_mu_week', 'x_studio_sigma_week',
    'x_studio_cover_weeks', 'x_studio_cover_label',
    'x_studio_reorder_target_weeks', 'x_studio_target_units',
    'x_studio_safety_stock_units',
    'x_studio_moq', 'x_studio_qty_a_pedir', 'x_studio_qty_a_pedir_cajas',
    'x_studio_qty_transferir', 'x_studio_stock_central',
    'x_studio_compra_mensual_estimada', 'x_studio_fecha_1',
]
rows = odoo.search_read(
    'x_analisis_de_stock',
    domain=[('x_studio_product_id', 'in', pids),
            ('x_studio_team_id', 'in', [8, 26])],
    fields=fields,
    order='x_studio_fecha_1 desc',
)
print('\n=== x_analisis_de_stock (team 8 sala + 26 CD) ===  filas:', len(rows))
for r in rows:
    print('-' * 60)
    for k in fields:
        print(f'{k:38}: {r.get(k)}')
