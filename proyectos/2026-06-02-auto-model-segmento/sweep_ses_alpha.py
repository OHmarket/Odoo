"""
Barrido de alfa en SES — busca el mejor alfa para el segmento donde SES es el
campeon (smooth/erratic) y global. Walk-forward shift(1), sin San Jose.
"""
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
MIN_HIST = 6
MIN_ACTIVE, ADI_TH, CV2_TH = 4, 1.32, 0.49
ALPHAS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T

def classify(series):
    vals = series.values; active = int((vals > 0).sum())
    if active < MIN_ACTIVE: return 'no_signal'
    adi = len(vals) / active; pos = vals[vals > 0]; mu = pos.mean()
    cv2 = (pos.var() / (mu*mu)) if mu > 0 else 0.0
    if adi >= ADI_TH: return 'lumpy' if cv2 >= CV2_TH else 'intermittent'
    return 'erratic' if cv2 >= CV2_TH else 'smooth'
stype = real_wide.fillna(0.0).apply(classify, axis=1).rename('series_type')

def ses(a): return Wt.ewm(alpha=a, adjust=False).mean().shift(1)

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for a in ALPHAS:
    s = ses(a).stack().rename('a%.1f' % a).reset_index(); s.columns = ['semana', 'combo', 'a%.1f' % a]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base = base.merge(stype, left_on='combo', right_index=True, how='left')
base['series_type'] = base['series_type'].fillna('no_signal')

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s

def sweep(g, titulo):
    print('\n=== %s (real %.0f) ===' % (titulo, g.real.sum()))
    print('%-6s %7s %8s' % ('alfa', 'WAPE', 'BIAS'))
    best = (None, 1e9)
    for a in ALPHAS:
        w, b = wb(g.real, g['a%.1f' % a])
        star = ' *' if w < best[1] else ''
        if w < best[1]: best = (a, w)
        print('%-6.1f %6.1f%% %+7.1f%%%s' % (a, w, b, star))
    print('  -> mejor WAPE: alfa=%.1f' % best[0])

sweep(base, 'GLOBAL (todas las series)')
sweep(base[base.series_type == 'smooth'], 'SMOOTH (donde SES es campeon)')
sweep(base[base.series_type == 'erratic'], 'ERRATIC')
sweep(base[base.series_type.isin(['smooth', 'erratic'])], 'SMOOTH+ERRATIC (reactivo en BASE-2)')
