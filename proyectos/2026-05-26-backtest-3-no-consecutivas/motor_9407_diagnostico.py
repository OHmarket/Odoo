"""
Que esta calculando el motor para el 9407?

Cruza:
1. Ventas POS reales ultimas 16 sem agregadas y por sala (pos.config.name).
2. Forecast del motor en las 3 sem backtest (CSV).
3. SMA(6) calculado sobre las ventas reales para entender que ve el motor.
4. Lo que persiste x_hm_si_forecast actualmente (forecast para proxima sem futura).
5. Campos detallados que el motor escribio: mu_base, si_main_factor, si_sku_factor,
   correccion_factor, trend_factor, regimen, forecast_model_code.
"""
from __future__ import annotations
import sys
import re
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CSV = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (3).csv")
TODAY = date(2026, 5, 27)
WEEKS_BACK = 16
BT_WEEKS = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
pd.set_option("display.width", 280)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 45)


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}\n")

    pid = odoo.search_read('product.product',
                            domain=[('default_code', '=', '9407')],
                            fields=['id', 'name'])[0]
    print(f"SKU 9407 -> pid={pid['id']}  {pid['name']}")
    PID = pid['id']

    week_now = _iso_monday(TODAY)
    start = week_now - timedelta(weeks=WEEKS_BACK)

    # ============================================================
    # 1. Pull POS por sala (via pos.config.name, no crm.team que dice 'Sales')
    # ============================================================
    lines = odoo.search_read(
        'pos.order.line',
        domain=[
            ('product_id', '=', PID),
            ('order_id.date_order', '>=', start.strftime('%Y-%m-%d')),
            ('order_id.date_order', '<', week_now.strftime('%Y-%m-%d')),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ],
        fields=['qty', 'order_id'],
    )
    df_l = pd.DataFrame(lines)
    df_l['order_id_id'] = df_l['order_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    order_ids = sorted(df_l['order_id_id'].unique().tolist())
    orders_all = []
    for i in range(0, len(order_ids), 5000):
        rs = odoo.search_read(
            'pos.order',
            domain=[('id', 'in', order_ids[i:i+5000])],
            fields=['date_order', 'config_id', 'crm_team_id'],
        )
        orders_all.extend(rs)
    df_o = pd.DataFrame(orders_all)
    df_o['config_name'] = df_o['config_id'].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and v else 'SIN_CFG')
    df_o['team_id'] = df_o['crm_team_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) and v else None)
    df_o['week_start'] = pd.to_datetime(df_o['date_order']).apply(lambda d: _iso_monday(d.date()))
    df = df_l.merge(df_o[['id', 'config_name', 'team_id', 'week_start']], left_on='order_id_id', right_on='id')
    df = df[df['team_id'] != 11]  # ex-SJ
    pivot = df.groupby(['week_start', 'config_name'])['qty'].sum().unstack(fill_value=0)
    pivot = pivot.reindex(columns=sorted(pivot.columns))
    pivot['TOTAL'] = pivot.sum(axis=1)

    print(f"\n========== VENTAS POS 9407 — 16 sem por sala (ex-SJ) ==========")
    print(pivot.to_string())

    # ============================================================
    # 2. SMA(6) rolling sobre TOTAL
    # ============================================================
    print(f"\n========== SMA(6) ROLLING sobre TOTAL semanal ==========")
    tot = pivot['TOTAL']
    sma6 = tot.rolling(window=6, min_periods=1).mean().round(0)
    sma8 = tot.rolling(window=8, min_periods=1).mean().round(0)
    df_sma = pd.DataFrame({
        'real': tot,
        'SMA6': sma6,
        'SMA8': sma8,
    })
    df_sma['vs_SMA6'] = ((tot - sma6) / sma6 * 100).round(0)
    print(df_sma.to_string())

    # ============================================================
    # 3. Forecast del motor en las 3 sem backtest (CSV)
    # ============================================================
    print(f"\n========== FORECAST DEL MOTOR EN BACKTEST (3 sem BT) ==========")
    df_bt = pd.read_csv(CSV, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "mu_week_pre_bias"]:
        df_bt[c] = pd.to_numeric(df_bt[c], errors="coerce").fillna(0.0)
    sub = df_bt[df_bt['product_id'].str.contains(r'\[9407\]', regex=True, na=False)]
    sub = sub[~sub['team_id'].fillna('').str.contains('San Jos')]

    print(f"\n  Por sem x team:")
    cols = ['target_week_start', 'team_id', 'regimen', 'forecast_model_code',
            'mu_week_pre_bias', 'forecast_qty', 'real_qty']
    print(sub[cols].sort_values(['target_week_start', 'team_id']).to_string(index=False))

    print(f"\n  Totales por semana BT:")
    agg = sub.groupby('target_week_start').agg(
        n_teams=('team_id', 'nunique'),
        sum_mu_pre=('mu_week_pre_bias', 'sum'),
        sum_fcst=('forecast_qty', 'sum'),
        sum_real=('real_qty', 'sum'),
    )
    agg['gap_real_vs_fcst'] = agg['sum_real'] - agg['sum_fcst']
    agg['bias_pct'] = ((agg['sum_real'] - agg['sum_fcst']) / agg['sum_real'] * 100).round(0)
    print(agg.to_string())

    # ============================================================
    # 4. Forecast vivo en x_hm_si_forecast (siguiente semana)
    # ============================================================
    print(f"\n========== x_hm_si_forecast VIVO (forecast actual proxima sem) ==========")
    fields_map = odoo.fields_get('x_hm_si_forecast')
    candidate = [
        'x_studio_product_id', 'x_studio_team_id', 'x_studio_week_start',
        'x_studio_mu_week', 'x_studio_mu_week_pre_bias', 'x_studio_mu_base',
        'x_studio_sigma_week', 'x_studio_si_current', 'x_studio_si_next',
        'x_studio_si_main_factor', 'x_studio_si_sku_factor', 'x_studio_si_n_years',
        'x_studio_correccion_factor', 'x_studio_correccion_tipo',
        'x_studio_forecast_zone', 'x_studio_regimen', 'x_studio_forecast_model_code',
        'x_studio_collapse_detected',
    ]
    fields_read = [f for f in candidate if f in fields_map]
    rows_vivo = odoo.search_read(
        'x_hm_si_forecast',
        domain=[('x_studio_product_id', '=', PID)],
        fields=fields_read,
        order='x_studio_week_start desc',
    )
    print(f"  Filas vivo: {len(rows_vivo)}")
    if rows_vivo:
        df_vivo = pd.DataFrame(rows_vivo)
        for c in df_vivo.columns:
            if df_vivo[c].apply(lambda v: isinstance(v, (list, tuple))).any():
                df_vivo[c] = df_vivo[c].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else v)
        # Filtrar San Jose
        df_vivo = df_vivo[~df_vivo.get('x_studio_team_id', pd.Series(dtype=str)).fillna('').str.contains('San Jos')]
        print(f"\n  Semanas distintas: {df_vivo['x_studio_week_start'].nunique()}")
        # Por semana, agregado
        cols_show = [c for c in [
            'x_studio_week_start', 'x_studio_team_id', 'x_studio_regimen',
            'x_studio_forecast_model_code', 'x_studio_mu_base',
            'x_studio_si_main_factor', 'x_studio_si_sku_factor',
            'x_studio_correccion_factor', 'x_studio_mu_week_pre_bias',
            'x_studio_mu_week', 'x_studio_collapse_detected',
        ] if c in df_vivo.columns]
        print(df_vivo[cols_show].to_string(index=False))

        # Totales por sem
        if 'x_studio_mu_week' in df_vivo.columns:
            df_vivo['x_studio_mu_week'] = pd.to_numeric(df_vivo['x_studio_mu_week'], errors='coerce')
            print(f"\n  TOTAL mu_week (agregado teams ex-SJ) por sem:")
            for wk, sub_v in df_vivo.groupby('x_studio_week_start'):
                tot_mu = sub_v['x_studio_mu_week'].sum()
                print(f"    {wk}: total_mu_week={tot_mu:,.0f}")


if __name__ == "__main__":
    main()
