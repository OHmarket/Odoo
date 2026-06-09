"""DIAG read-only: vista consolidada LI45701 + balance CD vs transferencias."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code", "=", "LI45701")],
    fields=[
        "x_studio_team_id", "x_studio_buy_action", "x_studio_supply_source",
        "x_studio_stock_real", "x_studio_stock_central",
        "x_studio_demanda_semanal", "x_studio_cover_weeks", "x_studio_cover_label",
        "x_studio_target_units", "x_studio_qty_a_pedir", "x_studio_qty_transferir",
        "x_studio_moq", "x_studio_over_target_units",
    ],
    order="x_studio_team_id")

hdr = f"{'team':>5} {'buy_action':>20} {'supply':>20} {'stk':>5} {'dem':>6} {'cob_w':>6} {'cob':>9} {'tgt':>6} {'pedir':>6} {'transf':>7} {'over':>6}"
print(hdr)
print("-"*len(hdr))
tot_transf = tot_pedir = 0.0
cd = None
for r in rows:
    t = r["x_studio_team_id"]
    tid = t[0] if t else 0
    cd = r["x_studio_stock_central"]
    tot_transf += r.get("x_studio_qty_transferir") or 0
    tot_pedir += r.get("x_studio_qty_a_pedir") or 0
    print(f"{tid:>5} {str(r['x_studio_buy_action']):>20} {str(r['x_studio_supply_source']):>20} "
          f"{r['x_studio_stock_real']:>5.0f} {r['x_studio_demanda_semanal']:>6.2f} "
          f"{r['x_studio_cover_weeks']:>6.2f} {str(r['x_studio_cover_label']):>9} "
          f"{r['x_studio_target_units']:>6.1f} {r['x_studio_qty_a_pedir']:>6.1f} "
          f"{r['x_studio_qty_transferir']:>7.1f} {r['x_studio_over_target_units']:>6.1f}")

print("-"*len(hdr))
print(f"Stock CD (stock_central):       {cd}")
print(f"SUMA qty_transferir (salas):    {tot_transf}")
print(f"SUMA qty_a_pedir (compra ext):  {tot_pedir}")
print(f"Balance CD tras transferencias: {cd - tot_transf}")
print(f"qty_available producto (global): 61   |  standard_price 6910  list 13990")
