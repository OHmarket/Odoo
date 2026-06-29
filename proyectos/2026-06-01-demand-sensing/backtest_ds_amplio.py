"""
Backtest AMPLIO del demand sensing + CRUCE DE QUIEBRE (paso B).

Universo: todas las cervezas con evento, 10 semanas (onset+tail), motor del harness.
Regla: SKU con evento, dias_post>=CONF_DAYS -> ds=MM7(cutoff)*7; 0..CONF_DAYS -> FLAG.

Cruce de quiebre (x_stock_balance_daily): una (SKU, semana) esta CONTAMINADA si
hubo quiebre material (>=QB_SALAS salas en stockout algun dia) en la semana
objetivo (real censurado) o en la ventana de medicion [cutoff-6, cutoff] (MM7
censurado). Se reporta WAPE total vs LIMPIO (sin contaminadas).

Pregunta: el win del ds se sostiene en las semanas SIN quiebre? Si si -> es
cambio de demanda por precio (genuino). Si desaparece -> era adivinar quiebres.
"""
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / 'proyectos' / '2026-05-27-harness-local'
CACHE = HARNESS / 'cache'
HERE = Path(__file__).parent
sys.path.insert(0, str(HARNESS))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache  # noqa: E402

CONF_DAYS = 7
QB_SALAS = 3   # >= salas en stockout el mismo dia = quiebre material


def main():
    pos, _ = load_cache(CACHE)
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    cerv_ids = set(prod[prod['categ_complete_name'].astype(str).str.contains('Cerveza', case=False, na=False)]['id'])

    daily = pd.read_parquet(HERE / 'pos_daily_cerv.parquet')
    daily['day'] = pd.to_datetime(daily['day'])
    all_days = pd.date_range(daily['day'].min(), daily['day'].max(), freq='D')
    wide = daily.pivot_table(index='day', columns='product_id', values='qty', aggfunc='sum').reindex(all_days, fill_value=0.0)
    mm7 = wide.rolling(7).mean()

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

    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    pc['det'] = pd.to_datetime(pc['x_studio_target_week_start']).dt.date
    ev = {p: d for p, d in pc[pc['x_studio_var_pct'].abs() > 0.001].groupby('product_id')['det'].max().items() if p in cerv_ids}

    weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]
    detail = []
    for target in weeks:
        cutoff = target - timedelta(days=1)
        cut_ts = pd.Timestamp(cutoff)
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        mot = fc.groupby('product_id')['mu_week'].sum()
        real = daily[(daily['day'] >= pd.Timestamp(target)) & (daily['day'] < pd.Timestamp(target) + timedelta(days=7))] \
            .groupby('product_id')['qty'].sum()
        for p in cerv_ids:
            motor = float(mot.get(p, 0.0)); r = float(real.get(p, 0.0))
            if motor <= 0 and r <= 0:
                continue
            applied, estado = motor, 'no-evt'
            evd = ev.get(p)
            if evd is not None:
                dp = (cutoff - evd).days
                if dp < 0:
                    estado = 'pre'
                elif dp < CONF_DAYS:
                    estado = 'flag'
                else:
                    mm = mm7.loc[cut_ts, p] if (cut_ts in mm7.index and p in mm7.columns) else float('nan')
                    if pd.notna(mm):
                        applied, estado = mm * 7, 'ds'
            qt = quiebre(p, target, target + timedelta(days=7))
            qw = quiebre(p, cutoff - timedelta(days=6), cutoff + timedelta(days=1))
            detail.append({'target': target, 'pid': p, 'motor': motor, 'ds': applied, 'real': r,
                           'estado': estado, 'has_evt': p in ev, 'quiebre': qt or qw})
        print(f"  {target} ok")

    d = pd.DataFrame(detail)
    d.to_parquet(HERE / 'detalle_ds_quiebre.parquet', index=False)

    def wape(df, col):
        R = df['real'].sum()
        return abs(df[col] - df['real']).sum() / R * 100 if R else 0.0

    evt = d[d['has_evt']]
    evt_clean = evt[~evt['quiebre']]
    dsrows = evt[evt['estado'] == 'ds']
    dsrows_clean = dsrows[~dsrows['quiebre']]
    print("\n" + "=" * 70)
    print(f"Filas solo-evento: {len(evt)}  | con quiebre: {evt['quiebre'].sum()} "
          f"({evt['quiebre'].mean()*100:.0f}%)  | ds-activas: {len(dsrows)}")
    print(f"\nSOLO-EVENTO (todas las semanas evento):")
    print(f"  TOTAL  motor {wape(evt,'motor'):.1f}  ds {wape(evt,'ds'):.1f}  ({wape(evt,'ds')-wape(evt,'motor'):+.2f}pp)")
    print(f"  LIMPIO motor {wape(evt_clean,'motor'):.1f}  ds {wape(evt_clean,'ds'):.1f}  ({wape(evt_clean,'ds')-wape(evt_clean,'motor'):+.2f}pp)  [sin quiebre]")
    print(f"\nSOLO filas ds-ACTIVO (post-confirmación):")
    print(f"  TOTAL  motor {wape(dsrows,'motor'):.1f}  ds {wape(dsrows,'ds'):.1f}  ({wape(dsrows,'ds')-wape(dsrows,'motor'):+.2f}pp)")
    print(f"  LIMPIO motor {wape(dsrows_clean,'motor'):.1f}  ds {wape(dsrows_clean,'ds'):.1f}  ({wape(dsrows_clean,'ds')-wape(dsrows_clean,'motor'):+.2f}pp)  [sin quiebre]")


if __name__ == '__main__':
    main()
