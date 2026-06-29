"""
VALIDAR LAYER — confirma que el camino de datos EN VIVO que usara la Server Action
(OH Demand Sensing) reproduce el FVA del gate.

gate_vs_base.py uso caches (parquet) para evento/diario/quiebre. La SA usara modelos
LIVE: x_price_change_event, pos.order.line (read_group 7d), x_stock_balance_daily.
Aqui replico EXACTAMENTE esa logica en vivo y mido WAPE base vs adjusted sobre el
backtest live (cervezas-evento, ciclo completo, limpio de quiebre).

Si reproduce ~ -1.86pp solo-evento / -2.87pp ds-activo => la SA es fiel al gate.
READ-ONLY.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

HERE = Path(__file__).parent
ROOT = HERE.resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

CONF_DAYS = 7
QB_SALAS = 3
EVENT_LOOKBACK_DAYS = 70
FACTOR_MIN, FACTOR_MAX = 0.2, 5.0
POS_STATES = ['paid', 'done', 'invoiced']


def m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def main():
    o = OdooReader()
    cerv = o.search_read('product.product', [('categ_id.complete_name', 'like', 'Cerveza')], fields=['id'])
    cerv_ids = sorted({r['id'] for r in cerv})
    print(f'cervezas: {len(cerv_ids)}')

    # semanas del backtest live
    wk_recs = o.execute('x_forecast_backtest', 'read_group', [],
                        ['x_studio_target_week_start'], ['x_studio_target_week_start:week'], lazy=False)
    weeks = sorted({r['__range']['x_studio_target_week_start:week']['from']
                    for r in wk_recs if r.get('__range')})

    detail = []
    for wk in weeks:
        target = datetime.strptime(wk, '%Y-%m-%d').date()
        cutoff = target - timedelta(days=1)
        win_from = cutoff - timedelta(days=6)
        ev_from = cutoff - timedelta(days=EVENT_LOOKBACK_DAYS)

        # motor + real del backtest live (suma por producto)
        bt = o.search_read('x_forecast_backtest',
                           [('x_studio_target_week_start', '=', wk),
                            ('x_studio_product_id', 'in', cerv_ids)],
                           fields=['x_studio_product_id', 'x_studio_forecast_qty', 'x_studio_real_qty'])
        motor, real = {}, {}
        for r in bt:
            p = m2o_id(r['x_studio_product_id'])
            motor[p] = motor.get(p, 0.0) + float(r.get('x_studio_forecast_qty') or 0.0)
            real[p] = real.get(p, 0.0) + float(r.get('x_studio_real_qty') or 0.0)

        # evento mas reciente <= cutoff (live)
        ev_rows = o.search_read('x_price_change_event',
                                [('x_studio_is_real_change', '=', True),
                                 ('x_studio_product_id', 'in', cerv_ids),
                                 ('x_studio_period_start', '>=', ev_from.isoformat()),
                                 ('x_studio_period_start', '<=', cutoff.isoformat())],
                                fields=['x_studio_product_id', 'x_studio_period_start'])
        ev_last = {}
        for r in ev_rows:
            p = m2o_id(r['x_studio_product_id'])
            ps = datetime.strptime(r['x_studio_period_start'][:10], '%Y-%m-%d').date()
            if p not in ev_last or ps > ev_last[p]:
                ev_last[p] = ps
        evt_pids = sorted(ev_last.keys())
        if not evt_pids:
            continue

        # quiebre material en ventana de medicion (live)
        sb = o.search_read('x_stock_balance_daily',
                           ['&', ('x_studio_product_id', 'in', evt_pids),
                            '&', ('x_studio_date', '>=', win_from.isoformat()),
                            ('x_studio_date', '<=', cutoff.isoformat()),
                            '|', ('x_studio_stockout', '=', True),
                            ('x_studio_stockout_partial', '=', True)],
                           fields=['x_studio_product_id', 'x_studio_team_id'])
        qteams = {}
        for r in sb:
            p = m2o_id(r['x_studio_product_id'])
            t = m2o_id(r.get('x_studio_team_id')) or 0
            qteams.setdefault(p, set()).add(t)
        qb_pids = {p for p, ts in qteams.items() if len(ts) >= QB_SALAS}

        # senal diaria = suma venta ultimos 7 dias (read_group) = MM7x7
        grp = o.execute('pos.order.line', 'read_group',
                        [('product_id', 'in', evt_pids),
                         ('order_id.date_order', '>=', win_from.isoformat() + ' 00:00:00'),
                         ('order_id.date_order', '<=', cutoff.isoformat() + ' 23:59:59'),
                         ('order_id.state', 'in', POS_STATES)],
                        ['qty:sum'], ['product_id'], lazy=False)
        ds_level = {m2o_id(g['product_id']): float(g.get('qty') or 0.0) for g in grp if g.get('product_id')}

        for p in evt_pids:
            mt = motor.get(p, 0.0); r = real.get(p, 0.0)
            if mt <= 0 and r <= 0:
                continue
            dp = (cutoff - ev_last[p]).days
            applied, estado = mt, 'pre' if dp < 0 else 'flag'
            qb = p in qb_pids
            if dp >= CONF_DAYS and not qb:
                lvl = ds_level.get(p)
                if mt > 0 and lvl is not None:
                    f = min(max(lvl / mt, FACTOR_MIN), FACTOR_MAX)
                    applied, estado = mt * f, 'ds'
            detail.append({'target': target, 'pid': p, 'motor': mt, 'ds': applied,
                           'real': r, 'estado': estado, 'quiebre': qb})
        print(f'  {wk}: evt={len(evt_pids)} qb={len(qb_pids)}')

    d = pd.DataFrame(detail)
    (HERE / 'resultados').mkdir(exist_ok=True)
    d.to_parquet(HERE / 'resultados' / 'validar_layer.parquet', index=False)

    def wape(x, col):
        R = x['real'].sum()
        return abs(x[col] - x['real']).sum() / R * 100 if R else 0.0

    evt = d
    evt_clean = evt[~evt['quiebre']]
    ds = evt[evt['estado'] == 'ds']
    ds_clean = ds[~ds['quiebre']]
    print('\n' + '=' * 72)
    print('VALIDAR LAYER (camino de datos LIVE de la Server Action) vs Forecast Base')
    print('=' * 72)
    print(f"filas evento: {len(evt)}  quiebre: {int(evt['quiebre'].sum())}  ds-activas: {len(ds)}")
    print('SOLO-EVENTO:')
    print(f"  TOTAL  base {wape(evt,'motor'):.1f}  ds {wape(evt,'ds'):.1f}  ({wape(evt,'ds')-wape(evt,'motor'):+.2f}pp)")
    print(f"  LIMPIO base {wape(evt_clean,'motor'):.1f}  ds {wape(evt_clean,'ds'):.1f}  ({wape(evt_clean,'ds')-wape(evt_clean,'motor'):+.2f}pp)")
    print('DS-ACTIVO:')
    print(f"  TOTAL  base {wape(ds,'motor'):.1f}  ds {wape(ds,'ds'):.1f}  ({wape(ds,'ds')-wape(ds,'motor'):+.2f}pp)")
    print(f"  LIMPIO base {wape(ds_clean,'motor'):.1f}  ds {wape(ds_clean,'ds'):.1f}  ({wape(ds_clean,'ds')-wape(ds_clean,'motor'):+.2f}pp)  (n={len(ds_clean)})")


if __name__ == '__main__':
    main()
