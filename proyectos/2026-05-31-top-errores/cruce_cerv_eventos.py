"""
Cruza los top SKU de cervezas (error, del backtest server 30-05) con los eventos
de precio FRESCOS de x_price_coreccion (via API). Cuantifica cuanto del error de
cervezas es atacable por canibalizacion/precio.
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared'))
from odoo_xmlrpc import OdooReader

CSV = ROOT / '02_forecast' / 'backtest-data-raw' / 'OH Forecast Backtest (x_forecast_backtest) 30-05.csv'


def main():
    df = pd.read_csv(CSV, encoding='latin-1')
    for c in ['abs_error_qty', 'real_qty', 'forecast_qty']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    cerv = df[df['categ_id'].astype(str).str.contains('Cerveza', case=False, na=False)]
    AE = cerv['abs_error_qty'].sum()
    g = cerv.groupby('product_id').agg(ae=('abs_error_qty', 'sum'), real=('real_qty', 'sum'),
                                       fcst=('forecast_qty', 'sum')).reset_index()
    g = g.sort_values('ae', ascending=False).head(20).reset_index(drop=True)

    def code(s):
        m = re.match(r'\[([^\]]+)\]', str(s))
        return m.group(1) if m else None
    g['code'] = g['product_id'].apply(code)

    odoo = OdooReader()
    codes = [c for c in g['code'] if c]
    prods = odoo.search_read('product.product', [('default_code', 'in', codes)], ['default_code'])
    code2id = {str(p['default_code']): p['id'] for p in prods}
    g['pid'] = g['code'].map(code2id)

    ids = [int(i) for i in g['pid'].dropna().unique()]
    evs = odoo.search_read('x_price_coreccion', [('x_studio_product_id', 'in', ids)],
                           ['x_studio_product_id', 'x_studio_var_pct', 'x_studio_factor_corr',
                            'x_studio_tipo_alerta'])
    ev = {}
    for e in evs:
        pv = e['x_studio_product_id']
        pid = pv[0] if isinstance(pv, (list, tuple)) else pv
        ev[int(pid)] = e

    print('TOP 20 cervezas x evento de precio (FRESCO via API)')
    print(f"  {'code':<10}{'dir':>6}{'%err':>6}  evento")
    err_evt = 0.0
    n_evt = 0
    for _, r in g.iterrows():
        pid = int(r['pid']) if pd.notna(r['pid']) else None
        e = ev.get(pid)
        d = 'SOBRE' if r['fcst'] > r['real'] else 'SUB'
        if e:
            n_evt += 1
            err_evt += r['ae']
            vp = (e.get('x_studio_var_pct') or 0) * 100
            f = e.get('x_studio_factor_corr')
            t = e.get('x_studio_tipo_alerta')
            info = f"var={vp:+.0f}% factor={f} {t}"
        else:
            info = '—'
        print(f"  {str(r['code']):<10}{d:>6}{r['ae'] / AE * 100:>5.1f}%  {info}")

    print()
    print(f"De los top 20: {n_evt}/20 con evento de precio")
    print(f"Error con evento: {err_evt / AE * 100:.0f}% del error total de cervezas")


if __name__ == '__main__':
    main()
