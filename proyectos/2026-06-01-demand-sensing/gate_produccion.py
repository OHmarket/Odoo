"""
GATE Fase 1 — verificar el demand sensing vs el motor de PRODUCCION (con bias_outlier).

Fase 0 corrio sobre el motor del harness (sin bias_outlier). bias_outlier (ON en
prod) ya recorta outliers y podria solaparse con lo que el ds corrige. Aqui el
"motor" = forecast_qty del backtest server 30-05 (W20-22, target 05-04/11/18).

Pregunta: el -15pp post-confirmacion se SOSTIENE contra el forecast de produccion?
  - Si si  -> bias_outlier no captura el salto de nivel; el ds aporta. Implementar.
  - Si no  -> bias_outlier ya lo hace; re-evaluar alcance antes de codear.

Union: columna 'Descripción' del CSV = "hm_si | cutoff | T<team> | P<product_id>".
Extraemos P(\\d+) -> product_id numerico (clave limpia, evita padding de default_code).
Real = real_qty del CSV (mismo real contra el que se midio produccion) agregado por pid.
ds = MM7(cutoff)x7 del diario, dias_post>=CONF_DAYS. Cruce quiebre igual que Fase 0.

READ-ONLY: solo lee CSV + parquets, escribe resultados/gate_resultados.parquet + print.
"""
import re
from pathlib import Path
from datetime import timedelta

import pandas as pd

HERE = Path(__file__).parent
CACHE = HERE.parents[1] / 'proyectos' / '2026-05-27-harness-local' / 'cache'
CSV = (HERE.parents[1] / '02_forecast' / 'backtest-data-raw'
       / 'OH Forecast Backtest (x_forecast_backtest) 30-05.csv')

CONF_DAYS = 7
QB_SALAS = 3


def load_csv():
    for enc in ('utf-8', 'latin-1'):
        try:
            return pd.read_csv(CSV, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError('no encoding')


def main():
    df = load_csv()
    # pid numerico desde 'Descripción' (P<id>); robust al encoding del nombre de col
    desc_col = [c for c in df.columns if 'descrip' in c.lower()][0]
    df['pid'] = df[desc_col].astype(str).str.extract(r'P(\d+)').astype('Int64')
    df = df.dropna(subset=['pid'])
    df['pid'] = df['pid'].astype(int)
    df['target'] = pd.to_datetime(df['target_week_start'])
    for c in ('forecast_qty', 'real_qty'):
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

    # cervezas
    cat = pd.read_parquet(CACHE / 'catalog_products.parquet')
    cerv_ids = set(cat[cat['categ_complete_name'].astype(str)
                       .str.contains('Cerveza', case=False, na=False)]['id'])

    # eventos (cervezas con cambio de precio): pid -> fecha evento mas reciente
    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    pc['det'] = pd.to_datetime(pc['x_studio_target_week_start']).dt.date
    ev = {p: d for p, d in pc[pc['x_studio_var_pct'].abs() > 0.001]
          .groupby('product_id')['det'].max().items() if p in cerv_ids}

    # serie diaria -> MM7
    daily = pd.read_parquet(HERE / 'pos_daily_cerv.parquet')
    daily['day'] = pd.to_datetime(daily['day'])
    all_days = pd.date_range(daily['day'].min(), daily['day'].max(), freq='D')
    wide = daily.pivot_table(index='day', columns='product_id', values='qty',
                             aggfunc='sum').reindex(all_days, fill_value=0.0)
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

    # motor produccion = forecast_qty agregado por (pid, target); real = real_qty agregado
    g = df.groupby(['pid', 'target']).agg(motor=('forecast_qty', 'sum'),
                                          real=('real_qty', 'sum')).reset_index()

    detail = []
    for _, row in g.iterrows():
        p = int(row['pid'])
        if p not in cerv_ids:
            continue
        target = row['target']
        motor = float(row['motor']); r = float(row['real'])
        if motor <= 0 and r <= 0:
            continue
        cutoff = (target - timedelta(days=1))
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
        detail.append({'target': tgt, 'pid': p, 'motor': motor, 'ds': applied,
                       'real': r, 'estado': estado, 'has_evt': p in ev,
                       'quiebre': qt or qw})

    d = pd.DataFrame(detail)
    (HERE / 'resultados').mkdir(exist_ok=True)
    d.to_parquet(HERE / 'resultados' / 'gate_resultados.parquet', index=False)

    def wape(x, col):
        R = x['real'].sum()
        return abs(x[col] - x['real']).sum() / R * 100 if R else 0.0

    evt = d[d['has_evt']]
    evt_clean = evt[~evt['quiebre']]
    ds = evt[evt['estado'] == 'ds']
    ds_clean = ds[~ds['quiebre']]
    print("=" * 72)
    print("GATE vs PRODUCCION (forecast_qty con bias_outlier) — W20-22 (3 sem)")
    print("=" * 72)
    print(f"cervezas-evento filas: {len(evt)}  con quiebre: {int(evt['quiebre'].sum())} "
          f"({evt['quiebre'].mean()*100:.0f}%)  ds-activas: {len(ds)}")
    print(f"\nSOLO-EVENTO:")
    print(f"  TOTAL  motor_prod {wape(evt,'motor'):.1f}  ds {wape(evt,'ds'):.1f}  ({wape(evt,'ds')-wape(evt,'motor'):+.2f}pp)")
    print(f"  LIMPIO motor_prod {wape(evt_clean,'motor'):.1f}  ds {wape(evt_clean,'ds'):.1f}  ({wape(evt_clean,'ds')-wape(evt_clean,'motor'):+.2f}pp)  [sin quiebre]")
    print(f"\nDS-ACTIVO (post-confirmacion, dias_post>={CONF_DAYS}):")
    print(f"  TOTAL  motor_prod {wape(ds,'motor'):.1f}  ds {wape(ds,'ds'):.1f}  ({wape(ds,'ds')-wape(ds,'motor'):+.2f}pp)")
    print(f"  LIMPIO motor_prod {wape(ds_clean,'motor'):.1f}  ds {wape(ds_clean,'ds'):.1f}  ({wape(ds_clean,'ds')-wape(ds_clean,'motor'):+.2f}pp)  [sin quiebre]")
    print(f"\n  (n ds-activo limpio = {len(ds_clean)})")


if __name__ == '__main__':
    main()
