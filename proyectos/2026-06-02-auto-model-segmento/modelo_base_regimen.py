"""
MODELO BASE FINAL — mapeo por regimen LOCAL (Script 1 / x_calculo_abc_xyz):
  REG-0                      -> HalfNaive (0.5 x ultima venta)   [coletazo muerto]
  REG-1, REG-2, REG-3, REG-4 -> SES(0.6)                         [smooth/erratic]
  REG-5, REG-6, REG-7, REG-8 -> Mediana(4)                       [lumpy/interm/seasonal]
  sin_regimen                -> SES(0.6) (default reactivo)
Walk-forward shift(1), sin San Jose. Mide global + por regimen vs SMA(4) plano.
"""
import os
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6

REACT = {'REG-1', 'REG-2', 'REG-3', 'REG-4', 'sin_regimen'}   # -> SES(0.6)
ROBUST = {'REG-5', 'REG-6', 'REG-7', 'REG-8'}                  # -> Mediana(4)
# REG-0 -> HalfNaive

v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T

def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def ses(a):    return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
SES06 = ses(0.6); MED4 = median(4); HALF = Wt.shift(1) * 0.5; SMA4 = Wt.rolling(4, min_periods=4).mean().shift(1)

m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
reg_by_combo = m.groupby('combo').regimen.agg(mode_or_nan)

base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for nm, fw in {'SES06': SES06, 'MED4': MED4, 'HALF': HALF, 'SMA4': SMA4}.items():
    s = fw.stack().rename(nm).reset_index(); s.columns = ['semana', 'combo', nm]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base['regimen'] = base['combo'].map(reg_by_combo).fillna('sin_regimen')

def modelo_de(rg):
    if rg == 'REG-0': return 'HALF'
    if rg in ROBUST: return 'MED4'
    return 'SES06'   # REACT + default
base['m'] = base.regimen.map(modelo_de)
base['BASE'] = base.apply(lambda r: r[r['m']], axis=1)

def wb(real, fc):
    mk = real.notna() & fc.notna(); r = real[mk]; f = fc[mk]; s = r.sum()
    if s == 0: return np.nan, np.nan
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s

w4, b4 = wb(base.real, base['SMA4'])
wb_, bb_ = wb(base.real, base['BASE'])
print('=== MODELO BASE por regimen local vs SMA(4) plano (%d obs) ===' % len(base))
print('  SMA(4) plano:  WAPE %.1f%%  BIAS %+.1f%%' % (w4, b4))
print('  MODELO BASE :  WAPE %.1f%%  BIAS %+.1f%%   FVA %+.1f%%' % (wb_, bb_, 100*(w4-wb_)/w4))

print('\n=== por regimen (modelo asignado) ===')
print('%-12s %-9s %9s %7s %8s' % ('regimen', 'modelo', 'real', 'WAPE', 'BIAS'))
MAP = {'HALF': 'HalfNaive', 'SES06': 'SES(0.6)', 'MED4': 'Mediana(4)'}
for rg, g in base.groupby('regimen'):
    if g.real.sum() == 0: continue
    w, b = wb(g.real, g['BASE'])
    print('%-12s %-9s %9.0f %6.1f%% %+7.1f%%' % (rg, MAP[modelo_de(rg)], g.real.sum(), w, b))

champs = pd.DataFrame([{'regimen': rg, 'modelo': MAP[modelo_de(rg)]} for rg in sorted(base.regimen.unique())])
champs.to_csv(os.path.join(OUTDIR, 'modelo_base_regimen.csv'), index=False, encoding='utf-8-sig')
print('\nOK: modelo_base_regimen.csv')
