"""
CALCULO read-only: modelo SAP PURO (piso = demanda_diaria * rango_dias),
SIN piso fisico de formato. Barre el rango de dias para ver desde que punto
el piso empieza a morder sobre el target operativo (mu*H + safety) que el
motor ya apunta. Responde: "un piso de 3 dias, ¿muerde o no?".

Read-only. PROXY: standard_price como costo, sin MOQ.
"""
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

DIAS_SWEEP = [3, 5, 7, 10, 14, 21]
SALAS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]
EXCLUDE_CIGARROS = [1628]

odoo = OdooReader()
cigarros_ids = set(odoo.execute('product.category', 'search',
                                [('id', 'child_of', EXCLUDE_CIGARROS)]))
rows = odoo.search_read(
    'x_analisis_de_stock', [('x_studio_team_id', 'in', SALAS)],
    ['x_studio_product_id', 'x_studio_demanda_semanal', 'x_studio_target_units',
     'x_studio_categ_id', 'x_studio_stock_proyectado'])
print(f"filas leidas: {len(rows)}")

tids = list({r['x_studio_product_id'][0] for r in rows if r['x_studio_product_id']})
cost = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template', [('id', 'in', tids[i:i+500])],
                              ['standard_price']):
        cost[t['id']] = t.get('standard_price') or 0.0

# tambien cuanto cubre HOY el target operativo, en dias de demanda
cob_dias = []
for r in rows:
    mu = r.get('x_studio_demanda_semanal') or 0.0
    tgt = r.get('x_studio_target_units') or 0.0
    if mu > 0:
        cob_dias.append(tgt / mu * 7.0)
cob_dias.sort()
if cob_dias:
    n = len(cob_dias)
    p = lambda q: cob_dias[int(q * (n - 1))]
    print(f"\nCobertura ACTUAL del target operativo (dias de demanda, SKU con venta):")
    print(f"  p10={p(.10):.1f}  p25={p(.25):.1f}  mediana={p(.50):.1f}  p75={p(.75):.1f}  p90={p(.90):.1f}")

print(f"\n{'dias':>5} {'muerde_filas':>13} {'inc_TARGET$':>15} {'compra_REAL$':>15}")
for D in DIAS_SWEEP:
    muerde = 0
    inc_t = 0.0
    inc_b = 0.0
    for r in rows:
        if not r['x_studio_product_id']:
            continue
        tid = r['x_studio_product_id'][0]
        if (r.get('x_studio_categ_id') or [0])[0] in cigarros_ids:
            continue
        mu = r.get('x_studio_demanda_semanal') or 0.0
        tgt = r.get('x_studio_target_units') or 0.0
        sp = r.get('x_studio_stock_proyectado') or 0.0
        c = cost.get(tid, 0.0)
        piso = D / 7.0 * mu
        inc = max(0.0, piso - tgt)
        if inc > 0:
            muerde += 1
            inc_t += inc * c
            buy_base = max(0.0, tgt - sp)
            buy_floor = max(0.0, max(tgt, piso) - sp)
            inc_b += (buy_floor - buy_base) * c
    print(f"{D:>5} {muerde:>13,} {inc_t:>15,.0f} {inc_b:>15,.0f}")
