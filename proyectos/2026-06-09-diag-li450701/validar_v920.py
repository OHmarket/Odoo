"""DIAG read-only: valida el resultado de v9.2.0 en datos actuales."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
odoo = OdooReader()
CD_TEAM = 26

# 1. LI45701 detalle
print("=== LI45701 (Jagermeister) ===")
rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code","=","LI45701")],
    fields=["x_studio_team_id","x_studio_buy_action","x_studio_qty_transferir",
            "x_studio_qty_a_pedir","x_studio_stock_real","x_studio_cover_label"],
    order="x_studio_team_id desc")
for r in rows:
    t = r["x_studio_team_id"]
    tid = t[0] if t else 0
    tag = "  <== CD" if tid==CD_TEAM else ""
    print(f"  team {tid:>3} {str(r['x_studio_buy_action']):>22} transf={r['x_studio_qty_transferir']:>4.0f} "
          f"pedir={r['x_studio_qty_a_pedir']:>4.0f} stock={r['x_studio_stock_real']:>4.0f} {str(r['x_studio_cover_label']):>9}{tag}")

# 2. orphans: sala compra_cd con transfer>0 y pedir=0
orph = odoo.search_count("x_analisis_de_stock",
    domain=[("x_studio_team_id","!=",CD_TEAM),("x_studio_buy_action","=","compra_cd"),
            ("x_studio_qty_transferir",">",0),("x_studio_qty_a_pedir","=",0)])
print(f"\n=== ORPHANS (sala compra_cd + transfer>0 + pedir=0): {orph}  (esperado 0) ===")

# 3. compra CD total (id 26)
cd_rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_team_id","=",CD_TEAM),("x_studio_qty_a_pedir",">",0)],
    fields=["x_studio_qty_a_pedir","x_studio_purchase_price_cash_unit"], limit=100000)
units = sum(r["x_studio_qty_a_pedir"] or 0 for r in cd_rows)
cash = sum((r["x_studio_qty_a_pedir"] or 0)*(r.get("x_studio_purchase_price_cash_unit") or 0) for r in cd_rows)
print(f"\n=== COMPRA CD TOTAL (id 26) ===")
print(f"  lineas compra_cd: {len(cd_rows)}")
print(f"  unidades:         {units:,.0f}")
print(f"  cash:             ${cash:,.0f}   (antes ~$121,5M, esperado ~$43M)")

# 4. salas aun marcadas compra_cd (deberian ser 0 con el modelo)
sala_cc = odoo.search_count("x_analisis_de_stock",
    domain=[("x_studio_team_id","!=",CD_TEAM),("x_studio_buy_action","=","compra_cd")])
print(f"\n=== salas (no-CD) aun con buy_action=compra_cd: {sala_cc}  (esperado 0 para solo_bodega) ===")
