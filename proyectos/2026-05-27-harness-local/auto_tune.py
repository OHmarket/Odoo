"""
Auto-tuning del motor HM-SI por fases. Random search sobre hyperparams,
constraint: REG-1 WAPE no degrada >0.5pp.

Cada fase ataca un regimen (o grupo). Resultados se guardan a parquet.

Uso:
    python auto_tune.py --phase 0    # sanity check
    python auto_tune.py --phase 1    # REG-2 + REG-4
    python auto_tune.py --phase 2    # REG-7
    python auto_tune.py --phase 3    # REG-8
    python auto_tune.py --phase 4    # REG-5
"""
from __future__ import annotations
import argparse
import itertools
import random
import sys
import time
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

# Semanas de evaluación: las 3 del backtest oficial (W04, W11, W18)
# Reducido de 10 a 3 sem por rendimiento. WAPE/BIAS sigue siendo significativo
# (32-39K real por semana) y coincide con la métrica oficial de Odoo.
TARGET_WEEKS = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

# Constraint
REG1_DEGRADE_MAX_PP = 0.5

# Baseline acumulado: overrides aprobados de fases anteriores. Aplica sobre
# DEFAULT_CONFIG en TODAS las evaluaciones (incluido baseline reference).
BASELINE_OVERRIDE = {
    # Fase 1 (REG-2 + REG-4) - config #8 ganador 2026-05-28
    "SERVICE_BASE_SHORT_WEEKS": 4,
    "SERVICE_BASE_LONG_WEEKS": 16,
    "SERVICE_RATIO_COLLAPSE": 0.30,
    "SERVICE_RATIO_HOLD": 0.90,
    "SERVICE_DOWN_W_SHORT": 0.5,
    # Fase 2 (REG-7 Croston/SBA) - config #17 ganador 2026-05-28
    "HEUR_BIAS": 0.80,
    "CROSTON_ALPHA": 0.25,
    "SBA_ALPHA": 0.20,
    # Fase 3 (REG-8 SI seasonal) - config #3 ganador 2026-05-28
    "SI_CEIL": 3.0,
    "SI_SKU_ADJ_ALPHA_HIGH": 0.20,
    "SI_MIN_YEARS_FOR_SKU": 2,
}

# Search spaces por fase
PHASES = {
    0: {
        "name": "sanity_baseline",
        "regimens_focus": [],
        "space": {},  # vacío = solo baseline
        "n_samples": 1,
    },
    1: {
        "name": "reg2_reg4_sma_blend",
        "regimens_focus": ["REG-2", "REG-4"],
        "space": {
            "SERVICE_BASE_SHORT_WEEKS": [4, 5, 6, 7, 8],
            "SERVICE_BASE_LONG_WEEKS": [12, 14, 16, 18, 20],
            "SERVICE_RATIO_COLLAPSE": [0.20, 0.25, 0.30, 0.35, 0.40],
            "SERVICE_RATIO_HOLD": [0.80, 0.85, 0.90, 0.95],
            "SERVICE_DOWN_W_SHORT": [0.50, 0.60, 0.70, 0.80],
        },
        "n_samples": 25,
    },
    2: {
        "name": "reg7_croston_sba",
        "regimens_focus": ["REG-7"],
        "space": {
            "HEUR_BIAS": [0.80, 0.85, 0.90, 0.95, 1.00],
            "CROSTON_ALPHA": [0.05, 0.10, 0.15, 0.20, 0.25],
            "SBA_ALPHA": [0.10, 0.15, 0.20, 0.25, 0.30],
        },
        "n_samples": 25,
    },
    3: {
        "name": "reg8_seasonal",
        "regimens_focus": ["REG-8"],
        "space": {
            "SI_CEIL": [3.0, 4.0, 5.0, 6.0],
            "SI_SKU_ADJ_ALPHA_HIGH": [0.20, 0.30, 0.40, 0.50],
            "SI_MIN_YEARS_FOR_SKU": [2, 3],
        },
        "n_samples": 20,
    },
    4: {
        "name": "reg5_lumpy",
        "regimens_focus": ["REG-5"],
        "space": {
            "FAIR_SHARE_TRIED_PENALTY": [0.05, 0.10, 0.15, 0.20, 0.30],
            "SERVICE_RATIO_COLLAPSE": [0.20, 0.25, 0.30, 0.35, 0.40],
        },
        "n_samples": 15,
    },
}


