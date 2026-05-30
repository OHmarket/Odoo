"""Comparativa final: baseline_v3_46 vs tuned (Fase 1-4 ganadores)
sobre W04, W11, W18 con detalle por regimen.
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

TARGET_WEEKS = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

TUNED_OVERRIDE = {
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
        print(f"  {label}: cutoff {cutoff}")
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


def metrics(df, value='mu_week', real='qty_sold'):
    r = df[real].sum()
    f = df[value].sum()
    ae = (df[value] - df[real]).abs().sum()
    err = (df[real] - df[value]).sum()
    return {
        'real': r, 'fcst': f, 'ae': ae,
        'WAPE': round(ae/r*100 if r > 0 else 0, 2),
        'BIAS': round(err/r*100 if r > 0 else 0, 2),
    }


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})[['team_id', 'product_id', 'week_start', 'avail']]

    print("BASELINE v3.46...")
    df_b = eval_full({}, pos, dn, "baseline")
    print("\nTUNED (Fase 1-4)...")
    df_t = eval_full(TUNED_OVERRIDE, pos, dn, "tuned")

    # Filtros: con/sin censura
    df_b['regimen_eff'] = df_b['regimen_eff'].fillna('NO_FC')
    df_t['regimen_eff'] = df_t['regimen_eff'].fillna('NO_FC')
    bc = df_b[~df_b['is_censored']]
    tc = df_t[~df_t['is_censored']]

    print("\n" + "=" * 110)
    print("TOTALES (sin censura)")
    print("=" * 110)
    mb = metrics(bc)
    mt = metrics(tc)
    print(f"  baseline v3.46:  real={mb['real']:>9,.0f}  fcst={mb['fcst']:>9,.0f}  WAPE={mb['WAPE']:>5.2f}%  BIAS={mb['BIAS']:>+5.2f}%")
    print(f"  tuned 4 fases:   real={mt['real']:>9,.0f}  fcst={mt['fcst']:>9,.0f}  WAPE={mt['WAPE']:>5.2f}%  BIAS={mt['BIAS']:>+5.2f}%")
    print(f"  Δ WAPE: {mt['WAPE']-mb['WAPE']:+.2f}pp")
    print(f"  Δ BIAS: {mt['BIAS']-mb['BIAS']:+.2f}pp")

    print("\n" + "=" * 110)
    print("POR REGIMEN (sin censura)")
    print("=" * 110)
    rows = []
    for reg in sorted(set(bc['regimen_eff'].unique()) | set(tc['regimen_eff'].unique())):
        bs = bc[bc['regimen_eff'] == reg]
        ts = tc[tc['regimen_eff'] == reg]
        mb_r = metrics(bs)
        mt_r = metrics(ts)
        rows.append({
            'regimen': reg, 'n': len(bs),
            'real': round(mb_r['real']),
            'WAPE_v346': mb_r['WAPE'],
            'WAPE_tuned': mt_r['WAPE'],
            'd_WAPE': round(mt_r['WAPE'] - mb_r['WAPE'], 2),
            'BIAS_v346': mb_r['BIAS'],
            'BIAS_tuned': mt_r['BIAS'],
            'd_BIAS': round(mt_r['BIAS'] - mb_r['BIAS'], 2),
            'fcst_v346': round(mb_r['fcst']),
            'fcst_tuned': round(mt_r['fcst']),
            'contrib_ae_v346': round(mb_r['ae']),
            'contrib_ae_tuned': round(mt_r['ae']),
        })
    df_reg = pd.DataFrame(rows).sort_values('contrib_ae_v346', ascending=False)
    print(df_reg.to_string(index=False))

    print("\n" + "=" * 110)
    print("POR SEMANA")
    print("=" * 110)
    for wk in TARGET_WEEKS:
        b = bc[bc['target_week'] == wk]
        t = tc[tc['target_week'] == wk]
        mb_w = metrics(b)
        mt_w = metrics(t)
        print(f"  {wk}:  baseline WAPE={mb_w['WAPE']:>5.2f}%  BIAS={mb_w['BIAS']:>+5.2f}%  ||  tuned WAPE={mt_w['WAPE']:>5.2f}%  BIAS={mt_w['BIAS']:>+5.2f}%  ||  Δ {mt_w['WAPE']-mb_w['WAPE']:+5.2f}pp")

    out = RESULTS / "compare_final.parquet"
    df_reg.to_parquet(out, index=False)
    print(f"\n -> {out}")


if __name__ == "__main__":
    main()
