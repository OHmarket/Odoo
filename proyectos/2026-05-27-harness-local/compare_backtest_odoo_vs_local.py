"""
Compara 1 a 1 (team, sku, target_week) backtest Odoo vs local.

Para cada fila del CSV Odoo, encuentra la fila correspondiente en el local
y reporta diff de mu_week. Stats agregadas + top divergencias.
"""
from __future__ import annotations
import re
import sys
import unicodedata
from pathlib import Path
from datetime import date

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from HM_SI_local import run, DEFAULT_CONFIG, load_cache

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"
CSV_ODOO = ROOT / "OH Forecast Backtest (x_forecast_backtest) (3).csv"


def _fix_mojibake(s):
    if not isinstance(s, str):
        return s
    if 'Ã' in s or 'Â' in s:
        try:
            return s.encode('latin-1').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def _norm(s):
    if not isinstance(s, str):
        return ''
    s = _fix_mojibake(s)
    s = unicodedata.normalize('NFKD', s)
    return s.encode('ascii', errors='ignore').decode('ascii').strip().upper()


def _parse_default_code(display):
    if not isinstance(display, str):
        return None
    m = re.match(r"^\[([^\]]+)\]", display.strip())
    return m.group(1).strip() if m else None


def load_odoo_csv():
    """Carga CSV de backtest y resuelve IDs."""
    print(f"\nLeyendo {CSV_ODOO.name} ({CSV_ODOO.stat().st_size/1e6:.1f} MB)...")
    df = pd.read_csv(CSV_ODOO, low_memory=False, encoding='latin-1', dtype=str)
    print(f"  raw filas: {len(df):,}")

    # Numérico
    for c in ['forecast_qty', 'real_qty']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

    df['target_week_start'] = pd.to_datetime(df['target_week_start']).dt.date
    df['default_code_str'] = df['product_id'].apply(_parse_default_code)

    # Cargar catálogo para match IDs
    cat_prods = pd.read_parquet(CACHE / "catalog_products.parquet")
    cat_prods['default_code_str'] = cat_prods['default_code'].astype(str).where(
        cat_prods['default_code'].notna(), None
    )
    code_to_id = dict(zip(cat_prods['default_code_str'], cat_prods['id']))
    df['product_id_int'] = df['default_code_str'].map(code_to_id)

    cfgs = pd.read_parquet(CACHE / "catalog_pos_configs.parquet")
    cfgs['local_prefix_norm'] = cfgs['name'].apply(
        lambda s: _norm(re.sub(r'\s+Caja\s+\d+\s*$', '', str(s) if s else ''))
    )
    local_to_team = dict(zip(cfgs['local_prefix_norm'], cfgs['crm_team_id_id']))

    df['team_label_norm'] = df['team_id'].apply(
        lambda s: _norm(re.sub(r'^\s*Ventas\s+', '', str(s) if s else ''))
    )
    df['team_id_int'] = df['team_label_norm'].map(local_to_team)

    n_pid = df['product_id_int'].notna().sum()
    n_tid = df['team_id_int'].notna().sum()
    print(f"  match product_id: {n_pid:,} / {len(df):,}")
    print(f"  match team_id: {n_tid:,} / {len(df):,}")

    valid = df['product_id_int'].notna() & df['team_id_int'].notna()
    df = df[valid].copy()
    df['product_id'] = df['product_id_int'].astype(int)
    df['team_id'] = df['team_id_int'].astype(int)

    return df[['team_id', 'product_id', 'target_week_start',
                'forecast_qty', 'real_qty', 'categ_id']].copy()


def run_local_all_cutoffs():
    """Corre mirror para los 3 cutoffs y devuelve concat."""
    cutoffs = [
        (date(2026, 5, 3),  date(2026, 5, 4)),
        (date(2026, 5, 10), date(2026, 5, 11)),
        (date(2026, 5, 17), date(2026, 5, 18)),
    ]

    parts = []
    for cutoff, target in cutoffs:
        print(f"\nRunning local cutoff={cutoff}...")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        fc = fc[['team_id', 'product_id', 'mu_week', 'mu_base', 'si_factor',
                  'forecast_model_code', 'demand_method', 'trend_factor']].copy()
        fc['target_week_start'] = target
        parts.append(fc)
    return pd.concat(parts, ignore_index=True)


