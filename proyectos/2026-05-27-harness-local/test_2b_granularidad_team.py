"""
Test 2B: comparar granularidades de categ_calib.

Reutiliza el detail.parquet de la simulacion_final_v347 (config A baseline
v3.46 + universo limpio) para evaluar 3 granularidades de factores:

  G1: (categ_id, abc_letter)              -- el actual de Test 2, ~50 factores
  G2: (team_id, categ_id, abc_letter)     -- maxima granularidad, ~600 teoricos
  G3: (team_id, abc_letter)               -- solo team x abc, ~36 factores

Para cada granularidad:
  - Calcula factor = sum_real / sum_fcst por cluster.
  - Aplica clamp [0.70, 1.30] y filtros (min_real=500, threshold |f-1|>=5%).
  - Vuelve a medir WAPE/BIAS del baseline con factor aplicado por cluster.
  - Reporta cobertura, varianza intra-categoria entre teams, y top clusters.

La pregunta clave que responde:
  - Que tan parecido es el factor de Cervezas Premium A entre team=5 vs team=10?
  - Si son muy parecidos -> G1 captura el 90%, agregar team no aporta.
  - Si son muy distintos -> G2 captura sesgos locales que G1 oculta.

Output:
  resultados/test_2b_granularidad.txt
  resultados/test_2b_granularidad_summary.json
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

MIN_REAL_UNITS = 500
CLAMP_LO = 0.70
CLAMP_HI = 1.30
APPLY_THRESHOLD = 0.05

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']


def compute_factors(df_clean, group_cols):
    g = df_clean.groupby(group_cols).agg(
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        n=('qty_sold', 'size'),
    ).reset_index()
    g['raw'] = g['real'] / g['fcst'].replace(0, 1)
    g['clamped'] = g['raw'].clip(CLAMP_LO, CLAMP_HI)
    g['apply'] = (g['real'] >= MIN_REAL_UNITS) & ((g['clamped'] - 1.0).abs() >= APPLY_THRESHOLD)
    return g


def apply_and_eval(df_clean, factors_df, group_cols, factor_col='clamped'):
    """Merge factors back into df_clean por group_cols y aplica al mu_week."""
    active = factors_df[factors_df['apply']][group_cols + [factor_col]].copy()
    active = active.rename(columns={factor_col: 'cluster_factor'})
    merged = df_clean.merge(active, on=group_cols, how='left')
    merged['cluster_factor'] = merged['cluster_factor'].fillna(1.0)
    merged['mu_week_adj'] = merged['mu_week'] * merged['cluster_factor']
    return merged


def metrics(df, value):
    r = df['qty_sold'].sum()
    f = df[value].sum()
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return {
        'real': float(r),
        'fcst': float(f),
        'WAPE': round(ae / r * 100, 2) if r > 0 else 0.0,
        'BIAS': round(err / r * 100, 2) if r > 0 else 0.0,
    }


def main():
    detail_path = RESULTS / "simulacion_final_v347_detail.parquet"
    if not detail_path.exists():
        print(f"ERROR: {detail_path} no existe. Correr simulacion_final_v347.py primero.")
        return

    print(f"Leyendo {detail_path}...")
    df = pd.read_parquet(detail_path)
    # solo config baseline (sin tuning hyperparams)
    if 'config' in df.columns:
        df = df[df['config'] == 'baseline_or_calib'].copy()
    print(f"  {len(df):,} filas (config baseline v3.46)")

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())

    clean = df[~df['categ_id'].isin(excl_cat_ids) & ~df['is_quiebre']].copy()
    clean = clean[clean['categ_id'].notna() & clean['abcxyz_eff'].notna()]
    clean['abc_letter'] = clean['abcxyz_eff'].str.slice(0, 1)
    clean = clean[clean['abc_letter'].isin(['A', 'B', 'C'])]
    clean['team_id'] = clean['team_id'].astype(int)
    clean['categ_id'] = clean['categ_id'].astype(int)
    print(f"  universo limpio: {len(clean):,}")

    # ------------------------------------------------------------------
    # G1: (categ, abc)
    # G2: (team, categ, abc)
    # G3: (team, abc)
    # ------------------------------------------------------------------
    f1 = compute_factors(clean, ['categ_id', 'abc_letter'])
    f2 = compute_factors(clean, ['team_id', 'categ_id', 'abc_letter'])
    f3 = compute_factors(clean, ['team_id', 'abc_letter'])

    print(f"\nClusters por granularidad:")
    print(f"  G1 (categ,abc):       total={len(f1):>5}  con factor activo={f1['apply'].sum():>5}")
    print(f"  G2 (team,categ,abc):  total={len(f2):>5}  con factor activo={f2['apply'].sum():>5}")
    print(f"  G3 (team,abc):        total={len(f3):>5}  con factor activo={f3['apply'].sum():>5}")

    # Aplicar y evaluar
    e1 = apply_and_eval(clean, f1, ['categ_id', 'abc_letter'])
    e2 = apply_and_eval(clean, f2, ['team_id', 'categ_id', 'abc_letter'])
    e3 = apply_and_eval(clean, f3, ['team_id', 'abc_letter'])

    m_base = metrics(clean, 'mu_week')
    m1 = metrics(e1, 'mu_week_adj')
    m2 = metrics(e2, 'mu_week_adj')
    m3 = metrics(e3, 'mu_week_adj')

    # Cobertura
    cov1 = (e1['cluster_factor'] != 1.0).sum()
    cov2 = (e2['cluster_factor'] != 1.0).sum()
    cov3 = (e3['cluster_factor'] != 1.0).sum()

    # ------------------------------------------------------------------
    # Variance intra-categoria entre teams (G2 vs G1)
    # ------------------------------------------------------------------
    # Por cada (categ, abc), si tenemos >= 4 teams con factor activo en G2,
    # medimos std del factor entre teams.
    g2_active = f2[f2['apply']].copy()
    intra = g2_active.groupby(['categ_id', 'abc_letter']).agg(
        n_teams=('team_id', 'count'),
        factor_mean=('clamped', 'mean'),
        factor_std=('clamped', 'std'),
        factor_min=('clamped', 'min'),
        factor_max=('clamped', 'max'),
        total_real=('real', 'sum'),
    ).reset_index()
    intra = intra[intra['n_teams'] >= 4].copy()
    intra['factor_spread'] = intra['factor_max'] - intra['factor_min']
    intra = intra.merge(
        cats[['categ_id_id', 'complete_name']].rename(columns={'categ_id_id': 'categ_id'}),
        on='categ_id', how='left',
    )
    intra['name'] = intra['complete_name'].fillna('').str.slice(0, 38)
    intra = intra.sort_values('total_real', ascending=False)

    # ------------------------------------------------------------------
    # REPORTE
    # ------------------------------------------------------------------
    lines = []
    lines.append("=" * 130)
    lines.append("TEST 2B: comparativa de granularidad para categ_calib_factor")
    lines.append("=" * 130)
    lines.append(f"  baseline v3.46 (sin ajuste):    WAPE={m_base['WAPE']:>6.2f}  BIAS={m_base['BIAS']:>+7.2f}")
    lines.append(f"  G1 (categ,abc) - actual:        WAPE={m1['WAPE']:>6.2f}  BIAS={m1['BIAS']:>+7.2f}  | factores activos={f1['apply'].sum()}  cobertura={cov1:,} filas")
    lines.append(f"  G2 (team,categ,abc) - max gran: WAPE={m2['WAPE']:>6.2f}  BIAS={m2['BIAS']:>+7.2f}  | factores activos={f2['apply'].sum()}  cobertura={cov2:,} filas")
    lines.append(f"  G3 (team,abc) - sin categ:      WAPE={m3['WAPE']:>6.2f}  BIAS={m3['BIAS']:>+7.2f}  | factores activos={f3['apply'].sum()}  cobertura={cov3:,} filas")
    lines.append("")
    lines.append(f"  Delta vs baseline:")
    lines.append(f"    G1: d_WAPE={m1['WAPE']-m_base['WAPE']:+.2f}pp  d_BIAS={m1['BIAS']-m_base['BIAS']:+.2f}pp")
    lines.append(f"    G2: d_WAPE={m2['WAPE']-m_base['WAPE']:+.2f}pp  d_BIAS={m2['BIAS']-m_base['BIAS']:+.2f}pp")
    lines.append(f"    G3: d_WAPE={m3['WAPE']-m_base['WAPE']:+.2f}pp  d_BIAS={m3['BIAS']-m_base['BIAS']:+.2f}pp")
    lines.append("")

    lines.append("=" * 130)
    lines.append("VARIANCE INTRA-CATEGORIA ENTRE TEAMS  (G2: si dispersion alta -> tu intuicion correcta)")
    lines.append("-" * 130)
    lines.append(f"  Mostrando (categ, abc) con >= 4 teams con factor activo, ordenado por unidades reales")
    lines.append("")
    lines.append(
        f"  {'categ':>5s} {'name':<38s} {'abc':>3s} | {'n_teams':>7s} {'real':>8s} | "
        f"{'mean':>5s} {'min':>5s} {'max':>5s} {'spread':>6s} {'std':>5s}"
    )
    for _, r in intra.head(30).iterrows():
        lines.append(
            f"  {int(r['categ_id']):>5d} {r['name']:<38s} {r['abc_letter']:>3s} | "
            f"{int(r['n_teams']):>7d} {r['total_real']:>8,.0f} | "
            f"{r['factor_mean']:>5.2f} {r['factor_min']:>5.2f} {r['factor_max']:>5.2f} "
            f"{r['factor_spread']:>6.2f} {r['factor_std']:>5.2f}"
        )
    lines.append("")

    lines.append("=" * 130)
    lines.append("INTERPRETACION")
    lines.append("-" * 130)
    # WAPE/BIAS interp
    if m2['WAPE'] < m1['WAPE'] - 0.5 and abs(m2['BIAS']) < abs(m1['BIAS']):
        veredicto_metric = "G2 mejora WAPE y BIAS sobre G1 -> agregar team aporta valor."
    elif m2['WAPE'] > m1['WAPE'] + 1.0:
        veredicto_metric = "G2 degrada WAPE > 1pp vs G1 -> overfit, mejor G1."
    elif abs(m2['BIAS'] - m1['BIAS']) < 1.0 and abs(m2['WAPE'] - m1['WAPE']) < 0.5:
        veredicto_metric = "G2 ~ G1 -> agregar team NO aporta significativamente; quedarse con G1 (mas robusto)."
    else:
        veredicto_metric = "Resultado mixto: revisar matriz por categoria."
    lines.append(f"  Metricas: {veredicto_metric}")
    # Spread interp
    if not intra.empty:
        high_spread = (intra['factor_spread'] > 0.30).sum()
        avg_spread = intra['factor_spread'].mean()
        lines.append(
            f"  Variance intra-categoria: avg_spread={avg_spread:.2f} entre teams,"
            f" {high_spread} categs con spread>0.30 (mucha dispersion)."
        )
        if avg_spread > 0.25:
            lines.append("  -> Tu intuicion correcta: factor por (categ,abc) NO captura bien las diferencias entre teams.")
        elif avg_spread < 0.10:
            lines.append("  -> Factores parecidos entre teams; G1 (sin team) captura la mayor parte.")
        else:
            lines.append("  -> Dispersion media; considerar agrupar teams en zonas comerciales antes de ir full G2.")
    lines.append("=" * 130)

    report = "\n".join(lines)
    print()
    print(report)

    out_txt = RESULTS / "test_2b_granularidad.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")

    summary = {
        'baseline': m_base,
        'G1_categ_abc': {
            'metrics': m1, 'n_factors_active': int(f1['apply'].sum()),
            'coverage_rows': int(cov1),
        },
        'G2_team_categ_abc': {
            'metrics': m2, 'n_factors_active': int(f2['apply'].sum()),
            'coverage_rows': int(cov2),
        },
        'G3_team_abc': {
            'metrics': m3, 'n_factors_active': int(f3['apply'].sum()),
            'coverage_rows': int(cov3),
        },
        'intra_category_spread': intra[[
            'categ_id', 'abc_letter', 'n_teams', 'total_real',
            'factor_mean', 'factor_min', 'factor_max', 'factor_spread', 'factor_std', 'name',
        ]].head(50).to_dict('records'),
    }
    out_json = RESULTS / "test_2b_granularidad_summary.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nArchivos generados:")
    print(f"  -> {out_txt}")
    print(f"  -> {out_json}")


if __name__ == "__main__":
    main()
