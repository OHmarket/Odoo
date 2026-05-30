"""
Cuánto del 'error' del motor desaparece si filtramos quiebres en target_week
con proxy más agresivo vs solo demanda_norm vs sin filtro?

No re-corre el motor: usa el detalle del Test 2 si existe o re-construye sobre
la marcha desde pareto + pos.
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

TARGET_WEEKS = [date(2026, 3, 16) + timedelta(weeks=i) for i in range(10)]


def main():
    pos, _ = load_cache(CACHE)
    if pos['week_start'].dtype == object:
        pos = pos.copy()
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")[['categ_id_id', 'complete_name']]
    cats = cats.rename(columns={'categ_id_id': 'categ_id'})

    # Baseline 10 sem (re-corre — necesitamos detalle por categoria)
    print("Corriendo baseline 10 sem (para detalle por categoria)...")
    parts = []
    for target in TARGET_WEEKS:
        cutoff = target - timedelta(days=1)
        print(f"  cutoff {cutoff}")
        fc = run(cutoff_date=cutoff, config=DEFAULT_CONFIG, cache_dir=CACHE)
        real = pos[pos['week_start'] == target][['team_id', 'product_id', 'qty_sold']]
        m = fc[['team_id', 'product_id', 'categ_id', 'mu_week', 'abcxyz_eff']].merge(
            real, on=['team_id', 'product_id'], how='outer'
        ).fillna({'mu_week': 0.0, 'qty_sold': 0.0})
        m['target_week'] = target
        parts.append(m)
    df = pd.concat(parts, ignore_index=True)
    df = df.merge(cats, on='categ_id', how='left')
    df['categ_short'] = df['complete_name'].str.split(' / ').str[1].fillna('OTROS')

    # 3 niveles de filtro de quiebre EN TARGET WEEK:
    # 1. SIN filtro
    # 2. demanda_norm (avail<1.0)
    # 3. proxy agresivo: avg_prev_8w >= 1 y qty_target < 20%*avg (o <0.5)
    # 4. proxy MUY agresivo: avg_prev_8w >= 5 (SKU con venta real significativa)
    #    y qty_target < 20%*avg

    hist_from = TARGET_WEEKS[0] - timedelta(weeks=8)
    hist = pos[(pos['week_start'] >= hist_from) & (pos['week_start'] < TARGET_WEEKS[0])]
    avg = hist.groupby(['team_id', 'product_id'])['qty_sold'].mean().reset_index()
    avg.columns = ['team_id', 'product_id', 'avg_prev_8w']
    df = df.merge(avg, on=['team_id', 'product_id'], how='left')
    df['avg_prev_8w'] = df['avg_prev_8w'].fillna(0.0)

    df['proxy_quiebre_laxo'] = (df['avg_prev_8w'] >= 1.0) & \
                                 (df['qty_sold'] < df['avg_prev_8w'].apply(lambda x: max(0.2 * x, 0.5)))
    df['proxy_quiebre_estricto'] = (df['avg_prev_8w'] >= 5.0) & \
                                     (df['qty_sold'] < 0.2 * df['avg_prev_8w'])

    # demanda_norm
    dn = pd.read_parquet(CACHE / "demanda_norm.parquet")
    dn['week_start'] = pd.to_datetime(dn['x_studio_week_start']).dt.date
    dn = dn.rename(columns={'x_studio_avail': 'avail'})
    dn_10w = dn[dn['week_start'].isin(TARGET_WEEKS)][['team_id', 'product_id', 'week_start', 'avail']]
    df = df.merge(dn_10w.rename(columns={'week_start': 'target_week'}),
                   on=['team_id', 'product_id', 'target_week'], how='left')
    df['dn_censored'] = df['avail'].notna() & (df['avail'] < 1.0)

    def metrics(d):
        r = d['qty_sold'].sum()
        f = d['mu_week'].sum()
        ae = (d['mu_week'] - d['qty_sold']).abs().sum()
        err = (d['qty_sold'] - d['mu_week']).sum()
        return r, f, ae, ae/r*100 if r > 0 else 0, err/r*100 if r > 0 else 0

    # 4 filtros para cada categoria foco
    focus_categs = ['Cigarros', 'Tabacos', 'Snack', 'Cervezas', 'Bebidas Gaseosas',
                     'Isotónicas y Energéticas', 'Vinos', 'Destilados', 'Cócteles y Licores']

    print("\n" + "=" * 130)
    print("Impacto del filtro de quiebre por categoria foco")
    print("=" * 130)
    print(f"\n{'Categoria':35s} | {'SIN FILTRO':<22s} | {'dn_censored':<22s} | {'proxy_LAXO':<22s} | {'proxy_ESTRICTO':<22s}")
    print(f"{'(WAPE/BIAS)':35s} | {' WAPE   BIAS  n':<22s} | {' WAPE   BIAS  n':<22s} | {' WAPE   BIAS  n':<22s} | {' WAPE   BIAS  n':<22s}")
    print("-" * 130)

    summary_rows = []
    for cs in focus_categs:
        # buscar categs que contengan el keyword
        d_cs = df[df['categ_short'].str.contains(cs, case=False, na=False)]
        if len(d_cs) == 0:
            continue
        d_dn = d_cs[~d_cs['dn_censored']]
        d_lax = d_cs[~d_cs['proxy_quiebre_laxo']]
        d_str = d_cs[~d_cs['proxy_quiebre_estricto']]
        r0, f0, ae0, w0, b0 = metrics(d_cs)
        r1, f1, ae1, w1, b1 = metrics(d_dn)
        r2, f2, ae2, w2, b2 = metrics(d_lax)
        r3, f3, ae3, w3, b3 = metrics(d_str)
        print(f"{cs[:35]:35s} | {w0:>5.1f} {b0:>+6.1f} {len(d_cs):>7,} | {w1:>5.1f} {b1:>+6.1f} {len(d_dn):>7,} | {w2:>5.1f} {b2:>+6.1f} {len(d_lax):>7,} | {w3:>5.1f} {b3:>+6.1f} {len(d_str):>7,}")
        summary_rows.append({
            'categ': cs, 'n_total': len(d_cs),
            'sin_filtro_WAPE': round(w0, 1), 'sin_filtro_BIAS': round(b0, 1),
            'dn_WAPE': round(w1, 1), 'dn_BIAS': round(b1, 1),
            'proxy_lax_WAPE': round(w2, 1), 'proxy_lax_BIAS': round(b2, 1),
            'proxy_str_WAPE': round(w3, 1), 'proxy_str_BIAS': round(b3, 1),
            'n_excluido_dn': len(d_cs) - len(d_dn),
            'n_excluido_lax': len(d_cs) - len(d_lax),
            'n_excluido_str': len(d_cs) - len(d_str),
        })

    # TOTAL (todas categorias)
    d_dn = df[~df['dn_censored']]
    d_lax = df[~df['proxy_quiebre_laxo']]
    d_str = df[~df['proxy_quiebre_estricto']]
    r0, f0, ae0, w0, b0 = metrics(df)
    r1, f1, ae1, w1, b1 = metrics(d_dn)
    r2, f2, ae2, w2, b2 = metrics(d_lax)
    r3, f3, ae3, w3, b3 = metrics(d_str)
    print("-" * 130)
    print(f"{'TOTAL (todas)':35s} | {w0:>5.1f} {b0:>+6.1f} {len(df):>7,} | {w1:>5.1f} {b1:>+6.1f} {len(d_dn):>7,} | {w2:>5.1f} {b2:>+6.1f} {len(d_lax):>7,} | {w3:>5.1f} {b3:>+6.1f} {len(d_str):>7,}")

    # Conteo por categoria de filas excluidas por cada filtro
    print("\n" + "=" * 100)
    print("Filas excluidas por cada filtro de quiebre (target_week)")
    print("=" * 100)
    for r in summary_rows:
        pct_dn = r['n_excluido_dn'] / r['n_total'] * 100
        pct_lax = r['n_excluido_lax'] / r['n_total'] * 100
        pct_str = r['n_excluido_str'] / r['n_total'] * 100
        print(f"  {r['categ'][:35]:35s}: n={r['n_total']:>7,}  dn={r['n_excluido_dn']:>5,} ({pct_dn:>4.1f}%)  lax={r['n_excluido_lax']:>5,} ({pct_lax:>4.1f}%)  str={r['n_excluido_str']:>5,} ({pct_str:>4.1f}%)")

    pd.DataFrame(summary_rows).to_parquet(RESULTS / "impact_quiebre_filter.parquet", index=False)
    print(f"\n -> impact_quiebre_filter.parquet")


if __name__ == "__main__":
    main()
