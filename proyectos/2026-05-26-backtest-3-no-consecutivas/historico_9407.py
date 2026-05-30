"""
Pull historico POS del SKU 9407 (Stella 660cc) las ultimas ~20 semanas por team,
y compara con mu_week que el motor genero (x_hm_si_forecast) para ver si hay
nivel reciente nuevo que SMA(6) no captura.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

WEEKS_BACK = 20
TODAY = date(2026, 5, 27)


def _iso_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # 1. Buscar product.product por default_code 9407
    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', '=', '9407')],
        fields=['id', 'name', 'default_code', 'product_tmpl_id', 'categ_id'],
    )
    if not prods:
        # Buscar por nombre
        prods = odoo.search_read(
            'product.product',
            domain=[('name', 'ilike', 'STELLA ARTOIS BOTELLA UNIDAD 660')],
            fields=['id', 'name', 'default_code', 'product_tmpl_id', 'categ_id'],
        )
    print(f"\nProductos encontrados:")
    for p in prods:
        print(f"  id={p['id']} default_code={p.get('default_code')!r} name={p['name']!r}")
    if not prods:
        print("NO ENCONTRADO")
        return
    pids = [p['id'] for p in prods]
    pid_to_name = {p['id']: p['name'] for p in prods}

    # 2. Pull POS lines ultimas 20 semanas (qty por week x team)
    start = _iso_monday(TODAY) - timedelta(weeks=WEEKS_BACK)
    print(f"\nVentana: {start} -> {TODAY}")

    # Search_read directo de pos.order.line + sub-fields via search_read.
    domain = [
        ('product_id', 'in', pids),
        ('order_id.date_order', '>=', start.strftime('%Y-%m-%d')),
        ('order_id.date_order', '<', TODAY.strftime('%Y-%m-%d')),
        ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
    ]
    rows = odoo.search_read(
        'pos.order.line',
        domain=domain,
        fields=['product_id', 'qty', 'order_id'],
    )
    print(f"  pos.order.line rows: {len(rows):,}")
    if not rows:
        print("Sin filas")
        return

    df_lines = pd.DataFrame(rows)
    df_lines['order_id_id'] = df_lines['order_id'].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df_lines['product_id_id'] = df_lines['product_id'].apply(lambda x: x[0] if isinstance(x, (list, tuple)) else x)
    df_lines['product_name'] = df_lines['product_id_id'].map(pid_to_name)

    # Read pos.order para sacar date_order + crm_team_id
    order_ids = sorted(df_lines['order_id_id'].unique().tolist())
    print(f"  pos.order distintos: {len(order_ids):,}")
    orders = odoo.search_read(
        'pos.order',
        domain=[('id', 'in', order_ids)],
        fields=['date_order', 'crm_team_id', 'config_id'],
    )
    df_orders = pd.DataFrame(orders)
    df_orders['team_id_id'] = df_orders['crm_team_id'].apply(lambda x: x[0] if isinstance(x, (list, tuple)) and x else None)
    df_orders['team_name'] = df_orders['crm_team_id'].apply(lambda x: x[1] if isinstance(x, (list, tuple)) and x else None)
    df_orders['config_name'] = df_orders['config_id'].apply(lambda x: x[1] if isinstance(x, (list, tuple)) and x else None)
    df_orders['date_order_dt'] = pd.to_datetime(df_orders['date_order'])
    df_orders['date_only'] = df_orders['date_order_dt'].dt.date
    df_orders['week_start'] = df_orders['date_order_dt'].apply(lambda d: _iso_monday(d.date()))

    merged = df_lines.merge(
        df_orders[['id', 'week_start', 'team_name', 'config_name']],
        left_on='order_id_id', right_on='id', how='left',
    )

    # 3. Pivot: week_start x team_name -> sum(qty)
    print("\n========= POS qty por semana x team (TODOS productos 9407 match) =========")
    pivot = merged.groupby(['week_start', 'team_name'])['qty'].sum().unstack(fill_value=0)
    pivot = pivot.sort_index()
    pivot['TOTAL'] = pivot.sum(axis=1)
    print(pivot.to_string())

    # 4. Solo para los teams del backtest (Ventas X)
    bt_teams = [
        'Coñaripe', 'Futrono', 'Lautaro', 'Los Lagos', 'Malalhue',
        'Mehuin Express', 'Nueva Imperial', 'Paillaco',
        'Panguipulli 645', 'Panguipulli 763', 'Panguipulli 790',
    ]
    print("\n========= TOTAL (11 teams ex-San José) por semana =========")
    bt_cols = [c for c in pivot.columns if any(t in str(c) for t in bt_teams)]
    if bt_cols:
        total_bt = pivot[bt_cols].sum(axis=1)
        for wk, v in total_bt.items():
            tag = ""
            if wk in (date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)):
                tag = "  <-- BACKTEST"
            print(f"  {wk}: {v:>8.0f}{tag}")

    OUT = Path(__file__).parent / "historico_9407.csv"
    pivot.to_csv(OUT, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
