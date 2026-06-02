"""
Harness local: auto-modelo por segmento.

Fase 0  Paridad: SMA(4) local == SMA(4) del server (gate de confianza).
Fase 1  Clasificar: series_type LOCAL (Syntetos-Boylan) + regimen (del export motor).
Fase 2  Candidatos: Naive, SMA(3/4/6), Mediana(4), WMA(4), SES(.3/.5), Croston, SBA.
Fase 3  Ganador por segmento: menor WAPE con |BIAS|<=BIAS_CAP; ensemble vs SMA(4).

Walk-forward 1 paso, shift(1) (sin look-ahead). Excluye San Jose (medicion).
Reusa patrones de bakeoff_simple.py y la clasificacion de HM SI Forecast.py.
"""
import os, re
import numpy as np
import pandas as pd

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SRV_P  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 P.csv'   # server SMA4 (paridad)
SRV_M  = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'   # motor (regimen/abc)
OUTDIR = 'proyectos/2026-06-02-auto-model-segmento/resultados'
MIN_HIST = 6          # semanas previas minimas para universo evaluable comun (SMA6)
MIN_ACTIVE = 4        # Syntetos-Boylan: <4 sem activas -> no_signal
ADI_TH, CV2_TH = 1.32, 0.49
BIAS_CAP = 10.0       # |BIAS| maximo (%) para que un candidato sea elegible

os.makedirs(OUTDIR, exist_ok=True)

# ---------------- carga venta ----------------
v = pd.read_csv(VENTAS)
v.columns = [c.strip() for c in v.columns]
v = v[~v.team_id.str.contains('San Jos', case=False, na=False)].copy()
v['combo'] = v.product_id.astype(str) + '|' + v.team_id.astype(str)
weeks = sorted(v.semana.unique())
idx = {w: i for i, w in enumerate(weeks)}
print('venta: %d filas | %d combos | %d sem (%s..%s)' % (len(v), v.combo.nunique(), len(weeks), weeks[0], weeks[-1]))

# pivot combo x semana (Wt = semanas x combos para rolling/ewm)
real_wide = v.pivot_table(index='combo', columns='semana', values='ventas', aggfunc='first').reindex(columns=weeks)
Wt = real_wide.fillna(0.0).T
Yv = Wt.values               # semanas x combos
n_w, n_c = Yv.shape

def as_df(arr):
    return pd.DataFrame(arr, index=Wt.index, columns=Wt.columns)

# ---------------- FASE 0: paridad SMA(4) local vs server ----------------
def sma(k):
    return Wt.rolling(k, min_periods=k).mean().shift(1)

sma4_local = sma(4)
p = pd.read_csv(SRV_P, encoding='latin-1')
p.columns = [c.strip() for c in p.columns]
p = p[p.forecast_model_code == 'sma4'].copy()
p['semana'] = pd.to_datetime(p.target_week_start).dt.strftime('%Y-%m-%d')
p['combo'] = p.product_id.astype(str) + '|' + p.team_id.astype(str)
sl = sma4_local.stack().rename('sma4_local').reset_index()
sl.columns = ['semana', 'combo', 'sma4_local']
par = p.merge(sl, on=['combo', 'semana'], how='inner').dropna(subset=['sma4_local'])
d = (par.forecast_qty - par.sma4_local).abs()
print('\n=== FASE 0 paridad SMA(4) local vs server ===')
print('  pares: %d | diff max: %.5f | corr: %.6f | <0.001: %.2f%%' % (
    len(par), d.max(), par.forecast_qty.corr(par.sma4_local), 100*(d < 0.001).mean()))
parity_ok = (d.max() < 0.001) or (par.forecast_qty.corr(par.sma4_local) > 0.9999)
with open(os.path.join(OUTDIR, 'parity.txt'), 'w', encoding='utf-8') as fo:
    fo.write('pares=%d diff_max=%.6f corr=%.6f pct_lt_0.001=%.2f OK=%s\n' % (
        len(par), d.max(), par.forecast_qty.corr(par.sma4_local), 100*(d < 0.001).mean(), parity_ok))
