# -*- coding: utf-8 -*-
"""
ANALISIS SERIO cola larga - read-only. Incorpora todos los antecedentes:
 - grano SKU x sala
 - excluye combos (type='combo') y kits phantom del stock (stock fantasma)
 - guard de valor list_price<=20k para el autopilot
 - separa servicio vs caja honestamente
"""
import pandas as pd, numpy as np
from shared.odoo_xmlrpc import OdooReader
o = OdooReader()
R = 'proyectos/2026-06-22-cola-larga-minmax/resultados/'

# ---------- demanda ----------
pw = pd.read_parquet('proyectos/2026-05-27-harness-local/cache/pos_weekly.parquet')
pw['week_start'] = pd.to_datetime(pw['week_start']); maxw = pw['week_start'].max()
ppall = pd.DataFrame(o.search_read('product.product',
        [['id', 'in', sorted(pw.product_id.unique().tolist())]], ['id', 'product_tmpl_id']))
pw['tmpl'] = pw['product_id'].map(dict(zip(ppall.id, ppall['product_tmpl_id'].apply(lambda x: x[0] if x else None))))
r13 = pw[pw.week_start > maxw - pd.Timedelta(weeks=13)]
mw = r13.week_start.nunique()
dem = r13.groupby(['team_id', 'tmpl'])['qty_sold'].sum().reset_index()
dem['u_mes'] = dem['qty_sold'] / (mw / 4.345)

# ---------- stock ----------
st = pd.DataFrame(o.search_read('x_analisis_de_stock', [],
     ['x_studio_team_id', 'x_studio_product_id', 'x_studio_stock_real', 'x_studio_stock_value_cash_physical']))
st['team_id'] = st['x_studio_team_id'].apply(lambda x: x[0] if x else None)
st['tmpl'] = st['x_studio_product_id'].apply(lambda x: x[0] if x else None)
st = st.dropna(subset=['team_id', 'tmpl'])
st['team_id'] = st.team_id.astype(int); st['tmpl'] = st.tmpl.astype(int)
st = st.rename(columns={'x_studio_stock_real': 'stock_u', 'x_studio_stock_value_cash_physical': 'stock_val'})

# ---------- atributos template ----------
tmpls = sorted(st['tmpl'].unique().tolist())
tp = pd.DataFrame(o.search_read('product.template', [['id', 'in', tmpls]],
     ['id', 'type', 'purchase_ok', 'active', 'list_price']))
attr = tp.set_index('id')

# ---------- kits phantom ----------
bom = pd.DataFrame(o.search_read('mrp.bom', [['type', '=', 'phantom']], ['product_tmpl_id']))
kit_tmpls = set(bom['product_tmpl_id'].apply(lambda x: x[0] if x else None).dropna().astype(int))

st['type'] = st['tmpl'].map(attr['type'])
st['es_kit'] = st['tmpl'].isin(kit_tmpls)
st['es_combo'] = st['type'] == 'combo'

# ============ PARTE 1: higiene de stock ============
raw = st['stock_val'].sum()
phantom = st[st['es_kit']]['stock_val'].sum()
combo_v = st[st['es_combo'] & ~st['es_kit']]['stock_val'].sum()
clean = st[~st['es_kit'] & ~st['es_combo']]
print('=' * 60)
print('PARTE 1 - HIGIENE DE STOCK PARADO')
print('=' * 60)
print(f'  stock_val RAW (x_analisis_de_stock):     ${raw:,.0f}')
print(f'  - kits phantom (stock fantasma):         ${phantom:,.0f}  ({100*phantom/raw:.1f}%)')
print(f'  - combos:                                ${combo_v:,.0f}')
print(f'  = stock parado REAL (SKU fisico):        ${clean.stock_val.sum():,.0f}')
print(f'    filas reales: {len(clean)} SKUxsala')

# ============ PARTE 2: clasificacion demanda (base limpia) ============
m = clean.merge(dem[['team_id', 'tmpl', 'u_mes']], on=['team_id', 'tmpl'], how='left')
m['u_mes'] = m['u_mes'].fillna(0.0)
m['list_price'] = m['tmpl'].map(attr['list_price'])
m['purchase_ok'] = m['tmpl'].map(attr['purchase_ok'])
GUARD = 20000
m['regimen'] = 'normal'
m.loc[(m.u_mes > 0) & (m.u_mes <= 4) & (m.list_price <= GUARD), 'regimen'] = 'min_max'
m.loc[(m.u_mes == 0), 'regimen'] = 'sin_demanda'
print()
print('=' * 60)
print('PARTE 2 - CLASIFICACION (base fisica limpia)')
print('=' * 60)
g = m.groupby('regimen').agg(pares=('tmpl', 'size'), stock_val=('stock_val', 'sum'),
                             en_cero=('stock_u', lambda s: int((s <= 0).sum()))).reset_index()
