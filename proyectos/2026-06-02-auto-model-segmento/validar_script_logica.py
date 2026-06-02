"""
Valida la logica EXACTA del script productivo OH Forecast Base.py:
reimplementa _classify_series_type / _ses_level / _median en Python puro y corre
walk-forward RECLASIFICANDO en cada cutoff (sin look-ahead, como en produccion).
Compara WAPE/BIAS/FVA vs el harness AUTO (62.54%) y vs SMA(4).
"""
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
MIN_HIST = 6
WIN = 26
ADI_TH, CV2_TH, MIN_ACTIVE = 1.32, 0.49, 4

def classify(vals):
    pos = [x for x in vals if x > 0.0]; active = len(pos); n = len(vals)
    if active < MIN_ACTIVE: return 'no_signal'
    adi = n / active
    mu = sum(pos) / active
    if mu <= 0: return 'no_signal'
    var = sum((x - mu) ** 2 for x in pos) / active
    cv2 = var / (mu * mu)
    if adi >= ADI_TH: return 'lumpy' if cv2 >= CV2_TH else 'intermittent'
    return 'erratic' if cv2 >= CV2_TH else 'smooth'

def ses_level(vals, alpha):
    lvl = None
    for y in vals:
        lvl = y if lvl is None else alpha * y + (1 - alpha) * lvl
    return lvl if lvl is not None else 0.0

def median(seq):
    s = sorted(seq); k = len(s)
    if k == 0: return 0.0
    return s[k // 2] if (k % 2) else (s[k // 2 - 1] + s[k // 2]) / 2.0

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks).fillna(0.0)
combos = real_wide.index.tolist()
prod_of = {c: c.split('|')[0] for c in combos}

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
abc_glob = m.groupby('product_id').abcxyz.agg(mode_or_nan).str[0].to_dict()

R = real_wide.values            # combos x weeks
def alpha_for(stype, abc):
    if stype == 'smooth': return 0.5 if abc == 'A' else 0.6
    if stype == 'erratic': return 0.7
    return None   # mediana

f_base, f_sma4, reals = [], [], []
for t in range(MIN_HIST, len(weeks)):
    lo = max(0, t - WIN)
    win = R[:, lo:t]            # cerradas hasta t-1
    rt = R[:, t]
    for i, c in enumerate(combos):
        if rt[i] == 0 and win[i].sum() == 0:
            continue
        vals = list(win[i])
        st = classify(vals)
        a = alpha_for(st, abc_glob.get(prod_of[c], ''))
        fb = ses_level(vals, a) if a is not None else median(vals[-4:])
        last4 = vals[-4:]
        fs = sum(last4) / len(last4) if last4 else 0.0
        f_base.append(max(fb, 0.0)); f_sma4.append(fs); reals.append(rt[i])

reals = np.array(reals); f_base = np.array(f_base); f_sma4 = np.array(f_sma4)
def wb(r, f):
    s = r.sum(); return 100*np.abs(f-r).sum()/s, 100*(f.sum()-s)/s
w4, b4 = wb(reals, f_sma4); wb_, bb_ = wb(reals, f_base)
print('=== Validacion logica script (walk-forward, reclasifica por cutoff) ===')
print('  obs evaluadas: %d' % len(reals))
print('  SMA(4)      : WAPE %.2f%%  BIAS %+.1f%%' % (w4, b4))
print('  FORECAST BASE: WAPE %.2f%%  BIAS %+.1f%%   FVA %+.2f%%' % (wb_, bb_, 100*(w4-wb_)/w4))
print('  (harness AUTO con clasificacion estatica daba 62.54%% / FVA +6.83%%)')