if not parity_ok:
    raise SystemExit('PARIDAD FALLO: el SMA(4) local no reproduce el server. DETENER.')
print('  GATE OK -> la base local reproduce el server.\n')

# ---------------- FASE 1: clasificar serie (local) + regimen (join) ----------------
# series_type local por combo desde la venta (Syntetos-Boylan)
def classify(series):
    vals = series.values
    active = int((vals > 0).sum())
    if active < MIN_ACTIVE:
        return 'no_signal'
    adi = len(vals) / active
    pos = vals[vals > 0]
    mu = pos.mean()
    cv2 = (pos.var() / (mu * mu)) if mu > 0 else 0.0
    if adi >= ADI_TH:
        return 'lumpy' if cv2 >= CV2_TH else 'intermittent'
    return 'erratic' if cv2 >= CV2_TH else 'smooth'

stype = real_wide.fillna(0.0).apply(classify, axis=1).rename('series_type')   # index=combo

# regimen + abcxyz del export motor (moda por combo)
m = pd.read_csv(SRV_M, encoding='latin-1')
m.columns = [c.strip() for c in m.columns]
m['combo'] = m.product_id.astype(str) + '|' + m.team_id.astype(str)
def mode_or_nan(s):
    s = s.dropna()
    return s.mode().iloc[0] if len(s) else np.nan
reg_by_combo = m.groupby('combo').regimen.agg(mode_or_nan).rename('regimen')
abc_by_combo = m.groupby('combo').abcxyz.agg(mode_or_nan).rename('abcxyz')
seg = pd.concat([stype, reg_by_combo, abc_by_combo], axis=1)
seg['regimen'] = seg['regimen'].fillna('sin_regimen')
print('=== FASE 1 clasificacion ===')
print('series_type (local):'); print(stype.value_counts().to_string())
print('\nregimen (del motor):'); print(seg['regimen'].value_counts().to_string())

# ---------------- FASE 2: candidatos ----------------
def median(k): return Wt.rolling(k, min_periods=k).median().shift(1)
def wma(k):
    w = np.arange(1, k + 1)
    return Wt.rolling(k, min_periods=k).apply(lambda x: np.dot(x, w) / w.sum(), raw=True).shift(1)
def ses(a): return Wt.ewm(alpha=a, adjust=False).mean().shift(1)
def naive(): return Wt.shift(1)

def croston(alpha, sba=False):
    """Croston(1972)/SBA(2005) vectorizado en combos; forecast 1-paso por semana."""
    F = np.full_like(Yv, np.nan)
    z = np.full(n_c, np.nan); pp = np.full(n_c, np.nan); q = np.zeros(n_c)
    started = np.zeros(n_c, dtype=bool)
    for t in range(n_w):
        with np.errstate(invalid='ignore', divide='ignore'):
            f = np.where(started & (pp > 0), z / pp, np.nan)
        F[t] = f
        q += 1.0
        y = Yv[t]
        dem = y > 0
        first = dem & ~started
        z[first] = y[first]; pp[first] = q[first]; started[first] = True; q[first] = 0.0
        upd = dem & started & ~first
        z[upd] = alpha * y[upd] + (1 - alpha) * z[upd]
        pp[upd] = alpha * q[upd] + (1 - alpha) * pp[upd]; q[upd] = 0.0
    out = as_df(F)
    return out * (1 - alpha / 2.0) if sba else out

MODELS = {
    'Naive': naive(), 'SMA(3)': sma(3), 'SMA(4)': sma(4), 'SMA(6)': sma(6),
    'Mediana(4)': median(4), 'WMA(4)': wma(4), 'SES(0.3)': ses(0.3), 'SES(0.5)': ses(0.5),
    'Croston(0.1)': croston(0.1), 'SBA(0.15)': croston(0.15, sba=True),
}

# base larga evaluable: filas de venta reales en semanas con >=MIN_HIST previas
base = v[v.semana.map(idx) >= MIN_HIST][['combo', 'semana', 'ventas']].rename(columns={'ventas': 'real'}).copy()
for name, fwide in MODELS.items():
    s = fwide.stack().rename(name).reset_index(); s.columns = ['semana', 'combo', name]
    base = base.merge(s, on=['semana', 'combo'], how='left')
