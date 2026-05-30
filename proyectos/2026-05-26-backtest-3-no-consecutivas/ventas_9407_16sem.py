"""
Ventas POS ultimas 16 semanas del SKU 9407 (STELLA ARTOIS 660 CC).
Pivot week_start x team_name.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 30)

WEEKS_BACK = 16
TODAY = date(2026, 5, 27)


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', '=', '9407')],
        fields=['id', 'name'],
    )
    pid = prods[0]['id']
    print(f"SKU 9407 -> pid={pid}  ({prods[0]['name']})")

    week_now = _iso_monday(TODAY)
    start = week_now - timedelta(weeks=WEEKS_BACK)
    print(f"Ventana: {start} -> {week_now} (semana en curso excluida)")

    lines = odoo.search_read(
        'pos.order.line',
        domain=[
            ('product_id', '=', pid),
            ('order_id.date_order', '>=', start.strftime('%Y-%m-%d')),
            ('order_id.date_order', '<', week_now.strftime('%Y-%m-%d')),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ],
        fields=['qty', 'order_id'],
    )
    print(f"  pos.order.line rows: {len(lines):,}")
    if not lines:
        print("  Sin ventas")
        return

    df_lines = pd.DataFrame(lines)
    df_lines['order_id_id'] = df_lines['order_id'].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)

    order_ids = sorted(df_lines['order_id_id'].unique().tolist())
    orders = odoo.search_read(
        'pos.order',
        domain=[('id', 'in', order_ids)],
        fields=['date_order', 'crm_team_id'],
    )
    df_orders = pd.DataFrame(orders)
    df_orders['team'] = df_orders['crm_team_id'].apply(
        lambda x: x[1] if isinstance(x, (list, tuple)) and x else 'SIN_TEAM'
    )
    df_orders['date_order_dt'] = pd.to_datetime(df_orders['date_order'])
    df_orders['week_start'] = df_orders['date_order_dt'].apply(lambda d: _iso_monday(d.date()))

    merged = df_lines.merge(
        df_orders[['id', 'week_start', 'team']],
        left_on='order_id_id', right_on='id', how='left',
    )

    pivot = merged.groupby(['week_start', 'team'])['qty'].sum().unstack(fill_value=0)
    pivot = pivot.sort_index()
    pivot['TOTAL'] = pivot.sum(axis=1)

    # San Jose aparte
    sj_cols = [c for c in pivot.columns if 'San Jos' in str(c)]
    bt_cols = [c for c in pivot.columns if c != 'TOTAL' and c not in sj_cols]
    pivot['TOTAL_ex_SJ'] = pivot[bt_cols].sum(axis=1)

    print("\n========== PIVOT SEMANA x TEAM (16 sem) ==========")
    print(pivot.to_string())

    print("\n========== TOTALES POR SEMANA ==========")
    tot = pivot[['TOTAL_ex_SJ', 'TOTAL']].copy()
    tot.columns = ['ex_San_Jose', 'todos']
    if sj_cols:
        tot['San_Jose'] = pivot[sj_cols].sum(axis=1)
    # Tag para semanas del backtest
    bt_weeks = {date(2026, 5, 4): 'W18-BT', date(2026, 5, 11): 'W19-BT',
                date(2026, 5, 18): 'W20-BT'}
    tot['tag'] = tot.index.map(lambda w: bt_weeks.get(w, ''))
    print(tot.to_string())

    print("\n========== RESUMEN ==========")
    print(f"  Promedio sem ex-SJ (16 sem): {pivot['TOTAL_ex_SJ'].mean():,.0f}")
    print(f"  Mediana sem ex-SJ:           {pivot['TOTAL_ex_SJ'].median():,.0f}")
    print(f"  Min / Max ex-SJ:             {pivot['TOTAL_ex_SJ'].min():,.0f} / {pivot['TOTAL_ex_SJ'].max():,.0f}")
    print(f"  Ultimas 3 sem (W18-W20):     {pivot.loc[date(2026,5,4):date(2026,5,18), 'TOTAL_ex_SJ'].tolist()}")
    print(f"  Promedio 4 sem mas recientes (W17-W20): {pivot['TOTAL_ex_SJ'].tail(4).mean():,.0f}")
    print(f"  Promedio 8 sem mas recientes (W13-W20): {pivot['TOTAL_ex_SJ'].tail(8).mean():,.0f}")

    OUT = Path(__file__).parent / "ventas_9407_16sem.csv"
    pivot.to_csv(OUT, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
