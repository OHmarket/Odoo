"""
Backtest 10 semanas por regimen, ajustando por quiebres de stock.

Para cada fila del backtest, busca en x_demanda_normalizada si tuvo censura:
  - avail < 1.0  -> hay quiebre detectado
  - qty_norm     -> demanda subyacente (estimada sin censura)
  - qty_obs      -> lo que se vendió (con quiebre)

Reporta WAPE/BIAS en 3 vistas:
  - "observed": fcst vs qty_sold (lo que medimos antes, con quiebres contaminados)
  - "normalized": fcst vs qty_norm (donde existe) o qty_sold (donde no)
  - "no_quiebre": excluyendo las filas censuradas (avail < 1.0)
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    # Cargar demanda_norm
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={
        'x_studio_qty_norm': 'qty_norm',
        'x_studio_qty_obs': 'qty_obs',
        'x_studio_factor': 'norm_factor',
        'x_studio_avail': 'avail',
    })
    dn = dn[['team_id', 'product_id', 'week_start', 'qty_norm', 'qty_obs', 'avail', 'norm_factor']]
    print(f"demanda_norm: {len(dn):,} filas censuradas (avail<1.0 indicador)")

    target_weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

    parts = []
    for target in target_weeks:
        cutoff = target - timedelta(days=1)
        print(f"\nCutoff {cutoff} -> Target {target}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)

        # Real qty_sold (lo medido directo POS)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]

        merged = fc[['team_id', 'product_id', 'mu_week', 'regimen_eff',
                      'forecast_model_code', 'abcxyz_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        )
        merged['target_week'] = target
        merged['qty_sold'] = merged['qty_sold'].fillna(0.0)
        merged['mu_week'] = merged['mu_week'].fillna(0.0)

        # Agregar info de censura
        dn_wk = dn[dn['week_start'] == target][['team_id', 'product_id', 'qty_norm', 'avail']]
        merged = merged.merge(
            dn_wk, on=['team_id', 'product_id'], how='left'
        )

        parts.append(merged)

    df = pd.concat(parts, ignore_index=True)
    df['regimen_eff'] = df['regimen_eff'].fillna('NO_FC')
    df['real_normalized'] = df['qty_norm'].where(df['qty_norm'].notna(), df['qty_sold'])
    df['is_censored'] = df['avail'].notna() & (df['avail'] < 1.0)

    print(f"\nTotal filas: {len(df):,}")
    print(f"  Censuradas (avail<1.0): {df['is_censored'].sum():,} ({100*df['is_censored'].mean():.1f}%)")

    # ===== Vista 1: por regimen, 3 modos =====
    print("\n" + "=" * 110)
    print("WAPE / BIAS por regimen (10 sem) - 3 modos")
    print("=" * 110)

    rows = []
    for reg, sub in df.groupby('regimen_eff'):
        # Observed (qty_sold raw)
        real_obs = sub['qty_sold'].sum()
        fcst = sub['mu_week'].sum()
        ae_obs = (sub['mu_week'] - sub['qty_sold']).abs().sum()
        err_obs = (sub['qty_sold'] - sub['mu_week']).sum()
        # Normalized (qty_norm donde existe)
        real_norm = sub['real_normalized'].sum()
        ae_norm = (sub['mu_week'] - sub['real_normalized']).abs().sum()
        err_norm = (sub['real_normalized'] - sub['mu_week']).sum()
        # Sin quiebre (excluir censuradas)
        clean = sub[~sub['is_censored']]
        real_clean = clean['qty_sold'].sum()
        fcst_clean = clean['mu_week'].sum()
        ae_clean = (clean['mu_week'] - clean['qty_sold']).abs().sum()
        err_clean = (clean['qty_sold'] - clean['mu_week']).sum()

        rows.append({
            'regimen': reg,
            'n': len(sub),
            'n_censored': int(sub['is_censored'].sum()),
            'real_obs': round(real_obs, 0),
            'real_norm': round(real_norm, 0),
            'fcst': round(fcst, 0),
            'WAPE_obs': round(ae_obs / real_obs * 100 if real_obs > 0 else 0, 1),
            'BIAS_obs': round(err_obs / real_obs * 100 if real_obs > 0 else 0, 1),
            'WAPE_norm': round(ae_norm / real_norm * 100 if real_norm > 0 else 0, 1),
            'BIAS_norm': round(err_norm / real_norm * 100 if real_norm > 0 else 0, 1),
            'WAPE_clean': round(ae_clean / real_clean * 100 if real_clean > 0 else 0, 1),
            'BIAS_clean': round(err_clean / real_clean * 100 if real_clean > 0 else 0, 1),
        })

    df_reg = pd.DataFrame(rows).sort_values('real_obs', ascending=False)
    print(df_reg.to_string(index=False))

    # ===== Vista 2: totales agregados =====
    print("\n" + "=" * 110)
    print("Totales agregados 10 semanas")
    print("=" * 110)
    for label, real_col in [('observed (qty_sold)', 'qty_sold'),
                             ('normalized (qty_norm o qty_sold)', 'real_normalized')]:
        real = df[real_col].sum()
        fcst = df['mu_week'].sum()
        ae = (df['mu_week'] - df[real_col]).abs().sum()
        err = (df[real_col] - df['mu_week']).sum()
        wape = ae / real * 100 if real > 0 else 0
        bias = err / real * 100 if real > 0 else 0
        print(f"  {label:35s}  real={real:>10,.0f}  fcst={fcst:>10,.0f}  WAPE={wape:>5.1f}%  BIAS={bias:>+5.1f}%")

    # Solo sin quiebre
    clean = df[~df['is_censored']]
    real_c = clean['qty_sold'].sum()
    fcst_c = clean['mu_week'].sum()
    ae_c = (clean['mu_week'] - clean['qty_sold']).abs().sum()
    err_c = (clean['qty_sold'] - clean['mu_week']).sum()
    wape_c = ae_c / real_c * 100 if real_c > 0 else 0
    bias_c = err_c / real_c * 100 if real_c > 0 else 0
    print(f"  {'sin quiebre (excluyendo censura)':35s}  real={real_c:>10,.0f}  fcst={fcst_c:>10,.0f}  WAPE={wape_c:>5.1f}%  BIAS={bias_c:>+5.1f}%")

    # Solo censuradas
    cens = df[df['is_censored']]
    real_obs_cens = cens['qty_sold'].sum()
    real_norm_cens = cens['real_normalized'].sum()
    fcst_cens = cens['mu_week'].sum()
    print(f"\n  Solo CENSURADAS (n={len(cens):,}):")
    print(f"    real_obs (lo medido): {real_obs_cens:,.0f}")
    print(f"    real_norm (subyacente): {real_norm_cens:,.0f}")
    print(f"    fcst: {fcst_cens:,.0f}")
    print(f"    factor norm/obs: {real_norm_cens/real_obs_cens:.2f}x")

    out = RESULTS / "backtest_10_quiebre.parquet"
    df_reg.to_parquet(out, index=False)
    print(f"\n  -> {out.name}")


if __name__ == "__main__":
    main()
