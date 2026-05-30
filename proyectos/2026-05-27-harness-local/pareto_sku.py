"""
Análisis Pareto: dónde se concentra el error absoluto del motor sobre 10 semanas.

Si pocos SKUs dominan el AE, atacarlos directamente da más palanca que tuning
general de hyperparams.

Output:
  - Top 30 SKUs con detalle: nombre, categ, regimen, AE, BIAS, contribucion %
  - Cumulative pct: X SKUs explican Y% del AE
  - Top 10 categorias
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


def run_baseline_10w():
    """Corre baseline_v3.46 sobre 10 semanas, devuelve concat con detalle."""
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})[['team_id', 'product_id', 'week_start', 'avail']]

    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  cutoff {cutoff}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        m = fc[['team_id', 'product_id', 'categ_id', 'mu_week', 'regimen_eff',
                 'abcxyz_eff', 'forecast_model_code']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        )
        m['target_week'] = target
        m['qty_sold'] = m['qty_sold'].fillna(0.0)
        m['mu_week'] = m['mu_week'].fillna(0.0)
        dn_wk = dn[dn['week_start'] == target][['team_id', 'product_id', 'avail']]
        m = m.merge(dn_wk, on=['team_id', 'product_id'], how='left')
        m['is_censored'] = m['avail'].notna() & (m['avail'] < 1.0)
        parts.append(m)
    return pd.concat(parts, ignore_index=True)


def main():
    print("Backtest baseline v3.46 sobre 10 semanas (DETALLE por SKU)...")
    df = run_baseline_10w()
    print(f"\nFilas: {len(df):,}")
    df = df[~df['is_censored']].copy()  # filtro quiebre
    print(f"Sin censura: {len(df):,}")

    # Cargar catalog + abcxyz para enriquecer
    cat_prods = pd.read_parquet(CACHE / "catalog_products.parquet")[['id', 'default_code', 'name']]
    cat_prods = cat_prods.rename(columns={'id': 'product_id', 'name': 'product_name'})
    cat_cats = pd.read_parquet(CACHE / "catalog_categories.parquet")[['categ_id_id', 'complete_name']]
    cat_cats = cat_cats.rename(columns={'categ_id_id': 'categ_id', 'complete_name': 'categ_name'})

    df = df.merge(cat_prods, on='product_id', how='left')
    df = df.merge(cat_cats, on='categ_id', how='left')

    # AE por SKU (sumando 10 sem × 12 teams)
    df['abs_error'] = (df['mu_week'] - df['qty_sold']).abs()
    df['err'] = df['qty_sold'] - df['mu_week']  # positivo = sub-forecast

    by_sku = df.groupby(['product_id', 'default_code', 'product_name', 'categ_id', 'categ_name', 'abcxyz_eff']).agg(
        n=('abs_error', 'size'),
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        ae=('abs_error', 'sum'),
        err=('err', 'sum'),
    ).reset_index()
    by_sku['WAPE'] = (by_sku['ae'] / by_sku['real'] * 100).where(by_sku['real'] > 0, 0).round(1)
    by_sku['BIAS'] = (by_sku['err'] / by_sku['real'] * 100).where(by_sku['real'] > 0, 0).round(1)

    by_sku = by_sku.sort_values('ae', ascending=False).reset_index(drop=True)
    total_ae = by_sku['ae'].sum()
    by_sku['contrib_pct'] = (by_sku['ae'] / total_ae * 100).round(2)
    by_sku['cumul_pct'] = by_sku['contrib_pct'].cumsum().round(2)

    print("\n" + "=" * 130)
    print(f"PARETO POR SKU (AE total = {total_ae:,.0f})")
    print("=" * 130)

    # Puntos clave del Pareto
    print("\n  Cumulative pct alcanzado:")
    for threshold in [25, 50, 75, 90]:
        idx = (by_sku['cumul_pct'] >= threshold).idxmax()
        n_skus = idx + 1
        pct = by_sku.iloc[idx]['cumul_pct']
        print(f"    {threshold}% AE alcanzado en SKU #{n_skus:>4,}  ({n_skus/len(by_sku)*100:.1f}% del universo)")

    print(f"\n  Total SKUs: {len(by_sku):,}")
    print(f"  Total real (10 sem, sin censura): {by_sku['real'].sum():,.0f}")
    print(f"  Total fcst: {by_sku['fcst'].sum():,.0f}")
    print(f"  WAPE global: {total_ae / by_sku['real'].sum() * 100:.2f}%")

    print("\n" + "=" * 130)
    print("TOP 30 SKUs por AE")
    print("=" * 130)
    cols_show = ['default_code', 'product_name', 'categ_name', 'abcxyz_eff',
                  'real', 'fcst', 'ae', 'contrib_pct', 'cumul_pct', 'WAPE', 'BIAS']
    top30 = by_sku.head(30)[cols_show].copy()
    # Truncar nombres largos
    top30['product_name'] = top30['product_name'].str.slice(0, 35)
    top30['categ_name'] = top30['categ_name'].str.slice(0, 30)
    print(top30.to_string(index=False))

    # Top categorias
    print("\n" + "=" * 130)
    print("TOP 15 CATEGORIAS por AE")
    print("=" * 130)
    by_cat = by_sku.groupby(['categ_id', 'categ_name']).agg(
        n_skus=('product_id', 'size'),
        real=('real', 'sum'),
        fcst=('fcst', 'sum'),
        ae=('ae', 'sum'),
        err=('err', 'sum'),
    ).reset_index()
    by_cat['WAPE'] = (by_cat['ae'] / by_cat['real'] * 100).where(by_cat['real'] > 0, 0).round(1)
    by_cat['BIAS'] = (by_cat['err'] / by_cat['real'] * 100).where(by_cat['real'] > 0, 0).round(1)
    by_cat['contrib_pct'] = (by_cat['ae'] / total_ae * 100).round(2)
    by_cat = by_cat.sort_values('ae', ascending=False).reset_index(drop=True)
    by_cat['cumul_pct'] = by_cat['contrib_pct'].cumsum().round(2)
    top15c = by_cat.head(15).copy()
    top15c['categ_name'] = top15c['categ_name'].str.slice(0, 50)
    print(top15c.to_string(index=False))

    # SKU 9407 Stella - estaba en el caso original?
    print("\n" + "=" * 130)
    print("CASOS ESPECIFICOS")
    print("=" * 130)
    stella = by_sku[by_sku['default_code'] == '9407']
    if not stella.empty:
        s = stella.iloc[0]
        rank = stella.index[0] + 1
        print(f"  SKU 9407 Stella 660cc:  rank #{rank}  AE={s['ae']:.0f}  contrib={s['contrib_pct']:.2f}%  WAPE={s['WAPE']:.1f}%  BIAS={s['BIAS']:+.1f}%")

    by_sku.to_parquet(RESULTS / "pareto_sku_10w.parquet", index=False)
    by_cat.to_parquet(RESULTS / "pareto_categ_10w.parquet", index=False)
    print(f"\n -> resultados/pareto_sku_10w.parquet ({len(by_sku):,} SKUs)")
    print(f" -> resultados/pareto_categ_10w.parquet ({len(by_cat):,} categs)")


if __name__ == "__main__":
    main()
