"""
Re-calcular factores categ_calib SIN excluir cigarros/snack/impulso
y comparar impacto contra:
  - U_actual: universo limpio sin cig/snack/impulso (los 50 factores actuales)
  - U_completo: universo limpio incluyendo cig/snack/impulso (factores nuevos)

Hipotesis: los quiebres son CIRCUNSTANCIALES. Filtrar filas con quiebre en
target_week es suficiente; no hace falta excluir categorias enteras a priori.
El filtro MIN_REAL_UNITS por cluster ya descarta clusters demasiado chicos.

Variaciones evaluadas:
  V1: Universo actual         (excluye cig/snack/impulso) - control
  V2: Universo completo       (NO excluye) min_real=500
  V3: Universo completo + min_real_alto=1000 para snack (filtro defensivo)

Salida: resultados/test_L1_universo_completo.txt + summary JSON
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

EXCLUDE_KEYWORDS_V1 = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']
SNACK_KEYWORDS = ['Snack', 'Impulso']

MIN_REAL_BASE = 500
MIN_REAL_SNACK = 1000  # filtro mas alto para snack/impulso por ruido
CLAMP_LO = 0.70
CLAMP_HI = 1.30
APPLY_THRESHOLD = 0.05


def compute_factors(df, group_cols, min_real_map):
    """min_real_map: dict {categ_id: min_real} para filtros por categoria."""
    g = df.groupby(group_cols).agg(
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        n=('qty_sold', 'size'),
    ).reset_index()
    g['raw'] = g['real'] / g['fcst'].replace(0, 1)
    g['clamped'] = g['raw'].clip(CLAMP_LO, CLAMP_HI)
    # filtro min_real por categoria (si esta en map) o base
    def get_thresh(row):
        cid = row['categ_id'] if 'categ_id' in row else None
        return min_real_map.get(int(cid) if cid is not None else -1, MIN_REAL_BASE)
    g['min_real_thresh'] = g.apply(get_thresh, axis=1)
    g['apply'] = (g['real'] >= g['min_real_thresh']) & ((g['clamped'] - 1.0).abs() >= APPLY_THRESHOLD)
    return g


def make_dict(g):
    return {(row['categ_id'], row['abc']): row['clamped']
            for _, row in g[g['apply']].iterrows()}


def metrics(df, value):
    r = df['qty_sold'].sum()
    if r <= 0:
        return {'WAPE': 0.0, 'BIAS': 0.0, 'real': 0.0, 'fcst': 0.0, 'n': int(len(df))}
    f = df[value].sum()
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return {
        'WAPE': round(ae / r * 100, 2),
        'BIAS': round(err / r * 100, 2),
        'real': float(r),
        'fcst': float(f),
        'n': int(len(df)),
    }


def main():
    print("Cargando detail.parquet...")
    df_all = pd.read_parquet(RESULTS / "simulacion_final_v347_detail.parquet")
    df = df_all[df_all['config'] == 'baseline_or_calib'].copy()
    print(f"  {len(df):,} filas")

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    df = df[df['categ_id'].notna() & df['team_id'].notna()].copy()
    df['categ_id'] = df['categ_id'].astype(int)
    df['abc'] = df['abcxyz_eff'].fillna('').str.slice(0, 1)
    df = df[df['abc'].isin(['A', 'B', 'C'])]

    excl_v1 = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS_V1), case=False, na=False
    )]['categ_id_id'])
    snack_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(SNACK_KEYWORDS), case=False, na=False
    )]['categ_id_id'])
    cig_ids = set(cats[cats['complete_name'].str.contains(
        'Cigarrillos|Cigarros|Tabaco', case=False, na=False
    )]['categ_id_id'])
    cerv_ids = set(cats[cats['complete_name'].str.contains(
        'Cervezas', case=False, na=False
    )]['categ_id_id'])

    # Universos de calibracion (siempre sin quiebres en target_week)
    sin_quiebres = df[~df['is_quiebre']]
    U_actual = sin_quiebres[~sin_quiebres['categ_id'].isin(excl_v1)]
    U_completo = sin_quiebres.copy()

    print(f"\nUniversos de calibracion (sin quiebres en target_week):")
    print(f"  U_actual (sin cig/snack/impulso): {len(U_actual):,} filas")
    print(f"  U_completo (incluye cig/snack):   {len(U_completo):,} filas")

    # V1: factores sobre U_actual con min_real=500 plano (replica Test 2)
    f_V1 = compute_factors(U_actual, ['categ_id', 'abc'], {})
    factors_V1 = make_dict(f_V1)
    # V2: factores sobre U_completo con min_real=500 plano
    f_V2 = compute_factors(U_completo, ['categ_id', 'abc'], {})
    factors_V2 = make_dict(f_V2)
    # V3: factores sobre U_completo, min_real=1000 para snack/impulso, 500 resto
    min_real_v3 = {cid: MIN_REAL_SNACK for cid in snack_ids}
    f_V3 = compute_factors(U_completo, ['categ_id', 'abc'], min_real_v3)
    factors_V3 = make_dict(f_V3)

    print(f"\nFactores activos:")
    print(f"  V1 (actual):       {len(factors_V1):>3d} clusters")
    print(f"  V2 (completo 500): {len(factors_V2):>3d} clusters")
    print(f"  V3 (completo c/snack=1000): {len(factors_V3):>3d} clusters")

    # ------------------------------------------------------------------
    # APLICAR cada set y medir
    # ------------------------------------------------------------------
    def apply_set(df_in, factors):
        df_in = df_in.copy()
        def fac(row):
            return factors.get((row['categ_id'], row['abc']), 1.0)
        df_in['fac'] = df_in.apply(fac, axis=1)
        df_in['mu_adj'] = df_in['mu_week'] * df_in['fac']
        return df_in

    df_V1 = apply_set(df, factors_V1)
    df_V2 = apply_set(df, factors_V2)
    df_V3 = apply_set(df, factors_V3)

    def section(df_in, value, mask):
        return metrics(df_in[mask], value)

    # Universos de evaluacion (siempre sin quiebres):
    #   eval_complete: TODO sin quiebres (incluye cig/snack)
    #   eval_actual:   sin quiebres, sin cig/snack (lo que se reporto en Test 2)
    no_q = ~df_V1['is_quiebre']
    no_cig_no_snack = ~df_V1['categ_id'].isin(excl_v1)
    is_cig = df_V1['categ_id'].isin(cig_ids)
    is_snack = df_V1['categ_id'].isin(snack_ids)
    is_cerv = df_V1['categ_id'].isin(cerv_ids)

    lines = []
    lines.append("=" * 140)
    lines.append("TEST L1 - universo de calibracion: incluir o excluir cigarros/snack?")
    lines.append("Hipotesis: quiebres son circunstanciales; el filtro de quiebre en target_week es suficiente.")
    lines.append("=" * 140)
    lines.append("")
    lines.append(f"FACTORES CALCULADOS:")
    lines.append(f"  V1 (actual, sin cig/snack/impulso, min_real=500): {len(factors_V1)} clusters")
    lines.append(f"  V2 (completo, min_real=500):                       {len(factors_V2)} clusters")
    lines.append(f"  V3 (completo, snack min_real=1000):                {len(factors_V3)} clusters")
    lines.append("")
    lines.append("METRICAS POR SUBSET (universo sin quiebres en target_week):")
    lines.append("")

    subsets = [
        ('TOTAL (incluye cig/snack)', no_q),
        ('SIN cigarros/snack/impulso (reporte oficial)', no_q & no_cig_no_snack),
        ('SOLO Cigarrillos/Tabaco', no_q & is_cig),
        ('SOLO Snack/Impulso', no_q & is_snack),
        ('SOLO Cervezas (foco)', no_q & is_cerv),
    ]

    for label, mask in subsets:
        m_base = section(df_V1, 'mu_week', mask)
        m_V1 = section(df_V1, 'mu_adj', mask)
        m_V2 = section(df_V2, 'mu_adj', mask)
        m_V3 = section(df_V3, 'mu_adj', mask)
        lines.append("-" * 140)
        lines.append(f"{label}    (n={m_base['n']:,}  real={m_base['real']:,.0f})")
        lines.append(f"  {'BASELINE':<24s} | WAPE={m_base['WAPE']:>6.2f}  BIAS={m_base['BIAS']:>+7.2f}")
        lines.append(f"  {'V1 (excluye cig/snack)':<24s} | WAPE={m_V1['WAPE']:>6.2f}  BIAS={m_V1['BIAS']:>+7.2f}   d_WAPE={m_V1['WAPE']-m_base['WAPE']:>+5.2f}  d_BIAS={m_V1['BIAS']-m_base['BIAS']:>+6.2f}")
        lines.append(f"  {'V2 (incluye cig/snack)':<24s} | WAPE={m_V2['WAPE']:>6.2f}  BIAS={m_V2['BIAS']:>+7.2f}   d_WAPE={m_V2['WAPE']-m_base['WAPE']:>+5.2f}  d_BIAS={m_V2['BIAS']-m_base['BIAS']:>+6.2f}")
        lines.append(f"  {'V3 (snack min=1000)':<24s} | WAPE={m_V3['WAPE']:>6.2f}  BIAS={m_V3['BIAS']:>+7.2f}   d_WAPE={m_V3['WAPE']-m_base['WAPE']:>+5.2f}  d_BIAS={m_V3['BIAS']-m_base['BIAS']:>+6.2f}")

    lines.append("")
    lines.append("=" * 140)
    lines.append("DIFF DE FACTORES V1 vs V2 (que clusters NUEVOS aparecen al incluir cig/snack?)")
    lines.append("-" * 140)
    new_in_V2 = set(factors_V2.keys()) - set(factors_V1.keys())
    removed = set(factors_V1.keys()) - set(factors_V2.keys())
    cat_map = cats.set_index('categ_id_id')['complete_name'].to_dict()
    lines.append(f"  Clusters nuevos en V2 (no estaban en V1): {len(new_in_V2)}")
    nuevos = []
    for k in sorted(new_in_V2):
        cid, abc = k
        nm = (cat_map.get(int(cid), '?') or '')[:55]
        nuevos.append((cid, abc, factors_V2[k], nm))
    nuevos.sort(key=lambda x: x[3])
    for cid, abc, f, nm in nuevos:
        lines.append(f"    cat={cid:>5d} abc={abc}  factor={f:.3f}  {nm}")
    lines.append(f"  Clusters perdidos (estaban en V1 y no en V2): {len(removed)}")
    for k in sorted(removed):
        lines.append(f"    cat={k[0]:>5d} abc={k[1]}  (perdido)")
    lines.append("")
    lines.append("=" * 140)
    lines.append("RECOMENDACION")
    lines.append("-" * 140)

    # Comparativa V1 vs V2 vs V3 sobre TOTAL (con cigarros/snack)
    m_tot_base = section(df_V1, 'mu_week', no_q)
    m_tot_V1 = section(df_V1, 'mu_adj', no_q)
    m_tot_V2 = section(df_V2, 'mu_adj', no_q)
    m_tot_V3 = section(df_V3, 'mu_adj', no_q)

    lines.append(f"  Sobre TOTAL (sin quiebres, incluye cig/snack para evaluar):")
    lines.append(f"    Baseline:     WAPE={m_tot_base['WAPE']:>6.2f}  BIAS={m_tot_base['BIAS']:>+7.2f}")
    lines.append(f"    V1 (excluye): WAPE={m_tot_V1['WAPE']:>6.2f}  BIAS={m_tot_V1['BIAS']:>+7.2f}  d_BIAS={m_tot_V1['BIAS']-m_tot_base['BIAS']:+.2f}")
    lines.append(f"    V2 (incluye): WAPE={m_tot_V2['WAPE']:>6.2f}  BIAS={m_tot_V2['BIAS']:>+7.2f}  d_BIAS={m_tot_V2['BIAS']-m_tot_base['BIAS']:+.2f}")
    lines.append(f"    V3 (snack defensivo): WAPE={m_tot_V3['WAPE']:>6.2f}  BIAS={m_tot_V3['BIAS']:>+7.2f}  d_BIAS={m_tot_V3['BIAS']-m_tot_base['BIAS']:+.2f}")
    lines.append("")
    # Veredicto
    options = [('V1', m_tot_V1), ('V2', m_tot_V2), ('V3', m_tot_V3)]
    options.sort(key=lambda x: (abs(x[1]['BIAS']), x[1]['WAPE']))
    winner = options[0]
    lines.append(f"  Mejor en |BIAS| (con WAPE controlado): {winner[0]}")
    lines.append(f"  Si quieres tambien medir 'sin cig/snack' como reporte oficial:")
    m_clean_V1 = section(df_V1, 'mu_adj', no_q & no_cig_no_snack)
    m_clean_V2 = section(df_V2, 'mu_adj', no_q & no_cig_no_snack)
    m_clean_V3 = section(df_V3, 'mu_adj', no_q & no_cig_no_snack)
    lines.append(f"    V1: WAPE={m_clean_V1['WAPE']:>6.2f} BIAS={m_clean_V1['BIAS']:>+7.2f}")
    lines.append(f"    V2: WAPE={m_clean_V2['WAPE']:>6.2f} BIAS={m_clean_V2['BIAS']:>+7.2f}  (debe ser ~igual V1 si los factores nuevos son solo de cig/snack)")
    lines.append(f"    V3: WAPE={m_clean_V3['WAPE']:>6.2f} BIAS={m_clean_V3['BIAS']:>+7.2f}")
    lines.append("=" * 140)

    report = "\n".join(lines)
    print()
    print(report)
    out_txt = RESULTS / "test_L1_universo_completo.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")
    print(f"\n -> {out_txt}")


if __name__ == "__main__":
    main()
