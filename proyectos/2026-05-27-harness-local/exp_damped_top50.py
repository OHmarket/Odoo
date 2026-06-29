"""
Detalle por SKU: efecto de damped en los top 50 outliers de REG-1 (mayor error
absoluto en 10 sem) y en el subset donde damped fue efectivamente elegido.
A/B mismo conjunto de SKUs.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"
DAMPED_CFG = {'regimenes': {'REG-1'}, 'alpha': 0.25, 'beta': 0.10, 'phi': 0.90, 'r2_min': 0.15}


def arm_detail(damped, pos, weeks):
    cfg = dict(DEFAULT_CONFIG); cfg['DAMPED'] = damped
    parts = []
    mcol = None
    for target in weeks:
        cutoff = target - timedelta(days=1)
        fc = run(cutoff_date=cutoff, config=cfg, cache_dir=CACHE)
        if mcol is None:
            mcol = 'demand_method' if 'demand_method' in fc.columns else 'method'
        d = fc[fc['regimen_eff'] == 'REG-1'][['team_id', 'product_id', 'mu_week', mcol]].copy()
        d = d.rename(columns={mcol: 'method'})
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']].rename(
            columns={'qty_sold': 'real_qty'})
        d = d.merge(real, on=['team_id', 'product_id'], how='left')
        d['real_qty'] = d['real_qty'].fillna(0.0)
        d['target'] = str(target)
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy(); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

    print("base..."); base = arm_detail(None, pos, weeks)
    print("damped..."); damp = arm_detail(DAMPED_CFG, pos, weeks)

    m = base.merge(
        damp[['target', 'team_id', 'product_id', 'mu_week', 'method']],
        on=['target', 'team_id', 'product_id'], suffixes=('_base', '_damp'))
    m['ae_base'] = (m['mu_week_base'] - m['real_qty']).abs()
    m['ae_damp'] = (m['mu_week_damp'] - m['real_qty']).abs()

    g = m.groupby(['team_id', 'product_id']).agg(
        real=('real_qty', 'sum'),
        ae_base=('ae_base', 'sum'),
        ae_damp=('ae_damp', 'sum'),
        n_damped=('method_damp', lambda s: int((s == 'damped').sum())),
    ).reset_index()
    g['d_ae'] = g['ae_damp'] - g['ae_base']

    def wape(d):
        r = d['real'].sum(); return d['ae_base'].sum() / r * 100, d['ae_damp'].sum() / r * 100

    print("\n" + "=" * 90)
    top = g.sort_values('ae_base', ascending=False).head(50)
    wb, wd = wape(top)
    print(f"TOP 50 OUTLIERS REG-1 (mayor error abs, 10 sem)  | vol real {top['real'].sum():,.0f}")
    print(f"  WAPE: base {wb:.1f}% -> damped {wd:.1f}%  ({wd - wb:+.2f}pp)")
    print(f"  error abs total: {top['ae_base'].sum():,.0f} -> {top['ae_damp'].sum():,.0f}  ({top['d_ae'].sum():+,.0f})")
    print(f"  mejoran {(top['d_ae'] < -0.5).sum()}/50 | empeoran {(top['d_ae'] > 0.5).sum()}/50 | damped elegido en {(top['n_damped'] > 0).sum()}/50")

    print("\n" + "=" * 90)
    ch = g[g['n_damped'] > 0]
    wb2, wd2 = wape(ch)
    print(f"SUBSET damped ELEGIDO  | {len(ch)} SKUs, vol real {ch['real'].sum():,.0f}")
    print(f"  WAPE: base {wb2:.1f}% -> damped {wd2:.1f}%  ({wd2 - wb2:+.2f}pp)")
    print(f"  mejoran {(ch['d_ae'] < -0.5).sum()} | empeoran {(ch['d_ae'] > 0.5).sum()} | iguales {((ch['d_ae'].abs() <= 0.5)).sum()}")

    print("\nTop 15 outliers (detalle):")
    sh = top.head(15).copy()
    sh['wape_b'] = (sh['ae_base'] / sh['real'].clip(lower=1e-9) * 100).round(0)
    sh['wape_d'] = (sh['ae_damp'] / sh['real'].clip(lower=1e-9) * 100).round(0)
    print(sh[['team_id', 'product_id', 'real', 'wape_b', 'wape_d', 'n_damped', 'd_ae']].to_string(index=False))

    g.to_parquet(RESULTS / "exp_damped_top50.parquet", index=False)
    print("\n-> resultados/exp_damped_top50.parquet")


if __name__ == "__main__":
    main()
