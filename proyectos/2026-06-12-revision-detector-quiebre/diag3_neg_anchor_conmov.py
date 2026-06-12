"""
DIAG read-only: pares con movimiento real PERO ancla (ultimo dia) negativa.
Muestra como un quant fantasma negativo offsetea la serie y crea falsos quiebres
en dias donde entro/salio mercaderia (o sea, habia actividad => habia stock).
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
            'x_studio_qty_in', 'x_studio_qty_out', 'x_studio_stockout',
            'x_studio_stockout_partial'],
    order='x_studio_date asc',
)
by_key = defaultdict(list)
for r in rows:
    t = r['x_studio_team_id']; p = r['x_studio_product_id']
    tid = t[0] if isinstance(t, (list, tuple)) else t
    pid = p[0] if isinstance(p, (list, tuple)) else p
    by_key[(tid, pid)].append(r)

# candidatos: ultimo dia negativo + con al menos 1 dia de qty_in>0
cands = []
for k, recs in by_key.items():
    recs.sort(key=lambda x: x['x_studio_date'])
    last_bal = recs[-1]['x_studio_qty_balance'] or 0
    has_in = any((r['x_studio_qty_in'] or 0) > 1e-4 for r in recs)
    if last_bal < -1e-4 and has_in:
        cands.append((k, recs))

print(f"pares con ancla<0 Y con qty_in>0 en su serie: {len(cands)}\n")
for (tid, pid), recs in cands[:4]:
    pn = recs[0]['x_studio_product_id']
    pname = pn[1] if isinstance(pn, (list, tuple)) else pn
    print(f"=== team={tid} product={pid} ({pname}) ancla_end={recs[-1]['x_studio_qty_balance']:.1f} ===")
    # mostrar dias con movimiento + sus vecinos
    for r in recs:
        if (r['x_studio_qty_in'] or 0) > 1e-4 or (r['x_studio_qty_out'] or 0) > 1e-4:
            print(f"  {r['x_studio_date']}  start={r['x_studio_qty_start']:.1f} "
                  f"end={r['x_studio_qty_balance']:.1f} in={r['x_studio_qty_in']:.1f} "
                  f"out={r['x_studio_qty_out']:.1f} so={int(r['x_studio_stockout'])}")
    print()
