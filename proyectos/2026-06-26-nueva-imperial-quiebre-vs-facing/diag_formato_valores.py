"""
DIAG read-only: valores de x_studio_formato en cerveza+bebida y conteo de
SKUs reales (con default_code) por formato. Sirve para tabular el piso.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader
from collections import Counter

odoo = OdooReader()

rg = odoo.execute(
    'product.template', 'read_group',
    [('categ_id', 'child_of', [1621, 1614]), ('active', '=', True)],
    ['__count'], ['x_studio_formato'], lazy=False,
)
print("== x_studio_formato (cerveza+bebida activos) ==")
for r in rg:
    print(f"  {str(r.get('x_studio_formato')):20} -> {r['__count_count' if '__count_count' in r else '__count']}")

# Cuantos tienen default_code (SKU real) vs sin codigo (promo/artefacto)
con_code = odoo.search_count('product.template',
    [('categ_id', 'child_of', [1621, 1614]), ('active', '=', True),
     ('default_code', '!=', False)])
sin_code = odoo.search_count('product.template',
    [('categ_id', 'child_of', [1621, 1614]), ('active', '=', True),
     ('default_code', '=', False)])
print(f"\nSKU con default_code: {con_code} | sin code (promo/artefacto): {sin_code}")

# formato vacio?
sin_formato = odoo.search_count('product.template',
    [('categ_id', 'child_of', [1621, 1614]), ('active', '=', True),
     ('default_code', '!=', False), ('x_studio_formato', '=', False)])
print(f"SKU real SIN x_studio_formato: {sin_formato}")
