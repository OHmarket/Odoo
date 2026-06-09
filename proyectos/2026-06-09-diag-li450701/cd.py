"""DIAG read-only: fila CD (team 26) LI45701 detalle de reposicion."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
odoo = OdooReader()
rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code", "=", "LI45701"),
            ("x_studio_team_id", "=", 26)],
    fields=["x_studio_decision_reason","x_studio_stock_real","x_studio_stock_central",
            "x_studio_stock_proyectado","x_studio_target_units","x_studio_demanda_semanal",
            "x_studio_mu_week","x_studio_qty_a_pedir","x_studio_qty_transferir",
            "x_studio_safety_stock_units","x_studio_reorder_target_weeks","x_studio_moq"])
for r in rows:
    for k,v in r.items():
        print(f"{k:38s} {v}")

# suma demanda salas
salas = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code","=","LI45701"),("x_studio_team_id","!=",26)],
    fields=["x_studio_mu_week","x_studio_stock_real"])
print("\nSUMA mu_week salas:", round(sum(s["x_studio_mu_week"] for s in salas),2))
print("SUMA stock_real salas:", sum(s["x_studio_stock_real"] for s in salas))
