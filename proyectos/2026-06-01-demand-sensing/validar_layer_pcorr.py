"""
Test decisivo: reproduce el gate (-1.86pp) el camino LIVE usando el trigger CORRECTO
(x_price_coreccion, var_pct!=0, semantica del gate: 'ever-had-event', sin lookback)?

Diferencia con validar_layer.py: trigger = x_price_coreccion (no x_price_change_event),
y ev = max(target_week_start) por producto sobre TODA la historia (como gate_vs_base).
Todo lo demas igual (daily live read_group, quiebre live, backtest live). READ-ONLY.
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
FACTOR_MIN, FACTOR_MAX = 0.2, 5.0
POS_STATES = ['paid', 'done', 'invoiced']


def m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def main():
    o = OdooReader()
    cerv_ids = sorted({r['id'] for r in o.search_read('product.product',
                       [('categ_id.complete_name', 'like', 'Cerveza')], fields=['id'])})

    # evento mas reciente por producto (cervezas) desde x_price_coreccion, var_pct!=0
    pc = o.search_read('x_price_coreccion', [('x_studio_product_id', 'in', cerv_ids)],
                       fields=['x_studio_product_id', 'x_studio_target_week_start', 'x_studio_var_pct'])
    ev_all = {}
    for r in pc:
        if abs(float(r.get('x_studio_var_pct') or 0.0)) <= 0.001:
            continue
        p = m2o_id(r['x_studio_product_id'])
        d = datetime.strptime(r['x_studio_target_week_start'][:10], '%Y-%m-%d').date()
        if p not in ev_all or d > ev_all[p]:
            ev_all[p] = d
    print(f'cervezas con evento (x_price_coreccion): {len(ev_all)}')

    wk_recs = o.execute('x_forecast_backtest', 'read_group', [],
                        ['x_studio_target_week_start'], ['x_studio_target_week_start:week'], lazy=False)
    weeks = sorted({r['__range']['x_studio_target_week_start:week']['from']
                    for r in wk_recs if r.get('__range')})

    detail = []
    for wk in weeks:
        target = datetime.strptime(wk, '%Y-%m-%d').date()
        cutoff = target - timedelta(days=1)
        win_from = cutoff - timedelta(days=6)

        bt = o.search_read('x_forecast_backtest',
                           [('x_studio_target_week_start', '=', wk),
                            ('x_studio_product_id', 'in', cerv_ids)],
                           fields=['x_studio_product_id', 'x_studio_forecast_qty', 'x_studio_real_qty'])
        motor, real = {}, {}
        for r in bt:
            p = m2o_id(r['x_studio_product_id'])
            motor[p] = motor.get(p, 0.0) + float(r.get('x_studio_forecast_qty') or 0.0)
            real[p] = real.get(p, 0.0) + float(r.get('x_studio_real_qty') or 0.0)

        evt_pids = [p for p in ev_all if p in motor or p in real]
        if not evt_pids:
            continue

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
            qteams.setdefault(p, set()).add(m2o_id(r.get('x_studio_team_id')) or 0)
        qb_pids = {p for p, ts in qteams.items() if len(ts) >= QB_SALAS}

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
            dp = (cutoff - ev_all[p]).days
            applied, estado = mt, ('pre' if dp < 0 else 'flag')
            qb = p in qb_pids
            if dp >= CONF_DAYS and not qb:
                lvl = ds_level.get(p)
                if mt > 0 and lvl is not None:
                    applied = mt * min(max(lvl / mt, FACTOR_MIN), FACTOR_MAX)
                    estado = 'ds'
            detail.append({'target': target, 'pid': p, 'motor': mt, 'ds': applied,
                           'real': r, 'estado': estado, 'quiebre': qb})
        print(f'  {wk}: evt={len(evt_pids)} qb={len(qb_pids)}')

    d = pd.DataFrame(detail)

    def wape(x, col):
        R = x['real'].sum()
        return abs(x[col] - x['real']).sum() / R * 100 if R else 0.0

    evt_clean = d[~d['quiebre']]
    ds = d[d['estado'] == 'ds']
    ds_clean = ds[~ds['quiebre']]
    print('\n' + '=' * 72)
    print('TRIGGER = x_price_coreccion (live) — reproduce el gate?')
    print('=' * 72)
    print(f"filas evento: {len(d)}  quiebre: {int(d['quiebre'].sum())}  ds-activas: {len(ds)}")
    print(f"SOLO-EVENTO  TOTAL  base {wape(d,'motor'):.1f}  ds {wape(d,'ds'):.1f}  ({wape(d,'ds')-wape(d,'motor'):+.2f}pp)")
    print(f"SOLO-EVENTO  LIMPIO base {wape(evt_clean,'motor'):.1f}  ds {wape(evt_clean,'ds'):.1f}  ({wape(evt_clean,'ds')-wape(evt_clean,'motor'):+.2f}pp)")
    print(f"DS-ACTIVO    LIMPIO base {wape(ds_clean,'motor'):.1f}  ds {wape(ds_clean,'ds'):.1f}  ({wape(ds_clean,'ds')-wape(ds_clean,'motor'):+.2f}pp)  (n={len(ds_clean)})")


if __name__ == '__main__':
    main()
