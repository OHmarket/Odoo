"""
Cruza ventas POS vs balance diario stock (x_stock_balance_daily) para los
6 SKUs del Patron A (chicles + bombones) que mostraron 4-5 sem en 0.

Hipotesis: los ceros en POS fueron quiebres reales de stock, no caida
de demanda. Para confirmar, balance_avg de esas semanas debe ser ~0
en la mayoria de las salas.

Tabla final: SKU x semana con:
  - qty_venta (POS, agregado teams)
  - balance_avg (stock promedio fin de dia, agregado teams)
  - dias_stockout (dias en la semana con balance<=0, agregado teams)
  - salas_stockout_pct (% de salas con balance<=0 esa semana)
  - lectura: VENTA_OK / QUIEBRE / DEMANDA_BAJA
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SKUS = ['5115316', '5115317', '5115315', '5115322', '5151151', '5151153']
TODAY = date(2026, 5, 27)
WEEKS_BACK = 16

# Equivalente a memoria pos.config.warehouse_id mal poblado:
TEAM_WAREHOUSE_MAP = {
    5: 1, 6: 4, 7: 2, 8: 3, 9: 16, 10: 8, 11: 5, 12: 9,
    13: 10, 16: 12, 17: 14, 18: 13,
}
N_SALAS_TOTAL = len([k for k in TEAM_WAREHOUSE_MAP.keys() if k != 11])  # ex-San Jose

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.width", 400)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_colwidth", 50)


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # ------------------------------------------------------------
    # 1. Resolver pids
    # ------------------------------------------------------------
    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', 'in', SKUS)],
        fields=['id', 'default_code', 'name'],
    )
    pid_to_code = {p['id']: p['default_code'] for p in prods}
    code_to_pid = {p['default_code']: p['id'] for p in prods}
    pid_to_name = {p['id']: p['name'] for p in prods}
    pids = list(pid_to_code.keys())
    print(f"Resueltos {len(pids)}/{len(SKUS)} SKUs")

    # ------------------------------------------------------------
    # 2. Descubrir campos x_stock_balance_daily
    # ------------------------------------------------------------
    sf = odoo.fields_get('x_stock_balance_daily')
    print(f"\nCampos x_stock_balance_daily relevantes:")
    relevant = [k for k in sf if any(t in k for t in
                ['product', 'team', 'warehouse', 'date', 'balance', 'stockout'])]
    for k in sorted(relevant):
        print(f"  {k:40s} {sf[k].get('type')}")

    sf_pid = next((k for k in sf if sf[k].get('type') == 'many2one'
                   and sf[k].get('relation') == 'product.product'), None)
    sf_team = next((k for k in sf if sf[k].get('type') == 'many2one'
                    and sf[k].get('relation') == 'crm.team'), None)
    sf_wh = next((k for k in sf if sf[k].get('type') == 'many2one'
                  and sf[k].get('relation') == 'stock.warehouse'), None)
    sf_date = next((k for k in sf if 'date' in k and sf[k].get('type') == 'date'), None)
    sf_balance = next((k for k in sf if 'balance' in k and sf[k].get('type') in ('float', 'integer')), None)
    print(f"\n  pid_field:     {sf_pid}")
    print(f"  team_field:    {sf_team}")
    print(f"  wh_field:      {sf_wh}")
    print(f"  date_field:    {sf_date}")
    print(f"  balance_field: {sf_balance}")

    # ------------------------------------------------------------
    # 3. Pull balance diario 16 sem para los 6 SKUs
    # ------------------------------------------------------------
    week_now = _iso_monday(TODAY)
    start = week_now - timedelta(weeks=WEEKS_BACK)
    print(f"\nVentana: {start} -> {week_now}")

    domain = [
        (sf_pid, 'in', pids),
        (sf_date, '>=', start.strftime('%Y-%m-%d')),
        (sf_date, '<', week_now.strftime('%Y-%m-%d')),
    ]
    fields_read = [sf_pid, sf_date, sf_balance]
    if sf_team:
        fields_read.append(sf_team)
    if sf_wh:
        fields_read.append(sf_wh)
    rows = odoo.search_read(
        'x_stock_balance_daily',
        domain=domain,
        fields=fields_read,
    )
    print(f"  filas balance: {len(rows):,}")
    if not rows:
        print("  *** SIN DATA EN x_stock_balance_daily ***")
        return

    df_b = pd.DataFrame(rows)
    df_b['pid'] = df_b[sf_pid].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    df_b['code'] = df_b['pid'].map(pid_to_code)
    df_b['date'] = pd.to_datetime(df_b[sf_date]).dt.date
    df_b['week_start'] = df_b['date'].apply(_iso_monday)
    df_b['balance'] = pd.to_numeric(df_b[sf_balance], errors='coerce').fillna(0.0)
    if sf_team:
        df_b['team_id'] = df_b[sf_team].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
        # Excluir San Jose (team 11)
        df_b = df_b[df_b['team_id'] != 11]
    df_b['stockout'] = (df_b['balance'] <= 0).astype(int)
    print(f"  filas post-filtro teams ex-SJ: {len(df_b):,}")

    # ------------------------------------------------------------
    # 4. Pull POS ventas 16 sem
    # ------------------------------------------------------------
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
    df_l = pd.DataFrame(lines)
    df_l['pid'] = df_l['product_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    df_l['order_id_id'] = df_l['order_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)

    order_ids = sorted(df_l['order_id_id'].unique().tolist())
    orders_all = []
    BATCH = 5000
    for i in range(0, len(order_ids), BATCH):
        rows_o = odoo.search_read(
            'pos.order',
            domain=[('id', 'in', order_ids[i:i+BATCH])],
            fields=['date_order', 'crm_team_id'],
        )
        orders_all.extend(rows_o)
    df_o = pd.DataFrame(orders_all)
    df_o['team_id'] = df_o['crm_team_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else None)
    df_o['week_start'] = pd.to_datetime(df_o['date_order']).apply(lambda d: _iso_monday(d.date()))

    df_l = df_l.merge(df_o[['id', 'team_id', 'week_start']], left_on='order_id_id', right_on='id')
    df_l = df_l[df_l['team_id'] != 11]
    df_l['code'] = df_l['pid'].map(pid_to_code)

    ventas = df_l.groupby(['code', 'week_start'])['qty'].sum().reset_index()
    ventas.columns = ['code', 'week_start', 'qty_venta']

    # ------------------------------------------------------------
    # 5. Agregado stock por semana x SKU
    # ------------------------------------------------------------
    # Por (code, week_start): balance promedio dia x sala, dias_stockout, salas_stockout
    agg_b = df_b.groupby(['code', 'week_start']).agg(
        balance_sum_dia=('balance', 'sum'),
        dias_total=('balance', 'size'),
        dias_stockout=('stockout', 'sum'),
        salas_distintas=('team_id', 'nunique'),
    ).reset_index()
    # balance promedio por dia-sala = balance_sum_dia / dias_total
    # 7 dias x N salas. Promedio "stock dia" suma todas las salas / dias.
    agg_b['balance_avg_dia_sala'] = (agg_b['balance_sum_dia'] / agg_b['dias_total']).round(1)
    # % salas stockout: dias_stockout / dias_total (proxy)
    agg_b['pct_dia_stockout'] = (agg_b['dias_stockout'] / agg_b['dias_total'] * 100).round(0)

    # Merge
    cross = ventas.merge(agg_b, on=['code', 'week_start'], how='outer').fillna(0)

    # ------------------------------------------------------------
    # 6. Lectura
    # ------------------------------------------------------------
    def _lectura(r):
        q = r['qty_venta']
        b = r['balance_avg_dia_sala']
        pct_o = r['pct_dia_stockout']
        if q > 50 and b > 10:
            return 'VENTA_NORMAL'
        if q == 0 and pct_o > 50:
            return 'QUIEBRE_CONFIRMADO'
        if q == 0 and b <= 1:
            return 'QUIEBRE_PROBABLE'
        if q == 0 and b > 10:
            return 'DEMANDA_CERO'  # raro - habia stock pero no se vendio
        if q < 20 and pct_o > 30:
            return 'QUIEBRE_PARCIAL'
        return 'NORMAL'
    cross['lectura'] = cross.apply(_lectura, axis=1)

    # ------------------------------------------------------------
    # 7. Tabla por SKU (pivot)
    # ------------------------------------------------------------
    for code in SKUS:
        sub = cross[cross['code'] == code].sort_values('week_start')
        if sub.empty:
            print(f"\n--- [{code}] SIN DATA ---")
            continue
        pid = code_to_pid.get(code)
        print(f"\n========== [{code}] {pid_to_name.get(pid, '')} ==========")
        cols = ['week_start', 'qty_venta', 'balance_avg_dia_sala', 'pct_dia_stockout',
                'salas_distintas', 'lectura']
        print(sub[cols].to_string(index=False))

    # ------------------------------------------------------------
    # 8. Resumen
    # ------------------------------------------------------------
    print(f"\n========== RESUMEN ==========")
    print(cross.groupby(['code', 'lectura']).size().unstack(fill_value=0).to_string())

    OUT = Path(__file__).parent / "cruce_quiebre_stock.csv"
    cross.to_csv(OUT, index=False, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
