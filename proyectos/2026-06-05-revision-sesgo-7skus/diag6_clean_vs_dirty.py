# -*- coding: utf-8 -*-
"""
DIAG6 read-only: aislar el doble conteo de-censura SIN re-correr el motor.
Experimento natural: bias por segmento en combos (SKU x sala) SIEMPRE DISPONIBLES
(0 dias de stockout en las 8 sem) vs combos que quebraron alguna vez.

Si CLEAN ~0 y DIRTY +alto -> el +bias es artefacto de medir forecast de-censurado
contra venta censurada (feedback_doble_conteo_decensura), no over-forecast real.
"""
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SAN_JOSE_TEAM = 11
APR06 = '2026-04-06'

odoo = OdooReader()

bt = odoo.search_read('x_forecast_backtest', domain=[],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_target_week_start',
            'x_studio_forecast_qty','x_studio_real_qty',
            'x_studio_abcxyz','x_studio_series_type'])
weeks = sorted(set(r['x_studio_target_week_start'] for r in bt))
d0 = date.fromisoformat(weeks[0])
dN = date.fromisoformat(weeks[-1]) + timedelta(days=6)

# stockout: cuenta dias-stockout por combo (pid, team) en TODA la ventana
sbd = odoo.search_read('x_stock_balance_daily',
    domain=['&', '&',
            ('x_studio_date', '>=', d0.isoformat()),
            ('x_studio_date', '<=', dN.isoformat()),
            '|', ('x_studio_stockout', '=', True),
                 ('x_studio_stockout_partial', '=', True)],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_date'])
oos_days = defaultdict(int)   # (pid, team) -> dias con stockout
for r in sbd:
    if r['x_studio_team_id'] and r['x_studio_product_id']:
        oos_days[(r['x_studio_product_id'][0], r['x_studio_team_id'][0])] += 1

def seg_of(r):
    return f"{r['x_studio_abcxyz'] or '??'}-{r['x_studio_series_type'] or 'na'}"

# excluye SanJose y apr06; clasifica combo clean (0 stockout) vs dirty
def usable(r):
    return (r['x_studio_team_id'] and r['x_studio_team_id'][0] != SAN_JOSE_TEAM
            and r['x_studio_product_id']
            and r['x_studio_target_week_start'] != APR06)

agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # seg -> 'clean'/'dirty' -> [F,R]
combos_clean = set(); combos_dirty = set()
for r in bt:
    if not usable(r):
        continue
    pid = r['x_studio_product_id'][0]; tid = r['x_studio_team_id'][0]
    grp = 'clean' if oos_days.get((pid, tid), 0) == 0 else 'dirty'
    (combos_clean if grp == 'clean' else combos_dirty).add((pid, tid))
    s = seg_of(r)
    agg[s][grp][0] += r['x_studio_forecast_qty'] or 0
    agg[s][grp][1] += r['x_studio_real_qty'] or 0

def bp(F, R):
    return (F - R) / R * 100 if R else float('nan')

# totales
tF_c = sum(agg[s]['clean'][0] for s in agg); tR_c = sum(agg[s]['clean'][1] for s in agg)
tF_d = sum(agg[s]['dirty'][0] for s in agg); tR_d = sum(agg[s]['dirty'][1] for s in agg)
print(f"combos CLEAN (0 stockout 8sem)={len(combos_clean)}   DIRTY={len(combos_dirty)}")
print(f"volR clean={tR_c:.0f}  dirty={tR_d:.0f}  ({tR_c/(tR_c+tR_d)*100:.0f}% del volumen es clean)")
print(f"\nBIAS GLOBAL (excl SanJose/apr06):")
print(f"  CLEAN (siempre disponible)  bias = {bp(tF_c, tR_c):>7.1f}%   <- comparable de verdad")
print(f"  DIRTY (quebro alguna vez)   bias = {bp(tF_d, tR_d):>7.1f}%   <- contaminado por censura")

print("\n" + "=" * 96)
print("BIAS POR SEGMENTO: CLEAN vs DIRTY   (+ sobre / - sub)")
print("=" * 96)
print(f"{'segmento':<16}{'volR_clean':>11}{'CLEAN bias':>12}{'volR_dirty':>11}{'DIRTY bias':>12}{'delta':>8}")
segs_ord = sorted(agg, key=lambda s: -(agg[s]['clean'][1] + agg[s]['dirty'][1]))
for s in segs_ord:
    Rc = agg[s]['clean'][1]; Rd = agg[s]['dirty'][1]
    if Rc + Rd < 100:
        continue
    bc = bp(*agg[s]['clean']); bd = bp(*agg[s]['dirty'])
    delta = (bd - bc) if (bc == bc and bd == bd) else float('nan')
    print(f"{s:<16}{Rc:>11.0f}{bc:>11.1f}%{Rd:>11.0f}{bd:>11.1f}%{delta:>7.1f}")

print("\nLECTURA:")
print("  Si CLEAN ~0 y DIRTY alto -> el +bias era doble conteo (medir de-censurado vs")
print("  venta censurada). El motor no sobre-pronostica; medimos mal. (decensor queda ON en prod.)")
print("  Si CLEAN sigue +alto -> hay sesgo REAL del motor, corregible. Ese es el numero limpio.")
print("  delta = DIRTY - CLEAN = magnitud de la contaminacion por censura en cada segmento.")
