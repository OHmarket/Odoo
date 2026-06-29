# -*- coding: utf-8 -*-
"""
Genera listado de SKU MUERTOS para descatalogar + liquidar.
Muerto = sin venta en >=52 semanas en NINGUNA sala, purchase_ok=True, active.
Salida CSV formato Chile (sep=';', decimal=',', utf-8-sig).
"""
import pandas as pd, numpy as np
from shared.odoo_xmlrpc import OdooReader
o = OdooReader()
OUT = 'proyectos/2026-06-22-cola-larga-minmax/resultados/'

pw = pd.read_parquet('proyectos/2026-05-27-harness-local/cache/pos_weekly.parquet')
pw['week_start'] = pd.to_datetime(pw['week_start'])
maxw = pw['week_start'].max()
hist_ini = pw['week_start'].min()

# variant -> template
prod_ids = sorted(pw['product_id'].unique().tolist())
pp = pd.DataFrame(o.search_read('product.product', [['id', 'in', prod_ids]],
                                ['id', 'product_tmpl_id']))
pp['tmpl'] = pp['product_tmpl_id'].apply(lambda x: x[0] if x else None)
pw['tmpl'] = pw['product_id'].map(dict(zip(pp['id'], pp['tmpl'])))

# por template: ultima venta y unidades 52 sem (todas las salas)
sold = pw[pw['qty_sold'] > 0]
last_sale = sold.groupby('tmpl')['week_start'].max()
u52 = sold[sold['week_start'] > maxw - pd.Timedelta(weeks=52)].groupby('tmpl')['qty_sold'].sum()

# stock por template (suma salas) + n salas con stock
st = pd.DataFrame(o.search_read('x_analisis_de_stock', [],
                  ['x_studio_team_id', 'x_studio_product_id',
                   'x_studio_stock_real', 'x_studio_stock_value_cash_physical']))
st['tmpl'] = st['x_studio_product_id'].apply(lambda x: x[0] if x else None)
st = st.dropna(subset=['tmpl'])
st['tmpl'] = st['tmpl'].astype(int)
st = st.rename(columns={'x_studio_stock_real': 'su', 'x_studio_stock_value_cash_physical': 'sv'})
stg = st.groupby('tmpl').agg(stock_u=('su', 'sum'), stock_val=('sv', 'sum'),
                             salas_con_stock=('su', lambda s: int((s > 0).sum()))).reset_index()

# atributos template
tmpls = sorted(stg['tmpl'].unique().tolist())
tp = pd.DataFrame(o.search_read('product.template', [['id', 'in', tmpls]],
                  ['id', 'default_code', 'name', 'list_price', 'purchase_ok',
                   'active', 'categ_id']))
tp['categ'] = tp['categ_id'].apply(lambda x: x[1] if x else '')

df = stg.merge(tp, left_on='tmpl', right_on='id', how='left')
df['ultima_venta'] = df['tmpl'].map(last_sale)
df['u_52sem'] = df['tmpl'].map(u52).fillna(0.0)
df['sem_sin_venta'] = ((maxw - df['ultima_venta']).dt.days / 7).round(0)
# nunca aparecio en pos_weekly -> sem_sin_venta NaN; marcar
df['nunca_vendio_en_hist'] = df['ultima_venta'].isna()

# MUERTO: 0 venta en 52 sem (en todas las salas), activo y comprable, con stock que liquidar
muerto = df[(df['u_52sem'] == 0) & (df['purchase_ok'] == True) & (df['active'] == True)].copy()
muerto['accion'] = np.where(muerto['stock_u'] > 0, 'LIQUIDAR + DESCATALOGAR', 'SOLO DESCATALOGAR')
muerto = muerto.sort_values('stock_val', ascending=False)

cols = ['default_code', 'name', 'categ', 'list_price', 'stock_u', 'stock_val',
        'salas_con_stock', 'ultima_venta', 'sem_sin_venta', 'nunca_vendio_en_hist', 'accion']
out = muerto[cols].rename(columns={
    'default_code': 'codigo', 'name': 'descripcion', 'categ': 'categoria',
    'list_price': 'precio_venta', 'stock_u': 'stock_unidades',
    'stock_val': 'stock_valor_costo', 'salas_con_stock': 'salas_con_stock',
    'ultima_venta': 'ultima_venta', 'sem_sin_venta': 'semanas_sin_venta'})

f_all = OUT + 'SKU_muertos_descatalogar.csv'
out.to_csv(f_all, sep=';', decimal=',', encoding='utf-8-sig', index=False)

print(f'Historia POS: {hist_ini.date()} a {maxw.date()} ({int((maxw-hist_ini).days/7)} sem)')
print(f'Templates evaluados (con registro de stock): {len(df)}')
print()
print(f'SKU MUERTOS (0 venta 52 sem, activo, comprable): {len(muerto)}')
print(f'  stock parado total: ${muerto.stock_val.sum():,.0f}')
print(f'  LIQUIDAR+DESCATALOGAR (con stock): {int((muerto.stock_u>0).sum())} | '
      f'${muerto[muerto.stock_u>0].stock_val.sum():,.0f}')
print(f'  SOLO DESCATALOGAR (sin stock):     {int((muerto.stock_u<=0).sum())}')
print(f'  nunca vendieron en historia POS:   {int(muerto.nunca_vendio_en_hist.sum())} (revisar: nuevos vs muertos)')
print()
print(f'>>> CSV: {f_all}')
print()
print('--- Top 15 por stock parado ---')
top = muerto.head(15)[['default_code', 'name', 'stock_u', 'stock_val', 'sem_sin_venta']]
for _, r in top.iterrows():
    nm = (str(r['name'])[:42]).ljust(42)
    sv = 's/d' if pd.isna(r['sem_sin_venta']) else f"{int(r['sem_sin_venta'])}sem"
    print(f"  {str(r['default_code'] or ''):>8}  {nm} {r['stock_u']:>6.0f}u  ${r['stock_val']:>11,.0f}  {sv}")
