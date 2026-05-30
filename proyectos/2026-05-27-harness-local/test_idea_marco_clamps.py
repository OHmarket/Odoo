"""
Refinamiento idea Marco: M1 (10 vs 26 avg) con distintos clamps.

M1 captura cambio de nivel del cluster (real vs histórico) — independiente
del motor, sin ciclo. Pero clamp [0.70, 1.30] degrada WAPE +2.81pp porque
over-correge clusters donde el motor ya capturó parte del cambio.

Hipotesis: clamp mas estrecho [0.85, 1.15] reduce over-correction y mantiene
mayor parte de la mejora en BIAS.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']
TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]
CUTOFF_MONDAY = TARGET_WEEKS[0] - timedelta(weeks=1)

MIN_REAL_UNITS = 500
APPLY_THRESHOLD = 0.05


def compute_factors_marco(pos, abcxyz_map, cat_excl, n_recent, n_long, clamp_lo, clamp_hi):
    pos = pos.copy()
    pos['abc'] = pos['product_id'].map(lambda p: abcxyz_map.get(p, '')).str.slice(0, 1)
    pos = pos[pos['abc'].isin(['A', 'B', 'C'])]
    pos = pos[~pos['categ_id'].isin(cat_excl)]

    weeks_recent = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_recent + 1)]
    weeks_long = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_long + 1)]

    pos_recent = pos[pos['week_start'].isin(weeks_recent)].groupby(['categ_id', 'abc'])['qty_sold'].sum().reset_index()
    pos_long = pos[pos['week_start'].isin(weeks_long)].groupby(['categ_id', 'abc'])['qty_sold'].sum().reset_index()

    pos_recent.columns = ['categ_id', 'abc', 'real_recent']
    pos_long.columns = ['categ_id', 'abc', 'real_long']
    g = pos_recent.merge(pos_long, on=['categ_id', 'abc'], how='outer').fillna(0)

    g['nivel_recent'] = g['real_recent'] / n_recent
    g['nivel_long'] = g['real_long'] / n_long
    g['raw'] = g['nivel_recent'] / g['nivel_long'].replace(0, 1)
    g['clamped'] = g['raw'].clip(clamp_lo, clamp_hi)
    g['apply'] = (g['real_recent'] >= MIN_REAL_UNITS) & ((g['clamped'] - 1.0).abs() >= APPLY_THRESHOLD) & (g['nivel_long'] > 0)
    return {(int(r['categ_id']), r['abc']): r['clamped'] for _, r in g[g['apply']].iterrows()}


def metrics(df, value):
    r = df['qty_sold'].sum()
    if r <= 0:
        return {'WAPE': 0.0, 'BIAS': 0.0}
    f = df[value].sum()
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return {'WAPE': round(ae / r * 100, 2), 'BIAS': round(err / r * 100, 2)}


def main():
    df_all = pd.read_parquet(RESULTS / "simulacion_final_v347_detail.parquet")
    df = df_all[df_all['config'] == 'baseline_or_calib'].copy()

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'])
    cerv_cat_ids = set(cats[cats['complete_name'].str.contains(
        'Cervezas', case=False, na=False
    )]['categ_id_id'])

    abcxyz_map = {}
    for _, r in df.dropna(subset=['product_id', 'abcxyz_eff']).drop_duplicates('product_id').iterrows():
        abcxyz_map[int(r['product_id'])] = str(r['abcxyz_eff']).strip().upper()

    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    if pos['week_start'].dtype == object:
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    df_eval = df.copy()
    df_eval['abc'] = df_eval['abcxyz_eff'].fillna('').str.slice(0, 1)
    no_q = ~df_eval['is_quiebre']
    no_cig = ~df_eval['categ_id'].isin(excl_cat_ids)
    clean_mask = no_q & no_cig
    cerv_mask = df_eval['categ_id'].isin(cerv_cat_ids) & clean_mask

    # Variantes: distintas ventanas y clamps
    variantes = [
        ('M1a 10/26 c[0.70,1.30]', 10, 26, 0.70, 1.30),
        ('M1b 10/26 c[0.80,1.20]', 10, 26, 0.80, 1.20),
        ('M1c 10/26 c[0.85,1.15]', 10, 26, 0.85, 1.15),
        ('M1d 10/26 c[0.90,1.10]', 10, 26, 0.90, 1.10),
        ('M1e  6/26 c[0.85,1.15]',  6, 26, 0.85, 1.15),
        ('M1f  6/13 c[0.85,1.15]',  6, 13, 0.85, 1.15),
        ('M1g  4/13 c[0.85,1.15]',  4, 13, 0.85, 1.15),
    ]

    lines = []
    lines.append("=" * 140)
    lines.append("Idea Marco - barrido de ventanas y clamps")
    lines.append(f"Cutoff calculo: {CUTOFF_MONDAY}")
    lines.append("=" * 140)

    m_base = metrics(df_eval[clean_mask], 'mu_week')
    m_cerv_base = metrics(df_eval[cerv_mask], 'mu_week')
    lines.append(f"\nA baseline v3.46:  TOTAL WAPE={m_base['WAPE']:>6.2f} BIAS={m_base['BIAS']:>+7.2f}  | "
                 f"CERV WAPE={m_cerv_base['WAPE']:>6.2f} BIAS={m_cerv_base['BIAS']:>+7.2f}")
    lines.append("")
    lines.append(f"  {'config':<28s} | {'n_fac':>5s} | {'WAPE':>6s} {'BIAS':>7s} {'d_WAPE':>7s} {'d_BIAS':>8s} | "
                 f"{'CERV_W':>7s} {'CERV_B':>8s} {'dC_W':>6s} {'dC_B':>6s}")
    lines.append("-" * 140)
    rows = []
    for name, n_r, n_l, lo, hi in variantes:
        factors = compute_factors_marco(pos, abcxyz_map, excl_cat_ids, n_r, n_l, lo, hi)
        # aplicar
        def fac(row):
            if pd.isna(row['categ_id']) or row['abc'] not in ('A', 'B', 'C'):
                return 1.0
            return factors.get((int(row['categ_id']), row['abc']), 1.0)
        df_x = df_eval.copy()
        df_x['fac'] = df_x.apply(fac, axis=1)
        df_x['mu_adj'] = df_x['mu_week'] * df_x['fac']
        m_t = metrics(df_x[clean_mask], 'mu_adj')
        m_c = metrics(df_x[cerv_mask], 'mu_adj')
        d_w = m_t['WAPE'] - m_base['WAPE']
        d_b = m_t['BIAS'] - m_base['BIAS']
        dC_w = m_c['WAPE'] - m_cerv_base['WAPE']
        dC_b = m_c['BIAS'] - m_cerv_base['BIAS']
        lines.append(f"  {name:<28s} | {len(factors):>5d} | "
                     f"{m_t['WAPE']:>6.2f} {m_t['BIAS']:>+7.2f} {d_w:>+7.2f} {d_b:>+8.2f} | "
                     f"{m_c['WAPE']:>7.2f} {m_c['BIAS']:>+8.2f} {dC_w:>+6.2f} {dC_b:>+6.2f}")
        rows.append({'cfg': name, 'WAPE': m_t['WAPE'], 'BIAS': m_t['BIAS'],
                     'd_WAPE': d_w, 'd_BIAS': d_b, 'n_fac': len(factors)})

    # Comparacion con canon B (Test 2)
    universe_calib = df_eval[clean_mask].copy()
    g_B = universe_calib.groupby(['categ_id', 'abc']).agg(
        real=('qty_sold', 'sum'), fcst=('mu_week', 'sum')).reset_index()
    g_B['raw'] = g_B['real'] / g_B['fcst'].replace(0, 1)
    g_B['clamped'] = g_B['raw'].clip(0.70, 1.30)
    g_B['apply'] = (g_B['real'] >= MIN_REAL_UNITS) & ((g_B['clamped'] - 1.0).abs() >= APPLY_THRESHOLD)
    factors_B = {(int(r['categ_id']), r['abc']): r['clamped'] for _, r in g_B[g_B['apply']].iterrows()}
    def fac_b(row):
        if pd.isna(row['categ_id']) or row['abc'] not in ('A', 'B', 'C'):
            return 1.0
        return factors_B.get((int(row['categ_id']), row['abc']), 1.0)
    df_B = df_eval.copy()
    df_B['fac'] = df_B.apply(fac_b, axis=1)
    df_B['mu_adj'] = df_B['mu_week'] * df_B['fac']
    m_B_t = metrics(df_B[clean_mask], 'mu_adj')
    m_B_c = metrics(df_B[cerv_mask], 'mu_adj')
    lines.append("-" * 140)
    lines.append(f"  {'B canon Test2 (referencia)':<28s} | {len(factors_B):>5d} | "
                 f"{m_B_t['WAPE']:>6.2f} {m_B_t['BIAS']:>+7.2f} {m_B_t['WAPE']-m_base['WAPE']:>+7.2f} {m_B_t['BIAS']-m_base['BIAS']:>+8.2f} | "
                 f"{m_B_c['WAPE']:>7.2f} {m_B_c['BIAS']:>+8.2f} {m_B_c['WAPE']-m_cerv_base['WAPE']:>+6.2f} {m_B_c['BIAS']-m_cerv_base['BIAS']:>+6.2f}")

    lines.append("")
    lines.append("=" * 140)
    lines.append("RANKING (menor WAPE degradacion para |BIAS| < 10):")
    lines.append("-" * 140)
    valid = [r for r in rows if abs(r['BIAS']) < 10]
    valid.sort(key=lambda x: x['d_WAPE'])
    for r in valid[:5]:
        lines.append(f"  {r['cfg']:<28s}  d_WAPE={r['d_WAPE']:+.2f}  BIAS={r['BIAS']:+.2f}  n_fac={r['n_fac']}")
    lines.append("")
    lines.append("=" * 140)

    report = "\n".join(lines)
    print(report)
    out = RESULTS / "test_idea_marco_clamps.txt"
    with open(out, 'w', encoding='utf-8') as f:
        f.write(report + "\n")
    print(f"\n -> {out}")


if __name__ == "__main__":
    main()
