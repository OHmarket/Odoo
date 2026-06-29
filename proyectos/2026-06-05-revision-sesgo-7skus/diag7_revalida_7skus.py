# -*- coding: utf-8 -*-
"""
DIAG7 read-only: re-valida el analisis inicial de los 7 SKUs con bias LIMPIO
(combos siempre disponibles) vs el bias contaminado que uso el analisis inicial.
Tambien muestra el bias clean semana a semana (nivel vs trend estacional).
"""
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SAN_JOSE_TEAM = 11
APR06 = '2026-04-06'
PP = {10772:'0154 CocaCola3L', 11967:'2233 Vital1.6', 11446:'1963 Monster',
      11449:'1966 MonsterUltra', 11061:'6242 Cab2L', 11065:'6243 Merlot2L',
      11063:'6244 Carmen2L'}
GRP = {10772:'CORTO',11967:'CORTO',11446:'CORTO',11449:'CORTO',
       11061:'PASADO',11065:'PASADO',11063:'PASADO'}
pids = list(PP.keys())

odoo = OdooReader()
bt = odoo.search_read('x_forecast_backtest',
    domain=[('x_studio_product_id','in',pids)],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_target_week_start',
            'x_studio_forecast_qty','x_studio_real_qty'])
weeks = sorted(set(r['x_studio_target_week_start'] for r in bt))
d0 = date.fromisoformat(weeks[0]); dN = date.fromisoformat(weeks[-1])+timedelta(days=6)

# dias-stockout por combo (pid,team) en toda la ventana
sbd = odoo.search_read('x_stock_balance_daily',
    domain=['&','&',('x_studio_date','>=',d0.isoformat()),('x_studio_date','<=',dN.isoformat()),
            '|',('x_studio_stockout','=',True),('x_studio_stockout_partial','=',True)],
    fields=['x_studio_product_id','x_studio_team_id'])
oos = defaultdict(int)
for r in sbd:
    if r['x_studio_team_id'] and r['x_studio_product_id']:
        oos[(r['x_studio_product_id'][0], r['x_studio_team_id'][0])] += 1

def bp(F,R): return (F-R)/R*100 if R else float('nan')

# clean vs dirty por SKU
agg = defaultdict(lambda: {'clean':[0.0,0.0],'dirty':[0.0,0.0]})
salas_clean = defaultdict(set); salas_dirty = defaultdict(set)
wk_clean = defaultdict(lambda: defaultdict(lambda:[0.0,0.0]))  # pid->week->[F,R] clean only
for r in bt:
    if not r['x_studio_team_id'] or r['x_studio_team_id'][0]==SAN_JOSE_TEAM: continue
    if r['x_studio_target_week_start']==APR06: continue
    pid=r['x_studio_product_id'][0]; tid=r['x_studio_team_id'][0]
    grp='clean' if oos.get((pid,tid),0)==0 else 'dirty'
    (salas_clean if grp=='clean' else salas_dirty)[pid].add(tid)
    agg[pid][grp][0]+=r['x_studio_forecast_qty'] or 0
    agg[pid][grp][1]+=r['x_studio_real_qty'] or 0
    if grp=='clean':
        w=r['x_studio_target_week_start']
        wk_clean[pid][w][0]+=r['x_studio_forecast_qty'] or 0
        wk_clean[pid][w][1]+=r['x_studio_real_qty'] or 0

print("="*100)
print("RE-VALIDACION 7 SKUs: bias CONTAMINADO (inicial) vs bias LIMPIO (combos siempre disponibles)")
print("="*100)
print(f"{'SKU':<18}{'grupo':<8}{'salas_clean':>12}{'CLEAN bias':>12}{'DIRTY bias':>12}{'veredicto':>26}")
for pid in pids:
    bc=bp(*agg[pid]['clean']); bd=bp(*agg[pid]['dirty'])
    nc=len(salas_clean[pid])
    if bc!=bc: ver='sin combos limpios'
    elif abs(bc)<5: ver='forecast OK (~0)'
    elif bc>0: ver='sobre-forecast REAL'
    else: ver='sub-forecast REAL'
    print(f"{PP[pid]:<18}{GRP[pid]:<8}{nc:>9}/13{bc:>11.1f}%{bd:>11.1f}%{ver:>26}")

print("\n"+"="*100)
print("BIAS LIMPIO SEMANA A SEMANA (nivel estable vs arranque invierno)  [excl apr06]")
print("="*100)
wl=[w[5:] for w in weeks if w!=APR06]
print(f"{'SKU':<18}"+"".join(f"{x:>9}" for x in wl)+f"{'mean':>8}")
for pid in pids:
    line=f"{PP[pid]:<18}"; bs=[]
    for w in weeks:
        if w==APR06: continue
        F,R=wk_clean[pid][w]; b=bp(F,R); bs.append(b)
        line+=f"{b:>9.1f}" if b==b else f"{'-':>9}"
    bx=[b for b in bs if b==b]; m=sum(bx)/len(bx) if bx else float('nan')
    line+=f"{m:>8.1f}"
    print(line)
