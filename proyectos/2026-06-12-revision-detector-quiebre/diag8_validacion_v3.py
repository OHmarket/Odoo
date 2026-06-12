"""
Validacion v3.0 vs baseline v2.0. Re-mide sobre la tabla reconstruida.

Baseline v2.0 (medido 2026-06-12 antes del cambio):
  filas=179918, %con_venta=44.6%, %balance_neg=59.5%, max_racha=413,
  pares>=30d=708.
"""
import sys, statistics
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
rows = o.search_read('x_stock_balance_daily', [],
    fields=['x_studio_team_id','x_studio_product_id','x_studio_date',
            'x_studio_qty_start','x_studio_qty_balance','x_studio_qty_out',
            'x_studio_stockout','x_studio_stockout_partial','x_studio_run_version'])
n = len(rows)
print(f"filas totales: {n}   (baseline v2.0: 179918)")
if not n:
    print("TABLA VACIA — el backfill no escribio. Revisar log del run.")
    sys.exit(0)

vers = defaultdict(int)
for r in rows: vers[r.get('x_studio_run_version') or '?'] += 1
print("run_version:", dict(vers))

def pos(x): return (x or 0) > 1e-4
def neg(x): return (x or 0) < -1e-4

full = [r for r in rows if not r['x_studio_stockout_partial']]
part = [r for r in rows if r['x_studio_stockout_partial']]
neg_n = sum(1 for r in rows if neg(r['x_studio_qty_balance']))
venta_full = sum(1 for r in full if pos(r['x_studio_qty_out']))
venta_part = sum(1 for r in part if pos(r['x_studio_qty_out']))

print(f"\n  full:    {len(full):>7} ({100*len(full)/n:.1f}%)")
print(f"  partial: {len(part):>7} ({100*len(part)/n:.1f}%)")
print(f"\n  balance NEGATIVO: {neg_n} ({100*neg_n/n:.1f}%)   [v2.0: 59.5% -> esperado 0%]")
print(f"  FULL con venta>0: {venta_full} ({100*venta_full/max(len(full),1):.1f}%)   [esperado ~0%: un full no vende]")
print(f"  PARTIAL con venta>0: {venta_part} ({100*venta_part/max(len(part),1):.1f}%)   [esperado ~100%: parcial = vendio y quedo en 0]")

# rachas por par
runlen = defaultdict(int)
for r in rows:
    t=r['x_studio_team_id']; p=r['x_studio_product_id']
    tid=t[0] if isinstance(t,(list,tuple)) else t
    pid=p[0] if isinstance(p,(list,tuple)) else p
    runlen[(tid,pid)] += 1
rl = sorted(runlen.values(), reverse=True)
ge30 = sum(1 for x in rl if x>=30)
print(f"\n  pares: {len(rl)}   max_racha={rl[0]} [v2.0: 413]   mediana={statistics.median(rl):.0f}")
print(f"  pares >=30 dias: {ge30} [v2.0: 708]")
buckets = {'1':0,'2-6':0,'7-13':0,'14-29':0,'30+':0}
for x in rl:
    if x<=1: buckets['1']+=1
    elif x<=6: buckets['2-6']+=1
    elif x<=13: buckets['7-13']+=1
    elif x<=29: buckets['14-29']+=1
    else: buckets['30+']+=1
print("  buckets racha:", buckets)

# Casos canonicos: deberian NO estar (tienen stock real hoy)
print("\n=== Casos canonicos (deberian NO aparecer como quiebre perpetuo) ===")
for pid,name in [(28905,'BON O BON'),(28827,'PAPAS LAYS AMERICANO'),(10474,'AUSTRAL CALAFATE')]:
    c = sum(1 for r in rows
            if (r['x_studio_product_id'][0] if isinstance(r['x_studio_product_id'],(list,tuple)) else r['x_studio_product_id'])==pid)
    print(f"  {name} (pid={pid}): {c} dias-quiebre [v2.0: ~400]")
