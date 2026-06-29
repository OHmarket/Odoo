"""
Snapshot de venta DIARIA (pos.order.line) para cervezas — señal del demand sensing.

Mismo pull validado que pos_weekly (snapshot_cache.py) pero bucket DIARIO.
Solo lectura. Modo:
  (default) probe : 1 team, 14 dias, 1 query -> confirma que el groupby por dia
                    funciona y muestra el formato de la clave de fecha.
  --full          : todos los teams, ~3 meses -> guarda pos_daily_cerv.parquet
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
OUT = Path(__file__).parent / 'pos_daily_cerv.parquet'


def cerv_pids():
    prod = pd.read_parquet(HARNESS_CACHE / 'catalog_products.parquet')
    ids = prod[prod['categ_complete_name'].astype(str).str.contains('Cerveza', case=False, na=False)]['id']
    return [int(i) for i in ids]


def _m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def read_day(odoo, pids, d0, d1):
    """Venta del rango [d0, d1) agregada a todas las salas, por product_id.
    Domain con order_id.date_order (dotted en domain SI funciona; en groupby NO)."""
    return odoo.execute(
        'pos.order.line', 'read_group',
        [
            ('order_id.date_order', '>=', d0.strftime('%Y-%m-%d')),
            ('order_id.date_order', '<', d1.strftime('%Y-%m-%d')),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('product_id', 'in', pids),
        ],
        ['qty:sum', 'price_subtotal:sum'],
        ['product_id'],
        lazy=False,
    )


def probe(odoo, pids):
    d1 = date.today()
    d0 = d1 - timedelta(days=1)
    print(f"PROBE 1 dia agregado todas las salas  {d0} -> {d1}  cervezas={len(pids)}")
    grp = read_day(odoo, pids, d0, d1)
    print(f"  productos con venta ese dia: {len(grp)}")
    for g in grp[:8]:
        pn = g.get('product_id')[1] if isinstance(g.get('product_id'), (list, tuple)) else g.get('product_id')
        print(f"    {_m2o_id(g.get('product_id'))}  {str(pn)[:34]:34s}  qty={g.get('qty')}")


def full(odoo, pids, months):
    d1 = date.today()
    d0 = d1 - timedelta(days=months * 31)
    days = []
    d = d0
    while d < d1:
        days.append(d)
        d += timedelta(days=1)
    print(f"FULL  {d0} -> {d1}  dias={len(days)}  cervezas={len(pids)} (agregado todas las salas)")
    rows = []
    for i, day in enumerate(days):
        grp = read_day(odoo, pids, day, day + timedelta(days=1))
        for g in grp:
            pid = _m2o_id(g.get('product_id'))
            if pid is None:
                continue
            rows.append({'product_id': pid, 'day': day,
                         'qty': float(g.get('qty', 0.0) or 0.0),
                         'revenue': float(g.get('price_subtotal', 0.0) or 0.0)})
        if (i + 1) % 15 == 0:
            print(f"  {i+1}/{len(days)} dias  ({len(rows):,} filas)")
    df = pd.DataFrame(rows)
    df.to_parquet(OUT, index=False)
    print(f"\n  filas: {len(df):,}  productos: {df['product_id'].nunique()}  dias: {df['day'].nunique()}")
    print(f"  rango: {df['day'].min()} -> {df['day'].max()}  -> {OUT.name}")


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
