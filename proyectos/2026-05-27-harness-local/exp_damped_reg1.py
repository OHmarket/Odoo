"""
Experimento: damped trend como candidato del bake-off, gateado a REG-1.
A/B en 10 semanas (W12-W21 de 2026). Mide WAPE/BIAS PONDERADO de REG-1,
con vs sin damped, por semana. Criterio: WAPE REG-1 baja y es consistente.

El conjunto REG-1 es identico en ambos brazos (el regimen no depende del
metodo), asi que es A/B limpio sobre los mismos SKUs.
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

DAMPED_CFG = {'regimenes': {'REG-1'}, 'alpha': 0.25, 'beta': 0.10,
              'phi': 0.90, 'r2_min': 0.15}


def measure_reg1(fc, real):
    """WAPE/BIAS ponderado sobre los SKUs REG-1 del forecast."""
    method_col = 'demand_method' if 'demand_method' in fc.columns else (
        'method' if 'method' in fc.columns else None)
    cols = ['team_id', 'product_id', 'mu_week']
    if method_col:
        cols.append(method_col)
    fc_reg1 = fc[fc['regimen_eff'] == 'REG-1'][cols].copy()
    n_damped = int((fc_reg1[method_col] == 'damped').sum()) if method_col else -1
    merged = fc_reg1.merge(real, on=['team_id', 'product_id'], how='left').fillna(0.0)
    r = merged['real_qty'].sum()
    ae = (merged['mu_week'] - merged['real_qty']).abs().sum()
    err = (merged['real_qty'] - merged['mu_week']).sum()
    wape = ae / r * 100 if r > 0 else 0.0
    bias = err / r * 100 if r > 0 else 0.0
    return wape, bias, r, len(fc_reg1), n_damped


def run_arm(damped_cfg, pos, target_weeks):
    cfg = dict(DEFAULT_CONFIG)
    cfg['DAMPED'] = damped_cfg
    rows = []
    for target in target_weeks:
        cutoff = target - timedelta(days=1)
        fc = run(cutoff_date=cutoff, config=cfg, cache_dir=CACHE)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']].rename(
            columns={'qty_sold': 'real_qty'})
        wape, bias, r, n_reg1, n_damped = measure_reg1(fc, real)
        rows.append({'target': str(target), 'real': round(r, 0), 'n_reg1': n_reg1,
                     'WAPE': round(wape, 2), 'BIAS': round(bias, 2), 'n_damped': n_damped})
    return pd.DataFrame(rows)


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    target_weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

    print("Baseline (sin damped)...")
    base = run_arm(None, pos, target_weeks)
    print("Tratamiento (damped REG-1)...")
    treat = run_arm(DAMPED_CFG, pos, target_weeks)

    comp = base[['target', 'real', 'n_reg1', 'WAPE', 'BIAS']].rename(
        columns={'WAPE': 'WAPE_base', 'BIAS': 'BIAS_base'})
    comp['WAPE_damp'] = treat['WAPE'].values
    comp['BIAS_damp'] = treat['BIAS'].values
    comp['n_damped'] = treat['n_damped'].values
    comp['dWAPE'] = (comp['WAPE_damp'] - comp['WAPE_base']).round(2)
    comp['dBIAS'] = (comp['BIAS_damp'] - comp['BIAS_base']).round(2)

    print("\n" + "=" * 120)
    print("DAMPED TREND en REG-1 - A/B 10 semanas (WAPE/BIAS ponderado por semana)")
    print("=" * 120)
    print(comp.to_string(index=False))

    # WAPE ponderado global 10 sem: WAPE_i * real_i == ae_i, sum/sum = ponderado exacto
    tot = comp['real'].sum()
    wb = (comp['WAPE_base'] * comp['real']).sum() / tot
    wd = (comp['WAPE_damp'] * comp['real']).sum() / tot
    bb = (comp['BIAS_base'] * comp['real']).sum() / tot
    bd = (comp['BIAS_damp'] * comp['real']).sum() / tot
    n_mejora = int((comp['dWAPE'] < -0.01).sum())
    n_empeora = int((comp['dWAPE'] > 0.01).sum())

    print("\n--- RESUMEN ---")
    print(f"WAPE REG-1 ponderado: {wb:.2f}% -> {wd:.2f}%  ({wd - wb:+.2f}pp)")
    print(f"BIAS REG-1 ponderado: {bb:+.2f}% -> {bd:+.2f}%  ({bd - bb:+.2f}pp)")
    print(f"Consistencia: {n_mejora}/10 sem mejora, {n_empeora}/10 empeora, {10 - n_mejora - n_empeora}/10 neutro")
    print(f"SKUs REG-1 que eligieron damped (avg/sem): {comp['n_damped'].mean():.0f} de {comp['n_reg1'].mean():.0f}")

    comp.to_parquet(RESULTS / "exp_damped_reg1.parquet", index=False)
    print("\n-> resultados/exp_damped_reg1.parquet")


if __name__ == "__main__":
    main()
