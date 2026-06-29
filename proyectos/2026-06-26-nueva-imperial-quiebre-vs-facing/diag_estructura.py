"""
DIAG read-only: estructura de warehouse 14 (Nueva Imperial) + categorias.
Paso 1: entender ubicaciones y categorias antes de traer stock.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
print(odoo)

# 1) Warehouse 14: ubicaciones clave
wh = odoo.search_read(
    'stock.warehouse',
    domain=[('id', '=', 14)],
    fields=['name', 'code', 'lot_stock_id', 'view_location_id'],
)
print("\n== WAREHOUSE 14 ==")
for w in wh:
    print(w)

# 2) Categorias que contengan cerveza / bebida / agua
cats = odoo.search_read(
    'product.category',
    domain=['|', '|', '|',
            ('name', 'ilike', 'cerveza'),
            ('name', 'ilike', 'bebida'),
            ('name', 'ilike', 'agua'),
            ('name', 'ilike', 'cocktail')],
    fields=['name', 'complete_name'],
    limit=50,
)
print("\n== CATEGORIAS bebida/cerveza ==")
for c in cats:
    print(c['id'], '|', c.get('complete_name') or c.get('name'))
