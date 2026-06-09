"""DIAG read-only: simula el modelo Marco (CD pass-through diferencial) sobre datos
actuales y lo compara contra lo que el motor produce hoy.

Modelo Marco:
  - transferir = distribuir stock CD entre salas con necesidad (prioridad).
  - compra_cd (id 26) = max(0, Sum necesidad_salas - stock_CD - OC_pendiente_CD), MOQ.
  - se elimina el target forward del CD (solo_bodega_cd_replenish).
NO modifica nada. Solo mide el delta.
"""
import sys, math
sys.path.insert(0, r"d:/Desarrollo/Odoo")
from shared.odoo_xmlrpc import OdooReader
from collections import defaultdict
odoo = OdooReader()

CD_TEAM = 26

# 1. CD lines con compra hoy (universo afectado)
cd_rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_team_id","=",CD_TEAM),("x_studio_qty_a_pedir",">",0)],
    fields=["x_studio_product_id","x_studio_qty_a_pedir","x_studio_stock_central",
            "x_studio_stock_real","x_studio_moq","x_studio_purchase_price_cash_unit",
            "x_studio_decision_reason"])
print("CD lines con compra hoy:", len(cd_rows))

prod_ids = [r["x_studio_product_id"][0] for r in cd_rows if r["x_studio_product_id"]]
cd_by_prod = {r["x_studio_product_id"][0]: r for r in cd_rows if r["x_studio_product_id"]}

# 2. salas de esos productos (necesidad = max(0, target - stock_proy))
sala_rows = odoo.search_read("x_analisis_de_stock",
    domain=[("x_studio_product_id","in",prod_ids),("x_studio_team_id","!=",CD_TEAM)],
    fields=["x_studio_product_id","x_studio_target_units","x_studio_stock_proyectado",
            "x_studio_cover_label","x_studio_qty_transferir"], limit=200000)
need_by_prod = defaultdict(float)
critico_by_prod = defaultdict(int)
for r in sala_rows:
    pid = r["x_studio_product_id"][0] if r["x_studio_product_id"] else None
    if pid is None: continue
    need = max(0.0, (r.get("x_studio_target_units") or 0.0) - (r.get("x_studio_stock_proyectado") or 0.0))
    need_by_prod[pid] += need
    if r.get("x_studio_cover_label") in ("sin_stock","critico"):
        critico_by_prod[pid] += 1

def ceil_moq(q, moq):
    if moq and moq > 0: return math.ceil(q/moq)*moq
    return math.ceil(q)

# 3. comparar
cur_units = sim_units = cur_cash = sim_cash = 0.0
n_baja = n_sube = n_cero = 0
riesgo = []  # SKUs con sala critica que igual quedan en compra 0
sample = []
for pid, cd in cd_by_prod.items():
    cur = cd["x_studio_qty_a_pedir"] or 0.0
    stock_cd = cd.get("x_studio_stock_central") or cd.get("x_studio_stock_real") or 0.0
    moq = cd.get("x_studio_moq") or 1.0
    price = cd.get("x_studio_purchase_price_cash_unit") or 0.0
    need = need_by_prod.get(pid, 0.0)
    # OC pendiente del CD: aprox no disponible aqui (stock_central ya es fisico); 0
    sim_raw = max(0.0, need - stock_cd)
    sim = ceil_moq(sim_raw, moq)
    cur_units += cur; sim_units += sim
    cur_cash += cur*price; sim_cash += sim*price
    if sim < cur - 1e-6: n_baja += 1
    elif sim > cur + 1e-6: n_sube += 1
    if sim <= 0:
        n_cero += 1
        if critico_by_prod.get(pid,0) > 0 and stock_cd < need:
            riesgo.append((pid, need, stock_cd, critico_by_prod[pid]))
    if len(sample) < 12:
        sample.append((pid, cur, sim, round(need,1), stock_cd, moq))

print("\n=== IMPACTO (solo SKUs que compran hoy en CD) ===")
print(f"SKUs afectados:            {len(cd_by_prod)}")
print(f"Compra HOY (unidades):     {cur_units:,.0f}")
print(f"Compra SIM Marco (unid):   {sim_units:,.0f}   (delta {sim_units-cur_units:+,.0f})")
print(f"Compra HOY (cash):         ${cur_cash:,.0f}")
print(f"Compra SIM Marco (cash):   ${sim_cash:,.0f}   (delta ${sim_cash-cur_cash:+,.0f})")
print(f"SKUs que BAJAN compra:     {n_baja}")
print(f"SKUs que SUBEN compra:     {n_sube}")
print(f"SKUs que quedan en 0:      {n_cero}")
print(f"\n*** RIESGO: SKUs con sala critica + CD no cubre, pero sim compra 0: {len(riesgo)} ***")
for pid,need,scd,nc in riesgo[:15]:
    print(f"    pid={pid} need={need:.1f} stock_cd={scd:.1f} salas_criticas={nc}")

print("\n=== muestra (pid, compra_hoy, compra_sim, need_salas, stock_cd, moq) ===")
for s in sample:
    print("   ", s)

# --- split por path: forward (solo_bodega_cd_replenish) vs diferencial (resto) ---
fwd_cur=fwd_sim=dif_cur=dif_sim=0.0
fwd_n=dif_n=0
for pid, cd in cd_by_prod.items():
    cur = cd["x_studio_qty_a_pedir"] or 0.0
    stock_cd = cd.get("x_studio_stock_central") or cd.get("x_studio_stock_real") or 0.0
    moq = cd.get("x_studio_moq") or 1.0
    sim = ceil_moq(max(0.0, need_by_prod.get(pid,0.0)-stock_cd), moq)
    reason = cd.get("x_studio_decision_reason") or ""
    if "solo_bodega_cd_replenish" in reason:
        fwd_cur+=cur; fwd_sim+=sim; fwd_n+=1
    else:
        dif_cur+=cur; dif_sim+=sim; dif_n+=1
print("\n=== SPLIT por path ===")
print(f"FORWARD (solo_bodega_cd_replenish): {fwd_n} SKUs | hoy {fwd_cur:,.0f} -> sim {fwd_sim:,.0f} (delta {fwd_sim-fwd_cur:+,.0f})")
print(f"DIFERENCIAL (policy compra_cd):     {dif_n} SKUs | hoy {dif_cur:,.0f} -> sim {dif_sim:,.0f} (delta {dif_sim-dif_cur:+,.0f})")
print("  (si DIFERENCIAL tiene delta grande, mi sim subestima need; si ~0, el recorte vive en FORWARD = doble conteo legitimo)")

# --- verificar LI45701 (pid 18980) ---
print("\n=== LI45701 (pid 18980) ===")
if 18980 in cd_by_prod:
    cd=cd_by_prod[18980]
    print(f"  compra_hoy={cd['x_studio_qty_a_pedir']} stock_cd={cd.get('x_studio_stock_central')} need_salas={need_by_prod.get(18980,0):.1f} -> sim={ceil_moq(max(0.0,need_by_prod.get(18980,0)-(cd.get('x_studio_stock_central') or 0)),cd.get('x_studio_moq') or 1):.0f}")
else:
    print("  no esta en cd_by_prod (no compra hoy o ya cubierto)")
