"""DIAG read-only: caracteriza las 77 salas con compra_cd."""
import sys
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
from collections import Counter
odoo = OdooReader()
CD_TEAM = 26

rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_team_id","!=",CD_TEAM),("x_studio_buy_action","=","compra_cd")],
    fields=["x_studio_team_id","x_studio_product_id","x_studio_qty_transferir",
            "x_studio_qty_a_pedir","x_studio_decision_reason","x_studio_cover_label"],
    limit=200)
print("total salas no-CD con compra_cd:", len(rows))

# product templates involucrados
tmpl_ids = sorted({r["x_studio_product_id"][0] for r in rows if r["x_studio_product_id"]})
print("templates distintos:", len(tmpl_ids))

# cuales son solo_bodega?
pt = odoo.search_read("product.template", domain=[("id","in",tmpl_ids)],
    fields=["id","default_code","name","x_studio_comprar_solo_en_bodega"])
sb = {p["id"]: p.get("x_studio_comprar_solo_en_bodega") for p in pt}
n_sb = sum(1 for r in rows if sb.get(r["x_studio_product_id"][0] if r["x_studio_product_id"] else 0))
print(f"  de esas filas, solo_bodega=True: {n_sb}   solo_bodega=False: {len(rows)-n_sb}")

# motivo (primer token del decision_reason)
mot = Counter()
for r in rows:
    dr = (r.get("x_studio_decision_reason") or "").split("|")[0].strip()
    mot[dr]+=1
print("\nmotivos (decision_reason[0]):")
for m,n in mot.most_common(8):
    print(f"   {n:>3}  {m}")

# transfer/pedir distribucion
con_transfer = sum(1 for r in rows if (r.get("x_studio_qty_transferir") or 0)>0)
con_pedir = sum(1 for r in rows if (r.get("x_studio_qty_a_pedir") or 0)>0)
print(f"\ncon qty_transferir>0: {con_transfer}   con qty_a_pedir>0: {con_pedir}")

print("\nmuestra:")
for r in rows[:12]:
    pid = r["x_studio_product_id"][0] if r["x_studio_product_id"] else 0
    code = next((p["default_code"] for p in pt if p["id"]==pid), "?")
    print(f"   team {r['x_studio_team_id'][0]:>3} {str(code):>10} sb={sb.get(pid)} "
          f"transf={r.get('x_studio_qty_transferir') or 0:.0f} pedir={r.get('x_studio_qty_a_pedir') or 0:.0f} "
          f"| {(r.get('x_studio_decision_reason') or '')[:55]}")
