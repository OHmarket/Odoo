"""DIAG read-only: de donde sale el 16 en transferir desde CD para LI45701."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
odoo = OdooReader()

PID = 18980  # product.product LI45701

# (a) qty_transferir agrupado por buy_action
rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code","=","LI45701"),("x_studio_team_id","!=",26)],
    fields=["x_studio_team_id","x_studio_buy_action","x_studio_qty_transferir"])
from collections import defaultdict
by_act = defaultdict(float)
for r in rows:
    by_act[r["x_studio_buy_action"]] += r.get("x_studio_qty_transferir") or 0
print("=== suma qty_transferir por buy_action (salas) ===")
for a,q in by_act.items():
    print(f"   {a:25s} {q}")
print("   TOTAL transfer salas:", sum(by_act.values()))

# (b) stock fisico del producto por ubicacion (quants)
print("\n=== stock.quant por ubicacion (LI45701) ===")
q = odoo.search_read("stock.quant",
    domain=[("product_id","=",PID),("location_id.usage","=","internal")],
    fields=["location_id","quantity","reserved_quantity","available_quantity"])
for r in q:
    print(f"   {str(r['location_id']):55s} on_hand={r['quantity']:6.1f} "
          f"reserved={r.get('reserved_quantity',0):5.1f} avail={r.get('available_quantity',0):6.1f}")

# (c) pickings internos recientes con este producto
print("\n=== stock.move internos recientes (LI45701) ===")
mv = odoo.search_read("stock.move",
    domain=[("product_id","=",PID),("picking_id.picking_type_id.code","=","internal")],
    fields=["picking_id","product_uom_qty","quantity","state","date","location_id","location_dest_id"],
    limit=40, order="date desc")
for r in mv:
    print(f"   {str(r.get('picking_id')):28s} demand={r['product_uom_qty']:5.1f} done={r.get('quantity',0):5.1f} "
          f"{r['state']:10s} {str(r['date'])[:10]} {str(r['location_id'])[:20]}->{str(r['location_dest_id'])[:20]}")
