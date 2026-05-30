"""
Test consolidado L1 (hierarchical calib) + L2 (residual bias cap).

L1 - bake-off de 5 configs sobre el baseline v3.46 (10 sem):
  A: baseline v3.46                                (control)
  B: (L3, abc) - Test 2 actual (50 factores)        (control - ya medido)
  C: (L2, abc)                                      (familia, recomendado por analisis)
  D: cascada (L2, abc) -> abc -> 1.0  + gate REG    (DISENADO)
  E: cascada igual D pero SIN gate                  (aisla efecto del gate)

L2 - cap residual sobre la mejor config L1:
  F: best_L1 + bias_residual_correction global      (canon SAP IBP final correction)

Datos: reutiliza simulacion_final_v347_detail.parquet (baseline + factor original).
Recalcula factores localmente; aplica post-hoc al baseline.

Outputs:
  resultados/test_L1L2_consolidado.txt        (reporte legible)
  resultados/test_L1L2_consolidado_summary.json
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

MIN_REAL_UNITS = 500
CLAMP_LO = 0.70
CLAMP_HI = 1.30
APPLY_THRESHOLD = 0.05
REGIMEN_GATE = {'REG-1', 'REG-2', 'REG-4', 'REG-8'}

# L2 cap residual (canon SAP IBP final correction)
RESIDUAL_BIAS_THRESHOLD = 5.0      # pct - solo aplicar si BIAS residual > 5%
RESIDUAL_CAP_LO = 0.95
RESIDUAL_CAP_HI = 1.05
RESIDUAL_HARD_STOP = 15.0          # pct - si > 15% NO aplicar (problema upstream)

CERV_PRODUCT_FOCUS = 11797         # SKU 9407 Stella


def split_levels(complete_name):
    if not isinstance(complete_name, str) or not complete_name:
        return ('', '', '')
    parts = [p.strip() for p in complete_name.split(' / ')]
    L1 = parts[0] if len(parts) >= 1 else ''
    L2 = parts[1] if len(parts) >= 2 else L1
    L3 = parts[2] if len(parts) >= 3 else L2
    return (L1, L2, L3)


def compute_factors_by_level(df, group_cols):
    """Calcula factor por cluster con filtros canon (min_real, clamp, threshold)."""
    g = df.groupby(group_cols).agg(
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        n=('qty_sold', 'size'),
    ).reset_index()
    g['raw'] = g['real'] / g['fcst'].replace(0, 1)
    g['clamped'] = g['raw'].clip(CLAMP_LO, CLAMP_HI)
    g['apply'] = (g['real'] >= MIN_REAL_UNITS) & ((g['clamped'] - 1.0).abs() >= APPLY_THRESHOLD)
    return g


def make_factor_dict(g, group_cols):
    active = g[g['apply']]
    if len(group_cols) == 1:
        return {row[group_cols[0]]: row['clamped'] for _, row in active.iterrows()}
    return {tuple(row[c] for c in group_cols): row['clamped'] for _, row in active.iterrows()}


def apply_hierarchical(row, factors_L2_abc, factors_abc, apply_gate, gate_set):
    """Cascada: L2-abc -> abc -> 1.0. Con gate opcional por regimen."""
    if apply_gate and row['regimen_eff'] not in gate_set:
        return 1.0, 'gated_out'
    L2 = row.get('L2', '')
    abc = row.get('abc', '')
    if L2 and abc:
        key = (L2, abc)
        if key in factors_L2_abc:
            return factors_L2_abc[key], 'L2'
    if abc and abc in factors_abc:
        return factors_abc[abc], 'abc'
    return 1.0, 'none'


def metrics(df, value):
    r = df['qty_sold'].sum()
    f = df[value].sum()
    if r <= 0:
        return {'n_rows': int(len(df)), 'real': 0.0, 'fcst': 0.0, 'WAPE': 0.0, 'BIAS': 0.0}
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return {
        'n_rows': int(len(df)),
        'real': float(r),
        'fcst': float(f),
        'WAPE': round(ae / r * 100, 2),
        'BIAS': round(err / r * 100, 2),
    }


def section(df_full, value, label, cerv_cat_ids):
    """Calcula metricas sobre 3 universos: limpio, cervezas, sku9407."""
    clean = df_full[~df_full['is_quiebre']].copy()  # ya viene sin cig/snack del filtro previo
    out = {'label': label}
    out['total'] = metrics(clean, value)
    cer = clean[clean['categ_id'].isin(cerv_cat_ids)]
    out['cervezas'] = metrics(cer, value)
    s9407 = clean[clean['product_id'] == CERV_PRODUCT_FOCUS]
    out['sku_9407'] = metrics(s9407, value)
    # por regimen
    by_reg = {}
    for reg, g in clean.groupby('regimen_eff'):
        by_reg[reg] = metrics(g, value)
    out['by_regimen'] = by_reg
    return out


def fmt_section(s, label):
    lines = []
    lines.append(f"  {label:<32s} | "
                 f"TOTAL  WAPE={s['total']['WAPE']:>6.2f} BIAS={s['total']['BIAS']:>+7.2f} | "
                 f"CERV   WAPE={s['cervezas']['WAPE']:>6.2f} BIAS={s['cervezas']['BIAS']:>+7.2f} | "
                 f"9407   WAPE={s['sku_9407']['WAPE']:>6.2f} BIAS={s['sku_9407']['BIAS']:>+7.2f}")
    return "\n".join(lines)


def main():
    print("Cargando simulacion_final_v347_detail.parquet...")
    df_all = pd.read_parquet(RESULTS / "simulacion_final_v347_detail.parquet")
    df = df_all[df_all['config'] == 'baseline_or_calib'].copy()
    print(f"  {len(df):,} filas baseline")

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())
    cerv_cat_ids = set(cats[cats['complete_name'].str.contains(
        'Cervezas', case=False, na=False
    )]['categ_id_id'].tolist())
    cats[['L1', 'L2', 'L3']] = cats['complete_name'].apply(
        lambda x: pd.Series(split_levels(x))
    )
    cat_map = cats.set_index('categ_id_id')[['L1', 'L2', 'L3']].to_dict('index')

    df = df[df['categ_id'].notna() & df['team_id'].notna() & df['regimen_eff'].notna()].copy()
    df['team_id'] = df['team_id'].astype(int)
    df['categ_id'] = df['categ_id'].astype(int)
    df['L1'] = df['categ_id'].map(lambda c: cat_map.get(c, {}).get('L1', ''))
    df['L2'] = df['categ_id'].map(lambda c: cat_map.get(c, {}).get('L2', ''))
    df['abc'] = df['abcxyz_eff'].fillna('').str.slice(0, 1)
    df = df[df['abc'].isin(['A', 'B', 'C'])]

    # universo de calibracion = sin cig/snack/impulso, sin quiebres
    calib_universe = df[~df['categ_id'].isin(excl_cat_ids) & ~df['is_quiebre']].copy()
    print(f"  universo de calibracion: {len(calib_universe):,} filas")
    print(f"  universo de evaluacion: idem (excluye cig + quiebre)")

    # ------------------------------------------------------------------
    # CALCULAR FACTORES POR NIVEL (sobre el universo limpio del baseline)
    # ------------------------------------------------------------------
    # B: (L3=categ_id, abc) - replica Test 2 actual
    f_L3 = compute_factors_by_level(calib_universe, ['categ_id', 'abc'])
    factors_L3 = make_factor_dict(f_L3, ['categ_id', 'abc'])
    # C: (L2, abc)
    f_L2 = compute_factors_by_level(calib_universe, ['L2', 'abc'])
    factors_L2 = make_factor_dict(f_L2, ['L2', 'abc'])
    # D/E: abc solo (fallback)
    f_abc = compute_factors_by_level(calib_universe, ['abc'])
    factors_abc = make_factor_dict(f_abc, ['abc'])

    print(f"\nFactores activos por nivel:")
    print(f"  L3 (categ, abc):     {len(factors_L3):>3d} clusters")
    print(f"  L2 (familia, abc):   {len(factors_L2):>3d} clusters")
    print(f"  abc:                 {len(factors_abc):>3d} clusters")

    # ------------------------------------------------------------------
    # APLICAR CADA CONFIG AL UNIVERSO LIMPIO
    # ------------------------------------------------------------------
    # Universo a aplicar = todo (incluido cig/snack/quiebres) - pero evaluamos solo limpio
    universe = df.copy()

    # A: baseline
    universe['mu_A'] = universe['mu_week']

    # B: (L3, abc) plano
    def factor_B(row):
        return factors_L3.get((row['categ_id'], row['abc']), 1.0)
    universe['fac_B'] = universe.apply(factor_B, axis=1)
    universe['mu_B'] = universe['mu_week'] * universe['fac_B']

    # B': (L3, abc) + gate por regimen
    def factor_Bp(row):
        if row['regimen_eff'] not in REGIMEN_GATE:
            return 1.0
        return factors_L3.get((row['categ_id'], row['abc']), 1.0)
    universe['fac_Bp'] = universe.apply(factor_Bp, axis=1)
    universe['mu_Bp'] = universe['mu_week'] * universe['fac_Bp']

    # C: (L2, abc) plano
    def factor_C(row):
        return factors_L2.get((row['L2'], row['abc']), 1.0)
    universe['fac_C'] = universe.apply(factor_C, axis=1)
    universe['mu_C'] = universe['mu_week'] * universe['fac_C']

    # D: cascada con gate REG
    def cascade_D(row):
        return apply_hierarchical(row, factors_L2, factors_abc, True, REGIMEN_GATE)
    res_D = universe.apply(cascade_D, axis=1, result_type='expand')
    universe['fac_D'] = res_D[0]
    universe['lvl_D'] = res_D[1]
    universe['mu_D'] = universe['mu_week'] * universe['fac_D']

    # E: cascada sin gate
    def cascade_E(row):
        return apply_hierarchical(row, factors_L2, factors_abc, False, REGIMEN_GATE)
    res_E = universe.apply(cascade_E, axis=1, result_type='expand')
    universe['fac_E'] = res_E[0]
    universe['lvl_E'] = res_E[1]
    universe['mu_E'] = universe['mu_week'] * universe['fac_E']

    # ------------------------------------------------------------------
    # METRICAS por config sobre universo limpio (sin cig/snack/quiebre)
    # ------------------------------------------------------------------
    eval_universe = universe[~universe['categ_id'].isin(excl_cat_ids) & ~universe['is_quiebre']].copy()

    sec_A = section(eval_universe, 'mu_A', 'A baseline v3.46', cerv_cat_ids)
    sec_B = section(eval_universe, 'mu_B', 'B (L3, abc) Test2', cerv_cat_ids)
    sec_Bp = section(eval_universe, 'mu_Bp', "B' (L3, abc) + gate REG", cerv_cat_ids)
    sec_C = section(eval_universe, 'mu_C', 'C (L2, abc) familia', cerv_cat_ids)
    sec_D = section(eval_universe, 'mu_D', 'D cascada+gate', cerv_cat_ids)
    sec_E = section(eval_universe, 'mu_E', 'E cascada NO gate', cerv_cat_ids)

    # ------------------------------------------------------------------
    # DECIDIR MEJOR L1 + APLICAR L2 (cap residual)
    # ------------------------------------------------------------------
    sec_all_L1 = [sec_A, sec_B, sec_Bp, sec_C, sec_D, sec_E]
    # Criterio mejor L1: minimiza |BIAS total| con WAPE no degradado > 0.5pp vs A
    wape_A = sec_A['total']['WAPE']
    candidates = []
    for s, key in [(sec_B, 'B'), (sec_Bp, "B'"), (sec_C, 'C'), (sec_D, 'D'), (sec_E, 'E')]:
        d_wape = s['total']['WAPE'] - wape_A
        candidates.append({
            'config': key, 'sec': s,
            'd_WAPE': d_wape,
            'abs_BIAS': abs(s['total']['BIAS']),
            'passes_wape': d_wape <= 0.5,
        })
    candidates.sort(key=lambda x: (not x['passes_wape'], x['abs_BIAS']))
    best_L1 = candidates[0]
    print(f"\nMejor L1: {best_L1['config']} (|BIAS|={best_L1['abs_BIAS']:.2f}, d_WAPE={best_L1['d_WAPE']:+.2f}pp)")

    best_col = f"mu_{best_L1['config']}".replace("'", "p")  # B' -> mu_Bp
    bias_residual = best_L1['sec']['total']['BIAS']
    abs_residual = abs(bias_residual)

    print(f"\nBIAS residual del mejor L1: {bias_residual:+.2f}%")
    apply_L2 = False
    L2_factor_global = 1.0
    if abs_residual > RESIDUAL_HARD_STOP:
        print(f"  -> NO aplicar L2 (residual > {RESIDUAL_HARD_STOP}%, sintoma de problema upstream)")
    elif abs_residual > RESIDUAL_BIAS_THRESHOLD:
        # aplicar cap residual
        L2_factor_global = max(RESIDUAL_CAP_LO, min(RESIDUAL_CAP_HI, 1.0 + bias_residual / 100.0))
        apply_L2 = True
        print(f"  -> aplicar L2 cap global = {L2_factor_global:.4f}")
    else:
        print(f"  -> NO aplicar L2 (residual < {RESIDUAL_BIAS_THRESHOLD}%, ya esta dentro)")

    # F: best_L1 + L2 cap
    if apply_L2:
        eval_universe['mu_F'] = eval_universe[best_col] * L2_factor_global
        sec_F = section(eval_universe, 'mu_F', f'F = {best_L1["config"]} + L2 cap', cerv_cat_ids)
    else:
        sec_F = None

    # ------------------------------------------------------------------
    # REPORTE
    # ------------------------------------------------------------------
    lines = []
    lines.append("=" * 150)
    lines.append("TEST L1 + L2 CONSOLIDADO - hierarchical calib + residual bias correction")
    lines.append(f"Ventana: 10 sem (2026-03-16 .. 2026-05-18), universo limpio = {len(eval_universe):,} filas")
    lines.append("=" * 150)
    lines.append("")
    lines.append("FACTORES CALCULADOS POR NIVEL:")
    lines.append(f"  L3 (categ_id, abc):  {len(factors_L3)} clusters activos")
    lines.append(f"  L2 (familia, abc):   {len(factors_L2)} clusters activos")
    lines.append(f"  abc solo:            {len(factors_abc)} clusters activos")
    lines.append(f"  Regimen gate aplicado: {sorted(REGIMEN_GATE)}")
    lines.append("")
    lines.append("=" * 150)
    lines.append("L1 - BAKE-OFF 5 CONFIGS")
    lines.append("-" * 150)
    lines.append(fmt_section(sec_A, 'A baseline v3.46'))
    lines.append(fmt_section(sec_B, 'B (L3, abc) Test2 actual'))
    lines.append(fmt_section(sec_Bp, "B' (L3, abc) + gate REG"))
    lines.append(fmt_section(sec_C, 'C (L2, abc) familia'))
    lines.append(fmt_section(sec_D, 'D cascada L2->abc + gate REG'))
    lines.append(fmt_section(sec_E, 'E cascada L2->abc sin gate'))
    lines.append("")
    lines.append("Deltas vs A baseline:")
    for s, key in [(sec_B, 'B'), (sec_Bp, "B'"), (sec_C, 'C'), (sec_D, 'D'), (sec_E, 'E')]:
        dT_wape = s['total']['WAPE'] - sec_A['total']['WAPE']
        dT_bias = s['total']['BIAS'] - sec_A['total']['BIAS']
        dC_wape = s['cervezas']['WAPE'] - sec_A['cervezas']['WAPE']
        dC_bias = s['cervezas']['BIAS'] - sec_A['cervezas']['BIAS']
        d9_wape = s['sku_9407']['WAPE'] - sec_A['sku_9407']['WAPE']
        d9_bias = s['sku_9407']['BIAS'] - sec_A['sku_9407']['BIAS']
        lines.append(
            f"  {key} vs A: TOTAL d_WAPE={dT_wape:+6.2f} d_BIAS={dT_bias:+7.2f} | "
            f"CERV d_WAPE={dC_wape:+6.2f} d_BIAS={dC_bias:+7.2f} | "
            f"9407 d_WAPE={d9_wape:+6.2f} d_BIAS={d9_bias:+7.2f}"
        )
    lines.append("")
    lines.append(f"MEJOR L1: config {best_L1['config']}  (|BIAS|={best_L1['abs_BIAS']:.2f}%, d_WAPE={best_L1['d_WAPE']:+.2f}pp)")
    lines.append("")

    lines.append("=" * 150)
    lines.append("DIAGNOSTICO POR REGIMEN - mejor L1 (config %s)" % best_L1['config'])
    lines.append("-" * 150)
    lines.append(f"  {'regimen':<10s} | {'n_filas':>8s} {'real':>9s} | "
                 f"{'WAPE_A':>7s} {'BIAS_A':>8s}  {'WAPE_best':>10s} {'BIAS_best':>10s}  "
                 f"{'d_WAPE':>7s} {'d_BIAS':>7s}")
    A_by_reg = sec_A['by_regimen']
    B_by_reg = best_L1['sec']['by_regimen']
    for reg in sorted(A_by_reg.keys()):
        a = A_by_reg[reg]
        b = B_by_reg.get(reg, a)
        d_wape = b['WAPE'] - a['WAPE']
        d_bias = b['BIAS'] - a['BIAS']
        veredicto = ''
        if d_bias < -2 and d_wape < 0.5:
            veredicto = '<- MEJORA'
        elif d_wape > 1.0:
            veredicto = '<- EMPEORA W'
        lines.append(
            f"  {reg:<10s} | {a['n_rows']:>8,} {a['real']:>9,.0f} | "
            f"{a['WAPE']:>7.2f} {a['BIAS']:>+8.2f}  {b['WAPE']:>10.2f} {b['BIAS']:>+9.2f}  "
            f"{d_wape:>+7.2f} {d_bias:>+7.2f}  {veredicto}"
        )
    lines.append("")

    lines.append("=" * 150)
    lines.append("L2 - RESIDUAL BIAS CAP")
    lines.append("-" * 150)
    lines.append(f"  BIAS residual del mejor L1 ({best_L1['config']}): {bias_residual:+.2f}%")
    lines.append(f"  Threshold para aplicar: |BIAS| > {RESIDUAL_BIAS_THRESHOLD}%")
    lines.append(f"  Hard stop (no aplicar si): |BIAS| > {RESIDUAL_HARD_STOP}%")
    lines.append(f"  Cap: factor_global in [{RESIDUAL_CAP_LO}, {RESIDUAL_CAP_HI}]")
    if apply_L2:
        lines.append(f"  Decision: APLICAR L2  factor_global = {L2_factor_global:.4f}")
        lines.append("")
        lines.append(fmt_section(sec_F, f'F = {best_L1["config"]} + L2 cap'))
        dT_wape = sec_F['total']['WAPE'] - sec_A['total']['WAPE']
        dT_bias = sec_F['total']['BIAS'] - sec_A['total']['BIAS']
        lines.append(f"  F vs A: d_WAPE={dT_wape:+.2f}pp d_BIAS={dT_bias:+.2f}pp")
        dF_wape = sec_F['total']['WAPE'] - best_L1['sec']['total']['WAPE']
        dF_bias = sec_F['total']['BIAS'] - best_L1['sec']['total']['BIAS']
        lines.append(f"  F vs {best_L1['config']}: d_WAPE={dF_wape:+.2f}pp d_BIAS={dF_bias:+.2f}pp")
    else:
        if abs_residual <= RESIDUAL_BIAS_THRESHOLD:
            lines.append(f"  Decision: NO aplicar L2 (residual ya dentro de tolerancia)")
        else:
            lines.append(f"  Decision: NO aplicar L2 (residual > hard_stop; investigar upstream)")
    lines.append("")

    lines.append("=" * 150)
    lines.append("RANKING FINAL - todas las configs ordenadas por |BIAS|")
    lines.append("-" * 150)
    all_secs = [(sec_A, 'A'), (sec_B, 'B'), (sec_Bp, "B'"), (sec_C, 'C'), (sec_D, 'D'), (sec_E, 'E')]
    if sec_F:
        all_secs.append((sec_F, 'F'))
    all_secs.sort(key=lambda x: abs(x[0]['total']['BIAS']))
    for s, k in all_secs:
        lines.append(
            f"  {k}: |BIAS|={abs(s['total']['BIAS']):>5.2f}  BIAS={s['total']['BIAS']:>+6.2f}  "
            f"WAPE={s['total']['WAPE']:>6.2f}  d_WAPE_vs_A={s['total']['WAPE']-sec_A['total']['WAPE']:+5.2f}pp"
        )
    lines.append("")

    lines.append("=" * 150)
    lines.append("RECOMENDACION DE PROMOCION")
    lines.append("-" * 150)
    # criterio formal: el mejor L1 + opcional L2 cumple WAPE no degrada > 0.5pp y BIAS magnitud baja >= 8pp
    best_final = all_secs[0][0]
    best_final_key = all_secs[0][1]
    d_wape = best_final['total']['WAPE'] - sec_A['total']['WAPE']
    bias_drop = abs(sec_A['total']['BIAS']) - abs(best_final['total']['BIAS'])
    cerv_d_wape = best_final['cervezas']['WAPE'] - sec_A['cervezas']['WAPE']
    cerv_bias_drop = abs(sec_A['cervezas']['BIAS']) - abs(best_final['cervezas']['BIAS'])

    if (d_wape <= 0.5 and bias_drop >= 8.0
            and cerv_d_wape <= 0.5 and cerv_bias_drop >= 10.0):
        veredicto = f"PROMOVER config {best_final_key} - cumple los 4 criterios"
    else:
        razones = []
        if d_wape > 0.5: razones.append(f"WAPE total degrada {d_wape:.2f}pp")
        if bias_drop < 8.0: razones.append(f"BIAS total solo baja {bias_drop:.2f}pp")
        if cerv_d_wape > 0.5: razones.append(f"WAPE cerv degrada {cerv_d_wape:.2f}pp")
        if cerv_bias_drop < 10.0: razones.append(f"BIAS cerv solo baja {cerv_bias_drop:.2f}pp")
        veredicto = f"REVISAR config {best_final_key} - {'; '.join(razones)}"

    lines.append(f"  {veredicto}")
    lines.append(f"  Config recomendada: {best_final_key}")
    lines.append(f"  WAPE: {sec_A['total']['WAPE']:.2f} -> {best_final['total']['WAPE']:.2f} ({d_wape:+.2f}pp)")
    lines.append(f"  BIAS: {sec_A['total']['BIAS']:+.2f} -> {best_final['total']['BIAS']:+.2f} ({best_final['total']['BIAS']-sec_A['total']['BIAS']:+.2f}pp)")
    lines.append(f"  Cervezas WAPE: {sec_A['cervezas']['WAPE']:.2f} -> {best_final['cervezas']['WAPE']:.2f} ({cerv_d_wape:+.2f}pp)")
    lines.append(f"  Cervezas BIAS: {sec_A['cervezas']['BIAS']:+.2f} -> {best_final['cervezas']['BIAS']:+.2f} ({best_final['cervezas']['BIAS']-sec_A['cervezas']['BIAS']:+.2f}pp)")
    lines.append(f"  SKU 9407 BIAS: {sec_A['sku_9407']['BIAS']:+.2f} -> {best_final['sku_9407']['BIAS']:+.2f}")
    lines.append("=" * 150)

    report = "\n".join(lines)
    print()
    print(report)

    out_txt = RESULTS / "test_L1L2_consolidado.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")

    summary = {
        'configs': {
            'A': sec_A, 'B': sec_B, "B'": sec_Bp, 'C': sec_C, 'D': sec_D, 'E': sec_E,
            'F': sec_F,
        },
        'best_L1': best_L1['config'],
        'apply_L2': apply_L2,
        'L2_factor_global': L2_factor_global,
        'recommendation': {
            'config': best_final_key,
            'verdict': veredicto,
            'd_wape_total': round(d_wape, 2),
            'd_bias_total': round(best_final['total']['BIAS'] - sec_A['total']['BIAS'], 2),
            'd_wape_cervezas': round(cerv_d_wape, 2),
            'd_bias_cervezas': round(best_final['cervezas']['BIAS'] - sec_A['cervezas']['BIAS'], 2),
        },
        'factors_count': {
            'L3_abc': len(factors_L3),
            'L2_abc': len(factors_L2),
            'abc_only': len(factors_abc),
        },
        'L2_factors_dict': {f"{k[0]}|{k[1]}": float(v) for k, v in factors_L2.items()},
        'abc_factors_dict': {k: float(v) for k, v in factors_abc.items()},
    }
    out_json = RESULTS / "test_L1L2_consolidado_summary.json"
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n -> {out_txt}")
    print(f" -> {out_json}")


if __name__ == "__main__":
    main()
