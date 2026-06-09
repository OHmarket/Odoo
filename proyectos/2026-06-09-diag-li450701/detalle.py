"""DIAG read-only: detalle completo LI45701 (Jagermeister 700cc) en analisis de stock."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# producto
prods = odoo.search_read("product.product",
    domain=[("default_code", "=", "LI45701")],
    fields=["id", "default_code", "name", "purchase_ok", "active", "qty_available",
            "list_price", "standard_price", "seller_ids"])
print("=== product.product LI45701 ===")
for p in prods:
    print(p)
pid_tmpl = None

# filas de analisis para LI45701 (todas las salas) -- match por nombre del m2o
rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code", "=", "LI45701")],
    fields=[
        "x_studio_team_id", "x_studio_proveedor_id", "x_studio_buy_action",
        "x_studio_decision_reason", "x_studio_supply_source",
        "x_studio_abcxyz", "x_studio_importancia_abc",
        "x_studio_stock_real", "x_studio_stock_effective", "x_studio_stock_central",
        "x_studio_stock_pedido_total", "x_studio_stock_proyectado",
        "x_studio_demanda_semanal", "x_studio_mu_week", "x_studio_cover_weeks",
        "x_studio_cover_label", "x_studio_reorder_target_weeks", "x_studio_target_units",
        "x_studio_safety_stock_units", "x_studio_lead_weeks", "x_studio_moq",
        "x_studio_qty_a_pedir", "x_studio_qty_transferir",
        "x_studio_over_target_units", "x_studio_rango_sobrestock",
        "x_studio_oc_pendientes",
    ],
    order="x_studio_team_id")
print(f"\n=== {len(rows)} filas analisis LI45701 ===")
for r in rows:
    print("\n--- sala:", r.get("x_studio_team_id"))
    for k, v in r.items():
        if k in ("id", "x_studio_team_id"):
            continue
        print(f"    {k:38s} {v}")
