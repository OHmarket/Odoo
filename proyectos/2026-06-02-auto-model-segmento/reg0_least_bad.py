"""
REG-0 (dead/declining/C-no_signal): que modelo es el menos malo?
Incluye forecast=0 (la politica del Script 1) y Naive como referencia.
"""
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
MIN_HIST = 6

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T; Yv = Wt.values; n_w, n_c = Yv.shape
def as_df(a): return pd.DataFrame(a, index=Wt.index, columns=Wt.columns)

def sma(k):    return Wt.rolling(k, min_periods=k).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def ses(a):    return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def naive():   return Wt.shift(1)
def zero():    return as_df(np.zeros_like(Yv)).where(Wt.shift(1).notna())  # 0 solo donde hay historia
def half_naive(): return Wt.shift(1) * 0.5
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

MODELS = {'Zero (=0)': zero(), 'HalfNaive(0.5)': half_naive(), 'Naive': naive(),
          'SMA(3)': sma(3), 'SMA(4)': sma(4), 'Mediana(4)': median(4),
          'SES(0.3)': ses(0.3), 'SES(0.5)': ses(0.5), 'Croston(0.1)': croston(0.1)}

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
reg_by_combo = m.groupby('combo').regimen.agg(mode_or_nan)

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for name, fw in MODELS.items():
    s = fw.stack().rename(name).reset_index(); s.columns = ['semana', 'combo', name]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base['regimen'] = base['combo'].map(reg_by_combo).fillna('sin_regimen')
g = base[base.regimen == 'REG-0']

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan, 0
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s, len(r)

print('=== REG-0: que es el menos malo? (real %.0f, %d combos) ===' % (g.real.sum(), g.combo.nunique()))
print('%-16s %8s %9s %8s' % ('modelo', 'WAPE', 'BIAS', 'n'))
rows = []
for name in MODELS:
    w, b, n = wb(g.real, g[name]); rows.append((name, w, b, n))
for name, w, b, n in sorted(rows, key=lambda x: x[1]):
    print('%-16s %6.1f%% %+8.1f%% %8d' % (name, w, b, n))
# cuanta venta queda viva en REG-0 por semana (para dimensionar el riesgo de poner 0)
print('\nventa media REG-0 por combo-semana activa: %.2f u' % g[g.real > 0].real.mean())
print('%% de filas REG-0 con venta>0: %.1f%%' % (100*(g.real > 0).mean()))
