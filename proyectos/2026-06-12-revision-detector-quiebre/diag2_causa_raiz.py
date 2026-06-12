"""
DIAG read-only: clasificar la causa raiz de las rachas de stockout.

Buckets por par (team, producto) segun su comportamiento en los dias persistidos:
  A) FLAT_NEG  : balance constante < 0, sin NINGUN movimiento (in=out=0 todo).
                 -> quant negativo fantasma propagado hacia atras. NO es quiebre.
  B) FLAT_ZERO : balance constante == 0, sin movimiento. -> sin actividad / no surtido.
  C) NEG_ANCHOR: el ultimo dia (mas reciente) tiene balance < 0.
                 -> el ancla (quant hoy) es negativo y contamina toda la serie.
  D) CON_MOV   : tiene algun in/out en la racha -> caso con actividad real.

Tambien: cuantas filas-dia totales aporta cada bucket (peso en la tabla).
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
rows = odoo.search_read(
    'x_stock_balance_daily',
    domain=[],
    fields=['x_studio_team_id', 'x_studio_product_id', 'x_studio_date',
            'x_studio_qty_start', 'x_studio_qty_balance',
            'x_studio_qty_in', 'x_studio_qty_out', 'x_studio_stockout'],
    order='x_studio_date asc',
)

by_key = defaultdict(list)
for r in rows:
    t = r['x_studio_team_id']; p = r['x_studio_product_id']
    tid = t[0] if isinstance(t, (list, tuple)) else t
    pid = p[0] if isinstance(p, (list, tuple)) else p
    by_key[(tid, pid)].append(r)

bucket_pairs = defaultdict(int)
bucket_days  = defaultdict(int)
neg_anchor_pairs = 0
neg_anchor_days = 0

for (tid, pid), recs in by_key.items():
    recs.sort(key=lambda x: x['x_studio_date'])
    n = len(recs)
    any_mov = any((r['x_studio_qty_in'] or 0) > 1e-4 or (r['x_studio_qty_out'] or 0) > 1e-4 for r in recs)
    all_neg = all((r['x_studio_qty_balance'] or 0) < -1e-4 for r in recs)
    all_zero = all(abs(r['x_studio_qty_balance'] or 0) < 1e-4 for r in recs)
    last_bal = recs[-1]['x_studio_qty_balance'] or 0

    if last_bal < -1e-4:
        neg_anchor_pairs += 1
        neg_anchor_days += n

    if not any_mov and all_neg:
        b = 'A_FLAT_NEG'
    elif not any_mov and all_zero:
        b = 'B_FLAT_ZERO'
    elif not any_mov:
        b = 'B2_FLAT_MIXED_noMov'
    else:
        b = 'D_CON_MOV'
    bucket_pairs[b] += 1
    bucket_days[b] += n

tot_pairs = len(by_key)
tot_days = sum(len(v) for v in by_key.values())
print(f"total pares={tot_pairs}  total filas-dia={tot_days}\n")
print(f"{'bucket':<22}{'pares':>8}{'% pares':>9}{'filas-dia':>12}{'% filas':>9}")
for b in sorted(bucket_pairs):
    print(f"{b:<22}{bucket_pairs[b]:>8}{100*bucket_pairs[b]/tot_pairs:>8.1f}%"
          f"{bucket_days[b]:>12}{100*bucket_days[b]/tot_days:>8.1f}%")

print(f"\nNEG_ANCHOR (ultimo dia balance<0): {neg_anchor_pairs} pares "
      f"({100*neg_anchor_pairs/tot_pairs:.1f}%), {neg_anchor_days} filas-dia "
      f"({100*neg_anchor_days/tot_days:.1f}%)")
print("  -> estos arrastran TODA su serie hacia abajo por un quant fantasma negativo.")
