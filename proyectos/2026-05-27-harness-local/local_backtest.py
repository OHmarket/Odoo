"""
Backtest local multi-config: corre el mirror N veces con distintas configs
para 1+ cutoffs, mide WAPE/BIAS contra real_qty del cache.

Permite iterar tuning rapido sin tocar el server.

Uso:
    python local_backtest.py
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


def load_real_qty(pos, target_week):
    """Real qty observado en target_week."""
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    return pos[pos['week_start'] == target_week][['team_id', 'product_id', 'qty_sold']].rename(
        columns={'qty_sold': 'real_qty'}
    )


def metrics(label, fc_df, real_df):
    """Calcula WAPE, BIAS, fcst_total, real_total."""
    merged = fc_df[['team_id', 'product_id', 'mu_week']].merge(
        real_df, on=['team_id', 'product_id'], how='outer'
    ).fillna(0.0)

    total_real = merged['real_qty'].sum()
    total_fcst = merged['mu_week'].sum()
    ae = (merged['mu_week'] - merged['real_qty']).abs().sum()
    err = (merged['real_qty'] - merged['mu_week']).sum()

    wape = (ae / total_real * 100) if total_real > 0 else 0.0
    bias = (err / total_real * 100) if total_real > 0 else 0.0

    return {
        'config': label,
        'n_skus': len(merged),
        'real': round(total_real, 0),
        'fcst': round(total_fcst, 0),
        'WAPE': round(wape, 1),
        'BIAS': round(bias, 1),
    }


def main():
    print("="*80)
    print("Local backtest multi-config")
    print("="*80)

    # Cargar POS para extraer real
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    # Cutoffs: las 3 ultimas semanas cerradas (W18, W19, W20 = backtest oficial)
    cutoffs = [
        (date(2026, 5, 3),  date(2026, 5, 4)),   # cutoff = sabado, target = lunes siguiente
        (date(2026, 5, 10), date(2026, 5, 11)),
        (date(2026, 5, 17), date(2026, 5, 18)),
    ]

    # Configs a comparar
    configs = [
        # Baseline v3.46
        ("baseline_v3_46", {}),
        # Variantes
        ("sma_4_short",     {"SERVICE_BASE_SHORT_WEEKS": 4}),
        ("sma_8_short",     {"SERVICE_BASE_SHORT_WEEKS": 8}),
        ("trend_off",       {"APPLY_TREND_CORRECTION": False}),
        ("trend_symm_115",  {"TREND_CLAMP_HIGH": 1.15}),  # asimetrico OFF: deja amplificar
    ]

    rows = []
    for cutoff, target in cutoffs:
        print(f"\n--- Cutoff={cutoff} target={target} ---")
        real_df = load_real_qty(pos, target)
        if real_df.empty:
            print(f"  Sin real_qty para {target}, skip")
            continue

        for label, overrides in configs:
            print(f"  Config: {label}")
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(overrides)

            fc_df = run(cutoff_date=cutoff, config=cfg, cache_dir=CACHE)
            m = metrics(label, fc_df, real_df)
            m['target_week'] = target
            print(f"    {m}")
            rows.append(m)

    df = pd.DataFrame(rows)
    print("\n" + "="*80)
    print("RESUMEN")
    print("="*80)

    # Pivot por config
    print("\nWAPE por config (por semana):")
    pv = df.pivot_table(index='config', columns='target_week', values='WAPE', aggfunc='mean')
    print(pv.to_string())

    print("\nBIAS por config (por semana):")
    pv = df.pivot_table(index='config', columns='target_week', values='BIAS', aggfunc='mean')
    print(pv.to_string())

    print("\nfcst_total por config (por semana):")
    pv = df.pivot_table(index='config', columns='target_week', values='fcst', aggfunc='mean')
    print(pv.to_string())

    out = RESULTS / "local_backtest.parquet"
    df.to_parquet(out, index=False)
    print(f"\n  -> {out.name}")


if __name__ == "__main__":
    main()
