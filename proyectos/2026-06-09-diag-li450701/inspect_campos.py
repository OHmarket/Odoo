"""DIAG read-only: lista campos de x_analisis_de_stock para el SKU LI450701."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# 1. Ubicar el producto por default_code
prods = odoo.search_read(
    "product.product",
    domain=["|", ("default_code", "=", "LI450701"), ("default_code", "ilike", "LI450701")],
    fields=["id", "default_code", "name", "product_tmpl_id", "purchase_ok", "active"],
)
print("=== product.product LI450701 ===")
for p in prods:
    print(p)

# 2. Campos del modelo de analisis de stock
fg = odoo.fields_get("x_analisis_de_stock")
print("\n=== campos x_analisis_de_stock ===")
for fname, meta in sorted(fg.items()):
    print(f"{fname:45s} {meta.get('type'):12s} {meta.get('string')}")
