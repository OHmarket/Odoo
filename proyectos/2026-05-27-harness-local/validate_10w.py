"""Validación tuning sobre 10 semanas (no solo las 3 usadas en tuning).
Mide overfitting de la config ganadora Test 1.
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

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

TUNED = {
    "SERVICE_BASE_SHORT_WEEKS": 4,
    "SERVICE_BASE_LONG_WEEKS": 16,
    "SERVICE_RATIO_COLLAPSE": 0.40,
    "SERVICE_RATIO_HOLD": 0.90,
    "SERVICE_DOWN_W_SHORT": 0.5,
    "HEUR_BIAS": 0.80,
    "CROSTON_ALPHA": 0.25,
    "SBA_ALPHA": 0.20,
    "SI_CEIL": 3.0,
    "SI_SKU_ADJ_ALPHA_HIGH": 0.20,
    "SI_MIN_YEARS_FOR_SKU": 2,
    "FAIR_SHARE_TRIED_PENALTY": 0.05,
}


def eval_full(override, pos, dn, label):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(override)
    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  {label}: {cutoff}")
        fc = run(cutoff_date=cutoff, config=cfg, cache_dir=CACHE)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        m = fc[['team_id', 'product_id', 'mu_week', 'regimen_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        )
        m['target_week'] = target
        m['qty_sold'] = m['qty_sold'].fillna(0.0)
        m['mu_week'] = m['mu_week'].fillna(0.0)
        dn_wk = dn[dn['week_start'] == target][['team_id', 'product_id', 'avail']]
        m = m.merge(dn_wk, on=['team_id', 'product_id'], how='left')
        m['is_censored'] = m['avail'].notna() & (m['avail'] < 1.0)
        parts.append(m)
    return pd.concat(parts, ignore_index=True)


def metrics(df):
    r = df['qty_sold'].sum()
    f = df['mu_week'].sum()
    ae = (df['mu_week'] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df['mu_week']).sum()
    return r, f, ae, (ae/r*100 if r > 0 else 0), (err/r*100 if r > 0 else 0)


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})[['team_id', 'product_id', 'week_start', 'avail']]

    print("BASELINE v3.46 (10 sem)...")
    df_b = eval_full({}, pos, dn, "baseline")
    print("\nTUNED test 1 (10 sem)...")
    df_t = eval_full(TUNED, pos, dn, "tuned")

    df_b['regimen_eff'] = df_b['regimen_eff'].fillna('NO_FC')
    df_t['regimen_eff'] = df_t['regimen_eff'].fillna('NO_FC')
    bc = df_b[~df_b['is_censored']]
    tc = df_t[~df_t['is_censored']]

    # Totales
    rb, fb, aeb, wb, biasb = metrics(bc)
    rt, ft, aet, wt, biast = metrics(tc)
    print("\n" + "=" * 100)
    print("TOTALES 10 sem (sin censura)")
    print("=" * 100)
    print(f"  baseline:  real={rb:>9,.0f}  fcst={fb:>9,.0f}  WAPE={wb:>5.2f}%  BIAS={biasb:>+5.2f}%")
    print(f"  tuned:     real={rt:>9,.0f}  fcst={ft:>9,.0f}  WAPE={wt:>5.2f}%  BIAS={biast:>+5.2f}%")
    print(f"  Δ WAPE: {wt-wb:+.2f}pp     Δ BIAS: {biast-biasb:+.2f}pp")

    # Comparar 3-sem (tuning) vs 7-sem (out-of-sample)
    tuning_w = {date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)}
    bc_in = bc[bc['target_week'].isin(tuning_w)]
    tc_in = tc[tc['target_week'].isin(tuning_w)]
    bc_out = bc[~bc['target_week'].isin(tuning_w)]
    tc_out = tc[~tc['target_week'].isin(tuning_w)]

    print("\n" + "=" * 100)
    print("3 sem tuning (in-sample) vs 7 sem out-of-sample")
    print("=" * 100)
    _, _, _, wb_in, biasb_in = metrics(bc_in)
    _, _, _, wt_in, biast_in = metrics(tc_in)
    _, _, _, wb_out, biasb_out = metrics(bc_out)
    _, _, _, wt_out, biast_out = metrics(tc_out)
    print(f"  IN-sample (3 sem):   baseline WAPE={wb_in:.2f}  tuned WAPE={wt_in:.2f}  Δ={wt_in-wb_in:+.2f}pp")
    print(f"  OUT-of-sample (7 sem): baseline WAPE={wb_out:.2f}  tuned WAPE={wt_out:.2f}  Δ={wt_out-wb_out:+.2f}pp")

    # Por semana
    print("\n" + "=" * 100)
    print("POR SEMANA")
    print("=" * 100)
    print(f"  {'semana':12s} | {'WAPE_base':>10s} {'WAPE_tuned':>11s} {'Δ':>7s} | {'BIAS_base':>10s} {'BIAS_tuned':>11s} | in/out")
    print(f"  {'-'*12} | {'-'*10} {'-'*11} {'-'*7} | {'-'*10} {'-'*11} | -----")
    for wk in TARGET_WEEKS:
        bs = bc[bc['target_week'] == wk]
        ts = tc[tc['target_week'] == wk]
        _, _, _, wb_w, biasb_w = metrics(bs)
        _, _, _, wt_w, biast_w = metrics(ts)
        marker = 'IN ' if wk in tuning_w else 'OUT'
        print(f"  {str(wk):12s} | {wb_w:>9.2f}% {wt_w:>10.2f}% {wt_w-wb_w:>+6.2f} | {biasb_w:>+9.2f}% {biast_w:>+10.2f}% | {marker}")

    out = RESULTS / "validate_10w.parquet"
    pd.concat([df_b.assign(config='baseline'), df_t.assign(config='tuned')]).to_parquet(out, index=False)
    print(f"\n -> {out}")


if __name__ == "__main__":
    main()
