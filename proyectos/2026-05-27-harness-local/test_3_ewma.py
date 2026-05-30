"""
Test 3: Reemplazar SMA short por EWMA con alpha alto para reducir el lag
temporal del motor en cambios de nivel (caso Stella).

EWMA(alpha=0.4):
  mu[t] = alpha * y[t] + (1-alpha) * mu[t-1]
  pesos: y[t]=0.40, y[t-1]=0.24, y[t-2]=0.144, y[t-3]=0.086, ... (suma=1)
  Responde 2-3 sem más rápido que SMA(4) ante shifts.

Implementación: modifica _calc_base_demand temporalmente para evaluar.
Compara baseline vs EWMA alpha=[0.30, 0.40, 0.50].
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
import HM_SI_local as mod
from HM_SI_local import run, DEFAULT_CONFIG, load_cache, _avg_std, _safe_float

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]

# Backup original
_orig_calc_base_demand = mod._calc_base_demand


def _ewma(vals, alpha):
    """EWMA simple."""
    if not vals:
        return 0.0, 0.0
    mu = float(vals[0])
    sq = mu * mu
    for v in vals[1:]:
        v = _safe_float(v, 0.0)
        mu = alpha * v + (1 - alpha) * mu
        sq = alpha * v * v + (1 - alpha) * sq
    var = max(sq - mu * mu, 0.0)
    return mu, var ** 0.5


def make_calc_base_demand_ewma(ewma_alpha):
    """Versión modificada de _calc_base_demand que usa EWMA en short."""
    def _calc(base_vals, raw_vals,
              short_weeks, long_weeks,
              ratio_up, ratio_hold, ratio_collapse,
              down_w_short, down_w_long):
        n = len(base_vals or [])
        if n <= 0:
            return 0.0, 0.0, 'no_history', False
        mu_all, sigma_all = _avg_std(base_vals)
        if n < long_weeks:
            return mu_all, sigma_all, 'avg_base_%sw' % n, False

        # EWMA sobre ventana short (en lugar de SMA)
        short_vals = base_vals[-short_weeks:]
        long_vals = base_vals[-long_weeks:]
        ewma_short, sigma_ewma = _ewma(short_vals, ewma_alpha)
        sma_long, sigma_long = _avg_std(long_vals)

        # Reemplazo: usar ewma_short como sma_short
        sma_short = ewma_short
        sigma_short = sigma_ewma

        if sma_long > 0.0:
            ratio = sma_short / sma_long
        else:
            ratio = 9.99 if sma_short > 0.0 else 1.0

        raw_n = len(raw_vals or [])
        if raw_n >= long_weeks:
            raw_ewma, _ = _ewma(raw_vals[-short_weeks:], ewma_alpha)
            raw_long_avg, _ = _avg_std(raw_vals[-long_weeks:])
            if raw_long_avg > 0.0:
                raw_ratio = raw_ewma / raw_long_avg
            else:
                raw_ratio = 9.99 if raw_ewma > 0.0 else 1.0
        else:
            raw_ratio = ratio

        if ratio >= ratio_up:
            return sma_short, sigma_short, 'ewma%s_base_up_r=%s' % (short_weeks, round(ratio, 3)), False
        if ratio >= ratio_hold:
            return sma_long, sigma_long, 'sma%s_base_hold_r=%s' % (long_weeks, round(ratio, 3)), False
        if raw_ratio < ratio_collapse:
            return sma_short, sigma_short, 'ewma%s_base_collapse_rawr=%s' % (short_weeks, round(raw_ratio, 3)), True

        mu_blend = (down_w_short * sma_short) + (down_w_long * sma_long)
        sigma_blend = (down_w_short * sigma_short) + (down_w_long * sigma_long)
        return mu_blend, sigma_blend, 'blend_ewma_down_r=%s' % round(ratio, 3), False
    return _calc


def detect_quiebres(pos, target_weeks):
    hist_from = target_weeks[0] - timedelta(weeks=8)
    hist = pos[(pos['week_start'] >= hist_from) & (pos['week_start'] < target_weeks[0])]
    avg = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg.columns = ['team_id', 'product_id', 'avg_8w']
    quiebres = set()
    for wk in target_weeks:
        pos_w = pos[pos['week_start'] == wk][['team_id', 'product_id', 'qty_sold']]
        merged = avg.merge(pos_w, on=['team_id', 'product_id'], how='left').fillna({'qty_sold': 0.0})
        proxy = merged[(merged['avg_8w'] >= 5.0) & (merged['qty_sold'] < 0.2 * merged['avg_8w'])]
        for _, r in proxy.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))
    return quiebres


def run_backtest(label, alpha, pos, quiebres):
    print(f"\n[{label}]")
    if alpha is not None:
        mod._calc_base_demand = make_calc_base_demand_ewma(alpha)
    else:
        mod._calc_base_demand = _orig_calc_base_demand

    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  cutoff {cutoff}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        m = fc[['team_id', 'product_id', 'categ_id', 'mu_week',
                 'abcxyz_eff', 'regimen_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        ).fillna({'mu_week': 0.0, 'qty_sold': 0.0})
        m['target_week'] = target
        m['is_quiebre'] = m.apply(
            lambda r: (int(r['team_id']), int(r['product_id']), target) in quiebres
                       if pd.notna(r['team_id']) and pd.notna(r['product_id'])
                       else False,
            axis=1,
        )
        parts.append(m)

    # Restaurar original
    mod._calc_base_demand = _orig_calc_base_demand
    return pd.concat(parts, ignore_index=True)


def metrics(df, value='mu_week'):
    r = df['qty_sold'].sum()
    f = df[value].sum()
    ae = (df[value] - df['qty_sold']).abs().sum()
    err = (df['qty_sold'] - df[value]).sum()
    return r, f, ae, ae/r*100 if r > 0 else 0, err/r*100 if r > 0 else 0


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_kw = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']
    excl_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(excl_kw), case=False, na=False
    )]['categ_id_id'].tolist())

    print("Detectando quiebres (proxy estricto)...")
    quiebres = detect_quiebres(pos, TARGET_WEEKS)
    print(f"  {len(quiebres):,}")

    # Corridas: baseline + 3 EWMA alphas
    configs = [
        ('baseline_v3.46', None),
        ('ewma_alpha_030', 0.30),
        ('ewma_alpha_040', 0.40),
        ('ewma_alpha_050', 0.50),
    ]
    results = {}
    for label, alpha in configs:
        df = run_backtest(label, alpha, pos, quiebres)
        results[label] = df

    print("\n" + "=" * 110)
    print("COMPARATIVA - sin cigarros/snack + sin quiebres (proxy estricto)")
    print("=" * 110)
    print(f"{'config':25s} | {'WAPE':>6s} {'BIAS':>+7s} | {'WAPE_cerveza':>13s} {'BIAS_cerveza':>13s} | {'WAPE_9407':>10s} {'BIAS_9407':>10s}")
    print("-" * 110)

    cerv_ids = set(cats[cats['complete_name'].str.contains('Cervezas', case=False, na=False)]['categ_id_id'].tolist())

    rows_summary = []
    for label in results:
        df = results[label]
        df_clean = df[~df['categ_id'].isin(excl_ids) & ~df['is_quiebre']]
        _, _, _, w, b = metrics(df_clean)
        df_cerv = df_clean[df_clean['categ_id'].isin(cerv_ids)]
        _, _, _, wc, bc = metrics(df_cerv)
        df_9407 = df_clean[df_clean['product_id'] == 11797]
        _, _, _, w94, b94 = metrics(df_9407)
        print(f"{label:25s} | {w:>5.2f} {b:>+7.2f} | {wc:>13.2f} {bc:>+12.2f} | {w94:>10.2f} {b94:>+9.2f}")
        rows_summary.append({
            'config': label,
            'WAPE_total': round(w, 2), 'BIAS_total': round(b, 2),
            'WAPE_cervezas': round(wc, 2), 'BIAS_cervezas': round(bc, 2),
            'WAPE_9407': round(w94, 2), 'BIAS_9407': round(b94, 2),
        })

    # Detalle 9407 por semana
    print("\n" + "=" * 110)
    print("Stella SKU 9407 - mu_week por semana (todos teams agregados)")
    print("=" * 110)
    print(f"{'semana':12s} |", end='')
    for label in results:
        print(f" {label:>17s}", end='')
    print(f" {'real':>8s}")
    for wk in TARGET_WEEKS:
        print(f"{str(wk):12s} |", end='')
        for label, df in results.items():
            df_wk = df[(df['product_id'] == 11797) & (df['target_week'] == wk)]
            fc = df_wk['mu_week'].sum()
            print(f" {fc:>17.0f}", end='')
        real = results['baseline_v3.46']
        real_wk = real[(real['product_id'] == 11797) & (real['target_week'] == wk)]['qty_sold'].sum()
        print(f" {real_wk:>8.0f}")

    pd.DataFrame(rows_summary).to_parquet(RESULTS / "test_3_ewma_summary.parquet", index=False)
    print(f"\n -> test_3_ewma_summary.parquet")


if __name__ == "__main__":
    main()
