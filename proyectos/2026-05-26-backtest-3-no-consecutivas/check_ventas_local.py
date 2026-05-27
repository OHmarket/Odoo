"""
Lee x_sales_month_team_kpi (OH Analisis de Ventas por Local) y muestra
el deterioro YoY por team y por mes. Esto valida la hipotesis de que existe
un trend bajista que el motor HM-SI no esta capturando.
"""
from __future__ import annotations
import sys
import io
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

OUT_PATH = Path(__file__).parent / "ventas_local_output.txt"

pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 240)


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    rows = odoo.search_read(
        'x_sales_month_team_kpi',
        domain=[],
        fields=['x_studio_period_date', 'x_studio_team_id',
                'x_studio_sales_gross', 'x_studio_sales_gross_ly',
                'x_studio_units', 'x_studio_units_ly',
                'x_studio_tickets', 'x_studio_tickets_ly',
                'x_studio_atv', 'x_studio_atv_ly',
                'x_studio_yoy_sales_pct', 'x_studio_yoy_units_pct',
                'x_studio_yoy_tickets_pct', 'x_studio_yoy_atv_pct',
                'x_studio_driver_code'],
    )
    p(f"Filas: {len(rows)}\n")
    df = pd.DataFrame(rows)
    df['team'] = df['x_studio_team_id'].apply(lambda x: x[1] if isinstance(x, list) else x)
    df['date'] = pd.to_datetime(df['x_studio_period_date'])
    df['month'] = df['date'].dt.month
    df['year'] = df['date'].dt.year
    df = df.sort_values(['date', 'team'])

    # Filtrar a teams del backtest (excluir San Jose noise)
    df_bt = df[~df['team'].str.lower().str.contains('san jos', na=False)].copy()

    p("=" * 100)
    p("1. GLOBAL: Ventas mes por mes (suma todos los teams, excluyendo San Jose)")
    p("=" * 100)
    g = df_bt.groupby('date').agg(
        units=('x_studio_units', 'sum'),
        units_ly=('x_studio_units_ly', 'sum'),
        sales=('x_studio_sales_gross', 'sum'),
        sales_ly=('x_studio_sales_gross_ly', 'sum'),
        tickets=('x_studio_tickets', 'sum'),
        tickets_ly=('x_studio_tickets_ly', 'sum'),
    ).reset_index()
    g['yoy_units_pct'] = (g['units']/g['units_ly'] - 1) * 100
    g['yoy_sales_pct'] = (g['sales']/g['sales_ly'] - 1) * 100
    g['yoy_tickets_pct'] = (g['tickets']/g['tickets_ly'] - 1) * 100
    g['date'] = g['date'].dt.strftime('%Y-%m')
    p(g.to_string(index=False))

    p("\n" + "=" * 100)
    p("2. YoY por team y mes (ultimo 12 meses, units pct)")
    p("=" * 100)
    cutoff = df_bt['date'].max() - pd.DateOffset(months=14)
    recent = df_bt[df_bt['date'] >= cutoff].copy()
    pivot_units = recent.pivot_table(
        index='team', columns=recent['date'].dt.strftime('%Y-%m'),
        values='x_studio_yoy_units_pct', aggfunc='first',
    ).round(1)
    p(pivot_units.to_string())

    p("\n" + "=" * 100)
    p("3. YoY por team y mes (ultimo 12 meses, sales_gross CLP pct)")
    p("=" * 100)
    pivot_sales = recent.pivot_table(
        index='team', columns=recent['date'].dt.strftime('%Y-%m'),
        values='x_studio_yoy_sales_pct', aggfunc='first',
    ).round(1)
    p(pivot_sales.to_string())

    p("\n" + "=" * 100)
    p("4. Promedio YoY (units pct) por team, ultimos 6 meses vs 12 meses")
    p("=" * 100)
    cut_6 = df_bt['date'].max() - pd.DateOffset(months=7)
    cut_12 = df_bt['date'].max() - pd.DateOffset(months=13)
    last6 = df_bt[df_bt['date'] >= cut_6]
    last12 = df_bt[df_bt['date'] >= cut_12]
    by_team = pd.DataFrame({
        'yoy_units_avg_6m': last6.groupby('team')['x_studio_yoy_units_pct'].mean(),
        'yoy_units_avg_12m': last12.groupby('team')['x_studio_yoy_units_pct'].mean(),
        'yoy_sales_avg_6m': last6.groupby('team')['x_studio_yoy_sales_pct'].mean(),
        'yoy_sales_avg_12m': last12.groupby('team')['x_studio_yoy_sales_pct'].mean(),
    }).round(1).sort_values('yoy_units_avg_6m')
    p(by_team.to_string())

    p("\n" + "=" * 100)
    p("5. Foco en los meses del backtest: Feb, Mar, Apr 2026")
    p("=" * 100)
    focus = df_bt[df_bt['date'].dt.strftime('%Y-%m').isin(['2026-02', '2026-03', '2026-04'])].copy()
    if not focus.empty:
        for mo in ['2026-02', '2026-03', '2026-04']:
            sub = focus[focus['date'].dt.strftime('%Y-%m') == mo]
            if sub.empty: continue
            p(f"\n--- {mo} ---")
            tot_u = sub['x_studio_units'].sum()
            tot_u_ly = sub['x_studio_units_ly'].sum()
            tot_s = sub['x_studio_sales_gross'].sum()
            tot_s_ly = sub['x_studio_sales_gross_ly'].sum()
            tot_t = sub['x_studio_tickets'].sum()
            tot_t_ly = sub['x_studio_tickets_ly'].sum()
            p(f"  Units    : {tot_u:>12,.0f}  vs LY {tot_u_ly:>12,.0f}   YoY {((tot_u/tot_u_ly)-1)*100:+.1f}%")
            p(f"  Sales CLP: {tot_s:>12,.0f}  vs LY {tot_s_ly:>12,.0f}   YoY {((tot_s/tot_s_ly)-1)*100:+.1f}%")
            p(f"  Tickets  : {tot_t:>12,.0f}  vs LY {tot_t_ly:>12,.0f}   YoY {((tot_t/tot_t_ly)-1)*100:+.1f}%")
            p(f"\n  Por team {mo}:")
            sub_g = sub[['team', 'x_studio_units', 'x_studio_units_ly',
                          'x_studio_yoy_units_pct', 'x_studio_yoy_sales_pct',
                          'x_studio_yoy_tickets_pct']].sort_values('x_studio_yoy_units_pct')
            p(sub_g.to_string(index=False))

    p("\n" + "=" * 100)
    p("6. Conclusion automatica:")
    p("=" * 100)
    g_units_yoy_recent = last6.groupby('date')['x_studio_yoy_units_pct'].mean()
    avg_yoy_units_6m = last6['x_studio_yoy_units_pct'].mean()
    avg_yoy_sales_6m = last6['x_studio_yoy_sales_pct'].mean()
    feb_yoy = focus[focus['date'].dt.strftime('%Y-%m') == '2026-02']['x_studio_yoy_units_pct'].mean()
    mar_yoy = focus[focus['date'].dt.strftime('%Y-%m') == '2026-03']['x_studio_yoy_units_pct'].mean()
    p(f"  YoY units promedio ultimos 6m: {avg_yoy_units_6m:+.1f}%")
    p(f"  YoY sales promedio ultimos 6m: {avg_yoy_sales_6m:+.1f}%")
    p(f"  YoY units Feb 2026: {feb_yoy:+.1f}%")
    p(f"  YoY units Mar 2026: {mar_yoy:+.1f}%")
    p(f"")
    if avg_yoy_units_6m < -2:
        p("  *** DETERIORO CONFIRMADO ***")
    elif avg_yoy_units_6m > 2:
        p("  *** CRECIMIENTO ***")
    else:
        p("  Estable YoY")

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
