"""
Para cada regimen que usa SES (REG-1/2/3/4/sin), barre alfa 0.4..0.8 y muestra
WAPE/BIAS. Pregunta: SES(0.6) unico es casi optimo, o conviene 0.7 en alguno?
Walk-forward shift(1), sin San Jose.
"""
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
MIN_HIST = 6
ALPHAS = [0.4, 0.5, 0.6, 0.7, 0.8]
SES_REG = ['REG-1', 'REG-2', 'REG-3', 'REG-4', 'sin_regimen']

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T
def ses(a): return Wt.ewm(alpha=a, adjust=False).mean().shift(1)

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
reg_by_combo = m.groupby('combo').regimen.agg(mode_or_nan)

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for a in ALPHAS:
    s = ses(a).stack().rename('a%.1f' % a).reset_index(); s.columns = ['semana', 'combo', 'a%.1f' % a]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base['regimen'] = base['combo'].map(reg_by_combo).fillna('sin_regimen')

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s

print('=== alfa optimo por regimen (WAPE / BIAS) ===')
hdr = 'regimen      real     ' + '  '.join('a=%.1f' % a for a in ALPHAS)
print(hdr)
for rg in SES_REG:
    g = base[base.regimen == rg]
    if g.real.sum() == 0: continue
    cells, best = [], (None, 1e9)
    for a in ALPHAS:
        w, b = wb(g.real, g['a%.1f' % a]); cells.append((a, w, b))
        if w < best[1]: best = (a, w)
    line = '%-11s %8.0f  ' % (rg, g.real.sum())
    line += '  '.join(('%5.1f%s' % (w, '*' if a == best[0] else ' ')) for a, w, b in cells)
    print(line + '   -> opt a=%.1f' % best[0])

# diferencia practica: SES(0.6) unico vs alfa-optimo por regimen, en el bloque SES
g = base[base.regimen.isin(SES_REG)].copy()
w06, b06 = wb(g.real, g['a0.6'])
# alfa optimo por regimen (precomputado una vez)
opt_a = {}
for rg in SES_REG:
    gg = base[base.regimen == rg]
    if gg.real.sum() == 0: continue
    opt_a[rg] = min(ALPHAS, key=lambda a: wb(gg.real, gg['a%.1f' % a])[0])
fc_opt = pd.Series(np.nan, index=g.index)
for rg, a in opt_a.items():
    mask = g.regimen == rg
    fc_opt[mask] = g.loc[mask, 'a%.1f' % a]
wopt, bopt = wb(g.real, fc_opt)
print('\n=== bloque SES (REG-1/2/3/4/sin, real %.0f) ===' % g.real.sum())
print('  SES(0.6) unico        : WAPE %.2f%%  BIAS %+.1f%%' % (w06, b06))
print('  alfa-optimo x regimen : WAPE %.2f%%  BIAS %+.1f%%   (gana %.2f pp)' % (wopt, bopt, w06 - wopt))
