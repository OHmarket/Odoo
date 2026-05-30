"""
Backtest local 10 semanas, breakdown por regimen (REG-0..REG-8).

Para cada regimen muestra:
  - cantidad de SKUs (avg por semana)
  - WAPE / BIAS agregado 10 sem
  - Contribucion al WAPE total
  - Modelo dominante (forecast_model_code)
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


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    target_weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

    parts = []
    for target in target_weeks:
        cutoff = target - timedelta(days=1)
        print(f"\nCutoff {cutoff} -> Target {target}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)

        # Real qty
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        real = real.rename(columns={'qty_sold': 'real_qty'})

        merged = fc[['team_id', 'product_id', 'mu_week', 'regimen_eff',
                      'forecast_model_code', 'demand_method',
                      'abcxyz_eff', 'lifecycle_eff', 'series_type_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        ).fillna({'mu_week': 0.0, 'real_qty': 0.0})
        merged['target_week'] = target
        parts.append(merged)

    df = pd.concat(parts, ignore_index=True)
    print(f"\nTotal filas: {len(df):,}")

    # Si falta regimen_eff (par no en fc), categorizar como 'no_forecast'
    df['regimen_eff'] = df['regimen_eff'].fillna('NO_FC').replace('', 'NO_FC')

    print("\n" + "=" * 110)
    print("1. WAPE / BIAS por regimen (10 sem agregadas)")
    print("=" * 110)
    rows = []
    for reg, sub in df.groupby('regimen_eff'):
        real = sub['real_qty'].sum()
        fcst = sub['mu_week'].sum()
        ae = (sub['mu_week'] - sub['real_qty']).abs().sum()
        err = (sub['real_qty'] - sub['mu_week']).sum()
        wape = ae / real * 100 if real > 0 else 0.0
        bias = err / real * 100 if real > 0 else 0.0
        rows.append({
            'regimen': reg,
            'n_filas': len(sub),
            'n_sku_team_avg': round(len(sub) / 10),  # avg por semana
            'real': round(real, 0),
            'fcst': round(fcst, 0),
            'ae': round(ae, 0),
            'WAPE': round(wape, 1),
            'BIAS': round(bias, 1),
            'contrib_ae': 0,  # se rellena abajo
        })
    df_reg = pd.DataFrame(rows).sort_values('ae', ascending=False)
    total_ae = df_reg['ae'].sum()
    df_reg['contrib_ae'] = (df_reg['ae'] / total_ae * 100).round(1)
    print(df_reg.to_string(index=False))

    print("\n" + "=" * 110)
    print("2. Modelo dominante por regimen")
    print("=" * 110)
    pivot = df.groupby(['regimen_eff', 'forecast_model_code']).size().unstack(fill_value=0)
    print(pivot.to_string())

    print("\n" + "=" * 110)
    print("3. demand_method top 3 por regimen")
    print("=" * 110)
    for reg, sub in df.groupby('regimen_eff'):
        top3 = sub['demand_method'].value_counts().head(3)
        print(f"  {reg}:")
        for m, n in top3.items():
            pct = 100 * n / len(sub)
            print(f"    {m:40s} {n:>6,} ({pct:.1f}%)")

    print("\n" + "=" * 110)
    print("4. WAPE / BIAS por semana y regimen (las 4 regimenes que mas pesan)")
    print("=" * 110)
    top_regs = df_reg.head(4)['regimen'].tolist()
    rows4 = []
    for reg in top_regs:
        for wk, sub in df[df['regimen_eff'] == reg].groupby('target_week'):
            real = sub['real_qty'].sum()
            fcst = sub['mu_week'].sum()
            ae = (sub['mu_week'] - sub['real_qty']).abs().sum()
            err = (sub['real_qty'] - sub['mu_week']).sum()
            wape = ae / real * 100 if real > 0 else 0.0
            bias = err / real * 100 if real > 0 else 0.0
            rows4.append({
                'regimen': reg,
                'target_week': wk,
                'real': round(real, 0),
                'fcst': round(fcst, 0),
                'WAPE': round(wape, 1),
                'BIAS': round(bias, 1),
            })
    df4 = pd.DataFrame(rows4)
    print("\nWAPE por semana x regimen:")
    print(df4.pivot_table(index='target_week', columns='regimen', values='WAPE', aggfunc='mean').to_string())
    print("\nBIAS por semana x regimen:")
    print(df4.pivot_table(index='target_week', columns='regimen', values='BIAS', aggfunc='mean').to_string())

    out = RESULTS / "backtest_10_por_regimen.parquet"
    df_reg.to_parquet(out, index=False)
    print(f"\n  -> {out.name}")


if __name__ == "__main__":
    main()
