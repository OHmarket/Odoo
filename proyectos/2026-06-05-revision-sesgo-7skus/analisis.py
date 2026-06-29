# -*- coding: utf-8 -*-
"""
Analisis sesgo 7 SKUs + safety stock activo.
- BIAS por SKU desde x_forecast_backtest (motor Forecast Base, run 2026-06-03)
- Separa filas con/sin quiebre cruzando x_stock_balance_daily (sem medida)
- Trae safety stock activo de x_analisis_de_stock
"""
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

PP = {10772:'0154 CocaCola 3L', 11446:'1963 Monster', 11449:'1966 Monster Ultra',
      11967:'2233 Vital gas 1.6L', 11061:'6242 Gran120 Cab 2L',
      11065:'6243 Gran120 Merlot 2L', 11063:'6244 Gran120 Carmenere 2L'}
SHORT = [10772,11967,11446,11449]   # ops: corto
OVER  = [11061,11065,11063]         # ops: pasado

odoo = OdooReader()
pids = list(PP.keys())

# ---------- 1. BACKTEST ----------
bt = odoo.search_read('x_forecast_backtest',
    domain=[('x_studio_product_id','in',pids)],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_target_week_start',
            'x_studio_forecast_qty','x_studio_real_qty','x_studio_forecast_model_code'])

# ---------- 2. QUIEBRE: stockout por product x team x semana medida ----------
weeks = sorted(set(r['x_studio_target_week_start'] for r in bt))
wk_dates = {}
for w in weeks:
    d0 = date.fromisoformat(w)
    wk_dates[w] = [(d0 + timedelta(days=i)).isoformat() for i in range(7)]
all_days = sorted({d for ds in wk_dates.values() for d in ds})

sbd = odoo.search_read('x_stock_balance_daily',
    domain=[('x_studio_product_id','in',pids),
            ('x_studio_date','>=',all_days[0]),
            ('x_studio_date','<=',all_days[-1])],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_date',
            'x_studio_stockout','x_studio_stockout_partial'])

# set de (pid, team_id, week) con algun dia de quiebre (total o parcial)
broke = set()
day2week = {d:w for w,ds in wk_dates.items() for d in ds}
for r in sbd:
    if not r['x_studio_team_id']:
        continue
    d = r['x_studio_date']
    w = day2week.get(d)
    if w is None:
        continue
    if r['x_studio_stockout'] or r['x_studio_stockout_partial']:
        broke.add((r['x_studio_product_id'][0], r['x_studio_team_id'][0], w))

# ---------- 3. agrega BIAS por SKU (total / limpio / quiebre) ----------
def bias(rows):
    sf = sum(r['x_studio_forecast_qty'] for r in rows)
    sr = sum(r['x_studio_real_qty'] for r in rows)
    n = len(rows)
    b = (sf - sr)/sr*100 if sr else float('nan')
    return sf, sr, b, n

print("="*92)
print("BIAS POR SKU  (forecast vs real, 12 salas x 3 sem)  + = sobre-forecast, - = sub-forecast")
print("="*92)
print(f"{'SKU':<26}{'grupo':<7}{'TOTAL bias':>12}{'  n':>4}{'   LIMPIO bias':>15}{' n':>4}{'  QUIEBRE bias':>15}{' n':>4}")
def teamkey(r): return (r['x_studio_product_id'][0], r['x_studio_team_id'][0], r['x_studio_target_week_start'])
for pid in pids:
    rs = [r for r in bt if r['x_studio_product_id'][0]==pid]
    clean = [r for r in rs if teamkey(r) not in broke]
    dirty = [r for r in rs if teamkey(r) in broke]
    _,_,bt_b,bt_n = bias(rs)
    _,_,cl_b,cl_n = bias(clean) if clean else (0,0,float('nan'),0)
    _,_,dt_b,dt_n = bias(dirty) if dirty else (0,0,float('nan'),0)
    grp = 'CORTO' if pid in SHORT else 'PASADO'
    print(f"{PP[pid]:<26}{grp:<7}{bt_b:>11.1f}%{bt_n:>4}{cl_b:>14.1f}%{cl_n:>4}{dt_b:>14.1f}%{dt_n:>4}")

# ---------- 4. SAFETY STOCK ACTIVO ----------
ads = odoo.search_read('x_analisis_de_stock',
    domain=[('x_studio_product_id','in',pids)],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_mu_week',
            'x_studio_sigma_week','x_studio_safety_stock_units','x_studio_demanda_semanal',
            'x_studio_target_units','x_studio_reorder_target_weeks','x_studio_stock_real',
            'x_studio_cover_weeks','x_studio_buy_action'])

print("\n"+"="*92)
print("SAFETY STOCK ACTIVO (x_analisis_de_stock, agregado salas)")
print("="*92)
print(f"{'SKU':<26}{'salas':>6}{'mu/sem':>9}{'sigma':>8}{'safety':>9}{'demanda':>9}{'target':>9}{'stock':>9}{'cob_w':>7}")
agg = defaultdict(lambda: defaultdict(float))
ncnt = defaultdict(int)
for r in ads:
    pid = r['x_studio_product_id'][0]
    ncnt[pid]+=1
    for f in ['x_studio_mu_week','x_studio_sigma_week','x_studio_safety_stock_units',
              'x_studio_demanda_semanal','x_studio_target_units','x_studio_stock_real']:
        agg[pid][f]+= r.get(f) or 0
for pid in pids:
    a=agg[pid]; n=ncnt[pid] or 1
    mu=a['x_studio_mu_week']; saf=a['x_studio_safety_stock_units']
    dem=a['x_studio_demanda_semanal']; tgt=a['x_studio_target_units']; st=a['x_studio_stock_real']
    cob = st/dem if dem else float('nan')
    print(f"{PP[pid]:<26}{ncnt[pid]:>6}{mu:>9.0f}{a['x_studio_sigma_week']:>8.0f}{saf:>9.0f}{dem:>9.0f}{tgt:>9.0f}{st:>9.0f}{cob:>7.1f}")

print("\nsafety/demanda = cuantas semanas de demanda cubre el safety:")
for pid in pids:
    a=agg[pid]; dem=a['x_studio_demanda_semanal']; saf=a['x_studio_safety_stock_units']
    print(f"  {PP[pid]:<26} safety={saf:>6.0f}  demanda/sem={dem:>6.0f}  -> {saf/dem if dem else float('nan'):.2f} sem")
