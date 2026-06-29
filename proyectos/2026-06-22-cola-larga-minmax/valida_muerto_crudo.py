# -*- coding: utf-8 -*-
"""
Tercera validacion: el bucket D_muerto_real ($20M) sale de pos_weekly (cache
Studio). Verificar contra pos.order.line CRUDO si esos templates realmente
nunca vendieron en 52 sem. Si vendieron -> el "muerto" es artefacto del cache.
"""
import pandas as pd, datetime
from shared.odoo_xmlrpc import OdooReader
o = OdooReader()

sd = pd.read_parquet('proyectos/2026-06-22-cola-larga-minmax/resultados/sin_demanda_buckets.parquet')
D = sd[sd['bucket'] == 'D_muerto_real']
tmpls = sorted(D['tmpl'].astype(int).unique().tolist())
print(f'D_muerto_real: {len(D)} pares, {len(tmpls)} templates unicos, ${D.stock_val.sum():,.0f}')

# variantes de esos templates
pv = pd.DataFrame(o.search_read('product.product', [['product_tmpl_id', 'in', tmpls]],
                  ['id', 'product_tmpl_id']))
pv['tmpl'] = pv['product_tmpl_id'].apply(lambda x: x[0])
var_ids = pv['id'].tolist()
v2t = dict(zip(pv['id'], pv['tmpl']))
print(f'variantes a chequear: {len(var_ids)}')

# ventas CRUDAS ult 52 sem por product_id (read_group, barato)
d52 = (datetime.date.today() - datetime.timedelta(weeks=52)).isoformat()
rg = o.execute('pos.order.line', 'read_group',
               [['product_id', 'in', var_ids], ['order_id.date_order', '>=', d52]],
               ['qty:sum'], ['product_id'])
sold = {}
for r in rg:
    pid = r['product_id'][0] if r['product_id'] else None
    sold[v2t.get(pid)] = sold.get(v2t.get(pid), 0) + (r.get('qty') or 0)

D2 = D.copy()
D2['qty_crudo_52s'] = D2['tmpl'].astype(int).map(lambda t: sold.get(t, 0.0))
vendio = D2[D2['qty_crudo_52s'] > 0]
nada = D2[D2['qty_crudo_52s'] <= 0]
print()
print('=== RESULTADO validacion cruda ===')
print(f'  SI vendieron en pos.order.line crudo (cache lo perdio): '
      f'{len(vendio)} pares | ${vendio.stock_val.sum():,.0f}')
print(f'  realmente 0 en crudo (muerto real confirmado):          '
      f'{len(nada)} pares | ${nada.stock_val.sum():,.0f}')
print()
print(f'  templates que vendieron pero el cache marco muertos: '
      f'{vendio.tmpl.nunique()} / {len(tmpls)}')
