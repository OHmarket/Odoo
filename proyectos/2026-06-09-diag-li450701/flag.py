"""DIAG read-only: confirma flag solo_bodega y categoria de LI45701."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# tmpl
t = odoo.search_read("product.template",
    domain=[("default_code", "=", "LI45701")],
    fields=["id", "default_code", "name", "categ_id", "purchase_ok",
            "x_studio_comprar_solo_en_bodega"])
print("=== product.template ===")
for r in t:
    print(r)
    cat = r.get("categ_id")

# variant flag (line 882 lee de r = registro analisis sobre producto)
v = odoo.search_read("product.product",
    domain=[("default_code", "=", "LI45701")],
    fields=["id", "x_studio_comprar_solo_en_bodega"])
print("\n=== product.product flag ===")
for r in v:
    print(r)

# categoria: tiene flag a nivel categoria?
if t:
    cat = t[0].get("categ_id")
    if cat:
        fg = odoo.fields_get("product.category")
        cand = [f for f in fg if "bodega" in f.lower() or "solo" in f.lower()]
        print("\n=== campos categoria con 'bodega/solo':", cand)
        if cand:
            c = odoo.search_read("product.category",
                domain=[("id", "=", cat[0])], fields=["id", "name"] + cand)
            print(c)
