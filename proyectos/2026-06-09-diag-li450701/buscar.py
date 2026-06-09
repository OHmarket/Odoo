"""DIAG read-only: ubica el SKU y el proveedor."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

print("=== buscar producto por varios campos (LI450701) ===")
for fld in ["default_code", "barcode", "name"]:
    rows = odoo.search_read(
        "product.product",
        domain=[(fld, "ilike", "LI450701")],
        fields=["id", "default_code", "barcode", "name", "purchase_ok", "active"],
        limit=10,
    )
    print(f"-- por {fld}: {len(rows)}")
    for r in rows:
        print("   ", r)

print("\n=== proveedor 96568970-2 (res.partner) ===")
prov = odoo.search_read(
    "res.partner",
    domain=["|", ("vat", "ilike", "96568970"), ("name", "ilike", "96568970")],
    fields=["id", "name", "vat", "supplier_rank"],
    limit=10,
)
for p in prov:
    print("   ", p)
