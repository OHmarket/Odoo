"""
Top 50 errores significativos:
  1. Excluir cigarros + snack + impulso (problemas de stock con proveedor)
  2. Detectar quiebres por proxy (avg_prev>=1, qty_target < 20% avg)
  3. Quedarme con SKUs cuyo error NO se explica por quiebre
  4. Clasificar por patron (categ, abcxyz, regimen, direccion BIAS)
  5. Reportar grupos dominantes para diseñar regla GENERAL

Objetivo: identificar 2-3 patrones que expliquen mayoría del top 50,
diseñar una regla GENERAL por segmento (no por SKU).
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']


def main():
    # 1. Pareto existente (con filtro dn censura ya aplicado)
    pareto = pd.read_parquet(RESULTS / "pareto_sku_10w.parquet")
    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")

    print(f"Universo pareto inicial: {len(pareto):,} SKUs, AE total {pareto['ae'].sum():,.0f}")

    # 2. Excluir cigarros + snack + impulso
    cig_snack_cats = cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]
    excl_cat_ids = set(cig_snack_cats['categ_id_id'].tolist())
    print(f"\nExcluyendo categorias ({len(excl_cat_ids)}):")
    for _, r in cig_snack_cats.iterrows():
        print(f"  {r['categ_id_id']}: {r['complete_name']}")

    pareto_f = pareto[~pareto['categ_id'].isin(excl_cat_ids)].copy()
    print(f"\nDespues de filtro cigarros/snack: {len(pareto_f):,} SKUs, AE total {pareto_f['ae'].sum():,.0f}")
    print(f"  Reduccion AE: -{(pareto['ae'].sum() - pareto_f['ae'].sum()):,.0f}")

    # 3. Detector proxy de quiebres: para cada SKU del top, ver si en las 10 sem
    # tuvo semanas con qty muy bajo vs historia. Esto requiere ver detalle (sku, semana).
    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    hist_from = TARGET_WEEKS[0] - timedelta(weeks=8)

    # avg histórico por (team, sku)
    hist = pos[(pos['week_start'] >= hist_from) & (pos['week_start'] < TARGET_WEEKS[0])]
    avg_hist = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg_hist.columns = ['team_id', 'product_id', 'avg_prev_8w']

    # Cargar demanda_norm censura
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})
    dn_10w = dn[dn['week_start'].isin(TARGET_WEEKS)][['team_id', 'product_id', 'week_start', 'avail']]

    # POS target_weeks
    pos_target = pos[pos['week_start'].isin(TARGET_WEEKS)]

    # Para cada (team, sku, week_target): marcar como quiebre si avg_prev>=1 y qty<thresh,
    # o si avail<1 en dn.
    target_pairs = []
    for wk in TARGET_WEEKS:
        # Producto cartesiano de (team, sku) con avg_prev_8w >= 1 y la semana
        active = avg_hist[avg_hist['avg_prev_8w'] >= 1.0].copy()
        active['week_start'] = wk
        target_pairs.append(active)
    grid = pd.concat(target_pairs, ignore_index=True)

    # Merge con pos para qty real
    grid = grid.merge(pos_target[['team_id', 'product_id', 'week_start', 'qty_sold']],
                       on=['team_id', 'product_id', 'week_start'], how='left')
    grid['qty_sold'] = grid['qty_sold'].fillna(0.0)
    # Merge con dn para avail
    grid = grid.merge(dn_10w, on=['team_id', 'product_id', 'week_start'], how='left')
    grid['thresh'] = grid['avg_prev_8w'].apply(lambda x: max(0.2 * x, 0.5))
    grid['quiebre_proxy'] = grid['qty_sold'] < grid['thresh']
    grid['dn_censored'] = grid['avail'].notna() & (grid['avail'] < 1.0)
    grid['is_quiebre'] = grid['quiebre_proxy'] | grid['dn_censored']

    print(f"\nGrid evaluado (team, sku, semana con avg_prev>=1): {len(grid):,}")
    print(f"  quiebre_proxy (qty < 20%*avg): {grid['quiebre_proxy'].sum():,} ({grid['quiebre_proxy'].mean()*100:.1f}%)")
    print(f"  dn_censored (motor productivo marca): {grid['dn_censored'].sum():,} ({grid['dn_censored'].mean()*100:.1f}%)")
    print(f"  cualquiera: {grid['is_quiebre'].sum():,} ({grid['is_quiebre'].mean()*100:.1f}%)")

    # AE excluido por SKU: cuanto AE "se cae" cuando excluimos quiebres
    # Re-agregar pos sin quiebre - ah pero esto requiere recalcular AE por SKU. Mejor:
    # marcar SKUs cuyo % de filas con quiebre es alto en las 10 sem.
    sku_quiebre = grid.groupby('product_id')['is_quiebre'].mean().reset_index()
    sku_quiebre.columns = ['product_id', 'pct_quiebre']

    pareto_f = pareto_f.merge(sku_quiebre, on='product_id', how='left')
    pareto_f['pct_quiebre'] = pareto_f['pct_quiebre'].fillna(0.0)

    # SKUs con >=30% de quiebre en sus filas
    pareto_f['affected_by_quiebre'] = pareto_f['pct_quiebre'] >= 0.30

    print(f"\nSKUs en pareto filtrado con >=30% quiebre: {pareto_f['affected_by_quiebre'].sum():,} de {len(pareto_f):,}")

    # 4. Top 50 sin cigarros/snack y con bajo % de quiebre
    candidates = pareto_f[~pareto_f['affected_by_quiebre']].sort_values('ae', ascending=False)
    top50 = candidates.head(50).copy()
    total_ae = pareto['ae'].sum()
    print(f"\nTop 50 (sin cigarros/snack + bajo quiebre): suma AE = {top50['ae'].sum():,.0f} ({top50['ae'].sum()/total_ae*100:.1f}% del AE total)")

    # 5. Clasificar por (categ, abcxyz, direccion BIAS, magnitud WAPE)
    top50['bias_dir'] = top50['BIAS'].apply(
        lambda b: 'SUB (motor pronostica menos)' if b > 5
              else 'OVER (motor pronostica mas)' if b < -5
              else 'CENTRADO')
    top50['wape_bucket'] = top50['WAPE'].apply(
        lambda w: 'extremo (>150)' if w > 150
              else 'alto (75-150)' if w > 75
              else 'medio (40-75)' if w > 40
              else 'bajo (<40)')

    print("\n" + "=" * 110)
    print("TOP 50 - clasificacion por (categoria, abcxyz, direccion BIAS)")
    print("=" * 110)

    # Top categorias en top50
    print("\nDistribucion categoria:")
    by_cat = top50.groupby('categ_name').agg(n=('product_id', 'size'), ae=('ae', 'sum')).sort_values('ae', ascending=False)
    print(by_cat.to_string())

    # Distribucion abcxyz
    print("\nDistribucion abcxyz:")
    print(top50.groupby('abcxyz_eff').agg(n=('product_id', 'size'), ae=('ae', 'sum')).sort_values('ae', ascending=False).to_string())

    # Distribucion direccion BIAS
    print("\nDistribucion direccion BIAS:")
    print(top50.groupby('bias_dir').agg(n=('product_id', 'size'), ae=('ae', 'sum')).sort_values('ae', ascending=False).to_string())

    # Cluster: (categ_short, abcxyz, bias_dir)
    top50['categ_short'] = top50['categ_name'].str.split(' / ').str[1].fillna('OTROS')
    print("\nCluster (categ_short, abcxyz, bias_dir):")
    clust = top50.groupby(['categ_short', 'abcxyz_eff', 'bias_dir']).agg(
        n=('product_id', 'size'), ae=('ae', 'sum')
    ).sort_values('ae', ascending=False)
    print(clust.head(15).to_string())

    # Top 50 detalle (compacto)
    print("\n" + "=" * 110)
    print("Top 50 detalle compacto")
    print("=" * 110)
    cols = ['default_code', 'product_name', 'categ_short', 'abcxyz_eff', 'WAPE', 'BIAS', 'ae', 'pct_quiebre']
    detail = top50[cols].copy()
    detail['product_name'] = detail['product_name'].str.slice(0, 35)
    print(detail.to_string(index=False))

    top50.to_parquet(RESULTS / "top50_classified.parquet", index=False)
    print(f"\n -> {RESULTS / 'top50_classified.parquet'}")


if __name__ == "__main__":
    main()
