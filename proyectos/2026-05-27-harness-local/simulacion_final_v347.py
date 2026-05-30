"""
Simulacion final v3.47: efectos combinados de Test 1 (tuning hyperparams) y
Test 2 (categ_calib) aplicados al motor productivo HM-SI v3.46.

4 configs comparadas sobre la misma ventana de 10 sem:
  A. baseline v3.46          (motor sin ajustes)
  B. Test 1 (tuning)         (12 hyperparams retunes - Fase 1..4 de Marco)
  C. v3.47 categ_calib       (baseline + factores categ_id x abc_letter)
  D. combo Test 1 + calib    (tuning hyperparams + categ_calib)

Premisas:
  - Excluir cigarros / snack / impulso (problemas de stock proveedor).
  - Excluir filas con quiebre real en target_week (no medir error contra
    venta censurada).
  - Cervezas es el foco. Reportar separado.

Outputs:
  - resultados/simulacion_final_v347.txt           (reporte legible)
  - resultados/simulacion_final_v347_detail.parquet (detalle por fila)
  - resultados/simulacion_final_v347_summary.json   (resumen estructurado)
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

# SKU testigo Stella 9407 (lag de nivel confirmado en drill)
TESTIGO_PRODUCT_ID = 11797

# Hyperparams Test 1 (Fase 1..4 de Marco).
TUNED_TEST1 = {
    # Fase 1: SMA blend
    "SERVICE_BASE_SHORT_WEEKS": 4,      # era 6
    "SERVICE_BASE_LONG_WEEKS":  16,     # igual
    "SERVICE_RATIO_COLLAPSE":   0.40,   # era 0.30
    "SERVICE_RATIO_HOLD":       0.90,   # igual
    "SERVICE_DOWN_W_SHORT":     0.50,   # era 0.70
    # Fase 2: bake-off Croston/SBA
    "HEUR_BIAS":                0.80,   # era 0.90
    "CROSTON_ALPHA":            0.25,   # era 0.10
    "SBA_ALPHA":                0.20,   # era 0.15
    # Fase 3: SI seasonal
    "SI_CEIL":                  3.0,    # era 5.0
    "SI_SKU_ADJ_ALPHA_HIGH":    0.20,   # era 0.30
    "SI_MIN_YEARS_FOR_SKU":     2,      # era 3
    # Fase 4: fair share
    "FAIR_SHARE_TRIED_PENALTY": 0.05,   # era 0.15
}


def detect_quiebres(pos, target_weeks):
    """Quiebre en target_week: proxy 8w (avg>=1, sold<max(20% avg, 0.5))
    o demanda_norm.avail<1.0. Mismo criterio que Test 2."""
    hist_from = target_weeks[0] - timedelta(weeks=8)
    hist = pos[(pos['week_start'] >= hist_from) & (pos['week_start'] < target_weeks[0])]
    avg = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg.columns = ['team_id', 'product_id', 'avg_8w']

    dn_path = CACHE / "demanda_norm.parquet"
    dn = pd.read_parquet(dn_path) if dn_path.exists() else pd.DataFrame()
    if not dn.empty:
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
        if not dn.empty:
            dn_w = dn[(dn['week_start'] == wk) & (dn['avail'] < 1.0)]
            for _, r in dn_w.iterrows():
                quiebres.add((int(r['team_id']), int(r['product_id']), wk))
    return quiebres


def run_backtest(config_override, label, pos, quiebres):
    """Corre 10 sem con un config dado y concatena."""
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


def apply_categ_calib(df, factors, src_col='mu_week', dst_col='mu_week_calib'):
    """Aplica factor (categ_id, abc_letter) -> mu_week*factor.
    No toca filas sin (categ, abc) o sin factor (factor=1.0).
    Devuelve copia con dst_col agregada."""
    def _factor(row):
        if pd.isna(row['categ_id']) or pd.isna(row['abcxyz_eff']):
            return 1.0
        letter = row['abcxyz_eff'][:1] if row['abcxyz_eff'] else ''
        if letter not in ('A', 'B', 'C'):
            return 1.0
        return factors.get((int(row['categ_id']), letter), 1.0)

    df = df.copy()
    fcol = f"{dst_col}_factor"
    df[fcol] = df.apply(_factor, axis=1)
    df[dst_col] = df[src_col] * df[fcol]
    return df


def metrics(df, value):
    r = df['qty_sold'].sum()
    f = df[value].sum()
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return {
        'n_rows': int(len(df)),
        'real': float(r),
        'fcst': float(f),
        'WAPE': round(ae / r * 100, 2) if r > 0 else 0.0,
        'BIAS': round(err / r * 100, 2) if r > 0 else 0.0,
    }


def main():
    print(f"Simulacion final v3.47 - ventana {TARGET_WEEKS[0]} .. {TARGET_WEEKS[-1]}")
    print(f"Cargando factores categ_calib (test_2_categ_factors.json)...")
    factors_json_path = RESULTS / "test_2_categ_factors.json"
    with open(factors_json_path, 'r', encoding='utf-8') as f:
        factors_meta = json.load(f)
    factors = {}
    for k, v in factors_meta['factors'].items():
        cid_str, letter = k.split('|')
        factors[(int(cid_str), letter)] = float(v)
    print(f"  {len(factors)} factores activos cargados")

    print("\nCargando cache POS + catalog...")
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())
    print(f"  cigarros/snack/impulso excluidos: {len(excl_cat_ids)} categorias")

    cerv_cat_ids = set(cats[cats['complete_name'].str.contains(
        'Cervezas', case=False, na=False
    )]['categ_id_id'].tolist())

    print("\nDetectando quiebres en target_week...")
    quiebres = detect_quiebres(pos, TARGET_WEEKS)
    print(f"  {len(quiebres):,} pares (team,sku,week) marcados quiebre")

    # ------------------------------------------------------------------
    # 2 corridas del motor (caras): baseline y Test 1 tuning.
    # Sobre cada una, aplicamos categ_calib en post-procesamiento.
    # Eso nos da las 4 configs sin necesidad de correr el motor 4 veces.
    # ------------------------------------------------------------------
    df_base = run_backtest({}, "baseline v3.46 puro", pos, quiebres)
    df_t1 = run_backtest(TUNED_TEST1, "Test 1 tuning (12 hyperparams)", pos, quiebres)

    # Aplicar categ_calib a ambos
    df_base = apply_categ_calib(df_base, factors, src_col='mu_week',
                                dst_col='mu_week_calib')
    df_t1 = apply_categ_calib(df_t1, factors, src_col='mu_week',
                              dst_col='mu_week_calib')

    # Cobertura
    n_with_factor_base = (df_base['mu_week_calib_factor'] != 1.0).sum()
    print(f"  cobertura factor en baseline raw: {n_with_factor_base:,} filas"
          f" ({n_with_factor_base / len(df_base) * 100:.1f}%)")

    # ------------------------------------------------------------------
    # Universos
    # ------------------------------------------------------------------
    base_clean = df_base[~df_base['categ_id'].isin(excl_cat_ids) & ~df_base['is_quiebre']]
    t1_clean = df_t1[~df_t1['categ_id'].isin(excl_cat_ids) & ~df_t1['is_quiebre']]

    def eval_block(df_clean_base, df_clean_t1, label):
        return {
            'label': label,
            'A_baseline':       metrics(df_clean_base, 'mu_week'),
            'B_test1':          metrics(df_clean_t1, 'mu_week'),
            'C_categ_calib':    metrics(df_clean_base, 'mu_week_calib'),
            'D_combo':          metrics(df_clean_t1, 'mu_week_calib'),
        }

    # Total
    block_total = eval_block(base_clean, t1_clean, 'TOTAL (sin cig/snack, sin quiebres)')
    # Cervezas
    bc_cerv = base_clean[base_clean['categ_id'].isin(cerv_cat_ids)]
    t1_cerv = t1_clean[t1_clean['categ_id'].isin(cerv_cat_ids)]
    block_cerv = eval_block(bc_cerv, t1_cerv, 'CERVEZAS')
    # Stella 9407
    bc_9407 = base_clean[base_clean['product_id'] == TESTIGO_PRODUCT_ID]
    t1_9407 = t1_clean[t1_clean['product_id'] == TESTIGO_PRODUCT_ID]
    block_9407 = eval_block(bc_9407, t1_9407, 'SKU 9407 Stella (testigo lag)')

    # Por semana
    weekly_rows = []
    for wk in TARGET_WEEKS:
        bb = base_clean[base_clean['target_week'] == wk]
        tt = t1_clean[t1_clean['target_week'] == wk]
        ma = metrics(bb, 'mu_week')
        mb = metrics(tt, 'mu_week')
        mc = metrics(bb, 'mu_week_calib')
        md = metrics(tt, 'mu_week_calib')
        weekly_rows.append({
            'week': str(wk),
            'A_WAPE': ma['WAPE'], 'A_BIAS': ma['BIAS'],
            'B_WAPE': mb['WAPE'], 'B_BIAS': mb['BIAS'],
            'C_WAPE': mc['WAPE'], 'C_BIAS': mc['BIAS'],
            'D_WAPE': md['WAPE'], 'D_BIAS': md['BIAS'],
        })

    # Por categoria top 20
    cat_summary = base_clean.merge(
        cats[['categ_id_id', 'complete_name']].rename(columns={'categ_id_id': 'categ_id'}),
        on='categ_id', how='left',
    )
    t1_cat = t1_clean.merge(
        cats[['categ_id_id', 'complete_name']].rename(columns={'categ_id_id': 'categ_id'}),
        on='categ_id', how='left',
    )
    cat_groups = []
    for cid, grp in cat_summary.groupby('categ_id'):
        if grp['qty_sold'].sum() < 200:
            continue
        grp_t1 = t1_cat[t1_cat['categ_id'] == cid]
        ma = metrics(grp, 'mu_week')
        mb = metrics(grp_t1, 'mu_week')
        mc = metrics(grp, 'mu_week_calib')
        md = metrics(grp_t1, 'mu_week_calib')
        cat_groups.append({
            'categ_id': int(cid),
            'name': (grp['complete_name'].iloc[0] or '')[:42],
            'real': ma['real'],
            'A_WAPE': ma['WAPE'], 'A_BIAS': ma['BIAS'],
            'B_WAPE': mb['WAPE'], 'B_BIAS': mb['BIAS'],
            'C_WAPE': mc['WAPE'], 'C_BIAS': mc['BIAS'],
            'D_WAPE': md['WAPE'], 'D_BIAS': md['BIAS'],
        })
    cat_groups.sort(key=lambda x: -x['real'])

    # ------------------------------------------------------------------
    # REPORTE
    # ------------------------------------------------------------------
    lines = []
    lines.append("=" * 140)
    lines.append("SIMULACION FINAL v3.47 - matriz 2x2 (hyperparams Test1 x categ_calib)")
    lines.append(f"Ventana: {TARGET_WEEKS[0]} .. {TARGET_WEEKS[-1]}  ({len(TARGET_WEEKS)} sem)")
    lines.append(f"Factores categ_calib aplicados: {len(factors)} (calibracion 2026-05-27, fuente test_2_categ_factors.json)")
    lines.append(f"Quiebres en target_week: {len(quiebres):,} pares (excluidos del error)")
    lines.append(f"Universo limpio total: {len(base_clean):,} filas (sin cig/snack/impulso)")
    lines.append(f"Cobertura factor: {n_with_factor_base:,} filas ({n_with_factor_base / len(df_base) * 100:.1f}% del raw)")
    lines.append("=" * 140)
    lines.append("")
    lines.append("CONFIGS COMPARADAS:")
    lines.append("  A = baseline v3.46          (motor productivo actual, sin ajustes)")
    lines.append("  B = Test 1 tuning           (12 hyperparams retunes Fase 1..4)")
    lines.append("  C = v3.47 categ_calib       (baseline + factor (categ_id x abc_letter))")
    lines.append("  D = combo Test 1 + calib    (tuning hyperparams + categ_calib)")
    lines.append("")

    def fmt_4col(label, ma, mb, mc, md):
        return (
            f"  {label:<34s} | "
            f"A WAPE={ma['WAPE']:>6.2f} BIAS={ma['BIAS']:>+7.2f} | "
            f"B WAPE={mb['WAPE']:>6.2f} BIAS={mb['BIAS']:>+7.2f} | "
            f"C WAPE={mc['WAPE']:>6.2f} BIAS={mc['BIAS']:>+7.2f} | "
            f"D WAPE={md['WAPE']:>6.2f} BIAS={md['BIAS']:>+7.2f}"
        )

    for blk in (block_total, block_cerv, block_9407):
        lines.append("-" * 140)
        lines.append(blk['label'])
        lines.append("-" * 140)
        lines.append(fmt_4col('metrica',
                              blk['A_baseline'], blk['B_test1'],
                              blk['C_categ_calib'], blk['D_combo']))
        # deltas vs A
        for k_dst, k_lbl in (('B_test1', 'd_B-A (tuning vs baseline)'),
                             ('C_categ_calib', 'd_C-A (calib vs baseline)'),
                             ('D_combo', 'd_D-A (combo vs baseline)')):
            dst = blk[k_dst]
            base = blk['A_baseline']
            lines.append(
                f"  {k_lbl:<34s} | "
                f"                                  | "
                f"d_WAPE={dst['WAPE']-base['WAPE']:>+6.2f} d_BIAS={dst['BIAS']-base['BIAS']:>+7.2f}  "
                f"(WAPE {base['WAPE']:.2f} -> {dst['WAPE']:.2f},  BIAS {base['BIAS']:+.2f} -> {dst['BIAS']:+.2f})"
            )
        lines.append("")

    lines.append("=" * 140)
    lines.append("EFECTO POR SEMANA (universo limpio total)")
    lines.append("-" * 140)
    lines.append(
        f"  {'semana':<12s} | "
        f"{'A baseline':>20s} | {'B test1':>20s} | "
        f"{'C calib':>20s} | {'D combo':>20s}"
    )
    for w in weekly_rows:
        lines.append(
            f"  {w['week']:<12s} | "
            f"WAPE={w['A_WAPE']:>5.2f} BIAS={w['A_BIAS']:>+6.2f} | "
            f"WAPE={w['B_WAPE']:>5.2f} BIAS={w['B_BIAS']:>+6.2f} | "
            f"WAPE={w['C_WAPE']:>5.2f} BIAS={w['C_BIAS']:>+6.2f} | "
            f"WAPE={w['D_WAPE']:>5.2f} BIAS={w['D_BIAS']:>+6.2f}"
        )
    lines.append("")

    lines.append("=" * 140)
    lines.append("EFECTO POR CATEGORIA TOP 20 (orden por unidades reales)")
    lines.append("-" * 140)
    lines.append(
        f"  {'cat':>5s} {'name':<42s} {'real':>8s} | "
        f"{'A WAPE':>7s} {'A BIAS':>8s} | "
        f"{'B WAPE':>7s} {'B BIAS':>8s} | "
        f"{'C WAPE':>7s} {'C BIAS':>8s} | "
        f"{'D WAPE':>7s} {'D BIAS':>8s}"
    )
    for c in cat_groups[:20]:
        lines.append(
            f"  {c['categ_id']:>5d} {c['name']:<42s} {c['real']:>8,.0f} | "
            f"{c['A_WAPE']:>7.2f} {c['A_BIAS']:>+8.2f} | "
            f"{c['B_WAPE']:>7.2f} {c['B_BIAS']:>+8.2f} | "
            f"{c['C_WAPE']:>7.2f} {c['C_BIAS']:>+8.2f} | "
            f"{c['D_WAPE']:>7.2f} {c['D_BIAS']:>+8.2f}"
        )
    lines.append("")
    lines.append("=" * 140)
    lines.append("INTERPRETACION RAPIDA")
    lines.append("-" * 140)
    A = block_total['A_baseline']
    B = block_total['B_test1']
    C = block_total['C_categ_calib']
    D = block_total['D_combo']
    lines.append(f"  Total WAPE: A={A['WAPE']:.2f}  B={B['WAPE']:.2f}  C={C['WAPE']:.2f}  D={D['WAPE']:.2f}")
    lines.append(f"  Total BIAS: A={A['BIAS']:+.2f} B={B['BIAS']:+.2f} C={C['BIAS']:+.2f} D={D['BIAS']:+.2f}")
    # Mejor por WAPE
    best_wape = min([(A['WAPE'], 'A'), (B['WAPE'], 'B'), (C['WAPE'], 'C'), (D['WAPE'], 'D')])
    best_bias = min([(abs(A['BIAS']), 'A'), (abs(B['BIAS']), 'B'),
                     (abs(C['BIAS']), 'C'), (abs(D['BIAS']), 'D')])
    lines.append(f"  Mejor WAPE: config {best_wape[1]} ({best_wape[0]:.2f})")
    lines.append(f"  Mejor BIAS magnitud: config {best_bias[1]} (|BIAS|={best_bias[0]:.2f})")
    lines.append("=" * 140)

    report = "\n".join(lines)
    print()
    print(report)

    # ------------------------------------------------------------------
    # GUARDAR
    # ------------------------------------------------------------------
    out_txt = RESULTS / "simulacion_final_v347.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")

    # Detalle: ambos df concatenados con label de config
    df_base['config'] = 'baseline_or_calib'
    df_t1['config'] = 'test1_or_combo'
    df_all = pd.concat([df_base, df_t1], ignore_index=True)
    out_parquet = RESULTS / "simulacion_final_v347_detail.parquet"
    df_all.to_parquet(out_parquet, index=False)

    summary = {
        'meta': {
            'window_weeks': len(TARGET_WEEKS),
            'window_start': str(TARGET_WEEKS[0]),
            'window_end': str(TARGET_WEEKS[-1]),
            'n_factors_loaded': len(factors),
            'factors_source': 'resultados/test_2_categ_factors.json',
            'n_quiebres': len(quiebres),
            'tuned_test1': TUNED_TEST1,
            'excluded_categs_n': len(excl_cat_ids),
            'n_rows_clean': int(len(base_clean)),
            'n_rows_with_factor': int(n_with_factor_base),
            'pct_coverage_factor': round(n_with_factor_base / len(df_base) * 100, 2),
        },
        'configs': {
            'A': 'baseline v3.46 (motor productivo)',
            'B': 'Test 1 tuning (12 hyperparams)',
            'C': 'v3.47 categ_calib (baseline + factor categ x abc)',
            'D': 'combo Test 1 + categ_calib',
        },
        'total': block_total,
        'cervezas': block_cerv,
        'sku_9407_stella': block_9407,
        'weekly': weekly_rows,
        'top_categorias': cat_groups[:30],
    }
    out_json = RESULTS / "simulacion_final_v347_summary.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nArchivos generados:")
    print(f"  -> {out_txt}")
    print(f"  -> {out_parquet}")
    print(f"  -> {out_json}")


if __name__ == "__main__":
    main()
