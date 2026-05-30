"""Diagnóstico rápido cigarros: usa parquet pareto + dn + pos para detectar
quiebres no marcados en demanda_norm.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]


def main():
    # 1. Categorias cigarros/tabaco
    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    cig_cats = cats[cats['complete_name'].str.contains('Cigarrillos|Cigarros|Tabaco', case=False, na=False)]
    cig_cat_ids = set(cig_cats['categ_id_id'].tolist())
    print(f"Categorias cigarros/tabaco: {len(cig_cat_ids)}")
    for _, r in cig_cats.iterrows():
        print(f"  {r['categ_id_id']}: {r['complete_name']}")

    # 2. SKUs cigarros
    prods = pd.read_parquet(CACHE / "catalog_products.parquet")
    cig_prods = prods[prods['categ_id_id'].isin(cig_cat_ids)]
    cig_pids = set(cig_prods['id'].tolist())
    print(f"\nSKUs en cigarros/tabaco: {len(cig_pids):,}")

    # 3. Pareto agregado actual (incluye filtro demanda_norm censurado)
    pareto = pd.read_parquet(RESULTS / "pareto_sku_10w.parquet")
    cig_in_pareto = pareto[pareto['product_id'].isin(cig_pids)]
    print(f"\nCigarros en pareto (sin censura dn): {len(cig_in_pareto):,}")
    print(f"  AE total cigarros: {cig_in_pareto['ae'].sum():,.0f}")
    print(f"  Real cigarros: {cig_in_pareto['real'].sum():,.0f}")
    print(f"  Fcst cigarros: {cig_in_pareto['fcst'].sum():,.0f}")
    bias = (cig_in_pareto['real'].sum() - cig_in_pareto['fcst'].sum()) / cig_in_pareto['real'].sum() * 100
    wape = cig_in_pareto['ae'].sum() / cig_in_pareto['real'].sum() * 100
    print(f"  WAPE: {wape:.1f}%  BIAS: {bias:+.1f}%")

    # 4. POS por (team, sku, target_week) para cigarros
    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    pos_cig = pos[pos['product_id'].isin(cig_pids)].copy()
    pos_cig_10w = pos_cig[pos_cig['week_start'].isin(TARGET_WEEKS)]
    print(f"\nPOS cigarros 10 sem: {len(pos_cig_10w):,}")

    # 5. demanda_norm
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})
    dn_cig_10w = dn[(dn['product_id'].isin(cig_pids)) & (dn['week_start'].isin(TARGET_WEEKS))]
    censored = (dn_cig_10w['avail'] < 1.0).sum()
    print(f"  demanda_norm marca censurado en cigarros 10 sem: {censored:,}")

    # 6. Detector proxy: para cada (team, sku) con venta en HISTORIA (8 sem previas
    # a las 10 sem target), ver cuántas veces qty=0 en target_weeks.
    # Si patrón: venta consistente prev → 0 puntual → venta otra vez = quiebre
    hist_from = TARGET_WEEKS[0] - timedelta(weeks=8)
    pos_cig_hist = pos_cig[(pos_cig['week_start'] >= hist_from) & (pos_cig['week_start'] < TARGET_WEEKS[0])]
    avg_prev = pos_cig_hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg_prev = avg_prev.rename(columns={'qty_sold': 'avg_prev_8w'})

    # Productos cigarros con venta significativa previa
    active_prev = avg_prev[avg_prev['avg_prev_8w'] >= 1.0]
    print(f"\n  (team, sku) cigarros con avg_prev_8w >= 1 unidad: {len(active_prev):,}")

    # Para cada (team, sku) activo, contar semanas target con qty<20% del avg
    # como proxy de quiebre
    proxy_susp_pairs = 0
    proxy_susp_filas = 0
    for _, r in active_prev.iterrows():
        t, p, avg = int(r['team_id']), int(r['product_id']), r['avg_prev_8w']
        thresh = max(0.2 * avg, 0.5)  # threshold mínimo: 0.5 unidad
        sub = pos_cig_10w[(pos_cig_10w['team_id'] == t) & (pos_cig_10w['product_id'] == p)]
        # Filas en target_weeks donde qty < thresh
        weeks_in_target = set(sub['week_start'].tolist())
        weeks_missing = set(TARGET_WEEKS) - weeks_in_target  # son qty=0 implicito
        for wk in TARGET_WEEKS:
            if wk in weeks_missing:
                proxy_susp_filas += 1  # qty=0 implícito
            else:
                row = sub[sub['week_start'] == wk]
                if not row.empty and row['qty_sold'].iloc[0] < thresh:
                    proxy_susp_filas += 1

    # Total pares (team, sku, sem) con avg_prev>=1
    total_target = len(active_prev) * 10
    print(f"\n  Pares (team, sku, sem) con avg_prev>=1 y real<20%*avg: {proxy_susp_filas:,} de {total_target:,}")
    print(f"  Pct sospechoso por proxy: {proxy_susp_filas/total_target*100:.1f}%")
    print(f"  Pct marcado por demanda_norm: {censored/total_target*100:.1f}%")
    print(f"\n  -> Si proxy >> dn, hay quiebres no detectados")

    # 7. Detalle por SKU top cigarros: qué pasó por semana
    print("\n" + "=" * 100)
    print("Top 10 cigarros por AE: detalle por semana")
    print("=" * 100)
    top_cig = cig_in_pareto.nlargest(10, 'ae')
    for _, sku in top_cig.iterrows():
        pid = int(sku['product_id'])
        # POS por semana este SKU (agregado a todos los teams)
        pos_sku = pos_cig_10w[pos_cig_10w['product_id'] == pid]
        weekly = pos_sku.groupby('week_start')['qty_sold'].sum()
        # avg histórico
        hist_sku = pos_cig_hist[pos_cig_hist['product_id'] == pid]
        avg_hist = hist_sku.groupby('week_start')['qty_sold'].sum().mean() if len(hist_sku) else 0
        print(f"\n  [{sku['default_code']}] {sku['product_name'][:50]}  avg_hist={avg_hist:.0f}/sem")
        print(f"  ABCXYZ={sku['abcxyz_eff']}  WAPE={sku['WAPE']:.0f}%  BIAS={sku['BIAS']:+.0f}%  AE={sku['ae']:.0f}")
        for wk in TARGET_WEEKS:
            q = weekly.get(wk, 0.0)
            marker = ' QUIEBRE?' if q < 0.2 * avg_hist and avg_hist > 1 else ''
            print(f"    {wk}: qty={q:>7.0f}{marker}")


if __name__ == "__main__":
    main()
