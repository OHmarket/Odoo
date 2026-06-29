# -*- coding: utf-8 -*-
"""
DIAG read-only: universo de SKUxsala con stock pero CERO venta en la ventana.
Separa muerto-real (0 en 52 sem) de intermitente (0 en 13 sem, >0 en 52).
Mide cuanto pediria el piso S>=2 si NO aplicaramos la regla u_mes=0 -> no pedir.
"""
import pandas as pd, numpy as np
from shared.odoo_xmlrpc import OdooReader
o = OdooReader()

pw = pd.read_parquet('proyectos/2026-05-27-harness-local/cache/pos_weekly.parquet')
pw['week_start'] = pd.to_datetime(pw['week_start'])
maxw = pw['week_start'].max()

# mapear variant->template
prod_ids = sorted(pw['product_id'].unique().tolist())
pp = pd.DataFrame(o.search_read('product.product', [['id', 'in', prod_ids]],
                                ['id', 'product_tmpl_id']))
pp['tmpl'] = pp['product_tmpl_id'].apply(lambda x: x[0] if x else None)
v2t = dict(zip(pp['id'], pp['tmpl']))
pw['tmpl'] = pw['product_id'].map(v2t)

def vendio(weeks):
    sub = pw[pw['week_start'] > maxw - pd.Timedelta(weeks=weeks)]
    s = sub.groupby(['team_id', 'tmpl'])['qty_sold'].sum()
    return set(s[s > 0].index)   # pares con venta>0

vend13 = vendio(13)
vend52 = vendio(52)

# universo de stock real
st = pd.DataFrame(o.search_read('x_analisis_de_stock', [],
                  ['x_studio_team_id', 'x_studio_product_id',
                   'x_studio_stock_real', 'x_studio_stock_value_cash_physical']))
st['team_id'] = st['x_studio_team_id'].apply(lambda x: x[0] if x else None)
st['tmpl'] = st['x_studio_product_id'].apply(lambda x: x[0] if x else None)
st = st.rename(columns={'x_studio_stock_real': 'stock_u',
                        'x_studio_stock_value_cash_physical': 'stock_val'})
st = st.dropna(subset=['team_id', 'tmpl'])
st['key'] = list(zip(st['team_id'].astype(int), st['tmpl'].astype(int)))

# atributos de template
tmpls = sorted(st['tmpl'].astype(int).unique().tolist())
tp = pd.DataFrame(o.search_read('product.template', [['id', 'in', tmpls]],
                                ['id', 'purchase_ok', 'list_price', 'active']))
pk = dict(zip(tp['id'], tp['purchase_ok']))
lp = dict(zip(tp['id'], tp['list_price']))
st['purchase_ok'] = st['tmpl'].astype(int).map(pk)
st['list_price'] = st['tmpl'].astype(int).map(lp)
st['v13'] = st['key'].isin(vend13)
st['v52'] = st['key'].isin(vend52)

print(f'Universo x_analisis_de_stock: {len(st)} SKUxsala')
print(f'  con venta en 13 sem: {int(st.v13.sum())}  | SIN venta 13 sem: {int((~st.v13).sum())}')
print()

# CERO demanda 13 sem, ACTIVO para compra, dentro del guard de valor
z = st[(~st.v13) & (st.purchase_ok == True) & (st.list_price <= 20000)].copy()
print(f'--- CERO venta 13 sem + purchase_ok + list_price<=20k: {len(z)} pares ---')
print(f'  stock parado en ellos: ${z.stock_val.sum():,.0f}')
print(f'  con stock>0 (parado vivo): {int((z.stock_u>0).sum())} | en cero: {int((z.stock_u<=0).sum())}')
print()
muerto = z[~z.v52]   # 0 en 52 sem = muerto real
inter = z[z.v52]     # vendio algo en 52 pero no en 13 = intermitente
print(f'  MUERTO REAL (0 en 52 sem): {len(muerto)} pares | stock ${muerto.stock_val.sum():,.0f}')
print(f'  INTERMITENTE (0 en 13, >0 en 52): {len(inter)} pares | stock ${inter.stock_val.sum():,.0f}')
print()

ucp = z['list_price'].values / 1.19 * (1 - 0.244)
ped_u = np.maximum(2 - z['stock_u'].values, 0)   # piso S>=2
print('--- Lo que el PISO S>=2 pediria si NO aplicaramos la regla u_mes=0 ---')
print(f'  {ped_u.sum():,.0f} unidades por ${(ped_u*ucp).sum():,.0f}  en {int((ped_u>0).sum())} SKU de CERO demanda')
mm = np.maximum(2 - muerto['stock_u'].values, 0)
ucpm = muerto['list_price'].values / 1.19 * (1 - 0.244)
print(f'    de eso, en MUERTO REAL: ${(mm*ucpm).sum():,.0f} (compra pura para reponer stock muerto)')
