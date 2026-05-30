"""
Snapshot one-shot de Odoo a parquet para el harness local HM-SI.

Tablas:
  - catalog: product.product + product.template + product.category + crm.team + pos.config
  - abcxyz: x_calculo_abc_xyz (clasificacion global)
  - price_corr: x_price_coreccion
  - demanda_norm: x_demanda_normalizada (overlay opcional)
  - pos_weekly: pos.order.line agregado a semana x team x producto (via read_group)

Idempotente: re-correr para refrescar. Cada tabla escribe parquet + log row count.

CLI:
  python snapshot_cache.py [--only catalog|abcxyz|price|demanda|pos|all]
"""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CACHE_DIR = Path(__file__).parent / "cache"
META_PATH = CACHE_DIR / "meta.json"

POS_HISTORY_MONTHS = 36  # SI usa hasta 36m, motor base usa 24m


# ----------------------------- helpers -----------------------------

def _m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) and v else None


def _m2o_name(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else None


def _save(df: pd.DataFrame, name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{name}.parquet"
    # Odoo manda False para chars/dates vacios. Normalizar a None para que
    # pyarrow infiera tipo correcto (no mezcla bool+str).
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].where(df[col].apply(lambda v: not isinstance(v, bool) or v is True), None)
            # Si tras el cleanup queda solo False/None lo dejamos como bool nullable
    df.to_parquet(p, index=False)
    print(f"  -> {p.name}  {len(df):,} filas  {p.stat().st_size/1024:.0f} KB")
    return p


def _meta_update(d: dict):
    cur = {}
    if META_PATH.exists():
        cur = json.loads(META_PATH.read_text(encoding="utf-8"))
    cur.update(d)
    META_PATH.write_text(json.dumps(cur, indent=2, default=str), encoding="utf-8")


# ----------------------------- snapshots -----------------------------

def snap_catalog(odoo: OdooReader):
    print("\n[catalog] product + categ + team + pos.config")

    prods = odoo.search_read(
        'product.product',
        domain=[],
        fields=['id', 'default_code', 'name', 'product_tmpl_id', 'active'],
    )
    df_p = pd.DataFrame(prods)
    df_p['product_tmpl_id_id'] = df_p['product_tmpl_id'].apply(_m2o_id)
    df_p = df_p.drop(columns=['product_tmpl_id'])

    tmpl_ids = sorted(df_p['product_tmpl_id_id'].dropna().unique().tolist())
    tmpls = odoo.search_read(
        'product.template',
        domain=[('id', 'in', tmpl_ids)],
        fields=['id', 'categ_id', 'sale_ok', 'type'],
    )
    df_t = pd.DataFrame(tmpls)
    df_t['categ_id_id'] = df_t['categ_id'].apply(_m2o_id)
    df_t['categ_id_name'] = df_t['categ_id'].apply(_m2o_name)
    df_t = df_t.drop(columns=['categ_id']).rename(columns={'id': 'product_tmpl_id_id'})

    cats = odoo.search_read(
        'product.category', [],
        fields=['id', 'name', 'complete_name', 'parent_id'],
    )
    df_c = pd.DataFrame(cats)
    df_c['parent_id_id'] = df_c['parent_id'].apply(_m2o_id)
    df_c = df_c.drop(columns=['parent_id']).rename(columns={'id': 'categ_id_id'})

    teams = odoo.search_read(
        'crm.team', [],
        fields=['id', 'name', 'active'],
    )
    df_team = pd.DataFrame(teams).rename(columns={'id': 'team_id_id'})

    configs = odoo.search_read(
        'pos.config', [],
        fields=['id', 'name', 'crm_team_id', 'company_id'],
    )
    df_cfg = pd.DataFrame(configs)
    df_cfg['crm_team_id_id'] = df_cfg['crm_team_id'].apply(_m2o_id)
    df_cfg = df_cfg.drop(columns=['crm_team_id'])
    df_cfg['company_id_id'] = df_cfg['company_id'].apply(_m2o_id)
    df_cfg = df_cfg.drop(columns=['company_id']).rename(columns={'id': 'pos_config_id'})

    # Merge product + template + categ
    df_prod_full = df_p.merge(df_t, on='product_tmpl_id_id', how='left')
    df_prod_full = df_prod_full.merge(df_c[['categ_id_id', 'complete_name']], on='categ_id_id', how='left')
    df_prod_full = df_prod_full.rename(columns={'complete_name': 'categ_complete_name'})

    _save(df_prod_full, 'catalog_products')
    _save(df_c, 'catalog_categories')
    _save(df_team, 'catalog_teams')
    _save(df_cfg, 'catalog_pos_configs')

    _meta_update({
        'catalog': {
            'products': len(df_prod_full),
            'categories': len(df_c),
            'teams': len(df_team),
            'pos_configs': len(df_cfg),
            'refreshed_at': datetime.now().isoformat(),
        }
    })


def snap_abcxyz(odoo: OdooReader):
    print("\n[abcxyz] x_calculo_abc_xyz")
    fields = [
        'id',
        'x_studio_product_id',
        'x_studio_categ_id',
        'x_studio_abc',
        'x_studio_xyz',
        'x_studio_abcxyz',
        'x_studio_series_type',
        'x_studio_series_type_short',
        'x_studio_series_type_active',
        'x_studio_ciclo_de_vida',
        'x_studio_adi',
        'x_studio_cv2',
        'x_studio_n_weeks',
        'x_studio_age_weeks',
        'x_studio_trimestres_activos',
        'x_studio_zero_sales_24m',
        'x_studio_last_sale_week',
        'x_studio_weeks_since_last_sale',
        'x_studio_uni_ltimo_trimestre',
        'x_studio_uni_trimestre_ly',
        'x_studio_eliminar_sino',
        'x_studio_period_end',
        'x_studio_updated_on',
    ]
    rows = odoo.search_read('x_calculo_abc_xyz', [], fields=fields)
    df = pd.DataFrame(rows)
    df['product_id'] = df['x_studio_product_id'].apply(_m2o_id)
    df['categ_id'] = df['x_studio_categ_id'].apply(_m2o_id)
    df = df.drop(columns=['x_studio_product_id', 'x_studio_categ_id'])
    _save(df, 'abcxyz')
    _meta_update({'abcxyz': {'rows': len(df), 'refreshed_at': datetime.now().isoformat()}})


def snap_price_corr(odoo: OdooReader):
    print("\n[price_corr] x_price_coreccion")
    fields = [
        'id', 'x_studio_product_id', 'x_studio_team_id',
        'x_studio_target_week_start', 'x_studio_factor_corr',
        'x_studio_tipo_alerta', 'x_studio_razon', 'x_studio_var_pct',
        'x_studio_lift_qty', 'x_studio_indice_canibal',
        'x_studio_weeks_since_change', 'x_studio_active', 'x_studio_source',
        'x_studio_abcxyz', 'x_studio_sub_cat',
    ]
    rows = odoo.search_read('x_price_coreccion', [], fields=fields)
    df = pd.DataFrame(rows)
    df['product_id'] = df['x_studio_product_id'].apply(_m2o_id)
    df['team_id'] = df['x_studio_team_id'].apply(_m2o_id)
    df = df.drop(columns=['x_studio_product_id', 'x_studio_team_id'])
    _save(df, 'price_corr')
    _meta_update({'price_corr': {'rows': len(df), 'refreshed_at': datetime.now().isoformat()}})


def snap_demanda_norm(odoo: OdooReader):
    print("\n[demanda_norm] x_demanda_normalizada (62K filas)")
    fields = [
        'id', 'x_studio_product_id', 'x_studio_team_id', 'x_studio_week_start',
        'x_studio_qty_norm', 'x_studio_qty_obs', 'x_studio_factor',
        'x_studio_metodo', 'x_studio_avail',
    ]
    rows = odoo.search_read('x_demanda_normalizada', [], fields=fields)
    df = pd.DataFrame(rows)
    df['product_id'] = df['x_studio_product_id'].apply(_m2o_id)
    df['team_id'] = df['x_studio_team_id'].apply(_m2o_id)
    df = df.drop(columns=['x_studio_product_id', 'x_studio_team_id'])
    _save(df, 'demanda_norm')
    _meta_update({'demanda_norm': {'rows': len(df), 'refreshed_at': datetime.now().isoformat()}})


def _iso_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def snap_pos_weekly(odoo: OdooReader, months: int = POS_HISTORY_MONTHS,
                     team_limit: int | None = None, throttle: float = 0.0):
    """
    Pull pos.order.line agregado a (week, team, product) via read_group por
    (team, week) con groupby=[product_id]. Sin dotted paths.

    Volumen full (36m, 12 teams): ~1.1M filas. ~22 min sin throttle.
    """
    import time
    today = date.today()
    start_anchor = today - timedelta(days=months * 31)
    start = _iso_monday(start_anchor)
    end = _iso_monday(today)
    print(f"\n[pos_weekly] pos.order.line {start} -> {end}  ({months}m)")
    if throttle > 0:
        print(f"  Throttle: {throttle}s entre queries")

    teams = odoo.search_read('crm.team', [], fields=['id', 'name'])
    teams = [t for t in teams if t.get('id')]
    if team_limit:
        teams = teams[:team_limit]
        print(f"  Teams (limited): {len(teams)}")
    else:
        print(f"  Teams: {len(teams)}")

    # Build week list
    weeks = []
    w = start
    while w < end:
        weeks.append(w)
        w += timedelta(days=7)
    print(f"  Semanas: {len(weeks)}")

    all_rows = []
    t_global = time.time()
    total_q = len(teams) * len(weeks)
    done_q = 0
    for ti, t in enumerate(teams):
        team_id = t['id']
        team_name = t['name'] or f"team_{team_id}"
        t_team = time.time()
        team_rows = 0
        for w in weeks:
            wn = w + timedelta(days=7)
            try:
                grp = odoo.execute(
                    'pos.order.line', 'read_group',
                    [
                        ('order_id.crm_team_id', '=', team_id),
                        ('order_id.date_order', '>=', w.strftime('%Y-%m-%d')),
                        ('order_id.date_order', '<', wn.strftime('%Y-%m-%d')),
                        ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                    ],
                    ['qty:sum', 'price_subtotal:sum'],
                    ['product_id'],
                    lazy=False,
                )
            except Exception as e:
                print(f"  team {team_id} wk {w}: ERROR {e}")
                grp = []
            for g in grp:
                pid = _m2o_id(g.get('product_id'))
                if pid is None:
                    continue
                all_rows.append({
                    'team_id': team_id,
                    'product_id': pid,
                    'week_start': w,
                    'qty': float(g.get('qty', 0.0) or 0.0),
                    'revenue': float(g.get('price_subtotal', 0.0) or 0.0),
                })
                team_rows += 1
            done_q += 1
            if throttle > 0:
                time.sleep(throttle)
        elapsed_team = time.time() - t_team
        elapsed_global = time.time() - t_global
        eta = (elapsed_global / done_q) * (total_q - done_q)
        print(f"  [{ti+1:>2}/{len(teams)}] team {team_id} ({team_name[:20]:20s}): {team_rows:>6,} filas en {elapsed_team:.0f}s  | global {elapsed_global:.0f}s eta {eta:.0f}s")

    if not all_rows:
        print("  Sin filas")
        return

    df = pd.DataFrame(all_rows)
    print(f"\n  Total filas: {len(df):,}")
    print(f"  Productos distintos: {df['product_id'].nunique():,}")
    print(f"  Rango semanas: {df['week_start'].min()} -> {df['week_start'].max()}")
    print(f"  qty_sum total: {df['qty'].sum():,.0f}")
    _save(df, 'pos_weekly')
    _meta_update({'pos_weekly': {
        'rows': len(df),
        'products': int(df['product_id'].nunique()),
        'teams': int(df['team_id'].nunique()),
        'week_min': str(df['week_start'].min()),
        'week_max': str(df['week_start'].max()),
        'refreshed_at': datetime.now().isoformat(),
    }})


# ----------------------------- CLI -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='all',
                     choices=['all', 'catalog', 'abcxyz', 'price', 'demanda', 'pos'])
    ap.add_argument('--months', type=int, default=POS_HISTORY_MONTHS,
                     help='Meses POS hacia atras (default 36)')
    ap.add_argument('--teams', type=int, default=None,
                     help='Limitar a primeros N teams (smoke test)')
    ap.add_argument('--throttle', type=float, default=0.0,
                     help='Sleep entre queries POS (sec). Default 0.')
    args = ap.parse_args()

    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    if args.only in ('all', 'catalog'):
        snap_catalog(odoo)
    if args.only in ('all', 'abcxyz'):
        snap_abcxyz(odoo)
    if args.only in ('all', 'price'):
        snap_price_corr(odoo)
    if args.only in ('all', 'demanda'):
        snap_demanda_norm(odoo)
    if args.only in ('all', 'pos'):
        snap_pos_weekly(odoo, months=args.months,
                         team_limit=args.teams, throttle=args.throttle)

    print("\nDONE")


if __name__ == "__main__":
    main()
