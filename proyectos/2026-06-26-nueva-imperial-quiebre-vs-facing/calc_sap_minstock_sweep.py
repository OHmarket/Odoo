"""
CALCULO read-only: modelo SAP minimum-target-stock como PISO.
  stock_minimo = (rango_dias / 7) * max(demanda_semanal, DEMANDA_MIN_SEM)
  target_final = max(target_operativo, stock_minimo)   (floor, no sumando)

Barrido 2D: rango_dias x demanda_minima. Reporta, por cada combo:
  - compra incremental REAL (neteando stock) en toda la cadena
  - "lentos rescatados": SKU x sala con demanda_local ~0 pero vivos en la red,
    que pasan de piso 0 a piso > 0 gracias a la demanda minima (la cara vacia).

Gates: 12 salas, excluye cigarros, salta SKU muerto en toda la red.
Read-only. PROXY: standard_price como costo, sin MOQ/redondeos.
"""
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

RANGO_DIAS = [7, 10, 14, 21]
DEMANDA_MIN_SEM = [0.0, 0.5, 1.0, 2.0]
SALAS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]

odoo = OdooReader()
cig = set(odoo.execute('product.category', 'search', [('id', 'child_of', [1628])]))
rows = odoo.search_read(
    'x_analisis_de_stock', [('x_studio_team_id', 'in', SALAS)],
    ['x_studio_product_id', 'x_studio_demanda_semanal', 'x_studio_target_units',
     'x_studio_stock_proyectado', 'x_studio_categ_id'])
print(f"filas leidas: {len(rows)}")

tids = list({r['x_studio_product_id'][0] for r in rows if r['x_studio_product_id']})
cost = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template', [('id', 'in', tids[i:i+500])],
                              ['standard_price']):
        cost[t['id']] = t.get('standard_price') or 0.0

global_mu = defaultdict(float)
for r in rows:
    if r['x_studio_product_id']:
        global_mu[r['x_studio_product_id'][0]] += (r.get('x_studio_demanda_semanal') or 0.0)

# pre-filtrar filas validas
items = []
for r in rows:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]
    if (r.get('x_studio_categ_id') or [0])[0] in cig:
        continue
    mu = r.get('x_studio_demanda_semanal') or 0.0
    if mu <= 0.0 and global_mu.get(tid, 0.0) <= 0.0:    # muerto en toda la red
        continue
    items.append((mu, r.get('x_studio_target_units') or 0.0,
                  r.get('x_studio_stock_proyectado') or 0.0, cost.get(tid, 0.0)))
print(f"filas en scope: {len(items):,}\n")


def run(rango, dmin):
    inc_buy = 0.0
    rescatados = 0      # local ~0, vivo en red, piso pasa a >0
    for mu, tgt, sp, c in items:
        mu_eff = max(mu, dmin)
        piso = rango / 7.0 * mu_eff
        if piso <= tgt:
            continue
        buy_base = max(0.0, tgt - sp)
        buy_floor = max(0.0, max(tgt, piso) - sp)
        inc_buy += (buy_floor - buy_base) * c
        if mu <= 0.0 and piso > 0.0:
            rescatados += 1
    return inc_buy, rescatados


print("COMPRA INCREMENTAL REAL (toda la cadena, $) por rango_dias x demanda_min")
hdr = "  rango\\dmin " + "".join(f"{d:>14}" for d in DEMANDA_MIN_SEM)
print(hdr)
for rg in RANGO_DIAS:
    line = f"  {rg:>4}d      "
    for dm in DEMANDA_MIN_SEM:
        b, _ = run(rg, dm)
        line += f"{b:>14,.0f}"
    print(line)

print("\nLENTOS RESCATADOS (SKUxsala demanda~0 vivos en red con piso>0)")
print(hdr)
for rg in RANGO_DIAS:
    line = f"  {rg:>4}d      "
    for dm in DEMANDA_MIN_SEM:
        _, resc = run(rg, dm)
        line += f"{resc:>14,}"
    print(line)

print("\nNota: dmin=0 = SAP puro (no rescata lentos, piso 0 para demanda 0).")
print("dmin>0 = adaptacion para la cara vacia del lento (presentation stock proxy).")
