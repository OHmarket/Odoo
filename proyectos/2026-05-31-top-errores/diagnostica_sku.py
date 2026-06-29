"""
Diagnostica un SKU: serie de venta + correccion de precio/promo.
Uso:  python diagnostica_sku.py <default_code>
Lee del cache local del harness (no toca el sistema) + 1 query API acotada.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]          # C:\Users\sanhu\Odoo
sys.path.insert(0, str(ROOT / 'shared'))
CACHE = ROOT / 'proyectos' / '2026-05-27-harness-local' / 'cache'


def main():
    code = sys.argv[1]
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    codecol = next((c for c in ['default_code', 'code', 'x_studio_codigo'] if c in prod.columns), None)
    namecol = next((c for c in ['display_name', 'name', 'complete_name'] if c in prod.columns), None)
    p = prod[prod[codecol].astype(str) == str(code)]
    if not len(p):
        print(f'{code}: no encontrado en cache. cols={prod.columns.tolist()}')
        return
    pid = int(p.iloc[0]['id'])
    name = str(p.iloc[0][namecol]) if namecol else ''
    print(f'{code} = {name[:50]}  (product_id {pid})')

    pos = pd.read_parquet(CACHE / 'pos_weekly.parquet')
    s = pos[pos['product_id'] == pid].groupby('week_start')['qty_sold'].sum().reset_index().sort_values('week_start')
    print('\nSERIE venta total (todas salas) ult 16 sem:')
    print(s.tail(16).to_string(index=False))

    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    b = pc[pc['product_id'] == pid]
    print(f'\nCORRECCION PRECIO (cache 27-05): {len(b)} filas')
    if len(b):
        cols = ['x_studio_target_week_start', 'x_studio_factor_corr', 'x_studio_tipo_alerta',
                'x_studio_razon', 'x_studio_sub_cat', 'x_studio_var_pct']
        cols = [c for c in cols if c in b.columns]
        print(b[cols].to_string(index=False))

    try:
        from odoo_xmlrpc import OdooReader
        odoo = OdooReader()
        rows = odoo.search_read('x_price_coreccion', domain=[('x_studio_product_id', '=', pid)],
                                fields=['x_studio_target_week_start', 'x_studio_factor_corr',
                                        'x_studio_tipo_alerta', 'x_studio_razon'], limit=10)
        print(f'\nCORRECCION PRECIO (API fresco): {len(rows)}')
        for r in rows:
            print('  ', {k: v for k, v in r.items() if k != 'id'})
    except Exception as e:
        print(f'\nAPI no disponible: {e}')


if __name__ == '__main__':
    main()
