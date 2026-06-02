"""
Detalle del segmento SMOOTH (series_type local) — el grueso del volumen (~60%).
Ranking de los 10 candidatos dentro de smooth, y cruce smooth x XYZ / smooth x ABC.
Walk-forward shift(1), sin San Jose.
"""
import os
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6
MIN_ACTIVE, ADI_TH, CV2_TH = 4, 1.32, 0.49
BIAS_CAP = 10.0
os.makedirs(OUTDIR, exist_ok=True)

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T; Yv = Wt.values; n_w, n_c = Yv.shape
def as_df(a): return pd.DataFrame(a, index=Wt.index, columns=Wt.columns)

def classify(series):
    vals = series.values; active = int((vals > 0).sum())
    if active < MIN_ACTIVE: return 'no_signal'
    adi = len(vals) / active; pos = vals[vals > 0]; mu = pos.mean()
    cv2 = (pos.var() / (mu*mu)) if mu > 0 else 0.0
    if adi >= ADI_TH: return 'lumpy' if cv2 >= CV2_TH else 'intermittent'
    return 'erratic' if cv2 >= CV2_TH else 'smooth'
stype = real_wide.fillna(0.0).apply(classify, axis=1).rename('series_type')

def sma(k):    return Wt.rolling(k, min_periods=k).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def wma(k):
    w = np.arange(1, k + 1)
    return Wt.rolling(k, min_periods=k).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).shift(1)
def ses(a):  return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def naive(): return Wt.shift(1)
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

MODELS = {'Naive': naive(), 'SMA(3)': sma(3), 'SMA(4)': sma(4), 'SMA(6)': sma(6),
          'Mediana(4)': median(4), 'WMA(4)': wma(4), 'SES(0.3)': ses(0.3), 'SES(0.5)': ses(0.5),
          'Croston(0.1)': croston(0.1), 'SBA(0.15)': croston(0.15, sba=True)}
NAMES = list(MODELS.keys())

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
abc_by_combo = m.groupby('combo').abcxyz.agg(mode_or_nan).rename('abcxyz')

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for name, fw in MODELS.items():
    s = fw.stack().rename(name).reset_index(); s.columns = ['semana', 'combo', name]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base = base.merge(stype, left_on='combo', right_index=True, how='left')
base = base.merge(abc_by_combo, left_on='combo', right_index=True, how='left')
base['series_type'] = base['series_type'].fillna('no_signal')
base['abcxyz'] = base['abcxyz'].fillna('sin_abc')
base['XYZ'] = base['abcxyz'].str[-1].where(base['abcxyz'] != 'sin_abc', 'sin')
base['ABC'] = base['abcxyz'].str[0].where(base['abcxyz'] != 'sin_abc', 'sin')

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan, len(r)
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s, len(r)
def pick(g):
    rows = [(n,) + wb(g.real, g[n]) for n in NAMES]
    df = pd.DataFrame(rows, columns=['modelo', 'WAPE', 'BIAS', 'n']).dropna(subset=['WAPE'])
    elig = df[df.BIAS.abs() <= BIAS_CAP]; pool = elig if len(elig) else df
    w = pool.sort_values('WAPE').iloc[0]; return w['modelo'], w['WAPE'], w['BIAS']

sm = base[base.series_type == 'smooth'].copy()
print('=== SMOOTH: %d obs | real %.0f | %d combos ===' % (len(sm), sm.real.sum(), sm.combo.nunique()))

print('\n--- Ranking 10 modelos dentro de smooth (orden WAPE) ---')
rows = [(n,) + wb(sm.real, sm[n]) for n in NAMES]
rk = pd.DataFrame(rows, columns=['modelo', 'WAPE', 'BIAS', 'n']).dropna(subset=['WAPE']).sort_values('WAPE')
for _, r in rk.iterrows():
    tag = '  <= cap' if abs(r.BIAS) <= BIAS_CAP else ''
    print('  %-13s %6.1f%%  BIAS %+6.1f%%%s' % (r.modelo, r.WAPE, r.BIAS, tag))
rk.to_csv(os.path.join(OUTDIR, 'ranking_smooth.csv'), index=False, encoding='utf-8-sig')
with pd.ExcelWriter(os.path.join(OUTDIR, 'ranking_smooth.xlsx')) as xl:
    rk.to_excel(xl, sheet_name='smooth_ranking', index=False)

print('\n--- smooth x XYZ (campeon cap10%) ---')
for x in ['X', 'Y', 'Z', 'sin']:
    g = sm[sm.XYZ == x]
    if not len(g) or g.real.sum() == 0: continue
    mc, wc, bc = pick(g); print('  %-4s real %8.0f -> %-12s %6.1f%% (%+.1f%%)' % (x, g.real.sum(), mc, wc, bc))

print('\n--- smooth x ABC (campeon cap10%) ---')
for a in ['A', 'B', 'C', 'sin']:
    g = sm[sm.ABC == a]
    if not len(g) or g.real.sum() == 0: continue
    mc, wc, bc = pick(g); print('  %-4s real %8.0f -> %-12s %6.1f%% (%+.1f%%)' % (a, g.real.sum(), mc, wc, bc))

print('\nOK: ranking_smooth.csv / ranking_smooth.xlsx')
