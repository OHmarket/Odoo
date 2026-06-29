"""
Snapshot de quiebre diario (x_stock_balance_daily) para cervezas — CONTROL del
demand sensing. Sirve para no confundir colapso-por-precio con colapso-por-quiebre.

Campos (validados via fields_get): x_studio_product_id, x_studio_team_id,
x_studio_date, x_studio_stockout (bool), x_studio_qty_balance (float).

  probe  : 1 dia, mide tasa de quiebre y valida el pull.
  --full : rango ~3m, trae filas stockout=True -> pos_stockout_cerv.parquet
"""
import sys
import argparse
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared'))
from odoo_xmlrpc import OdooReader  # noqa: E402

HARNESS_CACHE = ROOT / 'proyectos' / '2026-05-27-harness-local' / 'cache'
OUT = Path(__file__).parent / 'pos_stockout_cerv.parquet'
MODEL = 'x_stock_balance_daily'


def cerv_pids():
    prod = pd.read_parquet(HARNESS_CACHE / 'catalog_products.parquet')
    ids = prod[prod['categ_complete_name'].astype(str).str.contains('Cerveza', case=False, na=False)]['id']
    return [int(i) for i in ids]


def _m2o(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def probe(odoo, pids):
    d = date.today() - timedelta(days=2)
    rows = odoo.search_read(
        MODEL,
        [('x_studio_product_id', 'in', pids), ('x_studio_date', '=', d.strftime('%Y-%m-%d'))],
        ['x_studio_product_id', 'x_studio_team_id', 'x_studio_stockout', 'x_studio_qty_balance'])
    print(f"PROBE {MODEL}  dia={d}  cervezas={len(pids)}")
    print(f"  filas (SKU x sala) ese dia: {len(rows)}")
    if rows:
        so = sum(1 for r in rows if r.get('x_studio_stockout'))
        print(f"  en stockout=True: {so}  ({so/len(rows)*100:.0f}%)")
        for r in rows[:6]:
            print(f"    pid={_m2o(r.get('x_studio_product_id'))} team={_m2o(r.get('x_studio_team_id'))} "
                  f"stockout={r.get('x_studio_stockout')} bal={r.get('x_studio_qty_balance')}")


def full(odoo, pids, months):
    d1 = date.today()
    d0 = d1 - timedelta(days=months * 31)
    print(f"FULL stockout=True  {d0} -> {d1}  cervezas={len(pids)}")
    rows, off, page = [], 0, 5000
    while True:
        batch = odoo.search_read(
            MODEL,
            [('x_studio_product_id', 'in', pids),
             ('x_studio_date', '>=', d0.strftime('%Y-%m-%d')),
             ('x_studio_date', '<=', d1.strftime('%Y-%m-%d')),
             ('x_studio_stockout', '=', True)],
            ['x_studio_product_id', 'x_studio_team_id', 'x_studio_date'],
            offset=off, limit=page)
        if not batch:
            break
        rows.extend(batch)
        off += page
        print(f"  {len(rows):,} filas stockout...")
        if len(batch) < page:
            break
    df = pd.DataFrame([{'product_id': _m2o(r['x_studio_product_id']),
                        'team_id': _m2o(r.get('x_studio_team_id')),
                        'day': r['x_studio_date']} for r in rows])
    if len(df):
        df['day'] = pd.to_datetime(df['day']).dt.date
    df.to_parquet(OUT, index=False)
    print(f"\n  filas stockout: {len(df):,}  SKU: {df['product_id'].nunique() if len(df) else 0}  -> {OUT.name}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true')
    ap.add_argument('--months', type=int, default=3)
    args = ap.parse_args()
    odoo = OdooReader()
    pids = cerv_pids()
    if args.full:
        full(odoo, pids, args.months)
    else:
        probe(odoo, pids)
