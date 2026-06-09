"""DIAG read-only: cuantas filas mezclan transfer+compra; patron orphan compra_cd."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
from collections import Counter
odoo = OdooReader()

CENTRAL_TEAM = 26
flds = ["x_studio_team_id","x_studio_buy_action","x_studio_qty_transferir","x_studio_qty_a_pedir"]
# traer todo el universo accionable
rows = odoo.search_read("x_analisis_de_stock",
    domain=["|",("x_studio_qty_transferir",">",0),("x_studio_qty_a_pedir",">",0)],
    fields=flds, limit=100000)
print("filas con algun movimiento:", len(rows))

both = 0            # misma fila: transfer>0 Y compra>0
both_sala = 0
orphan_compra_cd = 0   # compra_cd en sala con qty_a_pedir=0 (solo transfiere, nunca se genera doc)
compra_cd_con_pedir = 0
by_action = Counter()
for r in rows:
    t = r.get("x_studio_qty_transferir") or 0
    p = r.get("x_studio_qty_a_pedir") or 0
    tid = r["x_studio_team_id"][0] if r["x_studio_team_id"] else 0
    act = r["x_studio_buy_action"]
    by_action[act]+=1
    if t>0 and p>0:
        both+=1
        if tid!=CENTRAL_TEAM: both_sala+=1
    if act=="compra_cd" and tid!=CENTRAL_TEAM:
        if p>0: compra_cd_con_pedir+=1
        if t>0 and p==0: orphan_compra_cd+=1

print("\nfilas con transfer>0 Y compra>0 (misma fila):", both, " | de salas:", both_sala)
print("compra_cd en SALA con qty_a_pedir=0 y transfer>0 (ORPHAN, nunca se envia):", orphan_compra_cd)
print("compra_cd en SALA con qty_a_pedir>0:", compra_cd_con_pedir)
print("\nbuy_action distrib (filas con movimiento):")
for a,n in by_action.most_common():
    print(f"   {a:25s} {n}")
