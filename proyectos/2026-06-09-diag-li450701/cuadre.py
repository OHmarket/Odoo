"""DIAG read-only: cuadre exacto salida CD = transferir_desde_cd + compra_cd."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
odoo = OdooReader()

rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code","=","LI45701"),("x_studio_team_id","!=",26)],
    fields=["x_studio_team_id","x_studio_buy_action","x_studio_supply_source",
            "x_studio_qty_transferir","x_studio_stock_real"],
    order="x_studio_buy_action,x_studio_team_id")

print(f"{'team':>5} {'buy_action':>22} {'supply':>20} {'transf':>7}")
print("-"*60)
t_transfer = t_compra = 0.0
for r in rows:
    q = r.get("x_studio_qty_transferir") or 0
    if r["x_studio_buy_action"] == "transferir_desde_cd":
        t_transfer += q
    elif r["x_studio_buy_action"] == "compra_cd":
        t_compra += q
    if q>0:
        tid = r["x_studio_team_id"][0] if r["x_studio_team_id"] else 0
        print(f"{tid:>5} {r['x_studio_buy_action']:>22} {str(r['x_studio_supply_source']):>20} {q:>7.0f}")

cd = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id.default_code","=","LI45701"),("x_studio_team_id","=",26)],
    fields=["x_studio_stock_central","x_studio_qty_a_pedir","x_studio_qty_transferir"])[0]

print("-"*60)
print(f"Suma 'transferir_desde_cd' : {t_transfer:>5.0f}  <- lo que ves etiquetado asi")
print(f"Suma 'compra_cd' (sale CD) : {t_compra:>5.0f}  <- TAMBIEN sale del CD")
print(f"SALIDA TOTAL del CD        : {t_transfer+t_compra:>5.0f}")
print(f"Stock CD hoy               : {cd['x_studio_stock_central']:>5.0f}")
print(f"CD tras vaciar             : {cd['x_studio_stock_central']-(t_transfer+t_compra):>5.0f}")
print(f"Compra al proveedor (CD)   : {cd['x_studio_qty_a_pedir']:>5.0f}")
