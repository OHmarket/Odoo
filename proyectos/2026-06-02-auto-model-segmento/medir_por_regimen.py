"""
Medir y asignar el campeon POR REGIMEN (la dimension que produccion ya keyea via
Script 1 / x_calculo_abc_xyz). Incluye SES(0.6). Marca regimenes con poca data
(campeon poco confiable) y propone un mapa colapsado a 2 modelos.
Sin Naive, cap |BIAS|<=15%, walk-forward shift(1), sin San Jose.
"""
import os
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6
BIAS_CAP = 15.0
THIN_REAL = 3000   # umbral de volumen para marcar regimen con campeon poco confiable

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T; Yv = Wt.values; n_w, n_c = Yv.shape
def as_df(a): return pd.DataFrame(a, index=Wt.index, columns=Wt.columns)

def sma(k):    return Wt.rolling(k, min_periods=k).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def wma(k):
    w = np.arange(1, k + 1)
    return Wt.rolling(k, min_periods=k).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).shift(1)
def ses(a):  return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def croston(alpha, sba=False):
    F = np.full_like(Yv, np.nan); z = np.full(n_c, np.nan); pp = np.full(n_c, np.nan)
    q = np.zeros(n_c); started = np.zeros(n_c, dtype=bool)
    for t in range(n_w):
        with np.errstate(invalid='ignore', divide='ignore'):
            F[t] = np.where(started & (pp > 0), z / pp, np.nan)
        q += 1.0; y = Yv[t]; dem = y > 0; first = dem & ~started
        z[first] = y[first]; pp[first] = q[first]; started[first] = True; q[first] = 0.0
        upd = dem & started & ~first
        z[upd] = alpha*y[upd] + (1-alpha)*z[upd]; pp[upd] = alpha*q[upd] + (1-alpha)*pp[upd]; q[upd] = 0.0
    out = as_df(F); return out * (1 - alpha/2.0) if sba else out

MODELS = {'SMA(3)': sma(3), 'SMA(4)': sma(4), 'SMA(6)': sma(6), 'Mediana(4)': median(4),
          'WMA(4)': wma(4), 'SES(0.3)': ses(0.3), 'SES(0.5)': ses(0.5), 'SES(0.6)': ses(0.6),
          'SES(0.7)': ses(0.7), 'Croston(0.1)': croston(0.1), 'SBA(0.15)': croston(0.15, sba=True)}
NAMES = list(MODELS.keys())

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
reg_by_combo = m.groupby('combo').regimen.agg(mode_or_nan).rename('regimen')

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for name, fw in MODELS.items():
    s = fw.stack().rename(name).reset_index(); s.columns = ['semana', 'combo', name]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base = base.merge(reg_by_combo, left_on='combo', right_index=True, how='left')
base['regimen'] = base['regimen'].fillna('sin_regimen')

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s
def pick(g):
    rows = [(n,) + wb(g.real, g[n]) for n in NAMES]
    df = pd.DataFrame(rows, columns=['modelo', 'WAPE', 'BIAS']).dropna(subset=['WAPE'])
    elig = df[df.BIAS.abs() <= BIAS_CAP]; pool = elig if len(elig) else df
    w = pool.sort_values('WAPE').iloc[0]; return w['modelo'], w['WAPE'], w['BIAS']

print('=== Campeon POR REGIMEN (cap %.0f%%, SES incl. 0.6/0.7) ===' % BIAS_CAP)
print('%-12s %9s  %-12s %7s %8s  %s' % ('regimen', 'real', 'campeon', 'WAPE', 'BIAS', 'nota'))
champ = {}
for rg, g in base.groupby('regimen'):
    if g.real.sum() == 0: continue
    mc, wc, bc = pick(g); champ[rg] = mc
    nota = 'POCA DATA' if g.real.sum() < THIN_REAL else ''
    print('%-12s %9.0f  %-12s %6.1f%% %+7.1f%%  %s' % (rg, g.real.sum(), mc, wc, bc, nota))

# ensemble campeon-libre por regimen
fc_free = base.apply(lambda r: r[champ.get(r['regimen'], 'SMA(4)')], axis=1)
wf, bf = wb(base.real, fc_free)

# mapa colapsado a 2 modelos: regimenes "reactivos" (campeon SES) -> SES(0.6); resto -> Mediana(4)
react_reg = {rg for rg, mdl in champ.items() if mdl.startswith('SES')}
base['reg2'] = np.where(base.regimen.isin(react_reg), base['SES(0.6)'], base['Mediana(4)'])
w2, b2 = wb(base.real, base['reg2'])
w4, b4 = wb(base.real, base['SMA(4)'])

print('\n=== Comparacion (global, %d obs) ===' % len(base))
print('%-40s %7s %8s %8s' % ('esquema', 'WAPE', 'BIAS', 'FVA'))
print('%-40s %6.1f%% %+7.1f%% %+7.1f%%' % ('SMA(4) plano', w4, b4, 0.0))
print('%-40s %6.1f%% %+7.1f%% %+7.1f%%' % ('Campeon libre por regimen (overfit thin)', wf, bf, 100*(w4-wf)/w4))
print('%-40s %6.1f%% %+7.1f%% %+7.1f%%' % ('Regimen -> 2 modelos [SES(0.6)/Med4]', w2, b2, 100*(w4-w2)/w4))
print('\nregimenes reactivos (->SES 0.6): %s' % sorted(react_reg))
