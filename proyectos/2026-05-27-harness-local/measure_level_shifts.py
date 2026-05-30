"""
Medir level shifts en los top 50 SKUs problemáticos.

Para cada (team, sku) del top 50, calcular sobre la serie weekly:
  - SMA(4) ultimas 4 sem
  - SMA(16) ultimas 16 sem
  - ratio_recent = SMA(4) / SMA(16)

Si ratio > 1.25 -> shift UP (subida de nivel reciente que motor no captura)
Si ratio < 0.75 -> shift DOWN (caida que motor sub-detecta)

Reportar cuántos SKUs/pares (team, sku) muestran este patrón en las 10 sem
target. Cuanto más alto el ratio en SKUs con BIAS+ (sub-forecast), más
fuerte la hipótesis Marco.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

SHORT_W = 4
LONG_W = 16
THRESH_UP = 1.25
THRESH_DOWN = 0.75


def main():
    # Top 50 SKUs ya filtrados (sin cigarros/snack + sin alto quiebre)
    top50 = pd.read_parquet(RESULTS / "top50_classified.parquet")
    top50_pids = top50['product_id'].tolist()
    print(f"Top 50 SKUs a analizar: {len(top50_pids):,}")

    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    # Para cada (team, sku, target_week): calcular SMA(4) y SMA(16) hasta cutoff
    # (sin incluir target_week)
    results = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        for pid in top50_pids:
            sku_pos = pos[(pos['product_id'] == pid) &
                          (pos['week_start'] < target)].sort_values('week_start')
            # Por team
            for team_id in sku_pos['team_id'].unique():
                if pd.isna(team_id):
                    continue
                tp = sku_pos[sku_pos['team_id'] == team_id]['qty_sold'].tolist()
                if len(tp) < LONG_W:
                    continue
                short_vals = tp[-SHORT_W:]
                long_vals = tp[-LONG_W:]
                sma_short = sum(short_vals) / len(short_vals)
                sma_long = sum(long_vals) / len(long_vals)
                if sma_long < 0.5:
                    continue  # serie muy chica
                ratio = sma_short / sma_long
                results.append({
                    'target_week': target,
                    'team_id': int(team_id),
                    'product_id': pid,
                    'sma_short': round(sma_short, 2),
                    'sma_long': round(sma_long, 2),
                    'ratio': round(ratio, 3),
                    'shift_up': ratio > THRESH_UP,
                    'shift_down': ratio < THRESH_DOWN,
                })

    df = pd.DataFrame(results)
    print(f"\nTotal pares (team, sku, sem) evaluados: {len(df):,}")
    print(f"  Shift UP   (ratio > {THRESH_UP}): {df['shift_up'].sum():,} ({df['shift_up'].mean()*100:.1f}%)")
    print(f"  Shift DOWN (ratio < {THRESH_DOWN}): {df['shift_down'].sum():,} ({df['shift_down'].mean()*100:.1f}%)")
    print(f"  Estable (entre thresholds): {(~df['shift_up'] & ~df['shift_down']).sum():,}")

    # Cruzar con BIAS del top 50: hipótesis Marco
    # Los SKUs con BIAS+ (motor sub-pronostica) deberían tener más shift UP
    top50_bias = top50[['product_id', 'BIAS']]
    df = df.merge(top50_bias, on='product_id', how='left')
    df['bias_signed'] = df['BIAS'].apply(lambda b: 'SUB' if b > 5 else 'OVER' if b < -5 else 'CENTERED')

    print("\n" + "=" * 90)
    print("Hipótesis: SKUs con BIAS+ (sub-forecast) tienen shift UP más frecuente")
    print("=" * 90)
    cross = df.groupby(['bias_signed', 'shift_up', 'shift_down']).size().reset_index(name='n')
    print(cross.to_string(index=False))

    print("\nPct shift UP por dir BIAS:")
    pct_up = df.groupby('bias_signed')['shift_up'].mean() * 100
    pct_dn = df.groupby('bias_signed')['shift_down'].mean() * 100
    for bs in pct_up.index:
        print(f"  {bs}: shift_up={pct_up[bs]:.1f}%  shift_down={pct_dn[bs]:.1f}%")

    # Resumen por SKU: cuántas semanas de las 10 muestran shift
    by_sku = df.groupby('product_id').agg(
        n_pares=('target_week', 'size'),
        n_shift_up=('shift_up', 'sum'),
        n_shift_down=('shift_down', 'sum'),
        avg_ratio=('ratio', 'mean'),
    ).reset_index()
    by_sku = by_sku.merge(
        top50[['product_id', 'default_code', 'product_name', 'WAPE', 'BIAS', 'abcxyz_eff']],
        on='product_id', how='left'
    )
    by_sku['pct_shift_up'] = (by_sku['n_shift_up'] / by_sku['n_pares'] * 100).round(0)
    by_sku['pct_shift_down'] = (by_sku['n_shift_down'] / by_sku['n_pares'] * 100).round(0)
    by_sku = by_sku.sort_values('pct_shift_up', ascending=False)

    print("\n" + "=" * 110)
    print("Top 20 SKUs por % de pares con shift UP")
    print("=" * 110)
    print(by_sku.head(20)[['default_code', 'product_name', 'abcxyz_eff', 'WAPE', 'BIAS',
                           'avg_ratio', 'pct_shift_up', 'pct_shift_down']].to_string(index=False))

    df.to_parquet(RESULTS / "level_shifts_top50.parquet", index=False)
    by_sku.to_parquet(RESULTS / "level_shifts_by_sku.parquet", index=False)
    print(f"\n -> level_shifts_top50.parquet")
    print(f" -> level_shifts_by_sku.parquet")


if __name__ == "__main__":
    main()
