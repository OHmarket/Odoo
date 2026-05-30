"""
Compara mu_week del mirror local vs x_hm_si_forecast productivo.

Pull liviano: search_read sobre x_hm_si_forecast con solo las columnas
necesarias (~20K filas, 1 query, ~2 seg). Match por (team_id, product_id).
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"


def pull_productivo():
    odoo = OdooReader()
    print(f"Pulling x_hm_si_forecast (productivo)...")
    rows = odoo.search_read(
        'x_hm_si_forecast',
        domain=[],
        fields=[
            'x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id',
            'x_studio_week_start', 'x_studio_mu_week', 'x_studio_sigma_week',
            'x_studio_mu_base', 'x_studio_mu_week_pre_bias',
            'x_studio_mu_week_pre_corr', 'x_studio_correccion_factor',
            'x_studio_forecast_zone', 'x_studio_forecast_model_code',
            'x_studio_regimen', 'x_studio_series_type', 'x_studio_ciclo_de_vida',
            'x_studio_si_current', 'x_studio_si_main_factor', 'x_studio_si_sku_factor',
            'x_studio_abcxyz', 'x_studio_demand_method',
        ],
    )
    print(f"  rows: {len(rows):,}")

    df = pd.DataFrame(rows)
    # Resolve m2o tuples a int
    for col in ['x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id']:
        df[col + '_id'] = df[col].apply(lambda v: v[0] if isinstance(v, (list, tuple)) and v else None)
    df = df.drop(columns=['x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id'])
    df = df.rename(columns={
        'x_studio_product_id_id': 'product_id',
        'x_studio_team_id_id': 'team_id',
        'x_studio_categ_id_id': 'categ_id',
        'x_studio_week_start': 'target_week_start',
        'x_studio_mu_week': 'mu_week_prod',
        'x_studio_mu_base': 'mu_base_prod',
        'x_studio_mu_week_pre_bias': 'mu_week_pre_trend_prod',
        'x_studio_mu_week_pre_corr': 'mu_week_pre_corr_prod',
        'x_studio_correccion_factor': 'correccion_factor_prod',
        'x_studio_forecast_zone': 'forecast_zone_prod',
        'x_studio_forecast_model_code': 'forecast_model_code_prod',
        'x_studio_regimen': 'regimen_prod',
        'x_studio_series_type': 'series_type_prod',
        'x_studio_ciclo_de_vida': 'lifecycle_prod',
        'x_studio_si_current': 'si_current_prod',
        'x_studio_si_main_factor': 'si_main_prod',
        'x_studio_si_sku_factor': 'si_sku_prod',
        'x_studio_abcxyz': 'abcxyz_prod',
        'x_studio_demand_method': 'demand_method_prod',
    })
    df['target_week_start'] = pd.to_datetime(df['target_week_start']).dt.date

    print(f"\n  target_week_start distribution:")
    print(df['target_week_start'].value_counts().head(5))

    out = CACHE / "hmsi_prod.parquet"
    df.to_parquet(out, index=False)
    print(f"\n  -> {out.name}  {out.stat().st_size/1024:.0f} KB")
    return df


def compare(local_parquet, prod_df):
    print(f"\nLoading local: {local_parquet}")
    df_loc = pd.read_parquet(local_parquet)
    print(f"  rows: {len(df_loc):,}")
    print(f"  target_week_start local: {df_loc['target_week_start'].iloc[0]}")

    # Filtrar productivo a la misma target_week
    target_local = df_loc['target_week_start'].iloc[0]
    if isinstance(target_local, pd.Timestamp):
        target_local = target_local.date()
    elif not isinstance(target_local, date):
        target_local = pd.to_datetime(target_local).date()

    df_prod = prod_df[prod_df['target_week_start'] == target_local].copy()
    print(f"  prod filtrado a target_week={target_local}: {len(df_prod):,}")

    if len(df_prod) == 0:
        print("  No prod rows en esa target_week. Productivo usa otra cutoff.")
        return

    # Match por (team_id, product_id)
    df_loc_k = df_loc[['team_id', 'product_id', 'mu_base', 'mu_week',
                        'forecast_model_code', 'demand_method',
                        'abcxyz_eff', 'regimen_eff', 'lifecycle_eff',
                        'series_type_eff']].rename(columns={
                            'abcxyz_eff': 'abcxyz_local',
                            'regimen_eff': 'regimen_local',
                            'lifecycle_eff': 'lifecycle_local',
                            'series_type_eff': 'series_type_local',
                        }).copy()
    merged = df_loc_k.merge(
        df_prod[['team_id', 'product_id', 'mu_week_prod', 'mu_base_prod',
                  'forecast_model_code_prod', 'demand_method_prod',
                  'abcxyz_prod', 'regimen_prod', 'lifecycle_prod', 'series_type_prod']],
        on=['team_id', 'product_id'], how='inner'
    )
    print(f"\n  Matched pairs (team, product): {len(merged):,}")

    # Métricas paridad
    merged['diff_mu_week'] = (merged['mu_week'] - merged['mu_week_prod']).abs()
    merged['diff_mu_base'] = (merged['mu_base'] - merged['mu_base_prod']).abs()
    merged['rel_diff_mu_week'] = merged['diff_mu_week'] / merged['mu_week_prod'].where(merged['mu_week_prod'] > 0.01, 1.0)

    print(f"\n  mu_week paridad:")
    print(f"    diff < 0.01: {(merged['diff_mu_week'] < 0.01).sum():,} ({(merged['diff_mu_week'] < 0.01).mean() * 100:.1f}%)")
    print(f"    diff < 0.10: {(merged['diff_mu_week'] < 0.10).sum():,} ({(merged['diff_mu_week'] < 0.10).mean() * 100:.1f}%)")
    print(f"    diff < 0.50: {(merged['diff_mu_week'] < 0.50).sum():,} ({(merged['diff_mu_week'] < 0.50).mean() * 100:.1f}%)")
    print(f"    diff > 1.00: {(merged['diff_mu_week'] >= 1.0).sum():,} ({(merged['diff_mu_week'] >= 1.0).mean() * 100:.1f}%)")
    print(f"    mean diff: {merged['diff_mu_week'].mean():.3f}")
    print(f"    median diff: {merged['diff_mu_week'].median():.3f}")
    print(f"    max diff: {merged['diff_mu_week'].max():.3f}")

    print(f"\n  Match de clasificacion:")
    print(f"    abcxyz: {(merged['abcxyz_local'] == merged['abcxyz_prod']).sum():,} / {len(merged):,}")
    print(f"    regimen: {(merged['regimen_local'] == merged['regimen_prod']).sum():,} / {len(merged):,}")
    print(f"    lifecycle: {(merged['lifecycle_local'] == merged['lifecycle_prod']).sum():,} / {len(merged):,}")
    print(f"    series_type: {(merged['series_type_local'] == merged['series_type_prod']).sum():,} / {len(merged):,}")
    print(f"    forecast_model_code: {(merged['forecast_model_code'] == merged['forecast_model_code_prod']).sum():,} / {len(merged):,}")
    print(f"    demand_method: {(merged['demand_method'] == merged['demand_method_prod']).sum():,} / {len(merged):,}")

    # Top divergencias
    print(f"\n  Top 10 mayores divergencias mu_week:")
    top = merged.nlargest(10, 'diff_mu_week')
    print(top[['team_id', 'product_id', 'mu_week', 'mu_week_prod', 'diff_mu_week',
                'forecast_model_code', 'forecast_model_code_prod',
                'demand_method', 'demand_method_prod']].to_string(index=False))

    out = RESULTS / "compare_parity.parquet"
    merged.to_parquet(out, index=False)
    print(f"\n  -> {out.name}  {out.stat().st_size/1024:.0f} KB")


def main():
    prod_df = pull_productivo()

    # Detectar la target_week productiva mas comun
    main_target = prod_df['target_week_start'].mode().iloc[0]
    print(f"\nTarget productivo principal: {main_target}")
    print(f"Necesito mirror local con cutoff -> domingo previo a {main_target}")

    from datetime import timedelta
    cutoff_needed = main_target - timedelta(days=1)
    local_parquet = RESULTS / f"forecast_local_{cutoff_needed}.parquet"

    if not local_parquet.exists():
        print(f"\nFalta: {local_parquet.name}")
        print(f"Corre primero: python HM_SI_local.py {cutoff_needed}")
        # Probar con uno disponible
        existing = sorted(RESULTS.glob("forecast_local_*.parquet"))
        if existing:
            print(f"\nUsando lo disponible: {existing[-1].name}")
            local_parquet = existing[-1]
        else:
            return

    compare(local_parquet, prod_df)


if __name__ == "__main__":
    main()
