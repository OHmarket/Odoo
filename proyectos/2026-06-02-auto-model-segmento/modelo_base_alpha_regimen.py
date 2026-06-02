"""
MODELO BASE con alfa SES por regimen (no unico). Compara contra SES(0.6) unico.
  REG-0  -> HalfNaive
  REG-1  -> SES(0.5)   REG-2 -> SES(0.6)   REG-3 -> SES(0.4)   REG-4 -> SES(0.7)
  sin    -> SES(0.7)
  REG-5/6/7/8 -> Mediana(4)
Walk-forward shift(1), sin San Jose.
"""
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
MIN_HIST = 6

# alfa optimo por regimen (del sweep). REG-5/6/7/8 usan Mediana, no SES.
ALPHA_REG = {'REG-1': 0.5, 'REG-2': 0.6, 'REG-3': 0.4, 'REG-4': 0.7, 'sin_regimen': 0.7}
MED_REG = {'REG-5', 'REG-6', 'REG-7', 'REG-8'}

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T

def ses(a):    return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
ALPHAS = sorted(set(ALPHA_REG.values()) | {0.6})
SESC = {a: ses(a) for a in ALPHAS}
MED4 = median(4); HALF = Wt.shift(1) * 0.5; SMA4 = Wt.rolling(4, min_periods=4).mean().shift(1)

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
reg_by_combo = m.groupby('combo').regimen.agg(mode_or_nan)

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
cols = {'MED4': MED4, 'HALF': HALF, 'SMA4': SMA4}
for a in ALPHAS: cols['SES%.1f' % a] = SESC[a]
for nm, fw in cols.items():
    s = fw.stack().rename(nm).reset_index(); s.columns = ['semana', 'combo', nm]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base['regimen'] = base['combo'].map(reg_by_combo).fillna('sin_regimen')

def col_unico(rg):    # SES(0.6) unico
    if rg == 'REG-0': return 'HALF'
    if rg in MED_REG: return 'MED4'
    return 'SES0.6'
def col_alpha(rg):    # alfa por regimen
    if rg == 'REG-0': return 'HALF'
    if rg in MED_REG: return 'MED4'
    return 'SES%.1f' % ALPHA_REG.get(rg, 0.6)

ALPHA_3N = {'REG-1': 0.5, 'REG-4': 0.7, 'sin_regimen': 0.7}   # resto SES -> 0.6
def col_3n(rg):
    if rg == 'REG-0': return 'HALF'
    if rg in MED_REG: return 'MED4'
    return 'SES%.1f' % ALPHA_3N.get(rg, 0.6)

base['BASE_u'] = base.apply(lambda r: r[col_unico(r['regimen'])], axis=1)
base['BASE_a'] = base.apply(lambda r: r[col_alpha(r['regimen'])], axis=1)
base['BASE_3'] = base.apply(lambda r: r[col_3n(r['regimen'])], axis=1)

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s

w4, b4 = wb(base.real, base['SMA4'])
wu, bu = wb(base.real, base['BASE_u'])
wa, ba = wb(base.real, base['BASE_a'])
w3, b3 = wb(base.real, base['BASE_3'])
print('=== MODELO BASE: 0.6 unico vs 3 niveles vs alfa x regimen (%d obs) ===' % len(base))
print('  SMA(4) plano        : WAPE %.2f%%  BIAS %+.1f%%' % (w4, b4))
print('  BASE SES(0.6) unico : WAPE %.2f%%  BIAS %+.1f%%   FVA %+.2f%%' % (wu, bu, 100*(w4-wu)/w4))
print('  BASE 3 niveles      : WAPE %.2f%%  BIAS %+.1f%%   FVA %+.2f%%' % (w3, b3, 100*(w4-w3)/w4))
print('  BASE alfa x regimen : WAPE %.2f%%  BIAS %+.1f%%   FVA %+.2f%%' % (wa, ba, 100*(w4-wa)/w4))

print('\n=== por regimen (alfa asignado) ===')
print('%-12s %-12s %9s %7s %8s' % ('regimen', 'modelo', 'real', 'WAPE', 'BIAS'))
for rg, g in base.groupby('regimen'):
    if g.real.sum() == 0: continue
    c = col_alpha(rg)
    lbl = {'HALF': 'HalfNaive', 'MED4': 'Mediana(4)'}.get(c, c.replace('SES', 'SES('))
    lbl = lbl + ')' if lbl.startswith('SES(') else lbl
    w, b = wb(g.real, g[c])
    print('%-12s %-12s %9.0f %6.1f%% %+7.1f%%' % (rg, lbl, g.real.sum(), w, b))
