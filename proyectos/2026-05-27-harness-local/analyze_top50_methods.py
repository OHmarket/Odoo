"""
Para cada (team, sku, target_week) del top 50: identificar qué modelo del
bake-off ganó (heur SMA, sba, croston, seasonal_naive). Cruzar con BIAS
direccional y categoria para ver patrones.

Hipótesis a validar:
- ¿En cervezas premium con BIAS+ (sub-forecast), qué modelo gana?
- ¿El bake-off elige el modelo que sub-pronostica o el motor lo elige bien
  pero la realidad sobrepasa todas las estimaciones?

Re-corre baseline 10 sem GUARDANDO detalle demand_method.
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

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]


def main():
    top50 = pd.read_parquet(RESULTS / "top50_classified.parquet")
    top50_pids = set(top50['product_id'].tolist())
    print(f"Top 50 SKUs: {len(top50_pids)}")

    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    print("\nCorriendo baseline 10 sem con detalle por (sku, sem)...")
    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  cutoff {cutoff}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        # Filtrar a top 50
        fc = fc[fc['product_id'].isin(top50_pids)].copy()
        real = pos[(pos['week_start'] == target) & (pos['product_id'].isin(top50_pids))][['team_id', 'product_id', 'qty_sold']]
        m = fc[['team_id', 'product_id', 'mu_week', 'mu_base', 'si_factor',
                 'demand_method', 'forecast_model_code', 'regimen_eff',
                 'abcxyz_eff', 'categ_id', 'trend_factor']].merge(
            real, on=['team_id', 'product_id'], how='left'
        ).fillna({'qty_sold': 0.0})
        m['target_week'] = target
        m['error'] = m['qty_sold'] - m['mu_week']
        m['abs_error'] = m['error'].abs()
        parts.append(m)
    df = pd.concat(parts, ignore_index=True)
    print(f"\nFilas top 50 × 10 sem: {len(df):,}")

    # Categoria short
    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")[['categ_id_id', 'complete_name']]
    cats = cats.rename(columns={'categ_id_id': 'categ_id'})
    df = df.merge(cats, on='categ_id', how='left')
    df['categ_short'] = df['complete_name'].str.split(' / ').str[2].fillna(
        df['complete_name'].str.split(' / ').str[1]
    ).fillna('OTROS')

    # Demand method simplificado
    def model_family(method):
        if not isinstance(method, str):
            return 'unknown'
        if method.startswith('sma'):
            return 'sma_heur'
        if method.startswith('blend_down'):
            return 'sma_heur'
        if method.startswith('sba'):
            return 'sba'
        if method.startswith('croston'):
            return 'croston'
        if method.startswith('seasonal_naive'):
            return 'sn_52'
        return method
    df['model_family'] = df['demand_method'].apply(model_family)

    print("\n" + "=" * 100)
    print("Distribución de modelos del bake-off en top 50 (10 sem × ~12 teams)")
    print("=" * 100)
    print(df['model_family'].value_counts().to_string())

    print("\n" + "=" * 100)
    print("Modelos por categoría (cervezas) y BIAS direccional")
    print("=" * 100)
    df['bias_dir'] = df.apply(
        lambda r: 'SUB' if r['error'] > 0 else 'OVER' if r['error'] < 0 else 'ZERO',
        axis=1,
    )
    cerv = df[df['categ_short'].str.contains('Cerveza', na=False)]
    print(f"\nFilas cervezas: {len(cerv):,}")

    # Por (categ_short, model_family, bias_dir)
    by_method = cerv.groupby(['categ_short', 'model_family']).agg(
        n=('mu_week', 'size'),
        ae=('abs_error', 'sum'),
        err=('error', 'sum'),
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
    ).reset_index()
    by_method['WAPE'] = (by_method['ae'] / by_method['real'] * 100).where(by_method['real'] > 0, 0).round(1)
    by_method['BIAS'] = (by_method['err'] / by_method['real'] * 100).where(by_method['real'] > 0, 0).round(1)
    print("\n(categ, model_family) en cervezas - top 50:")
    print(by_method.sort_values('ae', ascending=False).to_string(index=False))

    # Análisis específico: en cervezas con BIAS+ (Stella, Budweiser, etc), ¿qué modelo gana?
    print("\n" + "=" * 100)
    print("Detalle: cervezas con BIAS+ promedio")
    print("=" * 100)
    sku_bias = top50[['product_id', 'default_code', 'product_name', 'BIAS']]
    bias_pos_skus = sku_bias[(sku_bias['BIAS'] > 10)].copy()
    print(f"\nSKUs en top 50 con BIAS > +10: {len(bias_pos_skus):,}")
    df_bp = df[df['product_id'].isin(bias_pos_skus['product_id'])]
    method_in_bp = df_bp.groupby('model_family').agg(
        n=('mu_week', 'size'),
        ae=('abs_error', 'sum'),
        bias=('error', 'mean'),
    ).round(2)
    print(method_in_bp.to_string())

    # Patrón temporal: ¿el sub-forecast es uniforme o pico semanal?
    print("\n" + "=" * 100)
    print("Distribución de error por semana en top 50 (sumando todos)")
    print("=" * 100)
    by_week = df.groupby('target_week').agg(
        n=('mu_week', 'size'),
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        ae=('abs_error', 'sum'),
        err=('error', 'sum'),
    )
    by_week['WAPE'] = (by_week['ae'] / by_week['real'] * 100).round(1)
    by_week['BIAS'] = (by_week['err'] / by_week['real'] * 100).round(1)
    print(by_week.to_string())

    df.to_parquet(RESULTS / "top50_methods_detail.parquet", index=False)
    print(f"\n -> top50_methods_detail.parquet")


if __name__ == "__main__":
    main()
