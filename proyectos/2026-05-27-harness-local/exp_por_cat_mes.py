"""
WAPE/BIAS del motor baseline (limpio) agrupado por MES y por CATEGORIA.
10 semanas (W12-W21). Busca donde se concentra el sub-forecast.
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


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy(); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    cat = pd.read_parquet(CACHE / "catalog_categories.parquet")
    id_col = 'id' if 'id' in cat.columns else cat.columns[0]
    name_col = next((c for c in ['complete_name', 'name', 'display_name'] if c in cat.columns), None)
    cat_map = dict(zip(cat[id_col], cat[name_col])) if name_col else {}

    weeks = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]
    parts = []
    for target in weeks:
        cutoff = target - timedelta(days=1)
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        d = fc[['team_id', 'product_id', 'categ_id', 'mu_week', 'regimen_eff']].copy()
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']].rename(
            columns={'qty_sold': 'real_qty'})
        d = d.merge(real, on=['team_id', 'product_id'], how='left')
        d['real_qty'] = d['real_qty'].fillna(0.0)
        d['month'] = target.strftime('%Y-%m')
        d['ae'] = (d['mu_week'] - d['real_qty']).abs()
        d['err'] = d['real_qty'] - d['mu_week']
        parts.append(d)
    det = pd.concat(parts, ignore_index=True)

    def wb(g):
        g = g.copy()
        g['WAPE'] = (g['ae'] / g['real'].clip(lower=1e-9) * 100).round(1)
        g['BIAS'] = (g['err'] / g['real'].clip(lower=1e-9) * 100).round(1)
        return g

    print("=" * 70)
    print("POR MES (todo el universo pronosticado)")
    print("=" * 70)
    gm = det.groupby('month').agg(real=('real_qty', 'sum'), ae=('ae', 'sum'), err=('err', 'sum')).reset_index()
    print(wb(gm)[['month', 'real', 'WAPE', 'BIAS']].to_string(index=False))

    print("\n" + "=" * 70)
    print("POR CATEGORIA - top 25 por error absoluto")
    print("=" * 70)
    gc = det.groupby('categ_id').agg(real=('real_qty', 'sum'), ae=('ae', 'sum'), err=('err', 'sum')).reset_index()
    gc = wb(gc)
    gc['name'] = gc['categ_id'].map(cat_map).fillna(gc['categ_id'].astype(str)).str[:48]
    gc = gc.sort_values('ae', ascending=False).head(25)
    print(gc[['name', 'real', 'WAPE', 'BIAS', 'ae']].to_string(index=False))

    print("\n" + "=" * 70)
    print("CATEGORIAS MAS SUB-FORECASTEADAS (BIAS>0, vol real>=2000)")
    print("=" * 70)
    gc2 = det.groupby('categ_id').agg(real=('real_qty', 'sum'), ae=('ae', 'sum'), err=('err', 'sum')).reset_index()
    gc2 = wb(gc2)
    gc2['name'] = gc2['categ_id'].map(cat_map).fillna(gc2['categ_id'].astype(str)).str[:48]
    gc2 = gc2[gc2['real'] >= 2000].sort_values('BIAS', ascending=False).head(15)
    print(gc2[['name', 'real', 'WAPE', 'BIAS']].to_string(index=False))

    det.to_parquet(RESULTS / "exp_por_cat_mes.parquet", index=False)
    print("\n-> resultados/exp_por_cat_mes.parquet")


if __name__ == "__main__":
    main()
