"""DIAG read-only: desglose cover/target del SKU 450237 (CERVEZA CRISTAL LATA 6X470).
Confirma por qué reorder_target_weeks ~1 sem vs delay=15d del supplierinfo.
"""
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# 1. Template id por default_code
tmpls = odoo.search_read(
    'product.template',
    domain=[('default_code', '=', '450237')],
    fields=['id', 'name', 'default_code', 'x_studio_comprar_solo_en_bodega', 'uom_po_id'],
)
print('=== product.template ===')
for t in tmpls:
    print(t)

if not tmpls:
    raise SystemExit('No se encontro template 450237')

tid = tmpls[0]['id']

# 2. supplierinfo (delay = dias)
sinfo = odoo.search_read(
    'product.supplierinfo',
    domain=[('product_tmpl_id', '=', tid)],
    fields=['partner_id', 'delay', 'min_qty', 'sequence', 'price'],
)
print('\n=== product.supplierinfo (delay en dias) ===')
for s in sinfo:
    print(s)

# 3. filas de analisis de stock (sala + CD)
rows = odoo.search_read(
    'x_analisis_de_stock',
    domain=[('x_studio_product_id', '=', tid)],
    fields=[
        'x_studio_team_id',
        'x_studio_cover_weeks',
        'x_studio_reorder_target_weeks',
        'x_studio_periodo_repos_weeks',
        'x_studio_lead_weeks',
    ],
)
print('\n=== x_analisis_de_stock ===')
for r in rows:
    print(r)
