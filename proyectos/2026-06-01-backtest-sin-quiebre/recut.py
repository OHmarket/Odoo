"""
Re-corte del snapshot backtest excluyendo SKU x sala x semana con quiebre.

Hipotesis (Marco, 2026-06-01): el quiebre censura real_qty hacia abajo y produce
sobre-forecast falso (BIAS +). Excluir quiebres debe bajar BIAS y WAPE.

Cruce: x_name del backtest = 'hm_si | <semana> | T<team_id> | P<product_id>'.
T y P son IDs reales de Odoo (crm.team / product.product), iguales a los m2o de
x_stock_balance_daily. Join directo por id, no por texto.

Exclusion: una semana del backtest (week_start..+6) se descarta para ese par
(product, team) si hubo stockout cualquier dia de esa ventana.
"""
import json, re, datetime as dt
import pandas as pd

BASE = 'proyectos/2026-06-01-backtest-sin-quiebre'
CORE = ['hm_si_core', 'hm_si_core_a_low_mu', 'hm_si_core_az', 'fair_share_canon']
NW = 3

df = pd.read_csv('OH Forecast Backtest (x_forecast_backtest) 2026-06-01.csv')
d = df[df.forecast_model_code.isin(CORE)].copy()
d = d[~d.team_id.str.contains('San Jos', case=False, na=False)]

# parsear ids reales desde x_name (columna Descripción)
pat = re.compile(r'\|\s*T(\d+)\s*\|\s*P(\d+)')
m = d['Descripción'].str.extract(pat)
d['team_oid'] = pd.to_numeric(m[0], errors='coerce')
d['prod_oid'] = pd.to_numeric(m[1], errors='coerce')
assert d[['team_oid', 'prod_oid']].isna().sum().sum() == 0, 'x_name no parseo limpio'

# set de exclusion: (prod, team, week_start) con quiebre en la ventana de 7 dias
weeks = [dt.date.fromisoformat(w) for w in sorted(d.target_week_start.unique())]
so = json.load(open(f'{BASE}/resultados/stockout.json'))
excl = set()
for r in so:
    dd = dt.date.fromisoformat(r['d'])
    for w in weeks:
        if w <= dd <= w + dt.timedelta(days=6):
            excl.add((r['p'], r['t'], w.isoformat()))
            break

d['key'] = list(zip(d.prod_oid.astype(int), d.team_oid.astype(int), d.target_week_start))
d['quiebre'] = d['key'].isin(excl)

def wape(g):
    return 100 * g.abs_error_qty.sum() / g.real_qty.sum() if g.real_qty.sum() > 0 else float('nan')
def bias(g):
    return 100 * (g.forecast_qty.sum() - g.real_qty.sum()) / g.real_qty.sum() if g.real_qty.sum() > 0 else float('nan')

def report(g, label):
    print(f'\n=== {label} === (filas {len(g)})')
    print(f'GLOBAL  WAPE {wape(g):.1f}  BIAS {bias(g):+.1f}  real {int(g.real_qty.sum()):,}  fcst {int(g.forecast_qty.sum()):,}')
    for r in ['REG-1', 'REG-2', 'REG-4', 'REG-7', 'REG-8']:
        gg = g[g.regimen == r]
        if gg.real_qty.sum() == 0:
            continue
        real = gg.real_qty.sum(); upd = real / (NW * 7)
        sa = gg[gg.real_qty > 0].prod_oid.nunique()
        w = wape(gg)
        print(f'  {r} | WAPE {w:5.1f} | BIAS {bias(gg):+6.1f} | upd {upd:6.0f} | SKUsAct {sa:4d} | u/sku {upd/sa:4.1f} | errReal {w/100*upd:5.0f}')

report(d, 'CON quiebre (foto actual)')
report(d[~d.quiebre], 'SIN quiebre (filtrado)')

print(f'\nFilas marcadas quiebre: {d.quiebre.sum()} de {len(d)} ({100*d.quiebre.mean():.1f}%)')
print(f'Real censurado removido: {int(d[d.quiebre].real_qty.sum()):,} unid')
print(f'Forecast removido:       {int(d[d.quiebre].forecast_qty.sum()):,} unid')
