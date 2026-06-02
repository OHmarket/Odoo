"""
Modelo base: evalua candidatos GLOBALES y la regla best-fit por series_type
contra el SMA(4) plano (incumbente). Reusa la carga/clasificacion del harness.

Objetivo: elegir EL modelo base productivo (simple, explicable, mejor que SMA(4)).
Walk-forward 1 paso, shift(1) (sin look-ahead). Excluye San Jose (medicion).
"""
import os
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6
MIN_ACTIVE, ADI_TH, CV2_TH = 4, 1.32, 0.49
os.makedirs(OUTDIR, exist_ok=True)

# ---------------- carga venta ----------------
v = pd.read_csv(VENTAS)
v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique())
idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T

# ---------------- series_type local (Syntetos-Boylan) ----------------
def classify(series):
    vals = series.values
    active = int((vals > 0).sum())
    if active < MIN_ACTIVE:
        return 'no_signal'
    adi = len(vals) / active
    pos = vals[vals > 0]; mu = pos.mean()
    cv2 = (pos.var() / (mu * mu)) if mu > 0 else 0.0
    if adi >= ADI_TH:
        return 'lumpy' if cv2 >= CV2_TH else 'intermittent'
    return 'erratic' if cv2 >= CV2_TH else 'smooth'
stype = real_wide.fillna(0.0).apply(classify, axis=1).rename('series_type')

# ---------------- modelos ----------------
def sma(k):    return Wt.rolling(k, min_periods=k).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def wma(k):
    w = np.arange(1, k + 1)
    return Wt.rolling(k, min_periods=k).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).shift(1)
def ses(a):    return Wt.ewm(alpha=a, adjust=False).mean().shift(1)

M = {'SMA(4)': sma(4), 'Mediana(4)': median(4), 'WMA(4)': wma(4), 'SES(0.5)': ses(0.5)}

# ---------------- base: long con series_type ----------------
base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for name, fw in M.items():
    s = fw.stack().rename(name).reset_index(); s.columns = ['semana', 'combo', name]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base = base.merge(stype, left_on='combo', right_index=True, how='left')
base['series_type'] = base['series_type'].fillna('no_signal')

# regla best-fit por series_type: smooth/erratic -> WMA(4) ; resto -> Mediana(4)
REACTIVE = {'smooth', 'erratic'}
base['BASE_wma'] = np.where(base.series_type.isin(REACTIVE), base['WMA(4)'], base['Mediana(4)'])
base['BASE_ses'] = np.where(base.series_type.isin(REACTIVE), base['SES(0.5)'], base['Mediana(4)'])

def wb(real, fc):
    m = real.notna() & fc.notna(); r = real[m]; f = fc[m]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s

CANDS = ['SMA(4)', 'Mediana(4)', 'WMA(4)', 'SES(0.5)', 'BASE_wma', 'BASE_ses']
LABEL = {'BASE_wma': 'BASE: WMA4+Med4', 'BASE_ses': 'BASE: SES.5+Med4'}

w4, _ = wb(base.real, base['SMA(4)'])
print('=== Modelo base — global (%d obs, %d sem eval) ===' % (len(base), len(weeks) - MIN_HIST))
print('%-18s %7s %8s %8s' % ('modelo', 'WAPE', 'BIAS', 'FVA vs SMA4'))
for c in CANDS:
    wa, bi = wb(base.real, base[c])
    fva = 100*(w4 - wa)/w4
    print('%-18s %6.1f%% %+7.1f%% %+9.1f%%' % (LABEL.get(c, c), wa, bi, fva))

print('\n=== Desglose BASE (WMA4+Med4) por series_type ===')
print('%-13s %8s %7s %8s' % ('series_type', 'real', 'WAPE', 'BIAS'))
for st, g in base.groupby('series_type'):
    if g.real.sum() == 0: continue
    wa, bi = wb(g.real, g['BASE_wma'])
    print('%-13s %8.0f %6.1f%% %+7.1f%%' % (st, g.real.sum(), wa, bi))
