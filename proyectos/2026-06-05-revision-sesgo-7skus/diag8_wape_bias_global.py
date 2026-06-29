# -*- coding: utf-8 -*-
"""DIAG8 read-only: WAPE y BIAS globales del motor sobre los 8 periodos.
Reporta contaminado (todo) vs limpio (combos siempre disponibles), por la
leccion del doble conteo. Tambien por semana."""
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SAN_JOSE_TEAM = 11
odoo = OdooReader()
bt = odoo.search_read('x_forecast_backtest', domain=[],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_target_week_start',
            'x_studio_forecast_qty','x_studio_real_qty'])
weeks = sorted(set(r['x_studio_target_week_start'] for r in bt))
d0=date.fromisoformat(weeks[0]); dN=date.fromisoformat(weeks[-1])+timedelta(days=6)

sbd = odoo.search_read('x_stock_balance_daily',
    domain=['&','&',('x_studio_date','>=',d0.isoformat()),('x_studio_date','<=',dN.isoformat()),
            '|',('x_studio_stockout','=',True),('x_studio_stockout_partial','=',True)],
    fields=['x_studio_product_id','x_studio_team_id'])
oos=defaultdict(int)
for r in sbd:
    if r['x_studio_team_id'] and r['x_studio_product_id']:
        oos[(r['x_studio_product_id'][0], r['x_studio_team_id'][0])]+=1

def metrics(rows):
    sumAE=sum(abs((r['x_studio_forecast_qty'] or 0)-(r['x_studio_real_qty'] or 0)) for r in rows)
    sF=sum(r['x_studio_forecast_qty'] or 0 for r in rows)
    sR=sum(r['x_studio_real_qty'] or 0 for r in rows)
    wape=sumAE/sR*100 if sR else float('nan')
    bias=(sF-sR)/sR*100 if sR else float('nan')
    return wape,bias,sR,len(rows)

def is_sj(r): return r['x_studio_team_id'] and r['x_studio_team_id'][0]==SAN_JOSE_TEAM
def is_clean(r):
    if not r['x_studio_team_id'] or not r['x_studio_product_id']: return False
    return oos.get((r['x_studio_product_id'][0], r['x_studio_team_id'][0]),0)==0

base=[r for r in bt if not is_sj(r)]
clean=[r for r in base if is_clean(r)]

print("="*70)
print(f"WAPE y BIAS GLOBAL del motor  |  {len(weeks)} periodos: {weeks[0]} a {weeks[-1]}")
print("="*70)
for label,rows in [('TODO (excl San Jose)',base),('LIMPIO (combos siempre disponibles)',clean)]:
    w,b,sr,n=metrics(rows)
    print(f"  {label:<38} WAPE={w:>6.1f}%   BIAS={b:>+6.1f}%   (volR={sr:,.0f}, n={n:,})")

print("\nPOR SEMANA (excl San Jose):")
print(f"  {'semana':<12}{'WAPE':>8}{'BIAS':>8}{'  WAPE_clean':>13}{'BIAS_clean':>12}")
for wk in weeks:
    w,b,_,_=metrics([r for r in base if r['x_studio_target_week_start']==wk])
    wc,bc,_,_=metrics([r for r in clean if r['x_studio_target_week_start']==wk])
    print(f"  {wk:<12}{w:>7.1f}%{b:>+7.1f}%{wc:>12.1f}%{bc:>+11.1f}%")
