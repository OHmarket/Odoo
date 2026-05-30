"""
Test 3: Tracking Signal canon SAP IBP

Algoritmo (canon):
  TS = sum(error) / MAD
  Si |TS| > 3.75 -> sesgo persistente. Aplicar factor = sum(real)/sum(fcst).

Por (team, sku) con ventana rolling 6 sem.
Excluye quiebres (proxy estricto + demanda_norm).
Aplicación post-trend, pre-redondeo.

Compara baseline vs Test 2 (categ calib) vs Test 3 (TS).
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

# Necesitamos historia más larga: 10 sem target + 6 sem historia para TS
HISTORY_WEEKS = 6
TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]
# Cutoffs adicionales para alimentar la historia de los primeros target_weeks
EXTRA_WEEKS = [TARGET_WEEKS[0] - timedelta(weeks=i) for i in range(HISTORY_WEEKS, 0, -1)]
ALL_WEEKS = EXTRA_WEEKS + TARGET_WEEKS  # 16 cutoffs total

# Parámetros canon SAP IBP
TS_THRESHOLD = 3.75
MIN_OBS_VALID = 4  # mínimo no-quiebre de los 6
MAD_MIN = 0.5
CLAMP_LOW = 0.70
CLAMP_HIGH = 1.30

# Filtro categorías
EXCLUDE_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']

# Test 2 factors (para comparativa)
TEST2_FACTORS_FILE = RESULTS / "test_2_categ_factors.json"


def tracking_signal_correction(history_pairs):
    """history_pairs: lista de (fcst, real) sin quiebres, ordenada desc por fecha.
    Devuelve (factor, ts, n_valid) o (1.0, None, n_valid).
    """
    if len(history_pairs) < MIN_OBS_VALID:
        return 1.0, None, len(history_pairs)

    errors = [r - f for f, r in history_pairs]
    mad = sum(abs(e) for e in errors) / len(errors)
    if mad < MAD_MIN:
        return 1.0, None, len(history_pairs)

    ts = sum(errors) / mad
    if abs(ts) <= TS_THRESHOLD:
        return 1.0, ts, len(history_pairs)

    sum_real = sum(r for _, r in history_pairs)
    sum_fcst = sum(f for f, _ in history_pairs)
    if sum_fcst <= 0:
        return 1.0, ts, len(history_pairs)

    raw_factor = sum_real / sum_fcst
    return max(CLAMP_LOW, min(CLAMP_HIGH, raw_factor)), ts, len(history_pairs)


def detect_quiebres(pos, target_weeks):
    """Set de (team, sku, week) marcados como quiebre."""
    hist_from = min(target_weeks) - timedelta(weeks=8)
    quiebres = set()

    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})

    for wk in target_weeks:
        prev_8w = pos[(pos['week_start'] >= wk - timedelta(weeks=8)) &
                       (pos['week_start'] < wk)]
        avg = prev_8w.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
        avg.columns = ['team_id', 'product_id', 'avg_8w']

        pos_w = pos[pos['week_start'] == wk][['team_id', 'product_id', 'qty_sold']]
        merged = avg.merge(pos_w, on=['team_id', 'product_id'], how='left').fillna({'qty_sold': 0.0})
        proxy = merged[(merged['avg_8w'] >= 5.0) & (merged['qty_sold'] < 0.2 * merged['avg_8w'])]
        for _, r in proxy.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))

        dn_w = dn[(dn['week_start'] == wk) & (dn['avail'] < 1.0)]
        for _, r in dn_w.iterrows():
            quiebres.add((int(r['team_id']), int(r['product_id']), wk))
    return quiebres


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCLUDE_KEYWORDS), case=False, na=False
    )]['categ_id_id'].tolist())

    print(f"Detectando quiebres sobre {len(ALL_WEEKS)} sem...")
    quiebres = detect_quiebres(pos, ALL_WEEKS)
    print(f"  {len(quiebres):,} (team, sku, sem)")

    # 1. Correr baseline para TODOS los cutoffs (16 sem). Cachear a parquet
    # para no re-correr si solo iteramos sobre la lógica de TS.
    cache_baseline = RESULTS / "test_3_baseline_16w.parquet"
    if cache_baseline.exists():
        print(f"\nReutilizando baseline cacheado: {cache_baseline.name}")
        df = pd.read_parquet(cache_baseline)
        df['target_week'] = pd.to_datetime(df['target_week']).dt.date
    else:
        print(f"\nBacktest baseline sobre {len(ALL_WEEKS)} sem (motor base, sin corrección)...")
        all_records = []
        for target in ALL_WEEKS:
            cutoff = target - timedelta(days=1)
            print(f"  cutoff {cutoff}")
            fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
            fc = fc[['team_id', 'product_id', 'categ_id', 'mu_week',
                      'abcxyz_eff', 'regimen_eff']].copy()
            real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
            m = fc.merge(real, on=['team_id', 'product_id'], how='outer').fillna(
                {'mu_week': 0.0, 'qty_sold': 0.0}
            )
            m['target_week'] = target
            m['is_quiebre'] = m.apply(
                lambda r: (int(r['team_id']), int(r['product_id']), target) in quiebres
                           if pd.notna(r['team_id']) and pd.notna(r['product_id'])
                           else False,
                axis=1,
            )
            all_records.append(m)
        df = pd.concat(all_records, ignore_index=True)
        df.to_parquet(cache_baseline, index=False)
        print(f"  -> baseline cacheado en {cache_baseline.name}")
    print(f"\nTotal filas: {len(df):,}")
    # Filtrar NaN team/product (evitan duplicados en set_index)
    df = df[df['team_id'].notna() & df['product_id'].notna()].copy()
    df['team_id'] = df['team_id'].astype(int)
    df['product_id'] = df['product_id'].astype(int)
    print(f"  sin NaN team/sku: {len(df):,}")

    # 2. Aplicar Tracking Signal por (team, sku, target_week)
    # Para cada target_week en TARGET_WEEKS (no en EXTRA_WEEKS):
    #   Para cada (team, sku):
    #     history = filas de los 6 cutoffs anteriores, sin quiebre
    #     factor = tracking_signal_correction(history)
    #     mu_week_ts = mu_week_base * factor
    print("\nAplicando Tracking Signal por (team, sku, target_week)...")
    df['mu_week_ts'] = df['mu_week'].copy()
    df['ts_factor'] = 1.0
    df['ts_value'] = pd.NA
    df['ts_applied'] = False

    # Build lookup dict {(team, sku, target_week): (mu_week, qty_sold, is_quiebre)}
    print("  construyendo lookup dict...")
    lookup = {
        (int(r.team_id), int(r.product_id), r.target_week): (float(r.mu_week), float(r.qty_sold), bool(r.is_quiebre))
        for r in df.itertuples()
    }
    print(f"  {len(lookup):,} entries")

    for target in TARGET_WEEKS:
        hist_weeks = [target - timedelta(weeks=i) for i in range(1, HISTORY_WEEKS + 1)]
        target_mask = df['target_week'] == target

        n_applied = 0
        # Iterar solo target_week
        target_rows = df[target_mask]
        for idx, row in target_rows.iterrows():
            team_id = int(row['team_id'])
            prod_id = int(row['product_id'])

            history_pairs = []
            for hw in hist_weeks:
                key = (team_id, prod_id, hw)
                if key in lookup:
                    mu_h, real_h, is_q = lookup[key]
                    if not is_q:
                        history_pairs.append((mu_h, real_h))

            factor, ts, n_valid = tracking_signal_correction(history_pairs)
            df.at[idx, 'ts_factor'] = factor
            df.at[idx, 'ts_value'] = ts if ts is not None else pd.NA
            df.at[idx, 'mu_week_ts'] = row['mu_week'] * factor
            if factor != 1.0:
                df.at[idx, 'ts_applied'] = True
                n_applied += 1

        print(f"  target {target}: TS aplicado en {n_applied:,} pares (de {target_mask.sum():,})")

    # 3. Aplicar Test 2 (calibración categ × abc_letter) para comparar
    print("\nAplicando Test 2 (factores categ×abc) para comparar...")
    with open(TEST2_FACTORS_FILE, 'r') as f:
        test2_data = json.load(f)
    t2_factors = {}
    for key, factor in test2_data['factors'].items():
        cid, letter = key.split('|')
        t2_factors[(int(cid), letter)] = factor

    def apply_t2(row):
        if pd.isna(row['categ_id']) or pd.isna(row['abcxyz_eff']):
            return row['mu_week']
        letter = row['abcxyz_eff'][:1] if row['abcxyz_eff'] else ''
        return row['mu_week'] * t2_factors.get((int(row['categ_id']), letter), 1.0)
    df['mu_week_t2'] = df.apply(apply_t2, axis=1)

    # 4. Métricas comparativas (solo TARGET_WEEKS, sin quiebres, sin excluidas)
    df_eval = df[df['target_week'].isin(TARGET_WEEKS) &
                  ~df['is_quiebre'] &
                  ~df['categ_id'].isin(excl_ids)].copy()
    print(f"\nFilas evaluación: {len(df_eval):,}")

    def calc(d, col):
        r = d['qty_sold'].sum()
        f = d[col].sum()
        ae = (d[col] - d['qty_sold']).abs().sum()
        err = (d['qty_sold'] - d[col]).sum()
        return r, f, ae, ae/r*100 if r > 0 else 0, err/r*100 if r > 0 else 0

    print("\n" + "=" * 110)
    print("COMPARATIVA TOTAL")
    print("=" * 110)
    for label, col in [('baseline v3.46', 'mu_week'), ('Test 2 (categ calib)', 'mu_week_t2'), ('Test 3 (TS SAP)', 'mu_week_ts')]:
        r, f, ae, w, b = calc(df_eval, col)
        print(f"  {label:25s}: real={r:>9,.0f}  fcst={f:>9,.0f}  WAPE={w:>5.2f}%  BIAS={b:>+5.2f}%")

    # Cobertura Test 3
    n_applied = df_eval['ts_applied'].sum()
    print(f"\n  Test 3 cobertura: {n_applied:,} de {len(df_eval):,} pares ({n_applied/len(df_eval)*100:.1f}%)")

    # Por categoria cervezas
    cerv_ids = set(cats[cats['complete_name'].str.contains('Cervezas', case=False, na=False)]['categ_id_id'].tolist())
    df_cerv = df_eval[df_eval['categ_id'].isin(cerv_ids)]
    print("\n" + "=" * 110)
    print("CERVEZAS")
    print("=" * 110)
    for label, col in [('baseline v3.46', 'mu_week'), ('Test 2', 'mu_week_t2'), ('Test 3', 'mu_week_ts')]:
        r, f, ae, w, b = calc(df_cerv, col)
        print(f"  {label:25s}: real={r:>7,.0f}  fcst={f:>7,.0f}  WAPE={w:>5.2f}%  BIAS={b:>+5.2f}%")

    # SKU 9407 Stella
    df_9407 = df_eval[df_eval['product_id'] == 11797]
    print("\n" + "=" * 110)
    print("SKU 9407 STELLA")
    print("=" * 110)
    print(f"  Filas evaluadas: {len(df_9407)}")
    for label, col in [('baseline', 'mu_week'), ('Test 2', 'mu_week_t2'), ('Test 3', 'mu_week_ts')]:
        r, f, ae, w, b = calc(df_9407, col)
        print(f"  {label:25s}: real={r:>5,.0f}  fcst={f:>5,.0f}  WAPE={w:>5.2f}%  BIAS={b:>+5.2f}%")

    # ¿En qué semanas TS disparó en Stella?
    df_9407_target = df_eval[df_eval['product_id'] == 11797]
    print("\n  Stella TS activo por (team, semana):")
    stella_ts = df_9407_target[df_9407_target['ts_applied']].sort_values(['target_week', 'team_id'])
    if not stella_ts.empty:
        for _, r in stella_ts.head(20).iterrows():
            print(f"    {r['target_week']}  team={int(r['team_id'])}  TS={r['ts_value']:+.2f}  factor={r['ts_factor']:.3f}")
    else:
        print("    (ninguno - TS no disparó en Stella)")

    # Por semana
    print("\n" + "=" * 110)
    print("POR SEMANA - BIAS")
    print("=" * 110)
    for wk in TARGET_WEEKS:
        d = df_eval[df_eval['target_week'] == wk]
        _, _, _, w0, b0 = calc(d, 'mu_week')
        _, _, _, w2, b2 = calc(d, 'mu_week_t2')
        _, _, _, w3, b3 = calc(d, 'mu_week_ts')
        n_applied = d['ts_applied'].sum()
        print(f"  {wk}: baseline {w0:>5.2f}/{b0:>+5.2f}  |  T2 {w2:>5.2f}/{b2:>+5.2f}  |  T3 {w3:>5.2f}/{b3:>+5.2f}  (T3 aplicado: {n_applied}/{len(d)})")

    # Distribución TS
    print("\n" + "=" * 110)
    print("Distribución TS (donde calculado)")
    print("=" * 110)
    ts_vals = df_eval['ts_value'].dropna()
    if len(ts_vals) > 0:
        print(f"  Total con TS: {len(ts_vals):,}")
        print(f"  |TS|>3.75 (corrige): {(ts_vals.abs() > 3.75).sum():,} ({(ts_vals.abs() > 3.75).mean()*100:.1f}%)")
        print(f"  TS > 3.75 (sub-fc): {(ts_vals > 3.75).sum():,}")
        print(f"  TS < -3.75 (over-fc): {(ts_vals < -3.75).sum():,}")
        print(f"  Distribución factor:")
        factors_applied = df_eval[df_eval['ts_applied']]['ts_factor']
        if len(factors_applied):
            print(f"    factor > 1.0 (up): {(factors_applied > 1.0).sum():,}  mean={factors_applied[factors_applied > 1.0].mean():.3f}")
            print(f"    factor < 1.0 (down): {(factors_applied < 1.0).sum():,}  mean={factors_applied[factors_applied < 1.0].mean():.3f}")

    # Guardar
    df_eval.to_parquet(RESULTS / "test_3_ts_detail.parquet", index=False)
    summary = {
        'meta': {
            'method': 'Tracking Signal canon SAP IBP',
            'ventana_N': HISTORY_WEEKS,
            'threshold_TS': TS_THRESHOLD,
            'min_obs_valid': MIN_OBS_VALID,
            'mad_min': MAD_MIN,
            'clamp': [CLAMP_LOW, CLAMP_HIGH],
            'window_start': str(TARGET_WEEKS[0]),
            'window_end': str(TARGET_WEEKS[-1]),
        },
    }
    with open(RESULTS / "test_3_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\n -> test_3_ts_detail.parquet")
    print(f" -> test_3_summary.json")


if __name__ == "__main__":
    main()
