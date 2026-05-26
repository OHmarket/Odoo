"""
Compara 2 corridas de OH Forecast Backtest (pre vs post normalizacion).

Uso:
    python "02_forecast/analisis backtest/2026-05-25-normalizacion/comparar_backtest.py" \
        resultados/pre_*.csv resultados/post_*.csv

Genera reporte comparativo en consola + CSV con detalles.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

THIS_DIR = Path(__file__).resolve().parent


def _wape(df, mu_col, real_col):
    """WAPE = sum|forecast - real| / sum(real)"""
    err = (df[mu_col].fillna(0) - df[real_col].fillna(0)).abs().sum()
    total_real = df[real_col].fillna(0).abs().sum()
    return float(err / total_real * 100) if total_real > 0 else 0.0


def _bias(df, mu_col, real_col):
    """BIAS = (sum_forecast - sum_real) / sum_real"""
    f = df[mu_col].fillna(0).sum()
    r = df[real_col].fillna(0).sum()
    return float((f - r) / r * 100) if r > 0 else 0.0


def _mae(df, mu_col, real_col):
    """MAE = mean|forecast - real|"""
    return float((df[mu_col].fillna(0) - df[real_col].fillna(0)).abs().mean())


def _print_section(title):
    print(f"\n{'=' * 75}")
    print(f"  {title}")
    print('=' * 75)


def _print_kv(label, pre_v, post_v, fmt='%.2f', better='lower'):
    """Imprime una metrica pre/post con flecha de mejora."""
    diff = post_v - pre_v
    if better == 'lower':
        arrow = '[DOWN mejor]' if diff < 0 else ('[UP peor]' if diff > 0 else '=')
    elif better == 'closer_to_zero':
        arrow = '[OK mejor]' if abs(post_v) < abs(pre_v) else ('[KO peor]' if abs(post_v) > abs(pre_v) else '=')
    else:
        arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '=')
    pre_s = fmt % pre_v
    post_s = fmt % post_v
    diff_s = ('%+' + fmt[1:]) % diff
    print(f"  {label:<35s}  pre={pre_s:>10s}  post={post_s:>10s}  delta={diff_s:>10s}  {arrow}")


def main():
    if len(sys.argv) < 3:
        print("Uso: python comparar_backtest.py <pre.csv> <post.csv>")
        sys.exit(1)
    pre_path = Path(sys.argv[1])
    post_path = Path(sys.argv[2])

    print(f"Pre  : {pre_path}")
    print(f"Post : {post_path}")
    pre = pd.read_csv(pre_path)
    post = pd.read_csv(post_path)
    print(f"\nfilas pre = {len(pre):,}")
    print(f"filas post = {len(post):,}")

    # Detectar columnas reales (los nombres exactos dependen del modelo).
    # Buscamos heuristicamente.
    def _detect(df, candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    mu_hm_col = _detect(pre, [
        'x_studio_forecast_qty', 'x_studio_mu_week',
        'x_studio_mu_week_hm_si', 'x_studio_forecast_hm_si',
        'x_studio_hm_si_forecast', 'x_studio_mu_hm_si',
    ])
    real_col = _detect(pre, [
        'x_studio_real_qty', 'x_studio_units_real', 'x_studio_real_units',
        'x_studio_units_pos', 'x_studio_real', 'x_studio_qty_real',
    ])
    if not mu_hm_col or not real_col:
        print("\nNo se detectaron columnas estandar de forecast/real.")
        print(f"Columnas disponibles: {sorted(pre.columns)}")
        sys.exit(1)
    print(f"\nForecast HM-SI col: {mu_hm_col}")
    print(f"Real POS col:       {real_col}")

    # ------------------------------------------------------------
    # Metricas globales
    # ------------------------------------------------------------
    _print_section("METRICAS GLOBALES")
    pre_wape = _wape(pre, mu_hm_col, real_col)
    post_wape = _wape(post, mu_hm_col, real_col)
    _print_kv('WAPE (%)', pre_wape, post_wape, '%.2f', 'lower')

    pre_bias = _bias(pre, mu_hm_col, real_col)
    post_bias = _bias(post, mu_hm_col, real_col)
    _print_kv('BIAS (%)', pre_bias, post_bias, '%.2f', 'closer_to_zero')

    pre_mae = _mae(pre, mu_hm_col, real_col)
    post_mae = _mae(post, mu_hm_col, real_col)
    _print_kv('MAE (unidades)', pre_mae, post_mae, '%.3f', 'lower')

    sum_real = pre[real_col].fillna(0).sum()
    sum_fc_pre = pre[mu_hm_col].fillna(0).sum()
    sum_fc_post = post[mu_hm_col].fillna(0).sum()
    print(f"\n  sum_real        : {sum_real:>15,.0f}")
    print(f"  sum_forecast pre: {sum_fc_pre:>15,.0f} ({(sum_fc_pre/sum_real-1)*100:+.2f}% vs real)")
    print(f"  sum_forecast post:{sum_fc_post:>15,.0f} ({(sum_fc_post/sum_real-1)*100:+.2f}% vs real)")

    # ------------------------------------------------------------
    # Por dimension: regimen, sala, categoria
    # ------------------------------------------------------------
    dim_candidates = {
        'regimen': ['x_studio_regimen', 'x_studio_zone_code', 'x_studio_router_zone'],
        'sala':    ['x_studio_team_id', 'x_studio_sala', 'team_id'],
        'categoria': ['x_studio_categ_id', 'categ_id'],
    }

    for dim_name, candidates in dim_candidates.items():
        col = _detect(pre, candidates)
        if not col:
            continue
        _print_section(f"POR {dim_name.upper()} ({col})")
        print(f"  {'grupo':<25s} {'n':>6s} {'real':>10s} {'WAPE pre':>10s} {'WAPE post':>10s} {'delta':>8s} {'BIAS pre':>10s} {'BIAS post':>10s}")
        groups = sorted(set(pre[col].dropna().unique()) | set(post[col].dropna().unique()))
        for g in groups:
            pre_g = pre[pre[col] == g]
            post_g = post[post[col] == g]
            if len(pre_g) == 0 and len(post_g) == 0:
                continue
            n = max(len(pre_g), len(post_g))
            real_g = pre_g[real_col].fillna(0).sum()
            wape_pre = _wape(pre_g, mu_hm_col, real_col)
            wape_post = _wape(post_g, mu_hm_col, real_col)
            bias_pre = _bias(pre_g, mu_hm_col, real_col)
            bias_post = _bias(post_g, mu_hm_col, real_col)
            d_wape = wape_post - wape_pre
            arrow = 'v' if d_wape < -0.1 else ('^' if d_wape > 0.1 else '=')
            label = str(g)[:24]
            print(f"  {label:<25s} {n:>6,} {real_g:>10,.0f} {wape_pre:>10.2f} {wape_post:>10.2f} {d_wape:>+7.2f}{arrow} {bias_pre:>10.2f} {bias_post:>10.2f}")

    # ------------------------------------------------------------
    # Top 20 SKUs con mayor delta
    # ------------------------------------------------------------
    pid_col = _detect(pre, ['x_studio_product_id', 'product_id'])
    if pid_col:
        _print_section("TOP 20 SKUs CON MAYOR CAMBIO DE FORECAST")
        if pid_col in pre.columns and pid_col in post.columns:
            # mergear por sku
            keys = [pid_col]
            wk_col = _detect(pre, ['x_studio_week_start', 'week_start', 'week'])
            team_col = _detect(pre, ['x_studio_team_id', 'team_id'])
            if wk_col:
                keys.append(wk_col)
            if team_col:
                keys.append(team_col)

            merged = pre[keys + [mu_hm_col, real_col]].merge(
                post[keys + [mu_hm_col]], on=keys, suffixes=('_pre', '_post'),
            )
            merged['_delta'] = merged[mu_hm_col + '_post'] - merged[mu_hm_col + '_pre']
            top = merged.reindex(merged['_delta'].abs().sort_values(ascending=False).index).head(20)
            for _, r in top.iterrows():
                print(f"  team={r.get(team_col, '?')} sku={r[pid_col]} wk={r.get(wk_col, '?')} "
                      f"real={r[real_col]:.1f} fc_pre={r[mu_hm_col+'_pre']:.1f} "
                      f"fc_post={r[mu_hm_col+'_post']:.1f} delta={r['_delta']:+.1f}")

    # ------------------------------------------------------------
    # Guardar tabla comparativa
    # ------------------------------------------------------------
    out_csv = THIS_DIR / 'resultados' / 'comparativo.csv'
    out_csv.parent.mkdir(exist_ok=True)
    summary = pd.DataFrame([
        {'metric': 'WAPE', 'pre': pre_wape, 'post': post_wape, 'delta': post_wape - pre_wape},
        {'metric': 'BIAS', 'pre': pre_bias, 'post': post_bias, 'delta': post_bias - pre_bias},
        {'metric': 'MAE',  'pre': pre_mae,  'post': post_mae,  'delta': post_mae - pre_mae},
        {'metric': 'sum_forecast', 'pre': sum_fc_pre, 'post': sum_fc_post, 'delta': sum_fc_post - sum_fc_pre},
        {'metric': 'sum_real', 'pre': sum_real, 'post': sum_real, 'delta': 0.0},
    ])
    summary.to_csv(out_csv, index=False)
    print(f"\nResumen guardado en: {out_csv}")


if __name__ == '__main__':
    main()
