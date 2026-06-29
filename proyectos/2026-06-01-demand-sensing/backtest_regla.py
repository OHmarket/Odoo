"""
Backtest de la regla de confirmacion — CICLO COMPLETO (no la ventana comoda).

Demand sensing causal: en el cutoff (domingo previo a la semana W), el forecast es
  ds = MM7(run-rate diario, ultimos 7 dias) * 7
con regla de confirmacion: si pasaron <CONF_DAYS desde el evento -> FLAG (ventana
de medicion, no predice). Se compara contra el real semanal y, donde lo tengo,
contra el motor real del server (W20-22).

Pregunta: post-confirmacion, el nivel medido predice las semanas siguientes mejor
que el motor? Y cuantas semanas de FLAG cuesta el onset?
"""
import re
from pathlib import Path
from datetime import timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'proyectos' / '2026-05-27-harness-local' / 'cache'
DAILY = Path(__file__).parent / 'pos_daily_cerv.parquet'
SERVER_CSV = ROOT / '02_forecast' / 'backtest-data-raw' / 'OH Forecast Backtest (x_forecast_backtest) 30-05.csv'
CONF_DAYS = 7

TESTIGOS = [('Royal Guard', '451500', '2026-04-20'), ('Cristal', '451548', '2026-04-13'),
            ('Budweiser', '9413', '2026-05-04'), ('Quilmes', '9430', '2026-04-13')]


def server_motor():
    df = pd.read_csv(SERVER_CSV, encoding='latin-1')
    for c in ['real_qty', 'forecast_qty']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['tw'] = pd.to_datetime(df['target_week_start']).dt.date
    df['code'] = df['product_id'].apply(lambda s: (re.match(r'\[([^\]]+)\]', str(s)) or [None, None])[1]
                                        if re.match(r'\[([^\]]+)\]', str(s)) else None)
    g = df.groupby(['code', 'tw']).agg(motor=('forecast_qty', 'sum'), real=('real_qty', 'sum'))
    return g


def main():
    daily = pd.read_parquet(DAILY)
    daily['day'] = pd.to_datetime(daily['day'])
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    code2id = dict(zip(prod['default_code'].astype(str), prod['id']))
    all_days = pd.date_range(daily['day'].min(), daily['day'].max(), freq='D')
    srv = server_motor()

    weeks = [pd.Timestamp('2026-03-30') + timedelta(weeks=i) for i in range(8)]  # 03-30..05-18

    for nm, code, ev in TESTIGOS:
        pid = code2id.get(code)
        ev = pd.Timestamp(ev)
        s = daily[daily['product_id'] == pid].set_index('day')['qty'].reindex(all_days, fill_value=0.0)
        mm7 = s.rolling(7).mean()
        print(f"\n=== {nm} [{code}]  evento={ev.date()} ===")
        print(f"  {'semana':<11}{'real':>7}{'ds(MM7*7)':>11}{'motor':>8}{'estado':>14}")
        err_ds, err_mot, n_cmp, n_flag = 0.0, 0.0, 0, 0
        for w in weeks:
            cutoff = w - timedelta(days=1)
            real_w = s[(s.index >= w) & (s.index < w + timedelta(days=7))].sum()
            if real_w <= 0:
                continue
            dias_post = (cutoff - ev).days
            mm = mm7.loc[cutoff] if cutoff in mm7.index else float('nan')
            ds = mm * 7
            mrow = srv.loc[(code, w.date())] if (code, w.date()) in srv.index else None
            motor = mrow['motor'] if mrow is not None else float('nan')
            if dias_post < 0:
                estado = 'pre-evento'
            elif dias_post < CONF_DAYS:
                estado = 'FLAG(midiendo)'
                n_flag += 1
            else:
                estado = 'ds activo'
                err_ds += abs(ds - real_w)
                n_cmp += 1
                if mrow is not None:
                    err_mot += abs(motor - real_w)
            mtxt = f"{motor:>8.0f}" if mrow is not None else f"{'—':>8}"
            print(f"  {str(w.date()):<11}{real_w:>7.0f}{ds:>11.0f}{mtxt}{estado:>14}")
        if n_cmp:
            print(f"  -> post-confirmación: err_ds/sem={err_ds/n_cmp:.0f}   "
                  f"(semanas FLAG en onset: {n_flag})")


if __name__ == '__main__':
    main()
