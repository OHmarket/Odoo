"""
Calibración automática por (categoria, abcxyz_letter) usando histórico.

Proceso:
1. Backtest baseline 10 sem -> obtener fcst vs real (sin quiebres)
2. Excluir cigarros/snack/impulso
3. Agrupar por (categ_id, abcxyz_letter) y calcular factor = real/fcst
4. Filtrar clusters significativos (>= 500 unidades reales agregadas)
5. Aplicar clamp [0.70, 1.30] al factor (evita extremos)
6. Guardar como JSON para uso del motor

Resultado: dict {(categ_id, abcxyz_letter): factor_corr}

Aplicación en motor (v3.48 propuesto): post-trend, pre-redondeo,
   mu_week *= categ_bias_factor.get((categ_id, abc_letter), 1.0)
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

# Categorias excluidas del análisis (problemas conocidos de proveedor)
EXCLUDE_CATEG_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']

# Constraints
MIN_REAL_UNITS = 500       # cluster debe tener al menos 500 unidades reales agregadas
FACTOR_CLAMP_LOW = 0.70
FACTOR_CLAMP_HIGH = 1.30
MAX_QUIEBRE_PCT = 0.30     # excluir SKUs con >30% quiebre en sus filas


def _detect_quiebre(pos, target_weeks):
    """Devuelve set de (team, sku, week) marcados como quiebre por proxy o dn."""
    hist_from = target_weeks[0] - timedelta(weeks=8)
    hist = pos[(pos['week_start'] >= hist_from) & (pos['week_start'] < target_weeks[0])]
    avg = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg = avg.rename(columns={'qty_sold': 'avg_8w'})

    # demanda_norm
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})

    quiebres = set()
    for wk in target_weeks:
        # proxy
        pos_w = pos[pos['week_start'] == wk][['team_id', 'product_id', 'qty_sold']]
        merged = avg.merge(pos_w, on=['team_id', 'product_id'], how='left')
        merged['qty_sold'] = merged['qty_sold'].fillna(0.0)
        merged['thresh'] = merged['avg_8w'].apply(lambda x: max(0.2 * x, 0.5))
        proxy = merged[(merged['avg_8w'] >= 1.0) & (merged['qty_sold'] < merged['thresh'])]
        for _, r in proxy.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))
        # dn
        dn_w = dn[(dn['week_start'] == wk) & (dn['avail'] < 1.0)]
        for _, r in dn_w.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))
    return quiebres


def main():
    print("=" * 80)
    print("Cálculo factores de calibración por (categoria, ABC letter)")
    print("=" * 80)

    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    # Cargar categorias y filtrar excluidas
    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cats = cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_CATEG_KEYWORDS), case=False, na=False
    )]
    excl_cat_ids = set(excl_cats['categ_id_id'].tolist())
    print(f"Categorias excluidas: {len(excl_cat_ids)}")

    # Detectar quiebres una vez
    print("\nDetectando quiebres por proxy + demanda_norm...")
    quiebres = _detect_quiebre(pos, TARGET_WEEKS)
    print(f"  Marcados como quiebre: {len(quiebres):,}")

    # Backtest baseline 10 sem
    print("\nBacktest baseline v3.46 sobre 10 sem...")
    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  cutoff {cutoff}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        m = fc[['team_id', 'product_id', 'categ_id', 'mu_week',
                 'abcxyz_eff', 'regimen_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        ).fillna({'mu_week': 0.0, 'qty_sold': 0.0})
        m['target_week'] = target
        m['is_quiebre'] = m.apply(
            lambda r: (int(r['team_id']), int(r['product_id']), target) in quiebres
                       if pd.notna(r['team_id']) and pd.notna(r['product_id'])
                       else False,
            axis=1,
        )
        parts.append(m)
    df = pd.concat(parts, ignore_index=True)

    print(f"\nTotal filas: {len(df):,}")
    print(f"  Con quiebre: {df['is_quiebre'].sum():,} ({df['is_quiebre'].mean()*100:.1f}%)")

    # Excluir cigarros/snack + quiebres
    df_clean = df[~df['categ_id'].isin(excl_cat_ids) & ~df['is_quiebre']].copy()
    print(f"  Sin cigarros/snack + sin quiebres: {len(df_clean):,}")

    # ABC letter
    df_clean['abc_letter'] = df_clean['abcxyz_eff'].str.slice(0, 1).fillna('')

    # Agregar por (categ_id, abc_letter)
    df_clean = df_clean[df_clean['categ_id'].notna() & (df_clean['abc_letter'] != '')]
    grouped = df_clean.groupby(['categ_id', 'abc_letter']).agg(
        n=('qty_sold', 'size'),
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
    ).reset_index()
    grouped['raw_factor'] = grouped['real'] / grouped['fcst'].replace(0, 1)
    grouped['clamped_factor'] = grouped['raw_factor'].clip(FACTOR_CLAMP_LOW, FACTOR_CLAMP_HIGH)
    grouped['bias_pct'] = ((grouped['real'] - grouped['fcst']) / grouped['real'] * 100).round(1)

    # Filtrar clusters significativos
    significant = grouped[(grouped['real'] >= MIN_REAL_UNITS) &
                           (grouped['raw_factor'].between(0.50, 2.00))].copy()
    # Solo aplicar factor si la corrección es material (>=5% desviación)
    significant['apply'] = (significant['clamped_factor'] - 1.0).abs() >= 0.05

    # Merge con nombre categ
    significant = significant.merge(
        cats[['categ_id_id', 'complete_name']].rename(columns={'categ_id_id': 'categ_id'}),
        on='categ_id', how='left'
    )

    print(f"\n{len(significant):,} clusters (categ, abc) con >= {MIN_REAL_UNITS} units reales")
    print(f"  Con corrección material (>=5%): {significant['apply'].sum():,}")

    # Top clusters por magnitud de corrección
    print("\n" + "=" * 110)
    print("TOP CLUSTERS CON CORRECCIÓN APLICABLE")
    print("=" * 110)
    show = significant[significant['apply']].sort_values('real', ascending=False).copy()
    show['complete_name'] = show['complete_name'].str.slice(0, 50)
    cols = ['categ_id', 'complete_name', 'abc_letter', 'n', 'real', 'fcst',
             'raw_factor', 'clamped_factor', 'bias_pct']
    print(show[cols].head(30).to_string(index=False))

    # Guardar JSON con factores
    factors_dict = {}
    for _, r in significant[significant['apply']].iterrows():
        key = f"{int(r['categ_id'])}|{r['abc_letter']}"
        factors_dict[key] = round(float(r['clamped_factor']), 4)

    out_json = RESULTS / "calib_categ_factors.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({
            'meta': {
                'method': 'real/fcst por (categ_id, abc_letter)',
                'window_weeks': len(TARGET_WEEKS),
                'window_start': str(TARGET_WEEKS[0]),
                'window_end': str(TARGET_WEEKS[-1]),
                'excluded_categs': sorted(excl_cat_ids),
                'min_real_units': MIN_REAL_UNITS,
                'clamp_low': FACTOR_CLAMP_LOW,
                'clamp_high': FACTOR_CLAMP_HIGH,
                'apply_threshold_pct': 0.05,
                'n_clusters_applied': len(factors_dict),
            },
            'factors': factors_dict,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n -> {out_json}")
    print(f" Total clusters con factor aplicable: {len(factors_dict)}")


if __name__ == "__main__":
    main()
