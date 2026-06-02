"""
Cruce por XYZ (y ABCXYZ): ranking de los 10 candidatos por dimension de
variabilidad del motor (X=estable, Y=variable, Z=erratico/intermitente).
Reusa carga/modelos del harness. Walk-forward shift(1), sin San Jose.
"""
import os
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6
BIAS_CAP = 10.0
os.makedirs(OUTDIR, exist_ok=True)

# ---------------- venta ----------------
v = pd.read_csv(VENTAS); v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique()); idx = {w: i for i, w in enumerate(weeks)}
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T; Yv = Wt.values; n_w, n_c = Yv.shape
def as_df(a): return pd.DataFrame(a, index=Wt.index, columns=Wt.columns)

# ---------------- modelos ----------------
def sma(k):    return Wt.rolling(k, min_periods=k).mean().shift(1)
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def wma(k):
    w = np.arange(1, k + 1)
    return Wt.rolling(k, min_periods=k).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).shift(1)
def ses(a):    return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def naive():   return Wt.shift(1)
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
    out = as_df(F)
    return out * (1 - alpha/2.0) if sba else out

MODELS = {'Naive': naive(), 'SMA(3)': sma(3), 'SMA(4)': sma(4), 'SMA(6)': sma(6),
          'Mediana(4)': median(4), 'WMA(4)': wma(4), 'SES(0.3)': ses(0.3), 'SES(0.5)': ses(0.5),
          'Croston(0.1)': croston(0.1), 'SBA(0.15)': croston(0.15, sba=True)}
NAMES = list(MODELS.keys())

# ---------------- abcxyz del motor (moda por combo) ----------------
m = pd.read_csv(SRV_M, encoding='latin-1'); m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
abc_by_combo = m.groupby('combo').abcxyz.agg(mode_or_nan).rename('abcxyz')

# ---------------- base larga ----------------
base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for name, fw in MODELS.items():
    s = fw.stack().rename(name).reset_index(); s.columns = ['semana', 'combo', name]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base = base.merge(abc_by_combo, left_on='combo', right_index=True, how='left')
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

# ---------------- ranking por XYZ ----------------
rows = []
for seg, g in base.groupby('XYZ'):
    if g.real.sum() == 0: continue
    for n in NAMES:
        wa, bi, k = wb(g.real, g[n]); rows.append({'XYZ': seg, 'modelo': n, 'WAPE': wa, 'BIAS': bi, 'real': g.real.sum(), 'n': k})
rank_xyz = pd.DataFrame(rows)
rank_xyz.to_csv(os.path.join(OUTDIR, 'ranking_xyz.csv'), index=False, encoding='utf-8-sig')
with pd.ExcelWriter(os.path.join(OUTDIR, 'ranking_xyz.xlsx')) as xl:
    rank_xyz.to_excel(xl, sheet_name='por_XYZ', index=False)

print('=== Cruce por XYZ (X=estable, Y=variable, Z=erratico) ===')
order = ['X', 'Y', 'Z', 'sin']
print('%-5s %9s  %-13s %7s %8s   %-13s' % ('XYZ', 'real', 'campeon(cap10%)', 'WAPE', 'BIAS', 'mejor WAPE libre'))
champ_xyz = {}
for seg in order:
    g = base[base.XYZ == seg]
    if not len(g) or g.real.sum() == 0: continue
    mc, wc, bc = pick(g); champ_xyz[seg] = mc
    sub = rank_xyz[rank_xyz.XYZ == seg].sort_values('WAPE').iloc[0]
    print('%-5s %9.0f  %-13s %6.1f%% %+7.1f%%   %-9s %5.1f%% (%+.1f%%)' % (
        seg, g.real.sum(), mc, wc, bc, sub.modelo, sub.WAPE, sub.BIAS))

# ---------------- ABC x XYZ (matriz campeon) ----------------
print('\n=== Matriz ABC x XYZ — campeon (menor WAPE, |BIAS|<=10%) ===')
abcs = ['A', 'B', 'C']; xyzs = ['X', 'Y', 'Z']
print('%-4s %-12s %-12s %-12s' % ('', 'X', 'Y', 'Z'))
for a in abcs:
    cells = []
    for x in xyzs:
        g = base[(base.ABC == a) & (base.XYZ == x)]
        if not len(g) or g.real.sum() == 0: cells.append('-'); continue
        mc, wc, _ = pick(g); cells.append('%s %.0f%%' % (mc.replace('Mediana', 'Med').replace('Naive', 'Nv'), wc))
    print('%-4s %-12s %-12s %-12s' % (a, cells[0], cells[1], cells[2]))

print('\nOK: ranking_xyz.csv / ranking_xyz.xlsx')
