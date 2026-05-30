"""
Backtest local sobre 10 semanas cerradas (W12 a W21 de 2026).

Para cada target_week:
  - cutoff = domingo previo
  - corre HM_SI_local con DEFAULT_CONFIG
  - compara mu_week vs real_qty del cache
  - reporta WAPE / BIAS

Sin comparacion vs Odoo (no tenemos backtest oficial de 10 sem).
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


def metrics(df, value_col='mu_week', real_col='real_qty'):
    real = df[real_col].sum()
    fcst = df[value_col].sum()
    ae = (df[value_col] - df[real_col]).abs().sum()
    err = (df[real_col] - df[value_col]).sum()
    wape = ae / real * 100 if real > 0 else 0.0
    bias = err / real * 100 if real > 0 else 0.0
    return wape, bias, real, fcst


def main():
    print("=" * 100)
    print("Backtest local 10 semanas")
    print("=" * 100)

    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    # Target weeks: 10 mas recientes
    target_weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

    rows = []
    for target in target_weeks:
        cutoff = target - timedelta(days=1)
        print(f"\n--- Cutoff={cutoff}  Target={target} ---")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)

        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        real = real.rename(columns={'qty_sold': 'real_qty'})

        merged = fc[['team_id', 'product_id', 'mu_week']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        ).fillna(0.0)

        # Sin filtro noise (overall)
        wape_all, bias_all, real_all, fcst_all = metrics(merged)
        rows.append({
            'target_week': target,
            'n_skus': len(merged),
            'real': round(real_all, 0),
            'fcst': round(fcst_all, 0),
            'WAPE': round(wape_all, 1),
            'BIAS': round(bias_all, 1),
        })
        print(f"  WAPE: {wape_all:.1f}%  BIAS: {bias_all:+.1f}%  real: {real_all:,.0f}  fcst: {fcst_all:,.0f}")

    df = pd.DataFrame(rows)
    print()
    print("=" * 100)
    print("RESUMEN 10 SEMANAS")
    print("=" * 100)
    print()
    print(df.to_string(index=False))

    # Promedios
    print(f"\n  Avg WAPE: {df['WAPE'].mean():.1f}%")
    print(f"  Avg BIAS: {df['BIAS'].mean():+.1f}%")
    print(f"  Median WAPE: {df['WAPE'].median():.1f}%")
    print(f"  Total real: {df['real'].sum():,.0f}")
    print(f"  Total fcst: {df['fcst'].sum():,.0f}")
    print(f"  Total BIAS aggregated: {(df['real'].sum() - df['fcst'].sum()) / df['real'].sum() * 100:+.1f}%")

    out = RESULTS / "backtest_10_semanas.parquet"
    df.to_parquet(out, index=False)
    print(f"\n  -> {out.name}")


if __name__ == "__main__":
    main()
