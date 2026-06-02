"""
Version DEPLOYABLE auto-contenida: el script de forecast NO lee regimen (es global
en produccion). Clasifica series_type LOCAL (ADI/CV2 sobre su propia venta) + lee
ABC GLOBAL (x_studio_abcxyz, disponible por producto). SIN lifecycle.

Mapeo:
  series_type smooth  + ABC=A          -> SES(0.5)   (=REG-1)
  series_type smooth  + ABC=B/C        -> SES(0.6)   (=REG-2/3)
  series_type erratic                  -> SES(0.7)   (=REG-4)
  series_type lumpy/intermittent/no_sig-> Mediana(4) (=REG-5..7)

Compara contra el modelo base con regimen LOCAL (techo validado, FVA +8.08%).
Walk-forward shift(1), sin San Jose.
"""
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
MIN_HIST = 6
MIN_ACTIVE, ADI_TH, CV2_TH = 4, 1.32, 0.49

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

def ses(a):    return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
SES = {a: ses(a) for a in (0.5, 0.6, 0.7)}; MED4 = median(4); HALF = Wt.shift(1)*0.5
SMA4 = Wt.rolling(4, min_periods=4).mean().shift(1)

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
abc_glob = m.groupby('product_id').abcxyz.agg(mode_or_nan).str[0]    # ABC global por producto
reg_loc = m.groupby('combo').regimen.agg(mode_or_nan)               # regimen LOCAL (techo)

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas', 'product_id']].rename(columns={'ventas': 'real'}).copy()
cols = {'MED4': MED4, 'HALF': HALF, 'SMA4': SMA4}
for a in SES: cols['S%.1f' % a] = SES[a]
for nm, fw in cols.items():
    s = fw.stack().rename(nm).reset_index(); s.columns = ['semana', 'combo', nm]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base['st'] = base['combo'].map(stype).fillna('no_signal')
base['abc'] = base['product_id'].map(abc_glob).fillna('C')
base['reg'] = base['combo'].map(reg_loc).fillna('sin_regimen')

# --- version auto-contenida (sin lifecycle) ---
def col_auto(r):
    st, abc = r['st'], r['abc']
    if st == 'smooth':  return 'S0.5' if abc == 'A' else 'S0.6'
    if st == 'erratic': return 'S0.7'
    return 'MED4'   # lumpy/intermittent/no_signal
base['AUTO'] = base.apply(col_auto, axis=1)

# --- techo: regimen local con HalfNaive + 3 niveles ---
A3 = {'REG-1': 'S0.5', 'REG-4': 'S0.7', 'sin_regimen': 'S0.7'}
MEDR = {'REG-5', 'REG-6', 'REG-7', 'REG-8'}
def col_techo(r):
    rg = r['reg']
    if rg == 'REG-0': return 'HALF'
    if rg in MEDR: return 'MED4'
    return A3.get(rg, 'S0.6')
base['TECHO'] = base.apply(col_techo, axis=1)

base['f_auto'] = base.apply(lambda r: r[r['AUTO']], axis=1)
base['f_techo'] = base.apply(lambda r: r[r['TECHO']], axis=1)

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s

w4, b4 = wb(base.real, base['SMA4'])
wa, ba = wb(base.real, base['f_auto'])
wt, bt = wb(base.real, base['f_techo'])
print('=== DEPLOYABLE auto-contenido vs techo regimen-local (%d obs) ===' % len(base))
print('  SMA(4) plano                     : WAPE %.2f%%  BIAS %+.1f%%' % (w4, b4))
print('  AUTO (series_type local + ABC)   : WAPE %.2f%%  BIAS %+.1f%%   FVA %+.2f%%' % (wa, ba, 100*(w4-wa)/w4))
print('  TECHO (regimen local + HalfNaive): WAPE %.2f%%  BIAS %+.1f%%   FVA %+.2f%%' % (wt, bt, 100*(w4-wt)/w4))
print('  -> costo de saltarse lifecycle (REG-0/REG-8): %.2f pp WAPE' % (wa - wt))
