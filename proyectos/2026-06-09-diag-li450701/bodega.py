"""DIAG read-only: existe sucursal/bodega CD real?"""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
odoo = OdooReader()

print("=== stock.warehouse (todas) ===")
wh = odoo.search_read("stock.warehouse", domain=[],
    fields=["id","name","code","lot_stock_id","partner_id"], order="id")
for w in wh:
    print(f"   id={w['id']:3d} code={str(w.get('code')):8s} name={w['name']}")

print("\n=== crm.team id=26 (CENTRAL_TEAM_ID) ===")
t = odoo.search_read("crm.team", domain=[("id","=",26)], fields=["id","name"])
print("   ", t)

print("\n=== ubicacion CD/Stock (139) y su warehouse ===")
loc = odoo.search_read("stock.location", domain=[("id","=",139)],
    fields=["id","complete_name","usage","warehouse_id"])
print("   ", loc)

print("\n=== que tan activa es la bodega CD? movimientos internos ult 30d (cualquier producto) ===")
cnt = odoo.search_count("stock.move",
    domain=[("location_id","=",139),("state","=","done"),("date",">","2026-05-10")])
print("   stock.move DONE saliendo de CD/Stock (desde 2026-05-10):", cnt)

print("\n=== cuantos SKUs distintos tienen stock hoy en CD/Stock ===")
q = odoo.search_count("stock.quant",
    domain=[("location_id","=",139),("quantity",">",0)])
print("   SKUs con stock en CD:", q)
