# -*- coding: utf-8 -*-
"""DIAG4: incidencia de quiebre real (ultimas ~8 sem) y lead/target por SKU."""
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader
PP = {10772:'0154 CocaCola 3L', 11446:'1963 Monster', 11449:'1966 Monster Ultra',
      11967:'2233 Vital gas 1.6L', 11061:'6242 Gran120 Cab 2L',
      11065:'6243 Gran120 Merlot 2L', 11063:'6244 Gran120 Carmenere 2L'}
odoo = OdooReader()
pids=list(PP.keys())
since=(date.today()-timedelta(days=56)).isoformat()
sbd=odoo.search_read('x_stock_balance_daily',
    domain=[('x_studio_product_id','in',pids),('x_studio_date','>=',since)],
    fields=['x_studio_product_id','x_studio_date','x_studio_stockout','x_studio_stockout_partial','x_studio_team_id'])
tot=defaultdict(int); oos=defaultdict(int)
for r in sbd:
    pid=r['x_studio_product_id'][0]; tot[pid]+=1
    if r['x_studio_stockout'] or r['x_studio_stockout_partial']: oos[pid]+=1
print(f"QUIEBRE ultimas 8 sem (dias-sala con stockout / total dias-sala):")
for pid in pids:
    t=tot[pid] or 1
    print(f"  {PP[pid]:<26} {oos[pid]:>5}/{t:<6} = {oos[pid]/t*100:>5.1f}% dias-sala en quiebre")

ads=odoo.search_read('x_analisis_de_stock',
    domain=[('x_studio_product_id','in',pids)],
    fields=['x_studio_product_id','x_studio_lead_weeks','x_studio_reorder_target_weeks',
            'x_studio_buy_action','x_studio_cover_weeks'])
lead=defaultdict(list); tw=defaultdict(list); cov=defaultdict(list); ba=defaultdict(list)
for r in ads:
    pid=r['x_studio_product_id'][0]
    lead[pid].append(r.get('x_studio_lead_weeks') or 0)
    tw[pid].append(r.get('x_studio_reorder_target_weeks') or 0)
    cov[pid].append(r.get('x_studio_cover_weeks') or 0)
    ba[pid].append(r.get('x_studio_buy_action'))
print("\nLEAD / TARGET / COBERTURA (promedio salas) + buy_action mas comun:")
from collections import Counter
for pid in pids:
    n=len(lead[pid]) or 1
    bac=Counter(ba[pid]).most_common(1)[0]
    print(f"  {PP[pid]:<26} lead={sum(lead[pid])/n:>4.1f}w  target={sum(tw[pid])/n:>4.1f}w  cob={sum(cov[pid])/n:>4.1f}w  buy={bac[0]}({bac[1]})")