def main():
    print("=" * 80)
    print("COMPARATIVA 1-A-1: Backtest Odoo vs Local mirror (cutoff por SKU x team)")
    print("=" * 80)

    odoo = load_odoo_csv()
    print(f"\nOdoo limpio: {len(odoo):,} filas")
    print(f"  Semanas: {sorted(odoo['target_week_start'].unique())}")

    local = run_local_all_cutoffs()
    print(f"\nLocal: {len(local):,} filas")

    # Match 1 a 1
    print("\nMerge 1-a-1...")
    merged = odoo.merge(
        local,
        on=['team_id', 'product_id', 'target_week_start'],
        how='outer',
        suffixes=('_odoo', '_local'),
        indicator=True,
    )
    print(f"  merged: {len(merged):,}")
    print(f"  match status:")
    print(merged['_merge'].value_counts())

    # Solo filas en AMBOS
    both = merged[merged['_merge'] == 'both'].copy()
    both['mu_week'] = both['mu_week'].fillna(0.0)
    both['forecast_qty'] = both['forecast_qty'].fillna(0.0)
    both['real_qty'] = both['real_qty'].fillna(0.0)

    print(f"\nPair-wise comparison ({len(both):,} filas en ambos):")
    both['diff_mu'] = (both['mu_week'] - both['forecast_qty']).abs()
    both['rel_diff'] = both['diff_mu'] / both['forecast_qty'].where(both['forecast_qty'] > 0.01, 1.0)

    print(f"\n  diff_mu (|local - odoo|) distribuciones:")
    for t in [0.01, 0.10, 0.50, 1.00, 2.00, 5.00]:
        n = (both['diff_mu'] < t).sum()
        print(f"    < {t:.2f}: {n:,} ({100*n/len(both):.1f}%)")

    print(f"\n  mean: {both['diff_mu'].mean():.3f}")
    print(f"  median: {both['diff_mu'].median():.3f}")
    print(f"  P95: {both['diff_mu'].quantile(0.95):.3f}")
    print(f"  max: {both['diff_mu'].max():.3f}")

    # Métricas por método del local (qué modelo dio cada uno)
    print(f"\n  Top demand_method usados en local:")
    print(both['demand_method'].value_counts().head(10))

    # Comparación por semana
    print(f"\n  Métricas por semana (sin filtro noise):")
    for wk in sorted(both['target_week_start'].unique()):
        s = both[both['target_week_start'] == wk]
        real = s['real_qty'].sum()
        fc_odoo = s['forecast_qty'].sum()
        fc_loc = s['mu_week'].sum()
        wape_odoo = (s['forecast_qty'] - s['real_qty']).abs().sum() / real * 100 if real > 0 else 0
        wape_loc = (s['mu_week'] - s['real_qty']).abs().sum() / real * 100 if real > 0 else 0
        bias_odoo = (s['real_qty'] - s['forecast_qty']).sum() / real * 100 if real > 0 else 0
        bias_loc = (s['real_qty'] - s['mu_week']).sum() / real * 100 if real > 0 else 0
        print(f"    {wk}  n={len(s):>5,}  real={real:>7,.0f}  fcst_odoo={fc_odoo:>7,.0f}  fcst_loc={fc_loc:>7,.0f}  "
                f"WAPE_o={wape_odoo:>5.1f}%  WAPE_l={wape_loc:>5.1f}%  BIAS_o={bias_odoo:>+5.1f}%  BIAS_l={bias_loc:>+5.1f}%")

    # Top 15 mayores divergencias (de mismo SKU x team x sem)
    print(f"\n  Top 15 mayores divergencias |fc_local - fc_odoo|:")
    top = both.nlargest(15, 'diff_mu')[
        ['team_id', 'product_id', 'target_week_start',
         'forecast_qty', 'mu_week', 'real_qty', 'diff_mu',
         'forecast_model_code', 'demand_method', 'trend_factor']
    ]
    print(top.to_string(index=False))

    out = RESULTS / "compare_1a1.parquet"
    both.to_parquet(out, index=False)
    print(f"\n  -> {out.name}")


if __name__ == "__main__":
    main()
