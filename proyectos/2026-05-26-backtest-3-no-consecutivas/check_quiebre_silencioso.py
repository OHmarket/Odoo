"""
Confirma si PAPAS LAYS 330G y PALL MALL SUNSET XL 20 son quiebre
"silencioso" (no llegaron a las salas, no hay fila en x_stock_balance_daily).

Para cada SKU:
1. Ventas POS 16 sem por semana (ver si venian vendiendo antes).
2. Filas en x_stock_balance_daily en las 3 sem backtest.
3. Movimiento stock.move ultimos 60 dias (compras / recepciones a bodega central).
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SKUS = ['300064531', '10091095']
TODAY = date(2026, 5, 27)
WEEKS_BACK = 16
BT_WEEKS = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 60)


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}\n")

    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', 'in', SKUS)],
        fields=['id', 'default_code', 'name', 'active', 'sale_ok', 'create_date'],
    )
    print("=== Productos ===")
    for p in prods:
        print(f"  pid={p['id']:>6} code={p['default_code']!r:<12} active={p['active']} sale_ok={p['sale_ok']}")
        print(f"    name={p['name']!r}  create={p['create_date']}")
    pid_to_code = {p['id']: p['default_code'] for p in prods}
    pids = list(pid_to_code.keys())

    # ============================================================
    # 1. Ventas POS 16 sem
    # ============================================================
    week_now = _iso_monday(TODAY)
    start = week_now - timedelta(weeks=WEEKS_BACK)
    print(f"\n=== Ventas POS {start} -> {week_now} (ex-SJ) ===")

    lines = odoo.search_read(
        'pos.order.line',
        domain=[
            ('product_id', 'in', pids),
            ('order_id.date_order', '>=', start.strftime('%Y-%m-%d')),
            ('order_id.date_order', '<', week_now.strftime('%Y-%m-%d')),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ],
        fields=['qty', 'product_id', 'order_id'],
    )
    print(f"  pos.order.line rows: {len(lines):,}")

    if lines:
        df_l = pd.DataFrame(lines)
        df_l['pid'] = df_l['product_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
        df_l['order_id_id'] = df_l['order_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
        order_ids = sorted(df_l['order_id_id'].unique().tolist())
        orders_all = []
        for i in range(0, len(order_ids), 5000):
            rows = odoo.search_read(
                'pos.order',
                domain=[('id', 'in', order_ids[i:i+5000])],
                fields=['date_order', 'crm_team_id'],
            )
            orders_all.extend(rows)
        df_o = pd.DataFrame(orders_all)
        df_o['team'] = df_o['crm_team_id'].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and v else '')
        df_o['team_id'] = df_o['crm_team_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) and v else None)
        df_o['week_start'] = pd.to_datetime(df_o['date_order']).apply(lambda d: _iso_monday(d.date()))
        df_l = df_l.merge(df_o[['id', 'team_id', 'team', 'week_start']], left_on='order_id_id', right_on='id')
        df_l = df_l[df_l['team_id'] != 11]  # ex-SJ
        df_l['code'] = df_l['pid'].map(pid_to_code)

        for code in SKUS:
            sub = df_l[df_l['code'] == code]
            if sub.empty:
                print(f"\n  [{code}] SIN VENTAS POS en 16 sem")
                continue
            pivot = sub.groupby('week_start')['qty'].sum().reindex(
                pd.date_range(start, week_now - timedelta(days=1), freq='7D').date,
                fill_value=0,
            )
            print(f"\n  [{code}] ventas semanales:")
            for w, q in pivot.items():
                tag = '  <-- BT' if w in BT_WEEKS else ''
                print(f"    {w}: {q:>5,.0f}{tag}")
    else:
        print("  *** SIN ventas POS para estos SKUs ***")

    # ============================================================
    # 2. Filas en x_stock_balance_daily en backtest
    # ============================================================
    print(f"\n=== x_stock_balance_daily en sem backtest ===")
    rows_b = odoo.search_read(
        'x_stock_balance_daily',
        domain=[
            ('x_studio_product_id', 'in', pids),
            ('x_studio_date', '>=', min(BT_WEEKS).strftime('%Y-%m-%d')),
            ('x_studio_date', '<=', (max(BT_WEEKS) + timedelta(days=6)).strftime('%Y-%m-%d')),
        ],
        fields=['x_studio_product_id', 'x_studio_team_id', 'x_studio_date',
                'x_studio_qty_balance', 'x_studio_stockout', 'x_studio_stockout_partial'],
        order='x_studio_product_id, x_studio_date',
    )
    print(f"  Filas: {len(rows_b)}")
    if rows_b:
        for r in rows_b:
            pid = r['x_studio_product_id'][0] if isinstance(r['x_studio_product_id'], (list, tuple)) else r['x_studio_product_id']
            team = r['x_studio_team_id'][1] if isinstance(r['x_studio_team_id'], (list, tuple)) else ''
            print(f"  [{pid_to_code.get(pid)}] {r['x_studio_date']} team={team} balance={r['x_studio_qty_balance']:>5} stockout={r['x_studio_stockout']} partial={r['x_studio_stockout_partial']}")
    else:
        print("  *** SIN filas en x_stock_balance_daily ***")
        print("  Eso significa: nunca se registro evento de stockout para estos SKUs en las 3 sem.")
        print("  Si tampoco hay ventas POS = QUIEBRE SILENCIOSO (no llego a salas).")

    # ============================================================
    # 3. Movimiento stock.move ultimos 90 dias
    # ============================================================
    print(f"\n=== stock.move ultimos 90 dias (entradas a bodega) ===")
    start_90 = TODAY - timedelta(days=90)
    moves = odoo.search_read(
        'stock.move',
        domain=[
            ('product_id', 'in', pids),
            ('date', '>=', start_90.strftime('%Y-%m-%d')),
            ('state', '=', 'done'),
        ],
        fields=['product_id', 'date', 'product_qty', 'location_id', 'location_dest_id', 'reference'],
        order='date desc',
        limit=50,
    )
    print(f"  Movimientos (done) ultimos 90d: {len(moves)}")
    if moves:
        for m in moves[:30]:
            pid = m['product_id'][0] if isinstance(m['product_id'], (list, tuple)) else m['product_id']
            loc_src = m['location_id'][1] if isinstance(m['location_id'], (list, tuple)) else ''
            loc_dst = m['location_dest_id'][1] if isinstance(m['location_dest_id'], (list, tuple)) else ''
            print(f"  [{pid_to_code.get(pid)}] {m['date'][:10]} qty={m['product_qty']:>6.0f} ref={m.get('reference','')[:30]:<30} {loc_src[:25]:<25} -> {loc_dst[:25]}")
    else:
        print("  *** SIN movimientos done en 90 dias ***")
        print("  Confirma quiebre upstream: no llego stock ni a bodega central.")


if __name__ == "__main__":
    main()
