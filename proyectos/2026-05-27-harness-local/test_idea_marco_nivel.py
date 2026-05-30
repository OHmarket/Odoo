"""
Simulacion de la idea de Marco (2026-05-28):
  factor = nivel_actual / nivel_largo  por (categ, abc)

Donde:
  nivel_actual = avg(ventas reales POS, ventana corta antes del target)
  nivel_largo  = avg(ventas reales POS, ventana larga antes del target)

Premisa clave: el factor se calcula con datos ANTERIORES al target window,
sin tocar el motor en absoluto. Cero ciclo, cero dependencia del forecast.

Mide: si el cluster (categ, abc) ha cambiado de nivel comparado con su
historico largo, ese desbalance es exactamente lo que el motor SMA short
no captura (lag estructural).

Configs a comparar:
  A: baseline v3.46                                    (control)
  B: factor (categ, abc) = real_clean / fcst (Test 2)  (control - canon estandar)
  M1: factor Marco = nivel_actual_10 / nivel_largo_26  (ventana 10 vs 26 sem)
  M2: factor Marco = nivel_actual_4  / nivel_largo_16  (ventana corta - mas reactivo)
  M3: factor Marco = nivel_actual_10 / nivel_LY_10sem  (vs mismas 10 sem LY)

Universo limpio: sin cigarros/snack/impulso, sin quiebres en target_week.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import date, timedelta

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]
# Cutoff = ultima semana cerrada antes del primer target
CUTOFF_MONDAY = TARGET_WEEKS[0] - timedelta(weeks=1)   # 2026-03-09 lunes

MIN_REAL_UNITS = 500
CLAMP_LO = 0.70
CLAMP_HI = 1.30
APPLY_THRESHOLD = 0.05


def compute_factor_marco(pos_cluster, n_recent, n_long, mode='avg'):
    """factor = avg(n_recent ultimas) / avg(n_long ultimas).
    pos_cluster: DataFrame con columnas week_start, qty_sold para 1 cluster.
    mode='avg' -> avg vs avg. mode='ly' -> n_recent vs same period LY."""
    weeks_recent = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_recent + 1)]
    if mode == 'avg':
        weeks_long = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_long + 1)]
    elif mode == 'ly':
        # Mismas n_recent semanas pero 52 sem atras
        weeks_long = [w - timedelta(weeks=52) for w in weeks_recent]

    real_recent = pos_cluster[pos_cluster['week_start'].isin(weeks_recent)]['qty_sold'].sum()
    real_long = pos_cluster[pos_cluster['week_start'].isin(weeks_long)]['qty_sold'].sum()

    if real_recent < MIN_REAL_UNITS or real_long <= 0:
        return None, real_recent, real_long
    nivel_recent = real_recent / n_recent
    nivel_long = real_long / (n_recent if mode == 'ly' else n_long)
    raw = nivel_recent / nivel_long
    return raw, real_recent, real_long


def compute_factors_marco(pos, abcxyz_map, cat_to_excl, n_recent, n_long, mode='avg'):
    """Calcula factor Marco por (categ_id, abc_letter)."""
    # Filtrar POS: solo SKUs con abcxyz, no en categorias excluidas
    pos = pos.copy()
    pos['abc'] = pos['product_id'].map(lambda p: abcxyz_map.get(p, ''))
    pos['abc'] = pos['abc'].str.slice(0, 1)
    pos = pos[pos['abc'].isin(['A', 'B', 'C'])]
    pos = pos[~pos['categ_id'].isin(cat_to_excl)]

    factors = {}
    raw_summary = []
    for (cid, abc), grp in pos.groupby(['categ_id', 'abc']):
        raw, sr, sl = compute_factor_marco(grp, n_recent, n_long, mode)
        if raw is None:
            continue
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        if abs(clamped - 1.0) >= APPLY_THRESHOLD:
            factors[(int(cid), abc)] = clamped
            raw_summary.append({
                'categ_id': int(cid), 'abc': abc,
                'real_recent': sr, 'real_long': sl,
                'raw': round(raw, 3), 'clamped': round(clamped, 3),
            })
    return factors, raw_summary


def apply_set(df, factors):
    df = df.copy()
    def fac(row):
        return factors.get((int(row['categ_id']), row['abc']), 1.0) if pd.notna(row['categ_id']) and row['abc'] else 1.0
    df['fac'] = df.apply(fac, axis=1)
    df['mu_adj'] = df['mu_week'] * df['fac']
    return df


def metrics(df, value):
    r = df['qty_sold'].sum()
    if r <= 0:
        return {'n': int(len(df)), 'WAPE': 0.0, 'BIAS': 0.0, 'real': 0.0, 'fcst': 0.0}
    f = df[value].sum()
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return {
        'n': int(len(df)),
        'real': float(r),
        'fcst': float(f),
        'WAPE': round(ae / r * 100, 2),
        'BIAS': round(err / r * 100, 2),
    }


def main():
    print(f"Target window: {TARGET_WEEKS[0]} .. {TARGET_WEEKS[-1]}")
    print(f"Cutoff (calculo factor): {CUTOFF_MONDAY}")

    # Cargar baseline
    print("\nCargando baseline (simulacion_final_v347_detail.parquet)...")
    df_all = pd.read_parquet(RESULTS / "simulacion_final_v347_detail.parquet")
    df = df_all[df_all['config'] == 'baseline_or_calib'].copy()
    print(f"  {len(df):,} filas baseline")

    # Catalogo
    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'])
    cerv_cat_ids = set(cats[cats['complete_name'].str.contains(
        'Cervezas', case=False, na=False
    )]['categ_id_id'])

    # ABCXYZ map por SKU
    abcxyz = pd.read_parquet(CACHE / "abcxyz.parquet")
    abcxyz_map = {}
    if 'x_studio_product_id' in abcxyz.columns:
        for _, r in abcxyz.iterrows():
            pv = r['x_studio_product_id']
            pid = pv[0] if isinstance(pv, (list, tuple)) else int(pv) if pd.notna(pv) else 0
            if pid:
                abcxyz_map[pid] = str(r.get('x_studio_abcxyz', '') or '').strip().upper()
    else:
        # fallback: leer del detail
        for _, r in df.dropna(subset=['product_id', 'abcxyz_eff']).drop_duplicates('product_id').iterrows():
            abcxyz_map[int(r['product_id'])] = str(r['abcxyz_eff']).strip().upper()
    print(f"  abcxyz_map: {len(abcxyz_map):,} SKUs")

    # POS weekly
    print("\nCargando POS weekly...")
    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    if pos['week_start'].dtype == object:
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    print(f"  {len(pos):,} filas POS, weeks {pos['week_start'].min()} .. {pos['week_start'].max()}")

    # Calcular Test 2 ya esta en detail.parquet via mu_week_calib
    # Para B necesito recrear el factor (L3, abc) del Test 2:
    universe_calib = df[~df['categ_id'].isin(excl_cat_ids) & ~df['is_quiebre']].copy()
    universe_calib['abc'] = universe_calib['abcxyz_eff'].fillna('').str.slice(0, 1)
    universe_calib = universe_calib[universe_calib['abc'].isin(['A', 'B', 'C'])]
    g_B = universe_calib.groupby(['categ_id', 'abc']).agg(
        real=('qty_sold', 'sum'), fcst=('mu_week', 'sum'), n=('qty_sold', 'size'),
    ).reset_index()
    g_B['raw'] = g_B['real'] / g_B['fcst'].replace(0, 1)
    g_B['clamped'] = g_B['raw'].clip(CLAMP_LO, CLAMP_HI)
    g_B['apply'] = (g_B['real'] >= MIN_REAL_UNITS) & ((g_B['clamped'] - 1.0).abs() >= APPLY_THRESHOLD)
    factors_B = {(int(r['categ_id']), r['abc']): r['clamped'] for _, r in g_B[g_B['apply']].iterrows()}
    print(f"\nFactores B (Test 2 canon): {len(factors_B)} clusters")

    # Calcular Marco - 3 variantes
    print("\n--- Idea Marco ---")
    factors_M1, raw_M1 = compute_factors_marco(pos, abcxyz_map, excl_cat_ids, 10, 26, 'avg')
    print(f"  M1 (recent_10 vs long_26 avg):  {len(factors_M1)} clusters")
    factors_M2, raw_M2 = compute_factors_marco(pos, abcxyz_map, excl_cat_ids, 4, 16, 'avg')
    print(f"  M2 (recent_4 vs long_16 avg):   {len(factors_M2)} clusters")
    factors_M3, raw_M3 = compute_factors_marco(pos, abcxyz_map, excl_cat_ids, 10, 10, 'ly')
    print(f"  M3 (recent_10 vs LY 10):        {len(factors_M3)} clusters")

    # Aplicar al baseline (mapear abc_eff a abc)
    df_eval = df.copy()
    df_eval['abc'] = df_eval['abcxyz_eff'].fillna('').str.slice(0, 1)

    df_A = df_eval.copy()
    df_A['mu_adj'] = df_A['mu_week']

    def apply_factors(df_in, factors):
        df_in = df_in.copy()
        def fac(row):
            if pd.isna(row['categ_id']) or row['abc'] not in ('A', 'B', 'C'):
                return 1.0
            return factors.get((int(row['categ_id']), row['abc']), 1.0)
        df_in['fac'] = df_in.apply(fac, axis=1)
        df_in['mu_adj'] = df_in['mu_week'] * df_in['fac']
        return df_in

    df_B = apply_factors(df_eval, factors_B)
    df_M1 = apply_factors(df_eval, factors_M1)
    df_M2 = apply_factors(df_eval, factors_M2)
    df_M3 = apply_factors(df_eval, factors_M3)

    # Evaluar sobre universo limpio
    no_q = ~df_A['is_quiebre']
    no_cig = ~df_A['categ_id'].isin(excl_cat_ids)
    clean_mask = no_q & no_cig
    is_cerv = df_A['categ_id'].isin(cerv_cat_ids) & clean_mask

    def section(df_in, value, mask):
        return metrics(df_in[mask], value)

    rows = []
    for name, df_x, val in [
        ('A baseline',                df_A, 'mu_adj'),
        ('B (categ,abc) Test2 canon', df_B, 'mu_adj'),
        ('M1 (10vs26 avg)',           df_M1, 'mu_adj'),
        ('M2 (4vs16 avg)',            df_M2, 'mu_adj'),
        ('M3 (10vs LY10)',            df_M3, 'mu_adj'),
    ]:
        m_total = section(df_x, val, clean_mask)
        m_cerv = section(df_x, val, is_cerv)
        rows.append({'config': name, **{f'TOT_{k}': v for k, v in m_total.items()},
                     **{f'CERV_{k}': v for k, v in m_cerv.items()}})

    # Reporte
    lines = []
    lines.append("=" * 140)
    lines.append("TEST IDEA MARCO - nivel_actual / nivel_largo por (categ, abc)")
    lines.append(f"Target window: {TARGET_WEEKS[0]} .. {TARGET_WEEKS[-1]}  (10 sem)")
    lines.append(f"Cutoff calculo factor: {CUTOFF_MONDAY}  (data ANTES del target window)")
    lines.append("=" * 140)
    lines.append("")
    lines.append("CONFIGS:")
    lines.append("  A  = baseline v3.46 sin factor")
    lines.append("  B  = canon Test 2: factor = real_target / fcst_target por (categ, abc)  [usa target window]")
    lines.append("  M1 = MARCO: factor = avg(real ultimas 10 sem) / avg(real ultimas 26 sem) por (categ, abc)")
    lines.append("  M2 = MARCO: factor = avg(real ultimas 4 sem) / avg(real ultimas 16 sem)  [mas reactivo]")
    lines.append("  M3 = MARCO: factor = avg(real ultimas 10 sem) / avg(LY mismas 10 sem)    [vs ano anterior]")
    lines.append("")
    lines.append(f"  Universo limpio (sin cig/snack, sin quiebres): {df_A[clean_mask].shape[0]:,} filas")
    lines.append("")
    lines.append("METRICAS:")
    lines.append("-" * 140)
    lines.append(f"  {'config':<28s} | {'TOTAL WAPE':>11s} {'TOTAL BIAS':>11s} | {'CERV WAPE':>10s} {'CERV BIAS':>10s} | {'d_WAPE':>7s} {'d_BIAS':>7s}")
    base_wape = rows[0]['TOT_WAPE']; base_bias = rows[0]['TOT_BIAS']
    for r in rows:
        d_w = r['TOT_WAPE'] - base_wape
        d_b = r['TOT_BIAS'] - base_bias
        lines.append(f"  {r['config']:<28s} | {r['TOT_WAPE']:>10.2f}  {r['TOT_BIAS']:>+10.2f}  | "
                     f"{r['CERV_WAPE']:>10.2f}  {r['CERV_BIAS']:>+10.2f}  | "
                     f"{d_w:>+7.2f} {d_b:>+7.2f}")

    lines.append("")
    lines.append("=" * 140)
    lines.append("DIAGNOSTICO - factores Marco vs canon Test 2 para mismos clusters")
    lines.append("-" * 140)
    # Mostrar top 20 categs por volumen con factor B, M1, M2, M3
    cat_map = cats.set_index('categ_id_id')['complete_name'].to_dict()
    all_keys = set(factors_B.keys()) | set(factors_M1.keys()) | set(factors_M2.keys()) | set(factors_M3.keys())
    rows_diag = []
    for k in all_keys:
        cid, abc = k
        nm = (cat_map.get(int(cid), '?') or '')[:40]
        rows_diag.append({
            'cat': cid, 'abc': abc, 'name': nm,
            'B': factors_B.get(k, 1.0),
            'M1': factors_M1.get(k, 1.0),
            'M2': factors_M2.get(k, 1.0),
            'M3': factors_M3.get(k, 1.0),
        })
    rows_diag.sort(key=lambda x: abs(x['B'] - 1.0), reverse=True)
    lines.append(f"  {'cat':>5s} {'abc':>3s} {'name':<40s} | {'B canon':>8s} {'M1 10/26':>8s} {'M2 4/16':>8s} {'M3 LY':>8s}")
    for r in rows_diag[:25]:
        lines.append(f"  {int(r['cat']):>5d} {r['abc']:>3s} {r['name']:<40s} | "
                     f"{r['B']:>8.3f} {r['M1']:>8.3f} {r['M2']:>8.3f} {r['M3']:>8.3f}")
    lines.append("")
    lines.append("=" * 140)

    report = "\n".join(lines)
    print()
    print(report)
    out_txt = RESULTS / "test_idea_marco_nivel.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")
    print(f"\n -> {out_txt}")


if __name__ == "__main__":
    main()
