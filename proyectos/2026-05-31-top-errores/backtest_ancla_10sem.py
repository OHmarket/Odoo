"""
Fase 1 robustez — backtest 10 semanas en el harness: motor vs motor+ancla.

CORREGIDO: el flag es por RECENCIA DE DETECCION (no anacronico): para target tw,
se ancla un SKU si tuvo evento de precio detectado en [tw-8sem, tw]. Usa solo
detecciones pasadas respecto al target -> sin fuga de informacion del futuro.

Baseline = motor del harness (SIN bias_outlier). Mide si el ancla gana sobre el
motor limpio en 10 semanas con SI variado.
"""
import sys
import statistics
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / 'proyectos' / '2026-05-27-harness-local'
CACHE = HARNESS / 'cache'
sys.path.insert(0, str(HARNESS))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache  # noqa: E402

N_WIN = 4
RECENCY_WK = 8


def main():
    pos, _ = load_cache(CACHE)
    pos = pos.copy()
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    pos_sku = pos.groupby(['product_id', 'week_start'])['qty_sold'].sum()
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    cerv_ids = set(prod[prod['categ_complete_name'].astype(str).str.contains('Cerveza', case=False, na=False)]['id'])
    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    pc['det'] = pd.to_datetime(pc['x_studio_target_week_start']).dt.date
    det_week = pc[pc['x_studio_var_pct'].abs() > 0.001].groupby('product_id')['det'].max().to_dict()

    def anchor(pid, cutoff):
        try:
            s = pos_sku.loc[pid]
        except KeyError:
            return None
        prev = list(s[s.index <= cutoff].tail(N_WIN))
        return statistics.median(prev) if prev else None

    target_weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]
    rows = []
    for target in target_weeks:
        cutoff = target - timedelta(days=1)
        # flag por recencia: detectado en [target-8sem, target]
        flagged = {pid for pid, dw in det_week.items()
                   if 0 <= (target - dw).days / 7 <= RECENCY_WK}
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        mot = fc.groupby('product_id')['mu_week'].sum()
        real = pos[pos['week_start'] == target].groupby('product_id')['qty_sold'].sum()
        skus = sorted(set(mot.index) | set(real.index))
        d = pd.DataFrame({'pid': skus})
        d['motor'] = d['pid'].map(mot).fillna(0.0)
        d['real'] = d['pid'].map(real).fillna(0.0)
        d['cerv'] = d['pid'].isin(cerv_ids)
        d['flag'] = d['pid'].isin(flagged)
        d['anchor'] = [anchor(p, cutoff) if f else None for p, f in zip(d['pid'], d['flag'])]
        d['adj'] = d['motor'].where(d['anchor'].isna(), d['anchor'])

        def wape(col, mask=None):
            x = d if mask is None else d[mask]
            r = x['real'].sum()
            return (x[col] - x['real']).abs().sum() / r * 100 if r > 0 else 0.0
        wm, wa = wape('motor'), wape('adj')
        cm, ca = wape('motor', d['cerv']), wape('adj', d['cerv'])
        rows.append({'target': str(target),
                     'WAPE_mot': round(wm, 1), 'WAPE_anc': round(wa, 1), 'dG': round(wa - wm, 1),
                     'cerv_mot': round(cm, 1), 'cerv_anc': round(ca, 1), 'dC': round(ca - cm, 1),
                     'n_flag': int(d['flag'].sum()), 'n_anc': int(d['anchor'].notna().sum())})
        print(f"  {target}  GLOBAL {wm:5.1f}->{wa:5.1f} ({wa-wm:+.1f})   cerv {cm:5.1f}->{ca:5.1f} ({ca-cm:+.1f})   flag={d['flag'].sum()}")

    df = pd.DataFrame(rows)
    print("\n" + "=" * 78)
    print(df.to_string(index=False))
    print(f"\n  Semanas ancla GANA: global {(df['dG']<0).sum()}/10   cerveza {(df['dC']<0).sum()}/10")
    print(f"  Avg dWAPE global: {df['dG'].mean():+.2f}pp   cerveza: {df['dC'].mean():+.2f}pp")
    df.to_parquet(Path(__file__).parent / 'resultados_ancla_10sem.parquet', index=False)


if __name__ == '__main__':
    main()
