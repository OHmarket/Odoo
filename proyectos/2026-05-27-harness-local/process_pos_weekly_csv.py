"""
Procesa CSV exportado de Odoo (x_pos_week_sku_sale) a parquet con IDs numericos.

Input: c:\\Users\\sanhu\\Odoo\\OH Ventas Semanal SKU (x_pos_week_sku_sale).csv (latin-1)
Output: cache/pos_weekly.parquet
"""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path
import pandas as pd

CACHE = Path(__file__).parent / "cache"
CSV = Path(r"c:\Users\sanhu\Odoo\OH Ventas Semanal SKU (x_pos_week_sku_sale).csv")
OUT = CACHE / "pos_weekly.parquet"


def _fix_mojibake(s):
    """Fix CSV mojibake: bytes utf-8 leidos como latin-1 (Ã± -> ñ)."""
    if not isinstance(s, str):
        return s
    # Detectar mojibake: presencia de caracter 'Ã' (U+00C3) seguido de byte alto
    # es indicador casi seguro de bytes utf-8 stored as latin-1.
    if 'Ã' in s or 'Â' in s:
        try:
            fixed = s.encode('latin-1').decode('utf-8')
            return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def _norm(s):
    """ASCII upper sin acentos. Para match robusto entre Co + ñ + aripe."""
    if not isinstance(s, str):
        return ''
    s = _fix_mojibake(s)
    s = unicodedata.normalize('NFKD', s)
    return s.encode('ascii', errors='ignore').decode('ascii').strip().upper()


def _parse_default_code(display):
    """'[2509] AGUA MINERAL...' -> '2509' (str). None si no matchea."""
    if not isinstance(display, str):
        return None
    m = re.match(r"^\[([^\]]+)\]", display.strip())
    return m.group(1).strip() if m else None


def main():
    print("Cargando catalogos...")
    cat_prods = pd.read_parquet(CACHE / "catalog_products.parquet")
    cat_cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    cat_cfgs = pd.read_parquet(CACHE / "catalog_pos_configs.parquet")
    print(f"  productos: {len(cat_prods):,}")
    print(f"  categorias: {len(cat_cats):,}")
    print(f"  pos_configs: {len(cat_cfgs):,}")

    # 1. Build mapping local_prefix -> team_id desde pos_configs
    #    name = "Coñaripe Caja 1" -> prefix "CONARIPE" -> team_id 16
    cat_cfgs['local_prefix_norm'] = cat_cfgs['name'].apply(
        lambda s: _norm(re.sub(r'\s+Caja\s+\d+\s*$', '', str(s) if s else ''))
    )
    local_to_team = dict(zip(cat_cfgs['local_prefix_norm'], cat_cfgs['crm_team_id_id']))
    print(f"\n  Mapping local -> team_id:")
    for local, team in sorted(set(zip(cat_cfgs['local_prefix_norm'], cat_cfgs['crm_team_id_id']))):
        print(f"    {local!r:30s} -> team {team}")

    # 2. Leer CSV en latin-1
    print(f"\nLeyendo CSV ({CSV.stat().st_size/1e6:.1f} MB) en latin-1...")
    df = pd.read_csv(CSV, dtype=str, encoding="latin-1", low_memory=False)
    print(f"  filas: {len(df):,}")

    # 3. Productos via default_code
    print("\nMatch productos via default_code...")
    df['default_code_str'] = df['product_id'].apply(_parse_default_code)

    cat_prods['default_code_str'] = cat_prods['default_code'].astype(str).where(
        cat_prods['default_code'].notna(), None
    )
    code_to_id = dict(zip(cat_prods['default_code_str'], cat_prods['id']))
    df['product_id_int'] = df['default_code_str'].map(code_to_id)
    n_match = df['product_id_int'].notna().sum()
    print(f"  matcheados: {n_match:,} / {len(df):,}")

    # 4. Teams via "Ventas <local>" -> local prefix -> team_id
    print("\nMatch teams...")
    df['team_label_norm'] = df['team_id'].apply(
        lambda s: _norm(re.sub(r'^\s*Ventas\s+', '', str(s) if s else ''))
    )
    df['team_id_int'] = df['team_label_norm'].map(local_to_team)
    n_team = df['team_id_int'].notna().sum()
    print(f"  matcheados: {n_team:,} / {len(df):,}")
    if n_team < len(df):
        unmatched = sorted(df.loc[df['team_id_int'].isna(), 'team_label_norm'].drop_duplicates().tolist())
        print(f"  no match: {unmatched[:10]}")

    # 5. Categorias por complete_name (normalized)
    print("\nMatch categorias...")
    cat_cats['complete_name_norm'] = cat_cats['complete_name'].apply(_norm)
    catname_to_id = dict(zip(cat_cats['complete_name_norm'], cat_cats['categ_id_id']))
    df['categ_id_int'] = df['categ_id'].apply(_norm).map(catname_to_id)
    n_cat = df['categ_id_int'].notna().sum()
    print(f"  matcheados: {n_cat:,} / {len(df):,}")

    # 6. Tipos
    df['qty_sold'] = pd.to_numeric(df['qty_sold'], errors='coerce').fillna(0.0)
    df['iso_week'] = pd.to_numeric(df['iso_week'], errors='coerce')
    df['week_start'] = pd.to_datetime(df['week_start'], errors='coerce').dt.date
    df['week_end'] = pd.to_datetime(df['week_end'], errors='coerce').dt.date

    # 7. Filtrar validas
    valid = df['product_id_int'].notna() & df['team_id_int'].notna() & df['qty_sold'].notna() & df['week_start'].notna()
    print(f"\nFilas validas: {valid.sum():,} / {len(df):,}")

    out = df.loc[valid, [
        'team_id_int', 'product_id_int', 'categ_id_int',
        'week_start', 'week_end', 'iso_week', 'qty_sold'
    ]].rename(columns={
        'team_id_int': 'team_id',
        'product_id_int': 'product_id',
        'categ_id_int': 'categ_id',
    })
    out['team_id'] = out['team_id'].astype('Int64')
    out['product_id'] = pd.to_numeric(out['product_id'], errors='coerce').astype('Int64')
    out['categ_id'] = out['categ_id'].astype('Int64')
    out['iso_week'] = out['iso_week'].astype('Int64')
    out['qty_sold'] = out['qty_sold'].astype(float)

    print(f"\n  Productos distintos: {out['product_id'].nunique():,}")
    print(f"  Teams distintos: {out['team_id'].nunique():,}")
    print(f"  Rango: {out['week_start'].min()} -> {out['week_start'].max()}")
    print(f"  Semanas distintas: {out['week_start'].nunique()}")
    print(f"  qty_sold total: {out['qty_sold'].sum():,.0f}")

    out.to_parquet(OUT, index=False)
    print(f"\n  -> {OUT.name}  {OUT.stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
