"""DIAG read-only: code de proveedor + analisis de stock por proveedor 307."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

print("=== product.supplierinfo code LI450701 ===")
si = odoo.search_read(
    "product.supplierinfo",
    domain=["|", ("product_code", "ilike", "LI450701"), ("product_name", "ilike", "LI450701")],
    fields=["id", "product_code", "product_name", "product_id", "product_tmpl_id", "partner_id"],
    limit=10,
)
for r in si:
    print("   ", r)

print("\n=== analisis de stock del proveedor 307 ===")
rows = odoo.search_read(
    "x_analisis_de_stock",
    domain=[("x_studio_proveedor_id", "=", 307)],
    fields=["id", "x_studio_product_id", "x_studio_team_id", "x_studio_buy_action",
            "x_studio_decision_reason"],
    limit=80,
)
print("total filas proveedor 307:", len(rows))
# agrupar por producto
from collections import Counter
prods = Counter()
for r in rows:
    pid = r["x_studio_product_id"]
    prods[pid[1] if pid else "?"] += 1
for name, n in prods.most_common():
    print(f"   {n:3d}  {name}")
