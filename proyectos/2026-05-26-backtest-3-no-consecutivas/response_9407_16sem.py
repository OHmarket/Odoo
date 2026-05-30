"""
Pull x_pos_week_sku_sale para SKU 9407 ultimas 16 sem:
- qty_sold (real)
- sku_growth_qty_pct vs LY
- categ_growth_qty_pct vs LY
- response_vs_category_pct (= sku_growth - categ_growth)
- has_valid_ly_base
- seasonal_band, has_holiday

Hipotesis: si el dip Mar 9 - Abr 20 fue caida de promo efectiva
(no quiebre), entonces response_vs_category del 9407 deberia
estar muy negativo en esas semanas (la categoria Cervezas
Promocion no cayo tanto), mientras que en May ya estara cerca
de cero o positivo.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 40)

TODAY = date(2026, 5, 27)
WEEKS_BACK = 16


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # Resolver pid
    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', '=', '9407')],
        fields=['id', 'name'],
    )
    pid = prods[0]['id']
    print(f"SKU 9407 -> pid={pid}")

    # Inspect fields del modelo
    fields_map = odoo.fields_get('x_pos_week_sku_sale')
    relevant = [
        'x_studio_team_id', 'x_studio_week_start', 'x_studio_categ_id',
        'x_studio_product_id', 'x_studio_qty_sold', 'x_studio_sales_gross',
        'x_studio_qty_sold_ly', 'x_studio_sku_growth_qty_pct',
        'x_studio_categ_qty_sold', 'x_studio_categ_qty_sold_ly',
        'x_studio_categ_growth_qty_pct', 'x_studio_response_vs_category_pct',
        'x_studio_has_valid_ly_base', 'x_studio_seasonal_band',
        'x_studio_has_holiday', 'x_studio_iso_week',
    ]
    fields_to_read = [f for f in relevant if f in fields_map]
    print(f"Campos disponibles: {len(fields_to_read)}/{len(relevant)}")

    week_now = _iso_monday(TODAY)
    start = week_now - timedelta(weeks=WEEKS_BACK)

    rows = odoo.search_read(
        'x_pos_week_sku_sale',
        domain=[
            ('x_studio_product_id', '=', pid),
            ('x_studio_week_start', '>=', start.strftime('%Y-%m-%d')),
            ('x_studio_week_start', '<', week_now.strftime('%Y-%m-%d')),
        ],
        fields=fields_to_read,
        order='x_studio_week_start',
    )
    print(f"Filas pos_week_sku_sale: {len(rows)}")
    if not rows:
        print("Sin filas - quizas el script v12 no ha corrido todavia")
        return

    df = pd.DataFrame(rows)
    # Limpiar m2o
    for c in df.columns:
        if df[c].apply(lambda v: isinstance(v, (list, tuple))).any():
            df[c] = df[c].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else v)

    # Agregar a nivel SKU x week (suma teams)
    df['x_studio_qty_sold'] = pd.to_numeric(df['x_studio_qty_sold'], errors='coerce')
    df['x_studio_qty_sold_ly'] = pd.to_numeric(df.get('x_studio_qty_sold_ly', 0), errors='coerce')

    agg = df.groupby('x_studio_week_start').agg(
        n_teams=('x_studio_team_id', 'nunique'),
        qty=('x_studio_qty_sold', 'sum'),
        qty_ly=('x_studio_qty_sold_ly', 'sum'),
    ).reset_index()
    agg['sku_growth_pct'] = ((agg['qty'] / agg['qty_ly'] - 1) * 100).round(1)

    # Para categ: tomar de cualquier fila (el dato categ_qty_sold se persiste
    # ya agregado en cada fila; suma cross-team da el agregado)
    # OJO: x_studio_categ_qty_sold es total categoria EN ESE TEAM, no global.
    # Por team x week, valor identico para todos SKUs del team x week.
    # Para agregado global hay que sumar 1 fila por team-week (drop_duplicates).
    if 'x_studio_categ_qty_sold' in df.columns:
        cat_per_team_week = df.drop_duplicates(['x_studio_team_id', 'x_studio_week_start'])[
            ['x_studio_team_id', 'x_studio_week_start',
             'x_studio_categ_qty_sold', 'x_studio_categ_qty_sold_ly']
        ]
        cat_per_team_week['x_studio_categ_qty_sold'] = pd.to_numeric(cat_per_team_week['x_studio_categ_qty_sold'], errors='coerce')
        cat_per_team_week['x_studio_categ_qty_sold_ly'] = pd.to_numeric(cat_per_team_week['x_studio_categ_qty_sold_ly'], errors='coerce')
        cat_agg = cat_per_team_week.groupby('x_studio_week_start').agg(
            cat_qty=('x_studio_categ_qty_sold', 'sum'),
            cat_qty_ly=('x_studio_categ_qty_sold_ly', 'sum'),
        ).reset_index()
        cat_agg['categ_growth_pct'] = ((cat_agg['cat_qty'] / cat_agg['cat_qty_ly'] - 1) * 100).round(1)
        out = agg.merge(cat_agg, on='x_studio_week_start', how='left')
        out['response_pct'] = (out['sku_growth_pct'] - out['categ_growth_pct']).round(1)
    else:
        out = agg
        out['response_pct'] = None

    # Banda estacional y feriado: tomar primero
    meta_cols = [c for c in ['x_studio_seasonal_band', 'x_studio_has_holiday', 'x_studio_iso_week'] if c in df.columns]
    if meta_cols:
        meta = df.groupby('x_studio_week_start')[meta_cols].first().reset_index()
        out = out.merge(meta, on='x_studio_week_start', how='left')

    # Tag semanas backtest
    bt_weeks = {'2026-05-04': 'W18-BT', '2026-05-11': 'W19-BT', '2026-05-18': 'W20-BT'}
    out['tag'] = out['x_studio_week_start'].astype(str).map(lambda w: bt_weeks.get(w, ''))

    print("\n========== 9407 -- ultimas 16 sem (agregado 11 teams) ==========")
    cols = ['x_studio_week_start', 'qty', 'qty_ly', 'sku_growth_pct',
            'cat_qty', 'cat_qty_ly', 'categ_growth_pct', 'response_pct',
            'x_studio_seasonal_band', 'x_studio_has_holiday', 'tag']
    cols = [c for c in cols if c in out.columns]
    print(out[cols].to_string(index=False))

    OUT = Path(__file__).parent / "response_9407_16sem.csv"
    out.to_csv(OUT, index=False, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
