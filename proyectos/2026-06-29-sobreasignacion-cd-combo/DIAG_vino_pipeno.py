"""
DIAG read-only: caso VINO PIPEÑO (barcode 9780801379628, tmpl 24185).
Objetivo: discriminar las 3 hipotesis del diseno.
  H1 combo/kit, H2 echelon keying, H3 filas stale.

Corre desde la raiz del repo:  python proyectos/2026-06-29-sobreasignacion-cd-combo/DIAG_vino_pipeno.py
NO escribe en Odoo (cliente whitelist read-only).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

BARCODE = '9780801379628'
TMPL_HINT = 24185

odoo = OdooReader()

def show(title):
    print('\n' + '=' * 70)
    print(title)
    print('=' * 70)

# 1) Campos relevantes de x_analisis_de_stock (introspeccion barata)
show('1) Campos x_analisis_de_stock (transfer/central/buy/team/product)')
fg = odoo.fields_get('x_analisis_de_stock')
for fname, meta in sorted(fg.items()):
    low = fname.lower()
    if any(k in low for k in ('transfer', 'central', 'buy_action', 'team',
                              'product', 'tmpl', 'stock', 'write_date',
                              'qty', 'accion')):
        print(f"  {fname:45s} {meta.get('type'):10s} rel={meta.get('relation')}")

# 2) Resolver el/los template(s) por barcode (template y variante)
show('2) product.template / product.product por barcode')
tmpls = odoo.search_read('product.template',
                         [('barcode', '=', BARCODE)],
                         ['id', 'name', 'type', 'detailed_type', 'barcode'])
print('templates by barcode:', tmpls)
prods = odoo.search_read('product.product',
                         [('barcode', '=', BARCODE)],
                         ['id', 'name', 'product_tmpl_id', 'barcode'])
print('variants by barcode:', prods)

# Si el hint no aparece, igual lo inspeccionamos
tmpl_ids = sorted({t['id'] for t in tmpls} | {TMPL_HINT})
print('tmpl_ids a inspeccionar:', tmpl_ids)

# 3) BoM: es phantom/kit?
show('3) mrp.bom (phantom?) para esos templates')
try:
    boms = odoo.search_read('mrp.bom',
                            [('product_tmpl_id', 'in', tmpl_ids)],
                            ['id', 'product_tmpl_id', 'type', 'product_qty'])
    print('boms:', boms)
    for b in boms:
        lines = odoo.search_read('mrp.bom.line',
                                 [('bom_id', '=', b['id'])],
                                 ['product_id', 'product_qty'])
        print(f"  bom {b['id']} lines:", lines)
except Exception as e:
    print('mrp.bom no accesible:', e)

print('\n[siguiente bloque depende de los nombres de campo del paso 1]')
