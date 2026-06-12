"""
DIAG read-only: caracterizar la "perpetuacion" de quiebre.

Hipotesis del usuario: un producto que llega a 0 por quiebre queda marcado
stockout=True dia tras dia los dias posteriores.

Que mide:
  1. Distribucion de longitud de rachas consecutivas de stockout por (team, producto).
  2. Cuantos pares (team, producto) tienen rachas largas (>= 14 dias).
  3. Para los top ofensores, dump dia-a-dia: qty_start, qty_balance, qty_in, qty_out.
  4. Chequeo clave: en una racha larga, hubo qty_in > 0 en algun dia? (si si,
     el detector NO esta limpiando el quiebre tras reabastecer -> bug real.
     si no, es 0 genuino -> es delisting/no-surtido, no quiebre de venta).

NO escribe nada. Solo lee x_stock_balance_daily.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Ventana: traer todo lo que haya (la tabla solo persiste dias de quiebre).
rows = odoo.search_read(
    'x_stock_balance_daily',
    domain=[],
    fields=[
        'x_studio_team_id', 'x_studio_product_id', 'x_studio_date',
        'x_studio_qty_start', 'x_studio_qty_balance',
        'x_studio_qty_in', 'x_studio_qty_out',
        'x_studio_stockout', 'x_studio_stockout_partial',
    ],
    order='x_studio_date asc',
)
print(f"filas totales en x_stock_balance_daily: {len(rows)}")
if not rows:
    sys.exit(0)

fechas = sorted({r['x_studio_date'] for r in rows})
print(f"rango fechas persistidas: {fechas[0]} .. {fechas[-1]}  ({len(fechas)} dias distintos)")

# Agrupar por (team, product)
by_key = defaultdict(list)
for r in rows:
    t = r['x_studio_team_id']
    p = r['x_studio_product_id']
    tid = t[0] if isinstance(t, (list, tuple)) else t
    pid = p[0] if isinstance(p, (list, tuple)) else p
    by_key[(tid, pid)].append(r)

print(f"pares (team, producto) con al menos 1 dia persistido: {len(by_key)}")

# Como la tabla SOLO persiste dias de quiebre, dias consecutivos persistidos
# con stockout=True == racha de quiebre. Medimos longitud por par.
run_lengths = []
con_qty_in_en_racha = 0  # pares cuya racha tiene >=1 dia con qty_in>0
ejemplos_qty_in = []
for (tid, pid), recs in by_key.items():
    recs.sort(key=lambda x: x['x_studio_date'])
    dias_stockout = [r for r in recs if r['x_studio_stockout']]
    n = len(dias_stockout)
    run_lengths.append(n)
    tuvo_in = any((r['x_studio_qty_in'] or 0) > 0.0001 for r in dias_stockout)
    if tuvo_in:
        con_qty_in_en_racha += 1
        if len(ejemplos_qty_in) < 15:
            ejemplos_qty_in.append((tid, pid, n))

import statistics
run_lengths.sort(reverse=True)
print("\n=== Distribucion longitud de racha de stockout (dias persistidos por par) ===")
print(f"  max={run_lengths[0]}  p95={run_lengths[int(len(run_lengths)*0.05)]}  "
      f"mediana={statistics.median(run_lengths):.0f}  media={statistics.mean(run_lengths):.1f}")
buckets = {'1': 0, '2-6': 0, '7-13': 0, '14-29': 0, '30+': 0}
for n in run_lengths:
    if n <= 1: buckets['1'] += 1
    elif n <= 6: buckets['2-6'] += 1
    elif n <= 13: buckets['7-13'] += 1
    elif n <= 29: buckets['14-29'] += 1
    else: buckets['30+'] += 1
print("  buckets:", buckets)

print(f"\n=== Pares cuya racha de quiebre incluye un dia con qty_in>0 (reabasteci) ===")
print(f"  {con_qty_in_en_racha} de {len(by_key)} pares")
print("  (si es alto -> el detector marca stockout EN dias que entro mercaderia)")
print("  ejemplos (team, product, n_dias_stockout):", ejemplos_qty_in[:15])

# Dump dia-a-dia de los 5 pares con racha mas larga
print("\n=== Dump dia-a-dia: 5 pares con racha mas larga ===")
top = sorted(by_key.items(), key=lambda kv: -len([r for r in kv[1] if r['x_studio_stockout']]))[:5]
for (tid, pid), recs in top:
    recs.sort(key=lambda x: x['x_studio_date'])
    pn = recs[0]['x_studio_product_id']
    pname = pn[1] if isinstance(pn, (list, tuple)) else pn
    print(f"\n  team={tid} product={pid} ({pname}) -- {len(recs)} dias persistidos")
    for r in recs[-25:]:
        print(f"    {r['x_studio_date']}  start={r['x_studio_qty_start']:.1f} "
              f"end={r['x_studio_qty_balance']:.1f} in={r['x_studio_qty_in']:.1f} "
              f"out={r['x_studio_qty_out']:.1f} so={int(r['x_studio_stockout'])} "
              f"partial={int(r['x_studio_stockout_partial'])}")