for _, x in g.iterrows():
    print(f"  {x['regimen']:>12}: {x['pares']:>6} pares | ${x['stock_val']:>13,.0f} parado | {x['en_cero']} en cero")

# ============ PARTE 3: efecto min/max honesto ============
mm = m[m.regimen == 'min_max'].copy()
u = mm.u_mes.values; oh = mm.stock_u.values
uc = np.where(oh > 0, mm.stock_val.values / np.maximum(oh, 1e-9),
              mm.list_price.values / 1.19 * (1 - 0.244))
s = np.maximum(np.ceil(u * 1.5), 1); S = np.maximum(np.ceil(u * 3.0), 2)
libera = (np.maximum(oh - S, 0) * uc).sum()
invierte = (np.maximum(s - oh, 0) * uc).sum()
print()
print('=' * 60)
print('PARTE 3 - EFECTO POLITICA min/max (s=1.5m, S=3m, pisos)')
print('=' * 60)
print(f'  pares en regimen: {len(mm)} | stock hoy ${mm.stock_val.sum():,.0f}')
print(f'  LIBERA (sobre S): ${libera:,.0f}  en {int((np.maximum(oh-S,0)>0).sum())} pares')
print(f'  INVIERTE (bajo s):${invierte:,.0f}  en {int((np.maximum(s-oh,0)>0).sum())} pares')
print(f'  NETO caja: ${libera-invierte:+,.0f}')
print(f'  >>> premio = OPERACIONAL: sacar {len(mm)} pares del forecast semanal')

# ============ PARTE 4: descomponer el bucket sin_demanda (donde esta la plata) ============
# 52 sem por (team,tmpl) y por tmpl-en-cualquier-sala
r52 = pw[pw.week_start > maxw - pd.Timedelta(weeks=52)]
u52_pair = r52.groupby(['team_id', 'tmpl'])['qty_sold'].sum()
u52_tmpl = r52.groupby('tmpl')['qty_sold'].sum()
vivo_tmpl = set(u52_tmpl[u52_tmpl > 0].index)

sd = m[m.regimen == 'sin_demanda'].copy()
sd['u52_pair'] = sd.set_index(['team_id', 'tmpl']).index.map(u52_pair).fillna(0.0)
sd['vivo_otra_sala'] = sd['tmpl'].isin(vivo_tmpl)

# buckets
def clasif(row):
    if row['u52_pair'] > 0:
        return 'A_intermitente'           # vende lento (0 en 13s, >0 en 52s aqui)
    if row['vivo_otra_sala']:
        return 'B_mal_ubicado'            # muerto aqui, vivo en otra sala -> transferir
    if row['purchase_ok'] == False:
        return 'C_descontinuado_drena'    # ya sin compra, se vacia solo
    return 'D_muerto_real'                # 0 en 52s en todas las salas, aun comprable
sd['bucket'] = sd.apply(clasif, axis=1)
print()
print('=' * 60)
print(f'PARTE 4 - DESCOMPOSICION sin_demanda (${sd.stock_val.sum():,.0f})')
print('=' * 60)
gb = sd.groupby('bucket').agg(pares=('tmpl', 'size'), stock_val=('stock_val', 'sum'),
                              con_stock=('stock_u', lambda s: int((s > 0).sum()))).reset_index().sort_values('stock_val', ascending=False)
acc = {'A_intermitente': 'mantener / cobertura larga',
       'B_mal_ubicado': 'TRANSFERIR a sala que vende',
       'C_descontinuado_drena': 'dejar drenar (ok)',
       'D_muerto_real': 'LIQUIDAR + descatalogar'}
for _, x in gb.iterrows():
    print(f"  {x['bucket']:>22}: {x['pares']:>5} pares | ${x['stock_val']:>13,.0f} | {acc[x['bucket']]}")

m.drop(columns=['x_studio_team_id', 'x_studio_product_id'], errors='ignore').to_parquet(R + 'base_limpia.parquet')
sd.drop(columns=['x_studio_team_id', 'x_studio_product_id'], errors='ignore').to_parquet(R + 'sin_demanda_buckets.parquet')
print('\nguardado -> base_limpia.parquet, sin_demanda_buckets.parquet')
