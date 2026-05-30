"""
Test 2: Calibración estructural por (categoria, ABC letter)

Hipótesis: ciertas categorías tienen BIAS estructural persistente. Aplicar
factor multiplicativo por (categ, abc_letter) elimina ese sesgo sistemático.

Proceso:
1. Calcular factor = real_clean / fcst_clean por cluster sobre 10 sem baseline
2. Excluir cigarros/snack/impulso + filas con quiebre
3. Aplicar solo a clusters con: >= 500 unidades reales, |1-factor|>=5%
4. Clamp [0.70, 1.30]
5. Re-correr backtest 10 sem aplicando factor post-trend
6. Comparar baseline vs Test 1 (tuning) vs Test 2 (categ calib)
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']
MIN_REAL_UNITS = 500
FACTOR_CLAMP_LOW = 0.70
FACTOR_CLAMP_HIGH = 1.30
APPLY_THRESHOLD = 0.05  # solo aplicar si |factor-1| >= 5%

TUNED_TEST1 = {
    "SERVICE_BASE_SHORT_WEEKS": 4,
    "SERVICE_BASE_LONG_WEEKS": 16,
    "SERVICE_RATIO_COLLAPSE": 0.40,
    "SERVICE_RATIO_HOLD": 0.90,
    "SERVICE_DOWN_W_SHORT": 0.5,
    "HEUR_BIAS": 0.80,
    "CROSTON_ALPHA": 0.25,
    "SBA_ALPHA": 0.20,
    "SI_CEIL": 3.0,
    "SI_SKU_ADJ_ALPHA_HIGH": 0.20,
    "SI_MIN_YEARS_FOR_SKU": 2,
    "FAIR_SHARE_TRIED_PENALTY": 0.05,
}


def detect_quiebres(pos, target_weeks):
    """Devuelve set (team, sku, week) marcados como quiebre."""
    hist_from = target_weeks[0] - timedelta(weeks=8)
    hist = pos[(pos['week_start'] >= hist_from) & (pos['week_start'] < target_weeks[0])]
    avg = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg.columns = ['team_id', 'product_id', 'avg_8w']

    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})

    quiebres = set()
    for wk in target_weeks:
        pos_w = pos[pos['week_start'] == wk][['team_id', 'product_id', 'qty_sold']]
        merged = avg.merge(pos_w, on=['team_id', 'product_id'], how='left').fillna({'qty_sold': 0.0})
        merged['thresh'] = merged['avg_8w'].apply(lambda x: max(0.2 * x, 0.5))
        proxy = merged[(merged['avg_8w'] >= 1.0) & (merged['qty_sold'] < merged['thresh'])]
        for _, r in proxy.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))
        dn_w = dn[(dn['week_start'] == wk) & (dn['avail'] < 1.0)]
        for _, r in dn_w.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))
    return quiebres


def run_backtest(config_override, label, pos, quiebres):
    """Corre 10 sem con config_override, devuelve concat con detalle."""
    print(f"\n[{label}]")
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(config_override)
    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  cutoff {cutoff}")
        fc = run(cutoff_date=cutoff, config=cfg, cache_dir=CACHE)
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
    return pd.concat(parts, ignore_index=True)


def calc_metrics(df, value='mu_week', real='qty_sold'):
    r = df[real].sum()
    f = df[value].sum()
    ae = (df[value] - df[real]).abs().sum()
    err = (df[real] - df[value]).sum()
    return {
        'real': r, 'fcst': f, 'ae': ae,
        'WAPE': round(ae/r*100 if r > 0 else 0, 2),
        'BIAS': round(err/r*100 if r > 0 else 0, 2),
    }


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())
    print(f"Categorias excluidas: {len(excl_cat_ids)}")

    print("\nDetectando quiebres...")
    quiebres = detect_quiebres(pos, TARGET_WEEKS)
    print(f"  {len(quiebres):,}")

    # 1. Backtest BASELINE (necesario para calcular factores)
    df_b = run_backtest({}, "baseline v3.46", pos, quiebres)

    # 2. Calcular factores por (categ, abc_letter) sobre baseline
    df_clean = df_b[~df_b['categ_id'].isin(excl_cat_ids) & ~df_b['is_quiebre']].copy()
    df_clean['abc_letter'] = df_clean['abcxyz_eff'].str.slice(0, 1).fillna('')
    df_clean = df_clean[df_clean['categ_id'].notna() & (df_clean['abc_letter'] != '')]

    grouped = df_clean.groupby(['categ_id', 'abc_letter']).agg(
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
    ).reset_index()
    grouped['raw_factor'] = grouped['real'] / grouped['fcst'].replace(0, 1)
    grouped['clamped'] = grouped['raw_factor'].clip(FACTOR_CLAMP_LOW, FACTOR_CLAMP_HIGH)
    grouped['apply'] = (grouped['real'] >= MIN_REAL_UNITS) & \
                       ((grouped['clamped'] - 1.0).abs() >= APPLY_THRESHOLD)

    print(f"\nClusters (categ, abc): {len(grouped):,}")
    print(f"  Aplicables (real>={MIN_REAL_UNITS}, |factor-1|>={APPLY_THRESHOLD}): {grouped['apply'].sum():,}")

    factors = {}
    for _, r in grouped[grouped['apply']].iterrows():
        factors[(int(r['categ_id']), r['abc_letter'])] = float(r['clamped'])

    print(f"\nFactores activos: {len(factors)}")
    # Mostrar top 20
    show = grouped[grouped['apply']].merge(
        cats[['categ_id_id', 'complete_name']].rename(columns={'categ_id_id': 'categ_id'}),
        on='categ_id', how='left'
    ).sort_values('real', ascending=False)
    show['complete_name'] = show['complete_name'].str.slice(0, 50)
    print("\nTop 20 factores (ordenado por real):")
    print(show[['categ_id', 'complete_name', 'abc_letter', 'real', 'raw_factor', 'clamped']].head(20).to_string(index=False))

    # 3. Aplicar factores al baseline para simular Test 2
    def apply_categ_factor(row):
        if pd.isna(row['team_id']) or pd.isna(row['categ_id']) or pd.isna(row['abcxyz_eff']):
            return row['mu_week']
        letter = row['abcxyz_eff'][:1] if row['abcxyz_eff'] else ''
        key = (int(row['categ_id']), letter)
        return row['mu_week'] * factors.get(key, 1.0)

    print("\nAplicando factores al baseline (simulación Test 2)...")
    df_b['mu_week_test2'] = df_b.apply(apply_categ_factor, axis=1)

    # 4. Backtest Test 1 (tuning hyperparams) — para comparar
    df_t1 = run_backtest(TUNED_TEST1, "Test 1 (tuning hyperparams)", pos, quiebres)

    # 5. Comparativa
    print("\n" + "=" * 100)
    print("COMPARATIVA: baseline vs Test 1 vs Test 2 (categ calib)")
    print("=" * 100)

    # Sin quiebres
    bc = df_b[~df_b['is_quiebre']]
    tc1 = df_t1[~df_t1['is_quiebre']]
    print("\nSin quiebres (toda categoria):")
    mb = calc_metrics(bc)
    m1 = calc_metrics(tc1)
    m2 = calc_metrics(bc, value='mu_week_test2')
    print(f"  baseline v3.46:   WAPE={mb['WAPE']:>5.2f}  BIAS={mb['BIAS']:>+5.2f}  fcst={mb['fcst']:,.0f}")
    print(f"  Test 1 (tuning):  WAPE={m1['WAPE']:>5.2f}  BIAS={m1['BIAS']:>+5.2f}  fcst={m1['fcst']:,.0f}")
    print(f"  Test 2 (categ):   WAPE={m2['WAPE']:>5.2f}  BIAS={m2['BIAS']:>+5.2f}  fcst={m2['fcst']:,.0f}")
    print(f"\n  Δ Test 1 vs baseline: WAPE={m1['WAPE']-mb['WAPE']:+.2f}pp  BIAS={m1['BIAS']-mb['BIAS']:+.2f}pp")
    print(f"  Δ Test 2 vs baseline: WAPE={m2['WAPE']-mb['WAPE']:+.2f}pp  BIAS={m2['BIAS']-mb['BIAS']:+.2f}pp")

    # Por categoria foco (cervezas)
    print("\n" + "=" * 100)
    print("Comparativa en CERVEZAS (sin cigarros/snack)")
    print("=" * 100)
    cerv_ids = set(cats[cats['complete_name'].str.contains('Cervezas', case=False, na=False)]['categ_id_id'].tolist())
    bc_cer = bc[bc['categ_id'].isin(cerv_ids)]
    tc1_cer = tc1[tc1['categ_id'].isin(cerv_ids)]
    print(f"  Filas: {len(bc_cer):,}")
    mb_c = calc_metrics(bc_cer)
    m1_c = calc_metrics(tc1_cer)
    m2_c = calc_metrics(bc_cer, value='mu_week_test2')
    print(f"  baseline v3.46:   WAPE={mb_c['WAPE']:>5.2f}  BIAS={mb_c['BIAS']:>+5.2f}  fcst={mb_c['fcst']:,.0f}")
    print(f"  Test 1 (tuning):  WAPE={m1_c['WAPE']:>5.2f}  BIAS={m1_c['BIAS']:>+5.2f}  fcst={m1_c['fcst']:,.0f}")
    print(f"  Test 2 (categ):   WAPE={m2_c['WAPE']:>5.2f}  BIAS={m2_c['BIAS']:>+5.2f}  fcst={m2_c['fcst']:,.0f}")

    # Por semana
    print("\n" + "=" * 100)
    print("Por semana (sin quiebres)")
    print("=" * 100)
    for wk in TARGET_WEEKS:
        b = bc[bc['target_week'] == wk]
        t1 = tc1[tc1['target_week'] == wk]
        mb_w = calc_metrics(b)
        m1_w = calc_metrics(t1)
        m2_w = calc_metrics(b, value='mu_week_test2')
        print(f"  {wk}: baseline WAPE={mb_w['WAPE']:>5.2f} BIAS={mb_w['BIAS']:>+5.2f}  |  T1 WAPE={m1_w['WAPE']:>5.2f} BIAS={m1_w['BIAS']:>+5.2f}  |  T2 WAPE={m2_w['WAPE']:>5.2f} BIAS={m2_w['BIAS']:>+5.2f}")

    # Guardar
    out_json = RESULTS / "test_2_categ_factors.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({
            'meta': {
                'method': 'categ_id+abc_letter factor = real/fcst sobre 10 sem baseline',
                'window_weeks': len(TARGET_WEEKS),
                'window_start': str(TARGET_WEEKS[0]),
                'window_end': str(TARGET_WEEKS[-1]),
                'excluded_cats': sorted(excl_cat_ids),
                'min_real_units': MIN_REAL_UNITS,
                'clamp_low': FACTOR_CLAMP_LOW,
                'clamp_high': FACTOR_CLAMP_HIGH,
                'apply_threshold_pct': APPLY_THRESHOLD,
                'n_factors': len(factors),
            },
            'factors': {f"{k[0]}|{k[1]}": v for k, v in factors.items()},
            'comparativa': {
                'baseline':   {'WAPE': mb['WAPE'],  'BIAS': mb['BIAS']},
                'test_1':     {'WAPE': m1['WAPE'],  'BIAS': m1['BIAS']},
                'test_2':     {'WAPE': m2['WAPE'],  'BIAS': m2['BIAS']},
                'cervezas_baseline': {'WAPE': mb_c['WAPE'], 'BIAS': mb_c['BIAS']},
                'cervezas_test_1':   {'WAPE': m1_c['WAPE'], 'BIAS': m1_c['BIAS']},
                'cervezas_test_2':   {'WAPE': m2_c['WAPE'], 'BIAS': m2_c['BIAS']},
            },
        }, f, indent=2, ensure_ascii=False)
    print(f"\n -> {out_json}")


if __name__ == "__main__":
    main()
