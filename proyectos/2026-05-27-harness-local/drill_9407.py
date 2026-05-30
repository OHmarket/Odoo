"""Drill-down detallado del SKU 9407 (Stella Artois 660cc) sobre 10 sem.

Mostrar:
- Serie histórica weekly por team (8 sem antes + 10 sem target)
- Forecast mu_week por (team, target_week) baseline vs Test 2
- Real qty_sold por (team, target_week)
- Detección de quiebres (proxy + demanda_norm)
- Patrón temporal claro
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

SKU_ID = 11797  # default_code 9407
SKU_CODE = '9407'

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]


def main():
    # 1. Serie POS de las últimas 18 sem (8 antes + 10 target)
    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    pos_sku = pos[pos['product_id'] == SKU_ID].copy()
    print(f"SKU {SKU_CODE}: {pos_sku['team_id'].nunique()} teams, {len(pos_sku):,} filas POS")

    teams = pd.read_parquet(CACHE / "catalog_pos_configs.parquet")[['crm_team_id_id', 'name']]
    import re
    teams['local'] = teams['name'].apply(lambda s: re.sub(r'\s+Caja\s+\d+\s*$', '', str(s) if s else ''))
    team_name = dict(zip(teams['crm_team_id_id'], teams['local']))

    # 2. Histórico 8 sem antes del target_week[0] = 2026-03-16
    hist_from = TARGET_WEEKS[0] - timedelta(weeks=8)
    pos_hist = pos_sku[(pos_sku['week_start'] >= hist_from) & (pos_sku['week_start'] < TARGET_WEEKS[0])]
    pos_target = pos_sku[pos_sku['week_start'].isin(TARGET_WEEKS)]

    print(f"\nHistoria 8 sem prev: {len(pos_hist)} filas")
    print(f"Target 10 sem:        {len(pos_target)} filas")

    # 3. Corrida baseline 10 sem para tener mu_week por team
    print("\nCorriendo baseline para SKU 9407...")
    rows = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        fc_sku = fc[fc['product_id'] == SKU_ID]
        for _, r in fc_sku.iterrows():
            rows.append({
                'target_week': target,
                'team_id': int(r['team_id']),
                'mu_week': float(r['mu_week']),
                'mu_base': float(r['mu_base']),
                'si_factor': float(r['si_factor']),
                'trend_factor': float(r['trend_factor']),
                'demand_method': r['demand_method'],
                'regimen_eff': r['regimen_eff'],
                'abcxyz_eff': r['abcxyz_eff'],
            })
    fcst = pd.DataFrame(rows)
    print(f"Forecasts generados: {len(fcst)}")

    # 4. Merge con real
    merge = fcst.merge(
        pos_target.rename(columns={'week_start': 'target_week'})[['target_week', 'team_id', 'qty_sold']],
        on=['target_week', 'team_id'], how='left'
    ).fillna({'qty_sold': 0.0})

    # demanda_norm
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail', 'x_studio_qty_norm': 'qty_norm', 'x_studio_qty_obs': 'qty_obs'})
    dn_sku = dn[(dn['product_id'] == SKU_ID) & (dn['week_start'].isin(TARGET_WEEKS))]
    merge = merge.merge(
        dn_sku.rename(columns={'week_start': 'target_week'})[['target_week', 'team_id', 'avail', 'qty_norm']],
        on=['target_week', 'team_id'], how='left'
    )

    # avg histórico 8 sem por team
    avg_h = pos_hist.groupby('team_id')['qty_sold'].mean().reset_index()
    avg_h.columns = ['team_id', 'avg_prev_8w']
    merge = merge.merge(avg_h, on='team_id', how='left').fillna({'avg_prev_8w': 0.0})

    merge['error'] = merge['qty_sold'] - merge['mu_week']
    merge['abs_error'] = merge['error'].abs()
    merge['dn_censurado'] = merge['avail'].notna() & (merge['avail'] < 1.0)
    merge['proxy_quiebre'] = (merge['avg_prev_8w'] >= 1.0) & \
                              (merge['qty_sold'] < merge['avg_prev_8w'].apply(lambda x: max(0.2 * x, 0.5)))

    merge['team_name'] = merge['team_id'].map(team_name)

    # Resumen totals
    total_real = merge['qty_sold'].sum()
    total_fcst = merge['mu_week'].sum()
    total_ae = merge['abs_error'].sum()
    print(f"\n  Total real: {total_real:,.0f}")
    print(f"  Total fcst: {total_fcst:,.0f}")
    print(f"  AE: {total_ae:,.0f}  WAPE: {total_ae/total_real*100:.1f}%  BIAS: {(total_real-total_fcst)/total_real*100:+.1f}%")
    print(f"  dn_censurado: {merge['dn_censurado'].sum()} de {len(merge)}")
    print(f"  proxy_quiebre: {merge['proxy_quiebre'].sum()} de {len(merge)}")

    # 5. Tabla por team x semana
    print("\n" + "=" * 130)
    print(f"DETALLE SKU 9407 STELLA - mu_week / qty_sold por (team, semana)")
    print("=" * 130)
    print(f"\n  fcst regimen={merge['regimen_eff'].iloc[0] if len(merge) else 'NA'}  abcxyz={merge['abcxyz_eff'].iloc[0] if len(merge) else 'NA'}")

    # Pivot: filas team, columnas semana
    print("\n--- mu_week (baseline) ---")
    piv_fc = merge.pivot_table(index='team_name', columns='target_week', values='mu_week', aggfunc='first').round(1)
    print(piv_fc.to_string())

    print("\n--- qty_sold (real) ---")
    piv_real = merge.pivot_table(index='team_name', columns='target_week', values='qty_sold', aggfunc='first').fillna(0).astype(int)
    print(piv_real.to_string())

    print("\n--- error = real - fcst ---")
    piv_err = merge.pivot_table(index='team_name', columns='target_week', values='error', aggfunc='first').round(1)
    print(piv_err.to_string())

    # 6. Por team, BIAS / WAPE
    print("\n" + "=" * 100)
    print("Por team (10 sem agregadas)")
    print("=" * 100)
    by_team = merge.groupby('team_name').agg(
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        ae=('abs_error', 'sum'),
        n=('mu_week', 'size'),
    )
    by_team['WAPE'] = (by_team['ae'] / by_team['real'] * 100).round(1)
    by_team['BIAS'] = ((by_team['real'] - by_team['fcst']) / by_team['real'] * 100).round(1)
    print(by_team.to_string())

    # 7. Por semana
    print("\n" + "=" * 100)
    print("Por semana (12 teams agregados)")
    print("=" * 100)
    by_wk = merge.groupby('target_week').agg(
        real=('qty_sold', 'sum'),
        fcst=('mu_week', 'sum'),
        ae=('abs_error', 'sum'),
    )
    by_wk['WAPE'] = (by_wk['ae'] / by_wk['real'] * 100).round(1)
    by_wk['BIAS'] = ((by_wk['real'] - by_wk['fcst']) / by_wk['real'] * 100).round(1)
    print(by_wk.to_string())

    # 8. Serie histórica (8 sem prev + 10 sem target) por team agregado
    print("\n" + "=" * 100)
    print("Serie completa (18 sem) - venta total Stella todos los teams")
    print("=" * 100)
    all_weeks = sorted(set(pos_hist['week_start'].tolist() + pos_target['week_start'].tolist()))
    pos_all = pos_sku[pos_sku['week_start'].isin(all_weeks)]
    by_w = pos_all.groupby('week_start')['qty_sold'].sum()
    for w in all_weeks:
        marker = '  [TARGET]' if w in TARGET_WEEKS else '  [HIST]'
        print(f"  {w}: {by_w.get(w, 0):>6.0f}{marker}")

    # 9. método elegido por bake-off
    print("\n" + "=" * 100)
    print("Método elegido por bake-off, por (team, semana)")
    print("=" * 100)
    piv_m = merge.pivot_table(index='team_name', columns='target_week', values='demand_method', aggfunc='first')
    print(piv_m.to_string())

    merge.to_parquet(RESULTS / "sku_9407_detail.parquet", index=False)
    print(f"\n -> sku_9407_detail.parquet")


if __name__ == "__main__":
    main()
