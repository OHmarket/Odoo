# -*- coding: utf-8 -*-
"""
Listado por SKU para la decision DSD vs 790:
  demanda mensual promedio, MOQ (caja), cuanto dura la caja, costo, sugerencia.

Un renglon por SKU (template), agregando sus posiciones de sala.
Excluye hijos phantom (no compran) y CD/Web. Read-only.
"""
from shared.odoo_xmlrpc import OdooReader
import pandas as pd

WK_PER_MONTH = 4.345
DEMAND_FLOOR = 1.0 / WK_PER_MONTH
CD_TEAM, WEB_TEAM = 26, 2
M = 'x_analisis_de_stock'
FIELDS = ['x_studio_team_id', 'x_studio_product_id', 'x_studio_categ_id',
          'x_studio_abcxyz', 'x_studio_mu_week', 'x_studio_demanda_semanal',
          'x_studio_moq', 'x_studio_purchase_price_cash_unit',
          'x_studio_decision_reason']

o = OdooReader()
df = pd.DataFrame(o.search_read(M, [], fields=FIELDS, order='id'))
m2o = lambda v: v[0] if isinstance(v, list) and v else v
df['team_id'] = df['x_studio_team_id'].map(m2o)
df['pid'] = df['x_studio_product_id'].map(m2o)
for c in ['x_studio_mu_week', 'x_studio_demanda_semanal', 'x_studio_moq',
          'x_studio_purchase_price_cash_unit']:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

dr = df['x_studio_decision_reason'].fillna('')
df['phantom_child'] = dr.str.contains('phantom_child|blocked_child', case=False)

# salas reales con demanda
s = df[(~df['team_id'].isin([CD_TEAM, WEB_TEAM])) & (~df['phantom_child'])].copy()
s['runrate'] = s['x_studio_mu_week'].where(s['x_studio_mu_week'] > 0, s['x_studio_demanda_semanal'])
s = s[s['runrate'] > 0].copy()
s['dem_mes'] = s['runrate'] * WK_PER_MONTH

# agregacion por SKU
g = s.groupby('pid').agg(
    abcxyz=('x_studio_abcxyz', lambda x: x.mode().iat[0] if len(x.mode()) else ''),
    n_salas=('team_id', 'nunique'),
    dem_mes_red=('dem_mes', 'sum'),
    dem_mes_sala_prom=('dem_mes', 'mean'),
    moq=('x_studio_moq', 'max'),
    costo_unit=('x_studio_purchase_price_cash_unit', 'median'),
).reset_index()

g['moq'] = g['moq'].clip(lower=1.0)
g['costo_caja'] = g['moq'] * g['costo_unit']
# cuanto dura una caja (meses)
g['meses_caja_sala'] = g['moq'] / g['dem_mes_sala_prom'].clip(lower=DEMAND_FLOOR)
g['meses_caja_red'] = g['moq'] / g['dem_mes_red'].clip(lower=DEMAND_FLOOR)

def sugerencia(r):
    # la caja fisica vive en UNA sala -> manda meses_caja_sala
    if r['meses_caja_red'] > 12.0:
        return 'REVISAR_DELIST'      # ni la red entera gira una caja en 1 anio
    if r['meses_caja_sala'] <= 1.0:
        return 'DSD_SALA'            # una caja rota en <=1 mes en la sala
    if r['meses_caja_sala'] <= 2.0:
        return 'DSD_SI_PROVEEDOR'    # marginal: DSD si entrega chico, sino 790
    return '790'                     # consolidar en mini-CD

g['sugerencia'] = g.apply(sugerencia, axis=1)

# nombres del catalogo
ids = g['pid'].astype(int).tolist()
meta = {}
for i in range(0, len(ids), 500):
    for r in o.search_read('product.template', [('id', 'in', ids[i:i+500])],
                           fields=['name', 'default_code', 'categ_id']):
        meta[r['id']] = (r.get('default_code') or '', r.get('name') or '',
                         (r['categ_id'][1] if r.get('categ_id') else ''))
g['codigo'] = g['pid'].map(lambda p: meta.get(int(p), ('', '', ''))[0])
g['nombre'] = g['pid'].map(lambda p: meta.get(int(p), ('', '', ''))[1])
g['categoria'] = g['pid'].map(lambda p: meta.get(int(p), ('', '', ''))[2])

cols = ['codigo', 'nombre', 'categoria', 'abcxyz', 'n_salas',
        'dem_mes_sala_prom', 'dem_mes_red', 'moq', 'meses_caja_sala',
        'meses_caja_red', 'costo_unit', 'costo_caja', 'sugerencia']
out = g[cols].sort_values(['sugerencia', 'meses_caja_red'], ascending=[True, False])

for c in ['dem_mes_sala_prom', 'dem_mes_red', 'meses_caja_sala', 'meses_caja_red']:
    out[c] = out[c].round(2)
for c in ['costo_unit', 'costo_caja']:
    out[c] = out[c].round(0)

path = 'proyectos/2026-06-23-reestructuracion-dsd/resultados/listado_sku_dsd_790.csv'
out.to_csv(path, index=False, sep=';', decimal=',', encoding='utf-8-sig')

print('SKU en listado:', len(out))
print()
print('=== distribucion por sugerencia ===')
r = g.groupby('sugerencia').agg(skus=('pid', 'size'), caja_cash=('costo_caja', 'sum'))
pd.options.display.float_format = lambda v: f"{v:,.0f}"
print(r.sort_values('skus', ascending=False).to_string())
print()
print('=== muestra: top 15 por meses_caja_red (los mas lentos) ===')
show = ['codigo', 'nombre', 'abcxyz', 'n_salas', 'dem_mes_red', 'moq',
        'meses_caja_sala', 'meses_caja_red', 'costo_caja', 'sugerencia']
print(out[show].head(15).to_string(index=False))
print()
print('=== muestra: 10 DSD_SALA (rapidos) ===')
print(out[out['sugerencia'] == 'DSD_SALA'][show].sort_values('dem_mes_red', ascending=False).head(10).to_string(index=False))
print()
print('CSV:', path)
