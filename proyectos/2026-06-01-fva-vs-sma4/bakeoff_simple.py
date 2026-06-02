"""
Bake-off local de modelos SIMPLES contra la venta real. Campeon = SMA(4).
Pregunta: hay un modelo simple (o combinacion simple) que le gane al SMA(4)?

Fuente: OH Forecast Backtest (x_forecast_backtest) (4).csv -> real_qty por
SKU x sala x semana (misma vara con que se midio el error del motor). 21 semanas
ene->may. forecast_qty del motor entra solo como referencia (no se recalcula).

Protocolo: walk-forward 1 paso adelante (h=1) sobre el pivot combo x semana.
Cada modelo en la semana w usa SOLO semanas < w. Universo evaluable comun:
semanas con >=8 previas (para que SMA8/SES esten calientes) -> ~13 semanas.
Excluye Ventas San Jose. SIN exclusion de quiebre (primer corte).

Metricas: WAPE, BIAS, y FVA vs SMA(4) (+ = el retador le gana al campeon).
"""
import re, os, sys
import numpy as np
import pandas as pd

CSV = 'OH Forecast Backtest (x_forecast_backtest) (4).csv'
OUTDIR = 'proyectos/2026-06-01-fva-vs-sma4/resultados'
MIN_PREV = int(sys.argv[1]) if len(sys.argv) > 1 else 8   # semanas previas requeridas

# ---------------- carga ----------------
df = pd.read_csv(CSV, usecols=['product_id', 'team_id', 'target_week_start',
                               'real_qty', 'forecast_qty', 'regimen'])
df = df[~df['team_id'].str.contains('San Jos', case=False, na=False)].copy()
# clave de combo = product_id completo (default_code alfanumerico) + team_id.
# (product_id, team_id, semana) ya verificado unico -> no extraer id numerico.
df['combo'] = df['product_id'].astype(str) + '|' + df['team_id'].astype(str)

weeks = sorted(df['target_week_start'].unique())
idx = {w: i for i, w in enumerate(weeks)}
df['wi'] = df['target_week_start'].map(idx)

# pivot combo x semana; Wt = semanas(index) x combos(cols). NaN = combo ausente -> 0 venta
real_wide = df.pivot_table(index='combo', columns='target_week_start', values='real_qty', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T                       # semanas x combos
Yv = Wt.values                                     # np: n_weeks x n_combos
n_w, n_c = Yv.shape

# ---------------- modelos: cada uno devuelve forecast h=1, alineado semanas x combos ----------------
def as_df(arr):
    return pd.DataFrame(arr, index=Wt.index, columns=Wt.columns)

def sma(k):
    return Wt.rolling(k, min_periods=k).mean().shift(1)

def median(k):
    return Wt.rolling(k, min_periods=k).median().shift(1)

def wma(k):
    w = np.arange(1, k + 1)
    return Wt.rolling(k, min_periods=k).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).shift(1)

def ses(alpha):
    return Wt.ewm(alpha=alpha, adjust=False).mean().shift(1)

def naive():
    return Wt.shift(1)

def holt(alpha, beta, phi=1.0):
    F = np.full_like(Yv, np.nan)
    level = Yv[0].copy()
    trend = np.zeros(n_c)
    for t in range(1, n_w):
        F[t] = level + phi * trend
        prev = level
        level = alpha * Yv[t] + (1 - alpha) * (prev + phi * trend)
        trend = beta * (level - prev) + (1 - beta) * phi * trend
    return as_df(F)

def drift(N=6):
    F = np.full_like(Yv, np.nan)
    x = np.arange(N); xbar = x.mean(); Sxx = ((x - xbar) ** 2).sum()
    for t in range(N, n_w):
        win = Yv[t - N:t]                          # N x combos
        ybar = win.mean(axis=0)
        b = ((x[:, None] - xbar) * (win - ybar)).sum(axis=0) / Sxx
        a = ybar - b * xbar
        F[t] = a + b * N                           # proyecta al punto siguiente
    return as_df(F)