def sample_configs(space, n, seed=42):
    """Random sample n configs del espacio."""
    if not space:
        return [{}]
    keys = list(space.keys())
    rng = random.Random(seed)
    samples = set()
    out = []
    max_tries = n * 10
    tries = 0
    while len(out) < n and tries < max_tries:
        tries += 1
        cfg = tuple(rng.choice(space[k]) for k in keys)
        if cfg in samples:
            continue
        samples.add(cfg)
        out.append(dict(zip(keys, cfg)))
    return out


def eval_config(config_override, pos, dn, target_weeks):
    """Corre N semanas con config_override sobre baseline acumulado, devuelve metrics.

    cfg = DEFAULT_CONFIG + BASELINE_OVERRIDE (fases previas) + config_override (esta fase)
    """
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(BASELINE_OVERRIDE)
    cfg.update(config_override)

    parts = []
    for target in target_weeks:
        cutoff = target - timedelta(days=1)
        fc = run(cutoff_date=cutoff, config=cfg, cache_dir=CACHE)

        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        merged = fc[['team_id', 'product_id', 'mu_week', 'regimen_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        )
        merged['target_week'] = target
        merged['qty_sold'] = merged['qty_sold'].fillna(0.0)
        merged['mu_week'] = merged['mu_week'].fillna(0.0)
        # Censura
        dn_wk = dn[dn['week_start'] == target][['team_id', 'product_id', 'avail']]
        merged = merged.merge(dn_wk, on=['team_id', 'product_id'], how='left')
        merged['is_censored'] = merged['avail'].notna() & (merged['avail'] < 1.0)
        parts.append(merged)

    df = pd.concat(parts, ignore_index=True)
    df['regimen_eff'] = df['regimen_eff'].fillna('NO_FC')
    clean = df[~df['is_censored']]

    # Total
    real_t = clean['qty_sold'].sum()
    fcst_t = clean['mu_week'].sum()
    ae_t = (clean['mu_week'] - clean['qty_sold']).abs().sum()
    err_t = (clean['qty_sold'] - clean['mu_week']).sum()
    wape_t = ae_t / real_t * 100 if real_t > 0 else 0.0
    bias_t = err_t / real_t * 100 if real_t > 0 else 0.0

    # Por regimen
    by_reg = {}
    for reg, sub in clean.groupby('regimen_eff'):
        r = sub['qty_sold'].sum()
        a = (sub['mu_week'] - sub['qty_sold']).abs().sum()
        b = (sub['qty_sold'] - sub['mu_week']).sum()
        by_reg[reg] = {
            'WAPE': a / r * 100 if r > 0 else 0.0,
            'BIAS': b / r * 100 if r > 0 else 0.0,
        }

    return {
        'WAPE_total': round(wape_t, 2),
        'BIAS_total': round(bias_t, 2),
        'WAPE_REG-1': round(by_reg.get('REG-1', {}).get('WAPE', 0), 2),
        'WAPE_REG-2': round(by_reg.get('REG-2', {}).get('WAPE', 0), 2),
        'WAPE_REG-4': round(by_reg.get('REG-4', {}).get('WAPE', 0), 2),
        'WAPE_REG-5': round(by_reg.get('REG-5', {}).get('WAPE', 0), 2),
        'WAPE_REG-7': round(by_reg.get('REG-7', {}).get('WAPE', 0), 2),
        'WAPE_REG-8': round(by_reg.get('REG-8', {}).get('WAPE', 0), 2),
        'BIAS_REG-1': round(by_reg.get('REG-1', {}).get('BIAS', 0), 2),
        'BIAS_REG-2': round(by_reg.get('REG-2', {}).get('BIAS', 0), 2),
        'BIAS_REG-4': round(by_reg.get('REG-4', {}).get('BIAS', 0), 2),
        'BIAS_REG-7': round(by_reg.get('REG-7', {}).get('BIAS', 0), 2),
        'BIAS_REG-8': round(by_reg.get('REG-8', {}).get('BIAS', 0), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', type=int, required=True)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    phase = PHASES[args.phase]
    print(f"=" * 100)
    print(f"AUTO-TUNE FASE {args.phase}: {phase['name']}")
    print(f"  Focus regimens: {phase['regimens_focus']}")
    print(f"  Search space keys: {list(phase['space'].keys())}")
    print(f"  N samples: {phase['n_samples']}")
    print(f"=" * 100)

    # Cargar data una vez
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})
    dn = dn[['team_id', 'product_id', 'week_start', 'avail']]

    # Baseline
    print("\nBaseline (config default)...")
    t0 = time.time()
    baseline = eval_config({}, pos, dn, TARGET_WEEKS)
    t_one = time.time() - t0
    print(f"  WAPE_total={baseline['WAPE_total']}  BIAS_total={baseline['BIAS_total']}  WAPE_REG-1={baseline['WAPE_REG-1']}  [{t_one:.0f}s]")

    if args.phase == 0:
        print("\nSanity check: phase 0 solo evalua baseline. Done.")
        return

    # Sample
    configs = sample_configs(phase['space'], phase['n_samples'], seed=args.seed)
    eta_total = t_one * len(configs)
    print(f"\nSampleados {len(configs)} configs. ETA total: ~{eta_total/60:.1f} min")

    rows = []
    for i, cfg in enumerate(configs, 1):
        t0 = time.time()
        m = eval_config(cfg, pos, dn, TARGET_WEEKS)
        elapsed = time.time() - t0
        violates = m['WAPE_REG-1'] > baseline['WAPE_REG-1'] + REG1_DEGRADE_MAX_PP
        check = 'X' if violates else 'OK'
        row = {'config_idx': i, **cfg, **m, 'reg1_constraint': check}
        rows.append(row)
        cfg_str = ', '.join(f"{k}={v}" for k, v in cfg.items())
        print(f"  [{i:>3}/{len(configs)}]  WAPE={m['WAPE_total']:>5.2f}  REG-1={m['WAPE_REG-1']:>5.2f} {check}  "
              f"REG-2={m['WAPE_REG-2']:>5.2f}  REG-4={m['WAPE_REG-4']:>5.2f}  "
              f"REG-7={m['WAPE_REG-7']:>5.2f}  REG-8={m['WAPE_REG-8']:>5.2f}  "
              f"BIAS={m['BIAS_total']:>+5.2f}  [{elapsed:.0f}s]  | {cfg_str}")

    df = pd.DataFrame(rows)
    out = RESULTS / f"tune_phase_{args.phase}_{phase['name']}.parquet"
    df.to_parquet(out, index=False)

    print(f"\n{'=' * 100}")
    print(f"TOP 10 (filtrados por constraint REG-1)")
    print(f"{'=' * 100}")
    valid = df[df['reg1_constraint'] == 'OK'].sort_values('WAPE_total')
    cols_show = ['config_idx', 'WAPE_total', 'WAPE_REG-1', 'WAPE_REG-2', 'WAPE_REG-4',
                  'WAPE_REG-7', 'WAPE_REG-8', 'BIAS_total'] + list(phase['space'].keys())
    cols_show = [c for c in cols_show if c in valid.columns]
    print(valid[cols_show].head(10).to_string(index=False))
    print(f"\nBaseline:  WAPE={baseline['WAPE_total']}  REG-1={baseline['WAPE_REG-1']}  BIAS={baseline['BIAS_total']}")

    if not valid.empty:
        best = valid.iloc[0]
        delta = baseline['WAPE_total'] - best['WAPE_total']
        print(f"\nMejor: WAPE {best['WAPE_total']:.2f} (Δ {delta:+.2f}pp vs baseline)")
        print(f"Config ganadora: {dict((k, best[k]) for k in phase['space'].keys() if k in best)}")
    else:
        print("\nNINGUNA config respeta el constraint REG-1.")
    print(f"\n -> {out}")


if __name__ == "__main__":
    main()
