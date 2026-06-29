"""
DIAG read-only: stock teorico por SKU en Nueva Imperial (wh14, loc 115)
para cerveza (1621+) y bebida gaseosa (1614+). Clasifica:
  - stock<=0  -> QUIEBRE real (el sistema lo ve, abastecimiento debe responder)
  - stock>0   -> hay stock teorico; si la heladera esta vacia => FACING/fantasma

Cruza con venta semanal reciente (x_pos_week_sku_sale, team 17) para marcar
"facing-sospecha": stock>0 pero sin venta en las ultimas semanas (no rota =
puede estar fuera de gondola).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

LOC = 115            # IM495 (view location Nueva Imperial)
CATS = [1621, 1614]  # cervezas, bebidas gaseosas

# 1) Stock teorico por producto (quant) en la sala, categorias objetivo
rg = odoo.execute(
    'stock.quant', 'read_group',
    [('location_id', 'child_of', LOC),
     ('product_id.categ_id', 'child_of', CATS)],
    ['quantity:sum', 'reserved_quantity:sum'],
    ['product_id'],
    lazy=False,
)
stock = {}
for r in rg:
    pid = r['product_id'][0]
    name = r['product_id'][1]
    qty = (r.get('quantity') or 0) - (r.get('reserved_quantity') or 0)
    stock[pid] = {'name': name, 'stock': qty}
print(f"Productos con quant en sala (cerveza+bebida): {len(stock)}")

# 2) Venta semanal reciente team 17 (ultimas ~6 sem) -> ult venta por producto
#    x_pos_week_sku_sale: campos a confirmar
fg = odoo.fields_get('x_pos_week_sku_sale')
cand = {k: v.get('string') for k, v in fg.items()
        if any(t in k for t in ('product', 'qty', 'week', 'team', 'sale', 'date'))}
print("\n== campos x_pos_week_sku_sale relevantes ==")
for k, v in cand.items():
    print(' ', k, '->', v)