MODELS = {
    'SMA(4)*champ': sma(4),
    'SMA(3)': sma(3),
    'SMA(6)': sma(6),
    'SMA(8)': sma(8),
    'Mediana(4)': median(4),
    'WMA(4)': wma(4),
    'SES(0.2)': ses(0.2),
    'SES(0.3)': ses(0.3),
    'SES(0.5)': ses(0.5),
    'Blend SMA4+8': (sma(4) + sma(8)) / 2,
    'Holt(.3,.1)': holt(0.3, 0.1),
    'Holt damp(.3,.1,.9)': holt(0.3, 0.1, 0.9),
    'Drift OLS6': drift(6),
    'Naive': naive(),
}

# ---------------- ensamblar long y evaluar ----------------
base = df[df['wi'] >= MIN_PREV][['combo', 'target_week_start', 'real_qty', 'regimen']].copy()
for name, fwide in MODELS.items():
    s = fwide.stack().rename(name).reset_index()   # target_week_start, combo, name
    base = base.merge(s, on=['target_week_start', 'combo'], how='left')
# motor: referencia directa del CSV
base = base.merge(df[df['wi'] >= MIN_PREV][['combo', 'target_week_start', 'forecast_qty']],
                  on=['combo', 'target_week_start'], how='left').rename(columns={'forecast_qty': 'Motor HM-SI'})

ALL = list(MODELS.keys()) + ['Motor HM-SI']

def metrics(real_v, fcst):
    m = real_v.notna() & fcst.notna()
    r = real_v[m]; f = fcst[m]
    s = r.sum()
    if s == 0:
        return np.nan, np.nan, len(r)
    return 100 * (f - r).abs().sum() / s, 100 * (f.sum() - s) / s, len(r)

champ = metrics(base.real_qty, base['SMA(4)*champ'])[0]

rows = []
for name in ALL:
    wape, bias, n = metrics(base.real_qty, base[name])
    fva = 100 * (champ - wape) / champ                # + = mejor que SMA(4)
    rows.append({'modelo': name, 'WAPE': wape, 'BIAS': bias, 'FVA_vs_SMA4': fva, 'n': n})
rank = pd.DataFrame(rows).sort_values('WAPE').reset_index(drop=True)

print(f'Universo: semanas {weeks[MIN_PREV]}..{weeks[-1]} ({n_w-MIN_PREV} sem) | obs={len(base):,} | real={base.real_qty.sum():,.0f}')
print(f'Campeon SMA(4) WAPE = {champ:.2f}%\n')
print('RANKING (WAPE asc, FVA vs SMA4: + le gana al campeon)')
print(f'{"modelo":<22}{"WAPE":>8}{"BIAS":>8}{"FVA":>9}')
for _, r in rank.iterrows():
    mark = '  <= GANA' if r.FVA_vs_SMA4 > 0 and r.modelo != 'SMA(4)*champ' else ''
    print(f'{r.modelo:<22}{r.WAPE:>7.1f}%{r.BIAS:>+7.1f}%{r.FVA_vs_SMA4:>+8.1f}%{mark}')

# por regimen: FVA vs SMA4 de cada modelo
print('\nFVA vs SMA(4) por regimen (+ = le gana al campeon):')
regs = sorted(base.regimen.dropna().unique())
vol = base.groupby('regimen').real_qty.sum()
hdr = f'{"modelo":<22}' + ''.join(f'{r.replace("REG-","R"):>7}' for r in regs)
print(hdr)
for name in ALL:
    line = f'{name:<22}'
    for r in regs:
        g = base[base.regimen == r]
        wc = metrics(g.real_qty, g['SMA(4)*champ'])[0]
        wm = metrics(g.real_qty, g[name])[0]
        fva = 100 * (wc - wm) / wc if wc and not np.isnan(wc) else np.nan
        line += f'{fva:>+6.0f}%' if pd.notna(fva) else f'{"-":>7}'
    print(line)
print('vol real  ' + ' '*12 + ''.join(f'{vol.get(r,0)/1000:>6.0f}k' for r in regs))

os.makedirs(OUTDIR, exist_ok=True)
rank.to_csv(os.path.join(OUTDIR, 'bakeoff_simple.csv'), index=False, encoding='utf-8-sig')
print(f'\nOK: {OUTDIR}/bakeoff_simple.csv')
