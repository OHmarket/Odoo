"""Diagnóstico cigarros: ¿el over-forecast viene de quiebres no detectados?

Detector proxy: una semana con qty=0 cuando el promedio histórico es > N.
Si el motor pronosticó algo y la realidad fue 0, sospechoso de quiebre.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

CIGARROS_CATEG_IDS = []  # se carga abajo


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    # Categorias de cigarros
    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    cig_cats = cats[cats['complete_name'].str.contains('Cigarrillos|Cigarros|Tabaco', case=False, na=False)]
    print(f"Categorias cigarrillos/tabaco: {len(cig_cats)}")
    for _, r in cig_cats.iterrows():
        print(f"  {r['categ_id_id']}: {r['complete_name']}")
    cig_ids = cig_cats['categ_id_id'].tolist()

    # Productos en esas categorias
    products = pd.read_parquet(CACHE / "catalog_products.parquet")
    cig_prods = products[products['categ_id_id'].isin(cig_ids)]
    print(f"\nProductos cigarros: {len(cig_prods)}")
    cig_pids = cig_prods['id'].tolist()

    # Demanda_norm: cuántos cigarros aparecen?
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})
    dn_cig = dn[dn['product_id'].isin(cig_pids)]
    print(f"\nFilas demanda_norm para cigarros (toda historia): {len(dn_cig):,}")
    print(f"  avail < 1.0 (censura): {(dn_cig['avail'] < 1.0).sum():,}")

    # POS cigarros sobre las 10 sem target
    pos_cig = pos[(pos['product_id'].isin(cig_pids)) &
                   (pos['week_start'].isin(TARGET_WEEKS))]
    print(f"\nPOS cigarros 10 sem: {len(pos_cig):,} filas")
    print(f"  qty_sold > 0: {(pos_cig['qty_sold'] > 0).sum():,}")
    print(f"  qty_sold == 0: {(pos_cig['qty_sold'] == 0).sum():,}")

    # Detector proxy: para cada (team, sku, target_week), comparar qty real
    # con promedio histórico 8 sem previas. Si real < 20% del promedio Y promedio > 1,
    # sospechoso de quiebre.
    print("\nDetector proxy de quiebre (cigarros, ventana 8 sem):")
    suspicious_rows = []
    for target in TARGET_WEEKS:
        prev_8w_start = target - timedelta(weeks=8)
        # historia previa
        hist = pos[(pos['product_id'].isin(cig_pids)) &
                    (pos['week_start'] >= prev_8w_start) &
                    (pos['week_start'] < target)]
        # promedio por (team, sku)
        avg = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
        avg = avg.rename(columns={'qty_sold': 'avg_8w'})

        target_data = pos_cig[pos_cig['week_start'] == target]
        # incluir pares con avg_8w > 0 aunque no aparezcan en target_data (qty=0 implicito)
        merged = avg.merge(target_data[['team_id', 'product_id', 'qty_sold']],
                            on=['team_id', 'product_id'], how='left')
        merged['qty_sold'] = merged['qty_sold'].fillna(0.0)
        merged['target_week'] = target
        merged['suspicious'] = (merged['avg_8w'] > 1.0) & (merged['qty_sold'] < 0.2 * merged['avg_8w'])
        suspicious_rows.append(merged)

    susp = pd.concat(suspicious_rows, ignore_index=True)
    n_susp = susp['suspicious'].sum()
    print(f"  Pares (team, sku, sem) con avg_8w>1 y real<20% del avg: {n_susp:,}")
    print(f"  Total pares con avg_8w>1: {(susp['avg_8w'] > 1.0).sum():,}")
    print(f"  Pct sospechoso: {n_susp / max(1, (susp['avg_8w'] > 1.0).sum()) * 100:.1f}%")

    # Comparar con demanda_norm para esos pares
    dn_cig_target = dn_cig[dn_cig['week_start'].isin(TARGET_WEEKS)]
    print(f"\n  demanda_norm marca como censurado en cigarros 10 sem: {(dn_cig_target['avail'] < 1.0).sum():,}")
    print(f"  Detector proxy marca como sospechoso: {n_susp:,}")
    print(f"  -> Si proxy >> demanda_norm, hay censura sub-detectada")

    # AE total cigarros con/sin filtro proxy
    print("\n" + "=" * 90)
    print("AE cigarros con distintos filtros")
    print("=" * 90)
    # Re-correr baseline para tener fcst
    print("\n  Corriendo baseline 10 sem...")
    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        fc_cig = fc[fc['categ_id'].isin(cig_ids)][['team_id', 'product_id', 'mu_week']]
        real_w = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        m = fc_cig.merge(real_w, on=['team_id', 'product_id'], how='outer').fillna(0.0)
        m['target_week'] = target
        # Agregar avail
        dn_w = dn_cig_target[dn_cig_target['week_start'] == target][['team_id', 'product_id', 'avail']]
        m = m.merge(dn_w, on=['team_id', 'product_id'], how='left')
        m['demanda_norm_censored'] = m['avail'].notna() & (m['avail'] < 1.0)
        # Agregar proxy_suspicious
        susp_w = susp[susp['target_week'] == target][['team_id', 'product_id', 'suspicious', 'avg_8w']]
        m = m.merge(susp_w, on=['team_id', 'product_id'], how='left')
        m['suspicious'] = m['suspicious'].fillna(False)
        m['avg_8w'] = m['avg_8w'].fillna(0.0)
        parts.append(m)
        print(f"    cutoff {cutoff} OK")
    df = pd.concat(parts, ignore_index=True)

    def metrics(d):
        r = d['qty_sold'].sum()
        f = d['mu_week'].sum()
        ae = (d['mu_week'] - d['qty_sold']).abs().sum()
        err = (d['qty_sold'] - d['mu_week']).sum()
        return r, f, ae, (ae/r*100 if r > 0 else 0), (err/r*100 if r > 0 else 0)

    r, f, ae, w, b = metrics(df)
    print(f"\n  ALL cigarros:                       real={r:>7,.0f}  fcst={f:>7,.0f}  AE={ae:>7,.0f}  WAPE={w:>5.1f}%  BIAS={b:>+5.1f}%")
    d1 = df[~df['demanda_norm_censored']]
    r, f, ae, w, b = metrics(d1)
    print(f"  excl. demanda_norm censura (actual): real={r:>7,.0f}  fcst={f:>7,.0f}  AE={ae:>7,.0f}  WAPE={w:>5.1f}%  BIAS={b:>+5.1f}%")
    d2 = df[~df['demanda_norm_censored'] & ~df['suspicious']]
    r, f, ae, w, b = metrics(d2)
    print(f"  excl. dn + PROXY sospechoso:         real={r:>7,.0f}  fcst={f:>7,.0f}  AE={ae:>7,.0f}  WAPE={w:>5.1f}%  BIAS={b:>+5.1f}%")

    # Cuántos cambia
    print(f"\n  Filas excluidas extras por proxy: {df['suspicious'].sum() - df['demanda_norm_censored'].sum() - df.query('suspicious and demanda_norm_censored').shape[0] + df['demanda_norm_censored'].sum():,}")
    print(f"  Pares marcados solo por proxy (no por dn): {(df['suspicious'] & ~df['demanda_norm_censored']).sum():,}")


if __name__ == "__main__":
    main()
