"""
Por que qty_ly = 0 para 9407 en x_pos_week_sku_sale?

Hipotesis a chequear:
1. SKU es lanzamiento <12 meses (no existia en 2025).
2. Mismo SKU bajo otro pid en 2025 (cambio de variant/template).
3. Si existe data POS 2025 para pid=11797 pero el script v12 no la cargo.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 30)


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    pid = 11797

    # 1. Cuando fue creado el product.product?
    prod = odoo.search_read(
        'product.product',
        domain=[('id', '=', pid)],
        fields=['id', 'name', 'default_code', 'create_date', 'product_tmpl_id', 'active'],
    )[0]
    print(f"\n=== product.product pid={pid} ===")
    print(f"  name: {prod['name']}")
    print(f"  default_code: {prod['default_code']}")
    print(f"  create_date: {prod['create_date']}")
    print(f"  template: {prod['product_tmpl_id']}")

    # 2. Hay POS con pid=11797 en 2025?
    print(f"\n=== POS pid={pid} en 2025-01 a 2025-06 ===")
    rows_2025 = odoo.search_read(
        'pos.order.line',
        domain=[
            ('product_id', '=', pid),
            ('order_id.date_order', '>=', '2025-01-01'),
            ('order_id.date_order', '<', '2025-06-01'),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ],
        fields=['qty', 'order_id'],
        limit=5,
    )
    cnt_2025 = odoo.search_count(
        'pos.order.line',
        domain=[
            ('product_id', '=', pid),
            ('order_id.date_order', '>=', '2025-01-01'),
            ('order_id.date_order', '<', '2025-06-01'),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ],
    )
    print(f"  pos.order.line con pid={pid} en 2025-01-06: {cnt_2025:,}")

    # 3. Hay otro product.product con mismo template (variantes)?
    tmpl_id = prod['product_tmpl_id'][0] if isinstance(prod['product_tmpl_id'], (list, tuple)) else prod['product_tmpl_id']
    variants = odoo.search_read(
        'product.product',
        domain=[('product_tmpl_id', '=', tmpl_id)],
        fields=['id', 'default_code', 'name', 'create_date', 'active'],
    )
    print(f"\n=== Variantes del template {tmpl_id} ===")
    for v in variants:
        print(f"  id={v['id']:>6} code={v['default_code']!r:<15} active={v['active']} create={v['create_date']}  name={v['name']}")

    # 4. Hay otro pid con name STELLA ARTOIS 660 (independiente del template)?
    print(f"\n=== Otros products con name STELLA ARTOIS BOTELLA 660 ===")
    same_name = odoo.search_read(
        'product.product',
        domain=[
            '|', '|',
            ('name', 'ilike', 'STELLA ARTOIS BOTELLA 660'),
            ('name', 'ilike', 'STELLA ARTOIS 660'),
            ('default_code', '=', '9407'),
        ],
        fields=['id', 'default_code', 'name', 'create_date', 'active'],
    )
    for v in same_name:
        if v['id'] == pid:
            continue
        print(f"  id={v['id']:>6} code={v['default_code']!r:<15} active={v['active']} create={v['create_date']}  name={v['name']}")
    if len(same_name) <= 1:
        print("  (sin otros matches)")

    # 5. Hay filas en x_pos_week_sku_sale para pid=11797 en 2025?
    print(f"\n=== x_pos_week_sku_sale pid={pid} en 2025 ===")
    cnt_2025_model = odoo.search_count(
        'x_pos_week_sku_sale',
        domain=[
            ('x_studio_product_id', '=', pid),
            ('x_studio_week_start', '>=', '2025-01-01'),
            ('x_studio_week_start', '<', '2025-12-31'),
        ],
    )
    print(f"  filas modelo en 2025: {cnt_2025_model:,}")
    if cnt_2025_model:
        rows_2025_model = odoo.search_read(
            'x_pos_week_sku_sale',
            domain=[
                ('x_studio_product_id', '=', pid),
                ('x_studio_week_start', '>=', '2025-01-01'),
                ('x_studio_week_start', '<', '2025-12-31'),
            ],
            fields=['x_studio_week_start', 'x_studio_team_id', 'x_studio_qty_sold'],
            limit=20,
            order='x_studio_week_start',
        )
        df = pd.DataFrame(rows_2025_model)
        if not df.empty:
            df['team'] = df['x_studio_team_id'].apply(lambda v: v[1] if isinstance(v, (list, tuple)) else v)
            print(df[['x_studio_week_start', 'team', 'x_studio_qty_sold']].head(20).to_string(index=False))

    # 6. min/max week_start en el modelo para este pid
    rows_range = odoo.search_read(
        'x_pos_week_sku_sale',
        domain=[('x_studio_product_id', '=', pid)],
        fields=['x_studio_week_start'],
        order='x_studio_week_start',
    )
    if rows_range:
        weeks = sorted(set(r['x_studio_week_start'] for r in rows_range))
        print(f"\n=== Rango modelo para pid={pid} ===")
        print(f"  min: {weeks[0]}  max: {weeks[-1]}  n_weeks: {len(weeks)}")


if __name__ == "__main__":
    main()
