"""
compare_parity — Paridad 1-a-1 (team, sku, target_week) entre el backtest Odoo
(output de OH Forecast Base) y el mirror local forecast_base_local.

Reusa el parser del CSV del harness viejo (mojibake latin-1, team label "Ventas X",
default_code -> product_id). Adapta a las columnas de Forecast Base.

REQUISITOS del CSV de entrada (export del backtest):
  - corrido con context decensor_stockout=False (apples-to-apples; el mirror v0
    NO de-censura). Si se corrio con de-censura ON, las semanas con quiebre
    divergiran y es ESPERADO (ver memoria: doble conteo de-censura).
  - debe cubrir target weeks <= horizonte del cache (week_max de pos_weekly,
    hoy 2026-05-18). El comparador intersecta y avisa cobertura.

Uso:
    python compare_parity.py "ruta/al/backtest.csv"
"""
from __future__ import annotations
import re
import sys
import unicodedata
from pathlib import Path
from datetime import timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import run, CACHE_DIR_DEFAULT  # noqa: E402

CACHE = Path(CACHE_DIR_DEFAULT)
RESULTS = Path(__file__).resolve().parent / "resultados"
PARITY_THRESHOLD = 0.50   # criterio del harness: diff<0.5 en >=70% = A/B relativo OK


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


def load_odoo_csv(csv_path):
    print(f"\nLeyendo {csv_path.name} ({csv_path.stat().st_size/1e6:.1f} MB)...")
    df = pd.read_csv(csv_path, low_memory=False, encoding='latin-1', dtype=str)
    print(f"  raw filas: {len(df):,}")
    for c in ['forecast_qty', 'real_qty']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    if 'real_qty' not in df.columns:
        df['real_qty'] = 0.0
    df['target_week_start'] = pd.to_datetime(df['target_week_start']).dt.date
    df['default_code_str'] = df['product_id'].apply(_parse_default_code)

    cat_prods = pd.read_parquet(CACHE / "catalog_products.parquet")
    cat_prods['default_code_str'] = cat_prods['default_code'].astype(str).where(
        cat_prods['default_code'].notna(), None)
    code_to_id = dict(zip(cat_prods['default_code_str'], cat_prods['id']))
    df['product_id_int'] = df['default_code_str'].map(code_to_id)

    cfgs = pd.read_parquet(CACHE / "catalog_pos_configs.parquet")
    cfgs['local_prefix_norm'] = cfgs['name'].apply(
        lambda s: _norm(re.sub(r'\s+Caja\s+\d+\s*$', '', str(s) if s else '')))
    local_to_team = dict(zip(cfgs['local_prefix_norm'], cfgs['crm_team_id_id']))
    df['team_label_norm'] = df['team_id'].apply(
        lambda s: _norm(re.sub(r'^\s*Ventas\s+', '', str(s) if s else '')))
    df['team_id_int'] = df['team_label_norm'].map(local_to_team)

    print(f"  match product_id: {df['product_id_int'].notna().sum():,} / {len(df):,}")
    print(f"  match team_id: {df['team_id_int'].notna().sum():,} / {len(df):,}")
    valid = df['product_id_int'].notna() & df['team_id_int'].notna()
    df = df[valid].copy()
    df['product_id'] = df['product_id_int'].astype(int)
    df['team_id'] = df['team_id_int'].astype(int)
    return df[['team_id', 'product_id', 'target_week_start', 'forecast_qty', 'real_qty']].copy()


def run_local_for_targets(target_weeks):
    parts = []
    for target in sorted(target_weeks):
        cutoff = target - timedelta(days=1)   # domingo previo -> mirror alinea al lunes
        print(f"\nRunning local target={target} (cutoff={cutoff})...")
        fc = run(cutoff_date=cutoff, cache_dir=CACHE)
        fc = fc[['team_id', 'product_id', 'mu_week', 'forecast_model_code', 'series_type']].copy()
        fc['target_week_start'] = target
        parts.append(fc)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def main():
    if len(sys.argv) < 2:
        print("uso: python compare_parity.py <ruta_csv_backtest>")
        sys.exit(1)
    csv_path = Path(sys.argv[1])
    print("=" * 80)
    print("PARIDAD: Backtest Odoo (Forecast Base) vs mirror local")
    print("=" * 80)

    odoo = load_odoo_csv(csv_path)
    print(f"\nOdoo limpio: {len(odoo):,} filas | semanas: {sorted(odoo['target_week_start'].unique())}")

    # horizonte del cache: solo target weeks <= week_max(pos)+7 son producibles
    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    cache_week_max = pd.to_datetime(pos['week_start']).dt.date.max()
    producible = sorted(w for w in odoo['target_week_start'].unique() if (w - timedelta(days=7)) <= cache_week_max)
    descartadas = sorted(set(odoo['target_week_start'].unique()) - set(producible))
    print(f"\nCache week_max={cache_week_max}. Target producibles: {producible}")
    if descartadas:
        print(f"  ⚠ FUERA del cache (refrescar snapshot para incluir): {descartadas}")
    if not producible:
        print("  Sin semanas comparables con el cache actual. Refresca el snapshot.")
        sys.exit(0)

    odoo = odoo[odoo['target_week_start'].isin(producible)].copy()
    local = run_local_for_targets(producible)
    print(f"\nLocal: {len(local):,} filas")

    merged = odoo.merge(local, on=['team_id', 'product_id', 'target_week_start'],
                        how='outer', suffixes=('_odoo', '_local'), indicator=True)
    print("\nmatch status:"); print(merged['_merge'].value_counts())

    both = merged[merged['_merge'] == 'both'].copy()
    both['mu_week'] = both['mu_week'].fillna(0.0)
    both['forecast_qty'] = both['forecast_qty'].fillna(0.0)
    both['diff_mu'] = (both['mu_week'] - both['forecast_qty']).abs()

    print(f"\nComparacion 1-a-1 ({len(both):,} filas en ambos):")
    for t in [0.01, 0.10, 0.50, 1.00, 2.00, 5.00]:
        n = (both['diff_mu'] < t).sum()
        print(f"    diff < {t:.2f}: {n:,} ({100*n/len(both):.1f}%)")
    print(f"  mean={both['diff_mu'].mean():.3f}  median={both['diff_mu'].median():.3f}  "
          f"P95={both['diff_mu'].quantile(0.95):.3f}  max={both['diff_mu'].max():.3f}")

    pct_ok = 100 * (both['diff_mu'] < PARITY_THRESHOLD).sum() / len(both)
    print(f"\n  >>> diff<{PARITY_THRESHOLD}: {pct_ok:.1f}%  "
          f"({'PARIDAD OK para A/B relativo' if pct_ok >= 70 else 'REVISAR divergencia'})")

    print("\n  Top 15 divergencias:")
    top = both.nlargest(15, 'diff_mu')[['team_id', 'product_id', 'target_week_start',
          'forecast_qty', 'mu_week', 'diff_mu', 'forecast_model_code', 'series_type']]
    print(top.to_string(index=False))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "compare_parity.parquet"
    both.to_parquet(out, index=False)
    print(f"\n  -> {out}")


if __name__ == "__main__":
    main()
