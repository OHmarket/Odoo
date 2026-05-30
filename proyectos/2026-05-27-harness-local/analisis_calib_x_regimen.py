"""
Analisis: como interactua categ_calib_factor (v3.47) con los regimenes del motor?

Hipotesis: el motor ya tiene routing por regimen (REG-0..REG-8) que aplica
modelos distintos (SMA, Croston, SBA, seasonal, min_stock). Aplicar un factor
uniforme por (categ, abc) sobre todos los regimenes puede:
  - Mejorar los regimenes con sesgo (REG-1/3/4 sub-forecast estructural).
  - Empeorar los regimenes ya bien calibrados (REG-7 seasonal, REG-8 lumpy).

Mide:
  1. BIAS baseline por regimen (donde esta el problema).
  2. BIAS post-calib v3.47 por regimen (donde mejora vs empeora).
  3. Cobertura de filas con factor por regimen.
  4. Mix de regimenes dentro de cada (categ, abc) — si es muy mixto, el factor
     uniforme no puede ser optimo.

Datos: simulacion_final_v347_detail.parquet (baseline + categ_calib aplicado).
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']


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
    print("Cargando simulacion_final_v347_detail.parquet...")
    df = pd.read_parquet(RESULTS / "simulacion_final_v347_detail.parquet")
    # Filtrar solo baseline (no la version Test 1 tuning)
    if 'config' in df.columns:
        df = df[df['config'] == 'baseline_or_calib'].copy()
    print(f"  {len(df):,} filas baseline")

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())

    df = df[df['categ_id'].notna() & df['team_id'].notna() & df['regimen_eff'].notna()].copy()
    df['abc'] = df['abcxyz_eff'].fillna('').str.slice(0, 1)
    df = df[df['abc'].isin(['A', 'B', 'C'])]
    clean = df[~df['categ_id'].isin(excl_cat_ids) & ~df['is_quiebre']].copy()
    # mu_week_calib es la columna con factor aplicado
    clean['has_factor'] = clean['mu_week_calib_factor'] != 1.0

    lines = []
    lines.append("=" * 130)
    lines.append("ANALISIS: categ_calib_factor (v3.47) x regimen del motor")
    lines.append(f"Universo limpio: {len(clean):,} filas (baseline v3.46, sin cig/snack, sin quiebres)")
    lines.append("=" * 130)
    lines.append("")

    # ------------------------------------------------------------------
    # 1. BIAS baseline por regimen
    # ------------------------------------------------------------------
    lines.append("PARTE 1: BIAS baseline por regimen (donde esta el sesgo?)")
    lines.append("-" * 130)
    by_reg = clean.groupby('regimen_eff').apply(
        lambda g: pd.Series({
            'n_filas': int(len(g)),
            'real': g['qty_sold'].sum(),
            'fcst_base': g['mu_week'].sum(),
            'fcst_calib': g['mu_week_calib'].sum(),
            'ae_base': (g['mu_week'] - g['qty_sold']).abs().sum(),
            'ae_calib': (g['mu_week_calib'] - g['qty_sold']).abs().sum(),
            'n_with_factor': int(g['has_factor'].sum()),
        }), include_groups=False
    ).reset_index()
    by_reg['WAPE_base'] = (by_reg['ae_base'] / by_reg['real'] * 100).round(2)
    by_reg['BIAS_base'] = ((by_reg['real'] - by_reg['fcst_base']) / by_reg['real'] * 100).round(2)
    by_reg['WAPE_calib'] = (by_reg['ae_calib'] / by_reg['real'] * 100).round(2)
    by_reg['BIAS_calib'] = ((by_reg['real'] - by_reg['fcst_calib']) / by_reg['real'] * 100).round(2)
    by_reg['d_WAPE'] = (by_reg['WAPE_calib'] - by_reg['WAPE_base']).round(2)
    by_reg['d_BIAS'] = (by_reg['BIAS_calib'] - by_reg['BIAS_base']).round(2)
    by_reg['pct_cov'] = (by_reg['n_with_factor'] / by_reg['n_filas'] * 100).round(1)
    by_reg = by_reg.sort_values('real', ascending=False)

    lines.append(
        f"  {'regimen':<10s} {'n_filas':>8s} {'real':>9s} {'pct_cov':>7s} | "
        f"{'WAPE_base':>9s} {'BIAS_base':>9s} | "
        f"{'WAPE_calib':>10s} {'BIAS_calib':>10s} | "
        f"{'d_WAPE':>7s} {'d_BIAS':>7s}"
    )
    for _, r in by_reg.iterrows():
        veredicto = ''
        if r['d_BIAS'] < -2.0 and r['d_WAPE'] < 0.5:
            veredicto = '<- MEJORA'
        elif r['d_WAPE'] > 1.0:
            veredicto = '<- EMPEORA WAPE'
        elif r['d_BIAS'] > 2.0:
            veredicto = '<- EMPEORA BIAS'
        lines.append(
            f"  {r['regimen_eff']:<10s} {int(r['n_filas']):>8,} {r['real']:>9,.0f} {r['pct_cov']:>6.1f}% | "
            f"{r['WAPE_base']:>9.2f} {r['BIAS_base']:>+8.2f}  | "
            f"{r['WAPE_calib']:>10.2f} {r['BIAS_calib']:>+9.2f}  | "
            f"{r['d_WAPE']:>+7.2f} {r['d_BIAS']:>+7.2f}  {veredicto}"
        )
    lines.append("")

    # ------------------------------------------------------------------
    # 2. Mix de regimenes dentro de cada (categ, abc) cluster
    # ------------------------------------------------------------------
    lines.append("=" * 130)
    lines.append("PARTE 2: mix de regimenes dentro de cada (categ_id, abc_letter)")
    lines.append("-" * 130)
    lines.append("  Si un cluster tiene multiples regimenes -> el factor uniforme NO puede ser optimo.")
    lines.append("  Mide: n_regimenes presentes y la dispersion del BIAS baseline entre regimenes.")
    lines.append("")

    # Por cada (categ, abc) que tenga factor, ver cuantos regimenes y dispersion BIAS
    clusters_with_factor = clean[clean['has_factor']].copy()
    mix = clusters_with_factor.groupby(['categ_id', 'abc']).apply(
        lambda g: pd.Series({
            'real': g['qty_sold'].sum(),
            'n_regs': int(g['regimen_eff'].nunique()),
            'regs_present': ','.join(sorted(g['regimen_eff'].unique())),
            'factor_applied': float(g['mu_week_calib_factor'].iloc[0]),
        }), include_groups=False
    ).reset_index()

    # BIAS por (cluster, regimen) para ver dispersion intra-cluster
    bias_by_reg = clusters_with_factor.groupby(['categ_id', 'abc', 'regimen_eff']).apply(
        lambda g: pd.Series({
            'real': g['qty_sold'].sum(),
            'fcst': g['mu_week'].sum(),
        }), include_groups=False
    ).reset_index()
    bias_by_reg['BIAS_pct'] = np.where(
        bias_by_reg['real'] >= 50,
        (bias_by_reg['real'] - bias_by_reg['fcst']) / bias_by_reg['real'].replace(0, 1) * 100,
        np.nan,
    )
    # Std de BIAS entre regimenes dentro del mismo (categ, abc)
    bias_disp = bias_by_reg.dropna(subset=['BIAS_pct']).groupby(['categ_id', 'abc']).agg(
        regs_with_signal=('BIAS_pct', 'count'),
        bias_std=('BIAS_pct', 'std'),
        bias_range=('BIAS_pct', lambda x: x.max() - x.min()),
    ).reset_index()
    mix = mix.merge(bias_disp, on=['categ_id', 'abc'], how='left')
    mix = mix.merge(
        cats[['categ_id_id', 'complete_name']].rename(columns={'categ_id_id': 'categ_id'}),
        on='categ_id', how='left',
    )
    mix['name'] = mix['complete_name'].fillna('').str.slice(0, 38)
    mix = mix.sort_values('real', ascending=False)

    lines.append(
        f"  {'cat':>5s} {'name':<38s} {'abc':>3s} {'real':>7s} "
        f"{'factor':>6s} {'n_regs':>6s} {'regs_signal':>11s} {'BIAS_std':>9s} {'BIAS_range':>10s}  regimenes"
    )
    for _, r in mix.head(20).iterrows():
        bs = r['bias_std'] if pd.notna(r['bias_std']) else None
        br = r['bias_range'] if pd.notna(r['bias_range']) else None
        bs_s = f"{bs:>8.2f}pp" if bs is not None else "       --"
        br_s = f"{br:>9.2f}pp" if br is not None else "        --"
        lines.append(
            f"  {int(r['categ_id']):>5d} {r['name']:<38s} {r['abc']:>3s} {r['real']:>7,.0f} "
            f"{r['factor_applied']:>6.2f} {int(r['n_regs']):>6d} "
            f"{int(r['regs_with_signal']) if pd.notna(r['regs_with_signal']) else 0:>11d} "
            f"{bs_s} {br_s}  {r['regs_present']}"
        )

    # ------------------------------------------------------------------
    # 3. Tabla pivot: BIAS baseline por (regimen, abc) - confirma que abc x reg discrimina
    # ------------------------------------------------------------------
    lines.append("")
    lines.append("=" * 130)
    lines.append("PARTE 3: BIAS baseline por (regimen x abc) - donde concentra el sesgo del motor")
    lines.append("-" * 130)
    pivot_real = clean.groupby(['regimen_eff', 'abc'])['qty_sold'].sum().unstack(fill_value=0)
    pivot_fcst = clean.groupby(['regimen_eff', 'abc'])['mu_week'].sum().unstack(fill_value=0)
    pivot_bias = ((pivot_real - pivot_fcst) / pivot_real.replace(0, np.nan) * 100).round(1)
    pivot_n = clean.groupby(['regimen_eff', 'abc']).size().unstack(fill_value=0)

    lines.append("  BIAS% baseline:")
    lines.append(f"  {'regimen':<10s} | {'A':>10s} {'B':>10s} {'C':>10s} | {'real_total':>11s}")
    for reg in pivot_bias.index:
        a_b = pivot_bias.loc[reg].get('A', np.nan)
        b_b = pivot_bias.loc[reg].get('B', np.nan)
        c_b = pivot_bias.loc[reg].get('C', np.nan)
        real_t = pivot_real.loc[reg].sum()
        lines.append(
            f"  {reg:<10s} | "
            f"{(f'{a_b:+.1f}%' if pd.notna(a_b) else '--'):>10s} "
            f"{(f'{b_b:+.1f}%' if pd.notna(b_b) else '--'):>10s} "
            f"{(f'{c_b:+.1f}%' if pd.notna(c_b) else '--'):>10s} | "
            f"{real_t:>11,.0f}"
        )

    lines.append("")
    lines.append("=" * 130)
    lines.append("CONCLUSION OPERATIVA")
    lines.append("-" * 130)
    # Regimenes con BIAS positivo grande (sub-forecast) -> beneficiarios del calib
    high_bias = by_reg[by_reg['BIAS_base'] > 10].copy()
    low_bias = by_reg[by_reg['BIAS_base'].abs() < 5].copy()
    neg_bias = by_reg[by_reg['BIAS_base'] < -5].copy()
    lines.append(f"  Regimenes con BIAS baseline > +10% (sub-forecast sistemico - calib MEJORA):")
    for _, r in high_bias.iterrows():
        lines.append(f"    -> {r['regimen_eff']:<8s} real={r['real']:>8,.0f}  BIAS={r['BIAS_base']:+5.1f}%  d_BIAS calib={r['d_BIAS']:+5.1f}pp  d_WAPE={r['d_WAPE']:+5.1f}pp")
    lines.append(f"  Regimenes con BIAS baseline ~0 (calib puede SOBRE-corregir):")
    for _, r in low_bias.iterrows():
        lines.append(f"    -> {r['regimen_eff']:<8s} real={r['real']:>8,.0f}  BIAS={r['BIAS_base']:+5.1f}%  d_BIAS calib={r['d_BIAS']:+5.1f}pp  d_WAPE={r['d_WAPE']:+5.1f}pp")
    if not neg_bias.empty:
        lines.append(f"  Regimenes con BIAS baseline < -5% (over-forecast - calib puede AMPLIFICAR):")
        for _, r in neg_bias.iterrows():
            lines.append(f"    -> {r['regimen_eff']:<8s} real={r['real']:>8,.0f}  BIAS={r['BIAS_base']:+5.1f}%  d_BIAS calib={r['d_BIAS']:+5.1f}pp")
    lines.append("=" * 130)

    report = "\n".join(lines)
    print()
    print(report)

    out_txt = RESULTS / "analisis_calib_x_regimen.txt"
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write(report + "\n")
    print(f"\n -> {out_txt}")


if __name__ == "__main__":
    main()
