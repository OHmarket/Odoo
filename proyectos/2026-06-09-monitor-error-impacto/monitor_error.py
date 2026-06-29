"""
Monitor de error de forecast por impacto-$ (Fase 1, READ-ONLY).

Rankea el error del backtest (x_forecast_backtest) por PLATA EN RIESGO, no por WAPE,
y clasifica la CAUSA de cada fila de alto impacto para separar lo accionable del ruido.

Modelo canónico: Forecast Value Added (Gilliland / SAP IBP) + pinball/quantile loss
asimétrica ponderada por valor del ítem. Ver diseno.md.

No escribe nada en Odoo ni en el pipeline. Solo lee y emite CSVs en resultados/.

Uso:
    python monitor_error.py            # ultimas 4 semanas
    python monitor_error.py --weeks 3
    python monitor_error.py --top 80   # filas en el ranking detallado
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).parent / 'resultados'
OUT.mkdir(exist_ok=True)

# --- parametros de impacto (PROXY documentado en diseno.md) ---
K_UNDER = 2.0   # sub-forecast (quiebre/venta perdida) cuesta ~2x el sobrestock. PROXY.
K_OVER = 1.0

# --- salas a excluir de la medicion limpia (memoria forecast_noise_feedback) ---
EXCLUDE_TEAM_IDS = {11}  # San Jose

# nombre real de cada crm.team (todos se llaman "Sales"; el real vive en pos.config)
TEAM_NAMES = {
    5: 'Panguipulli 790', 6: 'Los Lagos', 7: 'Futrono', 8: 'Panguipulli 645',
    9: 'Panguipulli 763', 10: 'Lautaro', 11: 'San Jose', 12: 'Paillaco',
    13: 'Mehuin Express', 16: 'Conaripe', 17: 'Nueva Imperial', 18: 'Malalhue',
}

TAIL_TYPES = {'lumpy', 'intermittent', 'no_signal'}


def m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) else (None if v in (False, None) else v)


def m2o_name(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else ''


def iso_yw(d) -> tuple:
    """(iso_year, iso_week) desde 'YYYY-MM-DD' o date."""
    if isinstance(d, str):
        d = datetime.strptime(d[:10], '%Y-%m-%d').date()
    c = d.isocalendar()
    return (c[0], c[1])


def pull_backtest(o: OdooReader, weeks: list[str]) -> pd.DataFrame:
    fields = ['x_studio_product_id', 'x_studio_team_id', 'x_studio_target_week_start',
              'x_studio_real_qty', 'x_studio_forecast_qty', 'x_studio_error_qty',
              'x_studio_abs_error_qty', 'x_studio_series_type', 'x_studio_regimen',
              'x_studio_abcxyz', 'x_studio_importancia', 'x_studio_categ_id',
              'x_studio_forecast_model_code']
    rows = []
    for wk in weeks:
        r = o.search_read('x_forecast_backtest',
                          [('x_studio_target_week_start', '=', wk)], fields=fields)
        print(f'  backtest {wk}: {len(r)} filas')
        rows.extend(r)
    df = pd.DataFrame(rows)
    df['product_id'] = df['x_studio_product_id'].map(m2o_id)
    df['product_name'] = df['x_studio_product_id'].map(m2o_name)
    df['team_id'] = df['x_studio_team_id'].map(m2o_id)
    df['week'] = df['x_studio_target_week_start']
    df['real'] = pd.to_numeric(df['x_studio_real_qty'], errors='coerce').fillna(0.0)
    df['fcst'] = pd.to_numeric(df['x_studio_forecast_qty'], errors='coerce').fillna(0.0)
    df['series_type'] = df['x_studio_series_type'].astype(str)
    df['regimen'] = df['x_studio_regimen'].astype(str)
    df['abcxyz'] = df['x_studio_abcxyz'].astype(str)
    df['categ'] = df['x_studio_categ_id'].map(m2o_name)
    df['model_code'] = df['x_studio_forecast_model_code'].astype(str)
    df['yw'] = df['week'].map(iso_yw)
    return df


def pull_list_price(o: OdooReader, pids: list[int]) -> dict:
    out = {}
    for i in range(0, len(pids), 300):
        chunk = pids[i:i + 300]
        recs = o.search_read('product.product', [('id', 'in', chunk)],
                             fields=['id', 'list_price'])
        for r in recs:
            out[r['id']] = float(r.get('list_price') or 0.0)
    return out


def _add_event(ev: set, pid, ps):
    """Marca la semana del evento y la siguiente: un cambio de precio/promo en la
    semana E mueve la demanda en E y arrastra a E+1 (y a veces E-1 por anticipacion)."""
    if isinstance(ps, str):
        ps = datetime.strptime(ps[:10], '%Y-%m-%d').date()
    for off in (-7, 0, 7):
        ev.add((pid, iso_yw(ps + timedelta(days=off))))


def pull_event_weeks(o: OdooReader, d0: date, d1: date) -> set:
    """set de (product_id, (iso_year, iso_week)) con evento de precio o promo (ventana +-1 sem)."""
    ev = set()
    pce = o.search_read('x_price_change_event',
                        [('x_studio_is_real_change', '=', True),
                         ('x_studio_period_start', '>=', (d0 - timedelta(days=7)).strftime('%Y-%m-%d')),
                         ('x_studio_period_start', '<=', d1.strftime('%Y-%m-%d'))],
                        fields=['x_studio_product_id', 'x_studio_period_start'])
    for r in pce:
        pid = m2o_id(r.get('x_studio_product_id'))
        ps = r.get('x_studio_period_start')
        if pid and ps:
            _add_event(ev, pid, ps)
    lpe = o.search_read('x_loyalty_promo_event',
                        [('x_studio_period_start', '>=', (d0 - timedelta(days=7)).strftime('%Y-%m-%d')),
                         ('x_studio_period_start', '<=', d1.strftime('%Y-%m-%d'))],
                        fields=['x_studio_product_variant_id', 'x_studio_period_start'])
    for r in lpe:
        pid = m2o_id(r.get('x_studio_product_variant_id'))
        ps = r.get('x_studio_period_start')
        if pid and ps:
            _add_event(ev, pid, ps)
    print(f'  eventos (precio+promo, ventana +-1 sem): {len(ev)} pares (producto, semana)')
    return ev


def pull_stockout_weeks(o: OdooReader, d0: date, d1: date) -> set:
    """set de (product_id, team_id, (iso_year, iso_week)) con quiebre en la semana."""
    so = set()
    recs = o.search_read('x_stock_balance_daily',
                         ['&', ('x_studio_date', '>=', d0.strftime('%Y-%m-%d')),
                          ('x_studio_date', '<=', d1.strftime('%Y-%m-%d')),
                          '|', ('x_studio_stockout', '=', True),
                          ('x_studio_stockout_partial', '=', True)],
                         fields=['x_studio_product_id', 'x_studio_team_id', 'x_studio_date'])
    for r in recs:
        pid = m2o_id(r.get('x_studio_product_id'))
        tid = m2o_id(r.get('x_studio_team_id'))
        dd = r.get('x_studio_date')
        if pid and tid and dd:
            so.add((pid, tid, iso_yw(dd)))
    print(f'  quiebres: {len(so)} (producto, sala, semana)')
    return so


def classify(row, event_set, stockout_set) -> str:
    """Orden de prioridad (la primera que aplica gana). Ver diseno.md.
    quiebre  -> real censurado, artefacto (excluir)
    evento   -> demanda movida por precio/promo conocido (UNICO bucket corregible)
    cola     -> serie de cola: un cero o un pico es ruido esperado, no surtido
    fantasma -> serie continua que NO vendio (real=0, fcst>0) -> hueco de surtido
    smooth_real -> serie continua que vendio, sin evento ni quiebre -> residual puro"""
    yw = row['yw']
    if (row['product_id'], row['team_id'], yw) in stockout_set:
        return 'quiebre'
    if (row['product_id'], yw) in event_set:
        return 'evento'
    if row['series_type'] in TAIL_TYPES:
        return 'cola_intermitente'
    if row['real'] <= 0 and row['fcst'] > 0:
        return 'fantasma'
    return 'smooth_real'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--weeks', type=int, default=4)
    ap.add_argument('--top', type=int, default=100)
    args = ap.parse_args()

    o = OdooReader()
    print(f'Conectado: {o}')

    # semanas disponibles -> ultimas N (el lunes real viene en __range.from)
    wk_recs = o.execute('x_forecast_backtest', 'read_group', [],
                        ['x_studio_target_week_start'], ['x_studio_target_week_start:week'], lazy=False)
    weeks_all = sorted({r['__range']['x_studio_target_week_start:week']['from']
                        for r in wk_recs if r.get('__range')})
    weeks = weeks_all[-args.weeks:]
    print(f'Semanas analizadas ({len(weeks)}): {weeks}')

    df = pull_backtest(o, weeks)
    print(f'Total filas: {len(df)}')

    # list_price
    pids = sorted({int(p) for p in df['product_id'].dropna().unique()})
    print(f'Productos unicos: {len(pids)} -> pull list_price')
    lp = pull_list_price(o, pids)
    df['list_price'] = df['product_id'].map(lambda p: lp.get(int(p), 0.0) if pd.notna(p) else 0.0)

    # rango de fechas para cruces
    wdates = [datetime.strptime(w, '%Y-%m-%d').date() for w in weeks]
    d0 = min(wdates) - timedelta(days=2)
    d1 = max(wdates) + timedelta(days=8)
    event_set = pull_event_weeks(o, d0, d1)
    stockout_set = pull_stockout_weeks(o, d0, d1)

    # excluir salas sucias
    n_before = len(df)
    df = df[~df['team_id'].isin(EXCLUDE_TEAM_IDS)].copy()
    print(f'Excluidas {n_before - len(df)} filas de salas {EXCLUDE_TEAM_IDS}')

    # metrica de impacto
    under = (df['real'] - df['fcst']).clip(lower=0)
    over = (df['fcst'] - df['real']).clip(lower=0)
    df['pinball_u'] = K_UNDER * under + K_OVER * over
    df['impacto'] = df['pinball_u'] * df['list_price']

    # causa
    df['causa'] = df.apply(lambda r: classify(r, event_set, stockout_set), axis=1)
    df['team'] = df['team_id'].map(lambda t: TEAM_NAMES.get(int(t), str(t)) if pd.notna(t) else '')

    # ---- resumen por causa ----
    tot = df['impacto'].sum()
    res = (df.groupby('causa')
             .agg(filas=('impacto', 'size'),
                  impacto=('impacto', 'sum'),
                  abs_error_u=('x_studio_abs_error_qty', lambda s: pd.to_numeric(s, errors='coerce').sum()),
                  real_u=('real', 'sum'),
                  fcst_u=('fcst', 'sum'))
             .reset_index())
    res['impacto_pct'] = (res['impacto'] / tot * 100).round(1)
    res = res.sort_values('impacto', ascending=False)
    res['impacto'] = res['impacto'].round(0)
    print('\n=== IMPACTO-$ POR CAUSA (pinball K_UNDER=2 x list_price c/IVA) ===')
    print(res.to_string(index=False))
    print(f'\nImpacto-$ total (proxy): {tot:,.0f}')

    # bucket accionable: solo smooth_real (+ evento es candidato a Fase 2)
    accionable = res[res['causa'] == 'smooth_real']['impacto_pct'].sum()
    evento_pct = res[res['causa'] == 'evento']['impacto_pct'].sum()
    print(f'smooth_real (accionable puro): {accionable:.1f}% del impacto')
    print(f'evento (candidato Fase 2 demand sensing): {evento_pct:.1f}% del impacto')

    # --- diagnostico smooth_real: sesgo corregible vs varianza irreducible ---
    sr = df[df['causa'] == 'smooth_real']
    real_s, err_s = sr['real'].sum(), (sr['real'] - sr['fcst']).sum()
    over_imp = (sr.loc[sr['fcst'] > sr['real'], 'impacto']).sum()
    under_imp = (sr.loc[sr['real'] > sr['fcst'], 'impacto']).sum()
    sku_sr = sr.groupby('product_id')['impacto'].sum().sort_values(ascending=False)
    print('\n--- smooth_real: anatomia del error ---')
    print(f'  BIAS = {err_s / real_s * 100:+.1f}%  (>0 sub-forecast). Cerca de 0 => varianza, no sesgo')
    print(f'  impacto over-forecast: {over_imp / sr["impacto"].sum() * 100:.0f}%  | under-forecast: {under_imp / sr["impacto"].sum() * 100:.0f}%')
    print(f'  concentracion: top10 SKU = {sku_sr.head(10).sum() / sku_sr.sum() * 100:.0f}%  top50 = {sku_sr.head(50).sum() / sku_sr.sum() * 100:.0f}%  (de {len(sku_sr)} SKU)')

    # ---- ranking detallado por SKU-sala-semana ----
    cols = ['week', 'team', 'product_id', 'product_name', 'categ', 'abcxyz', 'series_type',
            'regimen', 'causa', 'real', 'fcst', 'list_price', 'pinball_u', 'impacto']
    rank = df.sort_values('impacto', ascending=False)[cols].head(args.top).copy()
    rank['impacto'] = rank['impacto'].round(0)
    rank['fcst'] = rank['fcst'].round(2)

    # ---- ranking por SKU agregado (suma impacto sobre salas/semanas) ----
    sku = (df.groupby(['product_id', 'product_name', 'categ'])
             .agg(impacto=('impacto', 'sum'), filas=('impacto', 'size'),
                  causa_top=('causa', lambda s: s.value_counts().index[0]))
             .reset_index().sort_values('impacto', ascending=False).head(args.top))
    sku['impacto'] = sku['impacto'].round(0)

    # ---- salida Excel-CL ----
    def to_cl(d, name):
        p = OUT / name
        d.to_csv(p, sep=';', decimal=',', encoding='utf-8-sig', index=False)
        print(f'  -> {p}')

    print('\nEscribiendo resultados:')
    to_cl(res, 'resumen_por_causa.csv')
    to_cl(rank, 'ranking_impacto_fila.csv')
    to_cl(sku, 'ranking_impacto_sku.csv')

    print('\nTop 15 SKU por impacto-$:')
    print(sku.head(15)[['product_name', 'categ', 'impacto', 'causa_top']].to_string(index=False))


if __name__ == '__main__':
    main()