base = base.merge(seg, left_on='combo', right_index=True, how='left')
base['series_type'] = base['series_type'].fillna('no_signal')
base['regimen'] = base['regimen'].fillna('sin_regimen')

# ---------------- FASE 3: ganador por segmento ----------------
def wape_bias(real, fc):
    m_ = real.notna() & fc.notna()
    r = real[m_]; f = fc[m_]; s = r.sum()
    if s == 0: return np.nan, np.nan, len(r)
    return 100*(f-r).abs().sum()/s, 100*(f.sum()-s)/s, len(r)

MODEL_NAMES = list(MODELS.keys())

def pick_winner(g):
    rows = []
    for name in MODEL_NAMES:
        wa, bi, n = wape_bias(g.real, g[name])
        rows.append((name, wa, bi))
    df = pd.DataFrame(rows, columns=['modelo', 'WAPE', 'BIAS']).dropna()
    elig = df[df.BIAS.abs() <= BIAS_CAP]
    pool = elig if len(elig) else df
    w = pool.sort_values('WAPE').iloc[0]
    return w['modelo'], w['WAPE'], w['BIAS']

def segment_table(segcol, label):
    print('\n=== FASE 3 — ganador por %s (menor WAPE, |BIAS|<=%.0f%%) ===' % (label, BIAS_CAP))
    print('%-13s %-13s %7s %8s %9s' % (label, 'campeon', 'WAPE', 'BIAS', 'real'))
    champs = {}
    for sv_, g in base.groupby(segcol):
        if g.real.sum() == 0: continue
        modelo, wa, bi = pick_winner(g)
        champs[sv_] = modelo
        # comparar vs SMA(4) en el mismo segmento
        wa4, bi4, _ = wape_bias(g.real, g['SMA(4)'])
        flag = '' if modelo == 'SMA(4)' else ('  (SMA4 %.1f%%)' % wa4)
        print('%-13s %-13s %6.1f%% %+7.1f%% %9.0f%s' % (str(sv_)[:13], modelo, wa, bi, g.real.sum(), flag))
    return champs

champ_reg = segment_table('regimen', 'regimen')
champ_st = segment_table('series_type', 'series_type')

# ---------------- ENSEMBLE: campeon por regimen aplicado a cada combo ----------------
base['ens'] = base.apply(lambda r: r[champ_reg.get(r['regimen'], 'SMA(4)')], axis=1)
we, be, _ = wape_bias(base.real, base['ens'])
w4, b4, _ = wape_bias(base.real, base['SMA(4)'])
fva = 100*(w4-we)/w4 if w4 else np.nan
print('\n=== ENSEMBLE (campeon por regimen) vs SMA(4) plano ===')
print('  SMA(4) plano:  WAPE %.1f%%  BIAS %+.1f%%' % (w4, b4))
print('  Ensemble:      WAPE %.1f%%  BIAS %+.1f%%' % (we, be))
print('  FVA ensemble vs SMA(4): %+.1f%%  (%s)' % (fva, 'ensemble gana' if we < w4 else 'SMA4 gana'))

# guardar
rank_rows = []
for segcol, lab in [('regimen', 'regimen'), ('series_type', 'series_type')]:
    for sv_, g in base.groupby(segcol):
        if g.real.sum() == 0: continue
        for name in MODEL_NAMES:
            wa, bi, n = wape_bias(g.real, g[name])
            rank_rows.append({'segmento_tipo': lab, 'segmento': sv_, 'modelo': name,
                              'WAPE': wa, 'BIAS': bi, 'real': g.real.sum(), 'n': n})
pd.DataFrame(rank_rows).to_csv(os.path.join(OUTDIR, 'ranking_segmento.csv'), index=False, encoding='utf-8-sig')
pd.DataFrame([{'segmento': k, 'campeon': v_} for k, v_ in champ_reg.items()]).to_csv(
    os.path.join(OUTDIR, 'champions.csv'), index=False, encoding='utf-8-sig')
print('\nOK: %s/{parity.txt, ranking_segmento.csv, champions.csv}' % OUTDIR)
