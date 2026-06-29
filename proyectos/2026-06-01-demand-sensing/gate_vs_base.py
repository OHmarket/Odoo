"""
GATE Fase 1 (v2) — demand sensing vs el motor PRODUCTIVO ACTUAL (OH Forecast Base v1.6).

gate_produccion.py corrio contra el CSV 30-05 (era HM-SI). El motor productivo cambio
a Forecast Base (model codes ses_a0.xx / sma6 en el backtest live). Este gate re-mide
la pregunta no negociable del plan: el demand sensing le gana a Forecast Base en las
cervezas con evento, ciclo completo, limpio de quiebre?

motor = forecast_qty del backtest LIVE (x_forecast_backtest), agregado por (pid, semana).
real  = real_qty del mismo backtest. ds = MM7(cutoff)x7 si dias_post>=CONF_DAYS, si no FLAG.
Cruce de quiebre y caches reutilizados de la Fase 0 (validados).

READ-ONLY: lee Odoo + parquets; escribe resultados/gate_vs_base.parquet + print.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.resolve().parents[1]
CACHE = ROOT / 'proyectos' / '2026-05-27-harness-local' / 'cache'
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

CONF_DAYS = 7
QB_SALAS = 3


def m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def main():
    o = OdooReader()
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    cerv_ids = set(prod[prod['categ_complete_name'].astype(str)
                        .str.contains('Cerveza', case=False, na=False)]['id'])

    # eventos (cervezas con cambio de precio): pid -> fecha evento mas reciente
    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    pc['det'] = pd.to_datetime(pc['x_studio_target_week_start']).dt.date
    ev = {p: d for p, d in pc[pc['x_studio_var_pct'].abs() > 0.001]
          .groupby('product_id')['det'].max().items() if p in cerv_ids}
    print(f'cervezas con evento: {len(ev)}')

    # MM7 diario
    daily = pd.read_parquet(HERE / 'pos_daily_cerv.parquet')
    daily['day'] = pd.to_datetime(daily['day'])
    all_days = pd.date_range(daily['day'].min(), daily['day'].max(), freq='D')
    mm7 = (daily.pivot_table(index='day', columns='product_id', values='qty', aggfunc='sum')
                .reindex(all_days, fill_value=0.0).rolling(7).mean())

    # quiebre: (pid, day) -> n_salas en stockout
    qb = pd.read_parquet(HERE / 'pos_stockout_cerv.parquet')
    qb['day'] = pd.to_datetime(qb['day']).dt.date
    qbcount = qb.groupby(['product_id', 'day']).size().to_dict()

    def quiebre(pid, d0, d1):
        d = d0
        while d < d1:
            if qbcount.get((pid, d), 0) >= QB_SALAS:
                return True
            d += timedelta(days=1)
        return False

    # motor productivo actual = forecast_qty del backtest LIVE, solo cervezas
    wk_recs = o.execute('x_forecast_backtest', 'read_group', [],
                        ['x_studio_target_week_start'], ['x_studio_target_week_start:week'], lazy=False)
    weeks = sorted({r['__range']['x_studio_target_week_start:week']['from']
                    for r in wk_recs if r.get('__range')})
    print(f'semanas backtest live: {weeks}')

    rows = []
    for wk in weeks:
        bt = o.search_read('x_forecast_backtest',
                           [('x_studio_target_week_start', '=', wk),
                            ('x_studio_product_id', 'in', sorted(cerv_ids))],
                           fields=['x_studio_product_id', 'x_studio_forecast_qty', 'x_studio_real_qty'])
        agg = {}
        for r in bt:
            p = m2o_id(r['x_studio_product_id'])
            f = float(r.get('x_studio_forecast_qty') or 0.0)
            rl = float(r.get('x_studio_real_qty') or 0.0)
            a = agg.setdefault(p, [0.0, 0.0]); a[0] += f; a[1] += rl
        for p, (f, rl) in agg.items():
            rows.append({'target': wk, 'pid': p, 'motor': f, 'real': rl})
        print(f'  {wk}: {len(agg)} cervezas')

    g = pd.DataFrame(rows)
    g['target'] = pd.to_datetime(g['target'])

    detail = []
    for _, row in g.iterrows():
        p = int(row['pid']); motor = float(row['motor']); r = float(row['real'])
        if motor <= 0 and r <= 0:
            continue
        target = row['target']
        cutoff = target - timedelta(days=1)
        cut_ts = pd.Timestamp(cutoff.date())
        applied, estado = motor, 'no-evt'
        evd = ev.get(p)
        if evd is not None:
            dp = (cutoff.date() - evd).days
            if dp < 0:
                estado = 'pre'
            elif dp < CONF_DAYS:
                estado = 'flag'
            else:
                mm = mm7.loc[cut_ts, p] if (cut_ts in mm7.index and p in mm7.columns) else float('nan')
                if pd.notna(mm):
                    applied, estado = mm * 7, 'ds'
        tgt = target.date()
        qt = quiebre(p, tgt, tgt + timedelta(days=7))
        qw = quiebre(p, cutoff.date() - timedelta(days=6), cutoff.date() + timedelta(days=1))
        detail.append({'target': tgt, 'pid': p, 'motor': motor, 'ds': applied, 'real': r,
                       'estado': estado, 'has_evt': p in ev, 'quiebre': qt or qw})

    d = pd.DataFrame(detail)
    (HERE / 'resultados').mkdir(exist_ok=True)
    d.to_parquet(HERE / 'resultados' / 'gate_vs_base.parquet', index=False)

    def wape(x, col):
        R = x['real'].sum()
        return abs(x[col] - x['real']).sum() / R * 100 if R else 0.0

    evt = d[d['has_evt']]
    evt_clean = evt[~evt['quiebre']]
    ds = evt[evt['estado'] == 'ds']
    ds_clean = ds[~ds['quiebre']]
    print('\n' + '=' * 72)
    print('GATE vs MOTOR PRODUCTIVO ACTUAL (OH Forecast Base v1.6) — todas las semanas')
    print('=' * 72)
    print(f"cervezas-evento filas: {len(evt)}  con quiebre: {int(evt['quiebre'].sum())} "
          f"({evt['quiebre'].mean()*100:.0f}%)  ds-activas: {len(ds)}")
    print('\nSOLO-EVENTO (ciclo completo):')
    print(f"  TOTAL  base {wape(evt,'motor'):.1f}  ds {wape(evt,'ds'):.1f}  ({wape(evt,'ds')-wape(evt,'motor'):+.2f}pp)")
    print(f"  LIMPIO base {wape(evt_clean,'motor'):.1f}  ds {wape(evt_clean,'ds'):.1f}  ({wape(evt_clean,'ds')-wape(evt_clean,'motor'):+.2f}pp)  [sin quiebre]")
    print('\nDS-ACTIVO (post-confirmacion, dias_post>=%d):' % CONF_DAYS)
    print(f"  TOTAL  base {wape(ds,'motor'):.1f}  ds {wape(ds,'ds'):.1f}  ({wape(ds,'ds')-wape(ds,'motor'):+.2f}pp)")
    print(f"  LIMPIO base {wape(ds_clean,'motor'):.1f}  ds {wape(ds_clean,'ds'):.1f}  ({wape(ds_clean,'ds')-wape(ds_clean,'motor'):+.2f}pp)  [sin quiebre]")
    print(f"\n  (n ds-activo limpio = {len(ds_clean)})")


if __name__ == '__main__':
    main()
