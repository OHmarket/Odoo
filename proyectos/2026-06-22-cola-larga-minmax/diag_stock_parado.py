# -*- coding: utf-8 -*-
"""
DIAG read-only: stock parado de la cola larga (<=4 u/mes) y sensibilidad
del guard de valor (list_price). Fase 0 - no toca productivo.
"""
import pandas as pd, numpy as np
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()

# 1) Gate de demanda: u_mes por template x sala (ventana 13 sem)
pw = pd.read_parquet('proyectos/2026-05-27-harness-local/cache/pos_weekly.parquet')
pw['week_start'] = pd.to_datetime(pw['week_start'])
cut = pw['week_start'].max() - pd.Timedelta(weeks=13)
r = pw[pw['week_start'] > cut]
mw = r['week_start'].nunique()

# pos_weekly.product_id es product.product (variant) -> mapear a template
prod_ids = sorted(r['product_id'].unique().tolist())
pp = o.search_read('product.product', [['id', 'in', prod_ids]],
                   ['id', 'product_tmpl_id', 'list_price'])
pp = pd.DataFrame(pp)
pp['tmpl'] = pp['product_tmpl_id'].apply(lambda x: x[0] if x else None)
v2t = dict(zip(pp['id'], pp['tmpl']))
lp_by_tmpl = pp.groupby('tmpl')['list_price'].max()  # list_price (con IVA)

r = r.copy()
r['tmpl'] = r['product_id'].map(v2t)
g = r.groupby(['team_id', 'tmpl'])['qty_sold'].sum().reset_index()
g['u_mes'] = g['qty_sold'] / (mw / 4.345)
g['list_price'] = g['tmpl'].map(lp_by_tmpl)

# 2) Stock parado: x_analisis_de_stock (template x crm.team)
st = o.search_read('x_analisis_de_stock', [],
                   ['x_studio_team_id', 'x_studio_product_id',
                    'x_studio_stock_real', 'x_studio_stock_value_cash_physical'])
st = pd.DataFrame(st)
st['team_id'] = st['x_studio_team_id'].apply(lambda x: x[0] if x else None)
st['tmpl'] = st['x_studio_product_id'].apply(lambda x: x[0] if x else None)
st = st.rename(columns={'x_studio_stock_real': 'stock_u',
                        'x_studio_stock_value_cash_physical': 'stock_val'})
st = st[['team_id', 'tmpl', 'stock_u', 'stock_val']]

# 3) Join demanda + stock
m = g.merge(st, on=['team_id', 'tmpl'], how='left')
m['stock_val'] = m['stock_val'].fillna(0.0)
m['stock_u'] = m['stock_u'].fillna(0.0)

tot_val = m['stock_val'].sum()
print(f'Ventana {mw} sem | pares demanda+stock: {len(m)} | stock parado total ${tot_val:,.0f}')
print()

# Cola larga = u_mes <= 4
cola = m[m['u_mes'] <= 4]
print(f'COLA LARGA (u_mes<=4): {len(cola)} pares ({100*len(cola)/len(m):.1f}%) | '
      f'stock ${cola.stock_val.sum():,.0f} ({100*cola.stock_val.sum()/tot_val:.1f}% del parado)')
print()

# 4) Sensibilidad del guard de valor sobre la cola larga
print('--- Sensibilidad guard list_price (dentro de la cola u_mes<=4) ---')
print('guard = SKU con list_price <= X entra a piloto automatico; el resto queda en revision')
print(f'{"guard $":>10} | {"pares auto":>10} | {"% pares cola":>12} | {"stock auto $":>14} | {"% stock cola":>12} | {"pares review":>12} | {"stock review $":>14}')
ccount = len(cola); cval = cola.stock_val.sum()
for X in [10000, 20000, 30000, 40000, 60000, 1e12]:
    auto = cola[cola['list_price'] <= X]
    rev = cola[cola['list_price'] > X]
    lbl = 'sin guard' if X > 1e11 else f'{X:,.0f}'
    print(f'{lbl:>10} | {len(auto):>10} | {100*len(auto)/ccount:>11.1f}% | '
          f'{auto.stock_val.sum():>13,.0f} | {100*auto.stock_val.sum()/cval:>11.1f}% | '
          f'{len(rev):>12} | {rev.stock_val.sum():>13,.0f}')

# 5) Distribucion de list_price en la cola larga
print()
print('--- list_price en la cola larga (percentiles) ---')
print(cola['list_price'].describe(percentiles=[.5, .75, .9, .95, .99]).round(0).to_string())

m.to_parquet('proyectos/2026-06-22-cola-larga-minmax/resultados/demanda_stock_join.parquet')
print('\nguardado join -> resultados/demanda_stock_join.parquet')
