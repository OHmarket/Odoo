"""
Analisis: a que nivel de agregacion el BIAS error es SIMILAR (homogeneo).

Para varias particiones candidatas (team, categ_L2, categ_L3, abc, combinaciones)
mide:
  - n_clusters: cuantos buckets hay a ese nivel
  - inter-cluster std del BIAS%: dispersion ENTRE clusters
  - intra-cluster avg ae/real: heterogeneidad DENTRO del cluster
  - share clusters con sum_real >= 500

Interpretacion:
  - Si inter-cluster std es BAJA -> los clusters tienen BIAS similar entre si,
    ese nivel NO discrimina (redundante).
  - Si inter-cluster std es ALTA -> los clusters difieren mucho entre si,
    ese nivel SI discrimina (util para calibrar).
  - Si en (team, categ_L2) la varianza intra-(team, categ_L2) entre teams
    es alta -> categ_L2 sola no captura los efectos de local.

Datos: test_3_baseline_16w.parquet (motor v3.46 puro, 16 cutoffs).
Universo: excluye cigarros/snack/impulso.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']


def split_levels(complete_name):
    """Devuelve (L1, L2, L3) del complete_name. Tolera niveles < 3."""
    if not isinstance(complete_name, str) or not complete_name:
        return ('', '', '')
    parts = [p.strip() for p in complete_name.split(' / ')]
    L1 = parts[0] if len(parts) >= 1 else ''
    L2 = parts[1] if len(parts) >= 2 else L1
    L3 = parts[2] if len(parts) >= 3 else L2
    return (L1, L2, L3)


def cluster_metrics(df, group_cols, label, min_real_threshold=500):
    """Calcula metricas por cluster a un nivel dado."""
    g = df.groupby(group_cols).agg(
        n=('qty_sold', 'size'),
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
    ).reset_index()
    g['ae'] = abs(g['fcst'] - g['real'])
    g['err'] = g['real'] - g['fcst']
    g['BIAS_pct'] = np.where(g['real'] > 0, g['err'] / g['real'] * 100.0, 0.0)
    g['WAPE_pct'] = np.where(g['real'] > 0, g['ae'] / g['real'] * 100.0, 0.0)

    n_total = len(g)
    n_qualifies = (g['real'] >= min_real_threshold).sum()
    gq = g[g['real'] >= min_real_threshold].copy()

    if len(gq) == 0:
        return {
            'label': label,
            'n_clusters_total': n_total,
            'n_clusters_robust': 0,
            'mean_bias_abs': None,
            'std_bias_inter': None,
            'p25_bias': None,
            'p75_bias': None,
            'spread_bias': None,
        }

    return {
        'label': label,
        'n_clusters_total': int(n_total),
        'n_clusters_robust': int(n_qualifies),
        'pct_robust': round(n_qualifies / n_total * 100, 1) if n_total else 0.0,
        'mean_bias_abs': round(gq['BIAS_pct'].abs().mean(), 2),
        'std_bias_inter': round(gq['BIAS_pct'].std(), 2),
        'p25_bias': round(gq['BIAS_pct'].quantile(0.25), 2),
        'p75_bias': round(gq['BIAS_pct'].quantile(0.75), 2),
        'spread_bias': round(gq['BIAS_pct'].quantile(0.75) - gq['BIAS_pct'].quantile(0.25), 2),
        'real_total_robust': float(gq['real'].sum()),
    }


def main():
    print("Cargando test_3_baseline_16w.parquet (baseline v3.46)...")
    df = pd.read_parquet(RESULTS / "test_3_baseline_16w.parquet")
    print(f"  {len(df):,} filas")

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())

    # Build category levels
    cats[['L1', 'L2', 'L3']] = cats['complete_name'].apply(
        lambda x: pd.Series(split_levels(x))
    )

    cat_map = cats.set_index('categ_id_id')[['L1', 'L2', 'L3']].to_dict('index')

    df = df[df['categ_id'].notna() & df['team_id'].notna()].copy()
    df['team_id'] = df['team_id'].astype(int)
    df['categ_id'] = df['categ_id'].astype(int)
    df['L1'] = df['categ_id'].map(lambda c: cat_map.get(c, {}).get('L1', ''))
    df['L2'] = df['categ_id'].map(lambda c: cat_map.get(c, {}).get('L2', ''))
    df['L3'] = df['categ_id'].map(lambda c: cat_map.get(c, {}).get('L3', ''))
    df['abc'] = df['abcxyz_eff'].fillna('').str.slice(0, 1)
    df['xyz'] = df['abcxyz_eff'].fillna('').str.slice(1, 2)
    df = df[df['abc'].isin(['A', 'B', 'C']) & df['xyz'].isin(['X', 'Y', 'Z'])]

    clean = df[~df['categ_id'].isin(excl_cat_ids)]
    print(f"  universo limpio (sin cigarros/snack/impulso): {len(clean):,}")
    print(f"  teams: {clean['team_id'].nunique()}")
    print(f"  L1: {clean['L1'].nunique()}  L2: {clean['L2'].nunique()}  L3: {clean['L3'].nunique()}")

    # Global como referencia
    real_g = clean['qty_sold'].sum()
    fcst_g = clean['mu_week'].sum()
    bias_g = (real_g - fcst_g) / real_g * 100.0 if real_g > 0 else 0
    print(f"\n  Global: real={real_g:,.0f}  fcst={fcst_g:,.0f}  BIAS={bias_g:+.2f}%")

    # ------------------------------------------------------------------
    # Niveles candidatos
    # ------------------------------------------------------------------
    levels = [
        ('team',           ['team_id']),
        ('L1 (super-cat)', ['L1']),
        ('L2 (familia)',   ['L2']),
        ('L3 (sub-fam)',   ['L3']),
        ('abc',            ['abc']),
        ('xyz',            ['xyz']),
        ('(L2, abc)',      ['L2', 'abc']),
        ('(L2, xyz)',      ['L2', 'xyz']),
        ('(L3, abc) Test2_actual', ['L3', 'abc']),
        ('(L3, xyz)',      ['L3', 'xyz']),
        ('(team, xyz)',    ['team_id', 'xyz']),
        ('(team, L2, xyz)', ['team_id', 'L2', 'xyz']),
        ('(team, L3, xyz)', ['team_id', 'L3', 'xyz']),
        ('(L2, abc, xyz)', ['L2', 'abc', 'xyz']),
        ('(team, L2, abc)', ['team_id', 'L2', 'abc']),
    ]

    rows = []
    for label, gcols in levels:
        m = cluster_metrics(clean, gcols, label)
        rows.append(m)

    # ------------------------------------------------------------------
    # Heterogeneidad INTRA - cuanto varia el BIAS dentro de un cluster
    # cuando bajamos un nivel mas
    # ------------------------------------------------------------------
    # Ejemplo: si dentro de (categ, abc) los teams tienen BIAS muy distintos,
    # entonces (categ, abc) NO captura el efecto local.
    def intra_dispersion(df_in, outer_cols, inner_cols, min_subclusters=4, min_real=500):
        """Para cada cluster outer, calcula std del BIAS de sus sub-clusters inner."""
        agg = df_in.groupby(outer_cols + inner_cols).agg(
            real=('qty_sold', 'sum'),
            fcst=('mu_week', 'sum'),
        ).reset_index()
        agg = agg[agg['real'] >= min_real]
        agg['BIAS_pct'] = (agg['real'] - agg['fcst']) / agg['real'] * 100.0

        outer_stats = agg.groupby(outer_cols).agg(
            n_sub=('BIAS_pct', 'size'),
            std_sub=('BIAS_pct', 'std'),
            spread_sub=('BIAS_pct', lambda x: x.max() - x.min()),
            real=('real', 'sum'),
        ).reset_index()
        outer_stats = outer_stats[outer_stats['n_sub'] >= min_subclusters]
        if outer_stats.empty:
            return None
        return {
            'n_outer_eval': int(len(outer_stats)),
            'avg_n_sub': round(outer_stats['n_sub'].mean(), 1),
            'avg_intra_std': round(outer_stats['std_sub'].mean(), 2),
            'avg_intra_spread': round(outer_stats['spread_sub'].mean(), 2),
            'p75_intra_spread': round(outer_stats['spread_sub'].quantile(0.75), 2),
        }

    intra_results = []
    # Dentro de team, cuanto varia el BIAS por L2?
    r = intra_dispersion(clean, ['team_id'], ['L2'])
    if r:
        intra_results.append({'outer': 'team', 'inner': 'L2', **r})
    r = intra_dispersion(clean, ['team_id'], ['L3'])
    if r:
        intra_results.append({'outer': 'team', 'inner': 'L3', **r})
    r = intra_dispersion(clean, ['team_id'], ['abc'])
    if r:
        intra_results.append({'outer': 'team', 'inner': 'abc', **r})
    r = intra_dispersion(clean, ['team_id'], ['xyz'])
    if r:
        intra_results.append({'outer': 'team', 'inner': 'xyz', **r})
    # Dentro de L2 (familia), cuanto varia entre teams?
    r = intra_dispersion(clean, ['L2'], ['team_id'])
    if r:
        intra_results.append({'outer': 'L2 (familia)', 'inner': 'team', **r})
    r = intra_dispersion(clean, ['L3'], ['team_id'])
    if r:
        intra_results.append({'outer': 'L3 (sub-fam)', 'inner': 'team', **r})
    # Dentro de (L2, abc) cuanto varia por team?
    r = intra_dispersion(clean, ['L2', 'abc'], ['team_id'])
    if r:
        intra_results.append({'outer': '(L2, abc)', 'inner': 'team', **r})
    r = intra_dispersion(clean, ['L2', 'xyz'], ['team_id'])
    if r:
        intra_results.append({'outer': '(L2, xyz)', 'inner': 'team', **r})
    r = intra_dispersion(clean, ['L3', 'xyz'], ['team_id'])
    if r:
        intra_results.append({'outer': '(L3, xyz)', 'inner': 'team', **r})
    # Dentro de (categ_id, abc) cuanto varia por team? -- Test 2 actual
    r = intra_dispersion(clean, ['categ_id', 'abc'], ['team_id'])
    if r:
        intra_results.append({'outer': '(categ_id, abc) Test2', 'inner': 'team', **r})
    # Dentro de xyz, cuanto varia por team?
    r = intra_dispersion(clean, ['xyz'], ['team_id'])
    if r:
        intra_results.append({'outer': 'xyz', 'inner': 'team', **r})
    r = intra_dispersion(clean, ['xyz'], ['L2'])
    if r:
        intra_results.append({'outer': 'xyz', 'inner': 'L2', **r})
    # Dentro de (team, L2) cuanto varia por L3?
    r = intra_dispersion(clean, ['team_id', 'L2'], ['L3'])
    if r:
        intra_results.append({'outer': '(team, L2)', 'inner': 'L3', **r})

    # ------------------------------------------------------------------
    # REPORTE
    # ------------------------------------------------------------------
    lines = []
    lines.append("=" * 130)
    lines.append("ANALISIS: a que nivel los BIAS son SIMILARES o DISTINTOS")
    lines.append(f"Universo: {len(clean):,} filas baseline v3.46 (sin cigarros/snack/impulso)")
    lines.append(f"Global BIAS = {bias_g:+.2f}% (referencia)")
    lines.append("=" * 130)
    lines.append("")
    lines.append("PARTE 1: dispersion INTER-cluster del BIAS por nivel")
    lines.append("-" * 130)
    lines.append("  Std alto entre clusters -> nivel DISCRIMINA (calibrar aqui aporta)")
    lines.append("  Std bajo entre clusters -> nivel REDUNDANTE (todos los clusters tienen BIAS similar)")
    lines.append("")
    lines.append(
        f"  {'nivel':<32s} | {'n_total':>7s} {'n_robust(>=500)':>15s} "
        f"{'pct_rob':>7s} {'mean_|BIAS|':>11s} {'std_BIAS':>9s} {'p25_BIAS':>9s} {'p75_BIAS':>9s} {'spread_p75-p25':>14s}"
    )
    for r in rows:
        if r['mean_bias_abs'] is None:
            lines.append(f"  {r['label']:<32s} | n_total={r['n_clusters_total']:>5d}  (sin clusters robustos)")
            continue
        lines.append(
            f"  {r['label']:<32s} | {r['n_clusters_total']:>7d} {r['n_clusters_robust']:>15d} "
            f"{r['pct_robust']:>6.1f}% {r['mean_bias_abs']:>10.2f}% {r['std_bias_inter']:>8.2f} "
            f"{r['p25_bias']:>+8.2f}% {r['p75_bias']:>+8.2f}% {r['spread_bias']:>13.2f}pp"
        )

    lines.append("")
    lines.append("=" * 130)
    lines.append("PARTE 2: dispersion INTRA-cluster (cuanto varia el BIAS al BAJAR un nivel)")
    lines.append("-" * 130)
    lines.append("  spread_alto -> el outer NO captura todo (necesita inner para discriminar)")
    lines.append("  spread_bajo -> el outer ya captura bien (no necesita inner)")
    lines.append("")
    lines.append(
        f"  {'outer':<28s} {'inner':<12s} | {'n_outer':>7s} {'avg_n_sub':>9s} "
        f"{'avg_intra_std':>13s} {'avg_intra_spread':>16s} {'p75_intra_spread':>16s}"
    )
    for r in intra_results:
        lines.append(
            f"  {r['outer']:<28s} {r['inner']:<12s} | {r['n_outer_eval']:>7d} {r['avg_n_sub']:>9.1f} "
            f"{r['avg_intra_std']:>12.2f}pp {r['avg_intra_spread']:>15.2f}pp {r['p75_intra_spread']:>15.2f}pp"
        )

    lines.append("")
    lines.append("=" * 130)
    lines.append("INTERPRETACION")
    lines.append("-" * 130)
    # Encontrar el nivel con mayor std inter-cluster (mas discriminante)
    sortable = [r for r in rows if r['std_bias_inter'] is not None]
    sortable.sort(key=lambda x: -x['std_bias_inter'])
    lines.append("  Nivel mas DISCRIMINANTE (std inter-cluster mas alto):")
    for r in sortable[:3]:
        lines.append(f"    -> {r['label']:<30s}  std_BIAS={r['std_bias_inter']:>5.2f}%  n_robust={r['n_clusters_robust']}")
    sortable.sort(key=lambda x: x['std_bias_inter'])
    lines.append("  Nivel mas HOMOGENEO (std inter-cluster mas bajo, redundante para calibrar):")
    for r in sortable[:3]:
        lines.append(f"    -> {r['label']:<30s}  std_BIAS={r['std_bias_inter']:>5.2f}%  n_robust={r['n_clusters_robust']}")
    lines.append("")
    # Pregunta clave: ABC vs XYZ - cual discrimina mejor el BIAS del motor?
    abc_row = next((r for r in rows if r['label'] == 'abc'), None)
    xyz_row = next((r for r in rows if r['label'] == 'xyz'), None)
    if abc_row and xyz_row:
        lines.append(f"  ABC vs XYZ como discriminador del BIAS:")
        lines.append(f"    ABC solo: std={abc_row['std_bias_inter']:.2f}%  spread_p75-p25={abc_row['spread_bias']:.2f}pp")
        lines.append(f"    XYZ solo: std={xyz_row['std_bias_inter']:.2f}%  spread_p75-p25={xyz_row['spread_bias']:.2f}pp")
        if xyz_row['std_bias_inter'] > abc_row['std_bias_inter'] * 1.2:
            lines.append(f"    -> XYZ discrimina MAS que ABC. Tu intuicion correcta: el sesgo del motor se predice por patron, no por volumen.")
        elif abc_row['std_bias_inter'] > xyz_row['std_bias_inter'] * 1.2:
            lines.append(f"    -> ABC discrimina MAS que XYZ. El sesgo se predice por volumen del SKU.")
        else:
            lines.append(f"    -> ABC y XYZ discriminan similar. Usar el mas robusto.")
    # Combinacion mas efectiva
    combos = [r for r in rows if r['label'] in ('(L2, abc)', '(L2, xyz)', '(L3, xyz)',
                                                 '(team, L2, xyz)', '(team, L2, abc)',
                                                 '(L2, abc, xyz)')]
    combos.sort(key=lambda x: (-x['std_bias_inter'], -x['n_clusters_robust']))
    lines.append("")
    lines.append("  Combinaciones ordenadas por discriminacion (std_BIAS desc):")
    for r in combos:
        lines.append(f"    -> {r['label']:<22s}  std={r['std_bias_inter']:>5.2f}%  n_robust={r['n_clusters_robust']:>4d}/{r['n_clusters_total']:>4d} ({r['pct_robust']:>5.1f}%)")
    lines.append("=" * 130)

    report = "\n".join(lines)
    print()
    print(report)

    out_txt = RESULTS / "analisis_nivel_bias.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")

    out_json = RESULTS / "analisis_nivel_bias_summary.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump({
            'global_bias_pct': bias_g,
            'levels_inter_cluster': rows,
            'intra_cluster': intra_results,
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n -> {out_txt}")
    print(f" -> {out_json}")


if __name__ == "__main__":
    main()
