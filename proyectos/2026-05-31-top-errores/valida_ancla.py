"""
Fase 1 — Validacion del ancla a mediana reciente para SKU con evento de precio.

Mecanismo: para SKU marcado con evento, reemplazar el forecast por la MEDIANA
de las ultimas N semanas de venta real (no multiplicar por un factor).

Datos: backtest server 30-05 (forecast + real de produccion, con bias_outlier ON)
        + venta semanal del cache harness (verificado == server en W20-22).

Corre todo read-only. Resultado esperado (2026-05-31):
  - calibracion: mediana N4 sweet spot (N6 media = la del motor, es PEOR que nada)
  - no-regresion: anclar los 671 SKU marcados -> GLOBAL -4.3pp, cervezas -6.3pp
  - genuino: el ancla gana sobre el motor CON y SIN bias_outlier
  - consistente: gana las 3 semanas
"""
import re
import datetime
import statistics
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'proyectos' / '2026-05-27-harness-local' / 'cache'
CSV = ROOT / '02_forecast' / 'backtest-data-raw' / 'OH Forecast Backtest (x_forecast_backtest) 30-05.csv'
N_WIN = 4  # ventana del ancla (semanas), calibrado


def code_of(s):
    m = re.match(r'\[([^\]]+)\]', str(s))
    return m.group(1) if m else None


def load():
    df = pd.read_csv(CSV, encoding='latin-1')
    for c in ['real_qty', 'forecast_qty', 'mu_week_pre_bias']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['tw'] = pd.to_datetime(df['target_week_start']).dt.date
    df['code'] = df['product_id'].apply(code_of)
    bt = df.groupby(['code', 'tw']).agg(
        real=('real_qty', 'sum'), fcst=('forecast_qty', 'sum'),
        prebias=('mu_week_pre_bias', 'sum'),
        iscerv=('categ_id', lambda s: s.astype(str).str.contains('Cerveza').any())).reset_index()
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    code2id = dict(zip(prod['default_code'].astype(str), prod['id']))
    pos = pd.read_parquet(CACHE / 'pos_weekly.parquet')
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    pos_sku = pos.groupby(['product_id', 'week_start'])['qty_sold'].sum()
    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    evt = set(pc[pc['x_studio_var_pct'].abs() > 0.001]['product_id'])
    bt['pid'] = bt['code'].map(code2id)
    bt['has_evt'] = bt['pid'].isin(evt)
    return bt, pos_sku


def anchor(pos_sku, pid, tw, n=N_WIN, stat='median'):
    cutoff = tw - datetime.timedelta(days=1)
    try:
        s = pos_sku.loc[pid]
    except KeyError:
        return None
    prev = list(s[s.index <= cutoff].tail(n))
    if not prev:
        return None
    return statistics.median(prev) if stat == 'median' else sum(prev) / len(prev)


def wape(d, col):
    return abs(d[col] - d['real']).sum() / d['real'].sum() * 100


def main():
    bt, pos_sku = load()
    bt['anchor'] = bt.apply(
        lambda r: anchor(pos_sku, r['pid'], r['tw']) if (r['has_evt'] and pd.notna(r['pid'])) else None, axis=1)
    bt['adj'] = bt['fcst'].where(bt['anchor'].isna(), bt['anchor'])
    cerv = bt['iscerv']
    n_sku = bt[bt['has_evt']]['code'].nunique()
    print(f'SKU marcados con evento: {n_sku}  (mediana N={N_WIN})\n')
    print(f"  {'forecast':<22}{'GLOBAL':>8}{'cervezas':>10}")
    print(f"  {'motor (prod)':<22}{wape(bt,'fcst'):>7.1f}%{wape(bt[cerv],'fcst'):>9.1f}%")
    print(f"  {'+ ancla mediana-4':<22}{wape(bt,'adj'):>7.1f}%{wape(bt[cerv],'adj'):>9.1f}%")
    print('\n  por semana (gana si baja):')
    for wk in sorted(set(bt['tw'])):
        d = bt[bt['tw'] == wk]
        print(f"    {wk}  GLOBAL {wape(d,'fcst'):.1f}->{wape(d,'adj'):.1f}"
              f"   cerv {wape(d[d['iscerv']],'fcst'):.1f}->{wape(d[d['iscerv']],'adj'):.1f}")


if __name__ == '__main__':
    main()
