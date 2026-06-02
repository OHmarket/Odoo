"""
Modelo base FINAL — cap |BIAS| <= 15% (decision Marco 2026-06-02).
Campeon por series_type y por XYZ; define la regla base de 2 modelos y mide
su WAPE/BIAS/FVA global vs SMA(4) plano. Walk-forward shift(1), sin San Jose.
"""
import os
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6
MIN_ACTIVE, ADI_TH, CV2_TH = 4, 1.32, 0.49
BIAS_CAP = 15.0
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

MODELS = {'SMA(3)': sma(3), 'SMA(4)': sma(4), 'SMA(6)': sma(6),
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
base['XYZ'] = base['abcxyz'].fillna('sin').str[-1]

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan, len(r)
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s, len(r)
def pick(g):
    rows = [(n,) + wb(g.real, g[n]) for n in NAMES]
    df = pd.DataFrame(rows, columns=['modelo', 'WAPE', 'BIAS', 'n']).dropna(subset=['WAPE'])
    elig = df[df.BIAS.abs() <= BIAS_CAP]; pool = elig if len(elig) else df
    w = pool.sort_values('WAPE').iloc[0]; return w['modelo'], w['WAPE'], w['BIAS']

print('=== Campeon por series_type (cap |BIAS|<=%.0f%%) ===' % BIAS_CAP)
champ_st = {}
for st, g in base.groupby('series_type'):
    if g.real.sum() == 0: continue
    mc, wc, bc = pick(g); champ_st[st] = mc
    print('  %-13s real %8.0f -> %-12s %6.1f%% (%+.1f%%)' % (st, g.real.sum(), mc, wc, bc))

print('\n=== Campeon por XYZ (cap |BIAS|<=%.0f%%) ===' % BIAS_CAP)
for x in ['X', 'Y', 'Z', 'sin']:
    g = base[base.XYZ == x]
    if not len(g) or g.real.sum() == 0: continue
    mc, wc, bc = pick(g); print('  %-4s real %8.0f -> %-12s %6.1f%% (%+.1f%%)' % (x, g.real.sum(), mc, wc, bc))

# ---- MODELO BASE = ensemble campeon por series_type ----
base['ENS'] = base.apply(lambda r: r[champ_st.get(r['series_type'], 'SMA(4)')], axis=1)
# regla simple de 2 modelos: reactivo en smooth/erratic, Mediana(4) en el resto
REACTIVE = {'smooth', 'erratic'}
base['BASE2'] = np.where(base.series_type.isin(REACTIVE), base['SES(0.5)'], base['Mediana(4)'])

w4, b4, _ = wb(base.real, base['SMA(4)'])
we, be, _ = wb(base.real, base['ENS'])
wb2, bb2, _ = wb(base.real, base['BASE2'])
print('\n=== MODELO BASE vs SMA(4) plano (global, %d obs) ===' % len(base))
print('  %-28s WAPE %6.1f%%  BIAS %+6.1f%%   FVA %+5.1f%%' % ('SMA(4) plano (incumbente)', w4, b4, 0.0))
print('  %-28s WAPE %6.1f%%  BIAS %+6.1f%%   FVA %+5.1f%%' % ('Ensemble campeon/series_type', we, be, 100*(w4-we)/w4))
print('  %-28s WAPE %6.1f%%  BIAS %+6.1f%%   FVA %+5.1f%%' % ('BASE-2: SES(.5)smooth+Med4', wb2, bb2, 100*(w4-wb2)/w4))

pd.DataFrame([{'series_type': k, 'campeon': v_} for k, v_ in champ_st.items()]).to_csv(
    os.path.join(OUTDIR, 'champions_cap15.csv'), index=False, encoding='utf-8-sig')
print('\nOK: champions_cap15.csv')
