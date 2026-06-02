"""
FVA con exclusion de quiebre — motor HM-SI vs naive SMA(4).

LIMITE DE DATOS: stockout_full.json solo cubre 2026-04-20 -> 05-31 (6 semanas).
Por eso la exclusion de quiebre solo es valida en ese tramo. Este script evalua
las semanas target dentro de la cobertura del stockout, usando TODO el historico
ene->may para el SMA(4). Para aislar el efecto, imprime el mismo universo de
semanas CON y SIN exclusion de quiebre.

PUENTE DE IDS: el export (4) trae product_id = id de PLANTILLA ([6253]); el
stockout y el real a nivel variante usan id de VARIANTE. Se reconstruye el mapa
plantilla->variante desde el CSV (3) (que trae Descripcion |T..|P..). 8 plantillas
con 2 variantes (0.6%) se dropean por ambiguas. team label->T-oid tambien desde (3).
"""
import re, json, datetime as dt
import pandas as pd, numpy as np

CSV4 = 'OH Forecast Backtest (x_forecast_backtest) (4).csv'
CSV3 = 'OH Forecast Backtest (x_forecast_backtest) (3).csv'
SO = 'proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'

# --- mapas plantilla->variante y team->T-oid desde el CSV (3) ---
d3 = pd.read_csv(CSV3, usecols=['Descripción', 'product_id', 'team_id'])
mm = d3['Descripción'].str.extract(re.compile(r'\|\s*T(\d+)\s*\|\s*P(\d+)'))
d3['T'] = pd.to_numeric(mm[0], errors='coerce')
d3['P'] = pd.to_numeric(mm[1], errors='coerce')
d3['tmpl'] = pd.to_numeric(d3['product_id'].str.extract(r'\[(\d+)\]')[0], errors='coerce')

pairs = d3.dropna(subset=['tmpl', 'P']).drop_duplicates(['tmpl', 'P'])
vcount = pairs.groupby('tmpl')['P'].nunique()
ok_tmpl = vcount[vcount == 1].index                      # solo plantillas 1:1
tmpl2var = pairs[pairs.tmpl.isin(ok_tmpl)].set_index('tmpl')['P'].astype(int).to_dict()
team2t = d3.dropna(subset=['T']).groupby('team_id')['T'].agg(lambda s: int(s.mode().iloc[0])).to_dict()
print(f'mapa plantilla->variante: {len(tmpl2var)} (dropeadas {len(vcount)-len(ok_tmpl)} ambiguas)')
print(f'mapa team->T-oid: {len(team2t)}')

# --- carga (4), puentea ids ---
df = pd.read_csv(CSV4, usecols=['product_id', 'team_id', 'target_week_start',
                                'real_qty', 'forecast_qty', 'regimen'])
df['tmpl'] = pd.to_numeric(df['product_id'].str.extract(r'\[(\d+)\]')[0], errors='coerce')
df['var'] = df['tmpl'].map(tmpl2var)                     # id variante (puente)
df['t'] = df['team_id'].map(team2t)                      # T-oid
df = df[~df['team_id'].str.contains('San Jos', case=False, na=False)].copy()
df = df.dropna(subset=['var', 't'])
df['var'] = df['var'].astype(int); df['t'] = df['t'].astype(int)
df['combo'] = df['var'].astype(str) + '|' + df['t'].astype(str)

weeks = sorted(df['target_week_start'].unique())
idx = {w: i for i, w in enumerate(weeks)}
wlist = [dt.date.fromisoformat(w) for w in weeks]

# --- set de quiebre por (var, t, week_start): quiebre cualquier dia de la ventana ---
so = json.load(open(SO))
so_days = sorted({r['d'] for r in so})
so_cov = (so_days[0], so_days[-1])
excl = set()
for r in so:
    dd = dt.date.fromisoformat(r['d'])
    for w in wlist:
        if w <= dd <= w + dt.timedelta(days=6):
            excl.add((r['p'], r['t'], w.isoformat()))
            break
# semanas target con cobertura de stockout (>= inicio cobertura)
cov_start = dt.date.fromisoformat(so_cov[0])
covered_weeks = [w for w in weeks if dt.date.fromisoformat(w) >= cov_start]
print(f'stockout cubre {so_cov[0]} -> {so_cov[1]} | semanas target cubiertas: {len(covered_weeks)} ({covered_weeks[0]}..{covered_weeks[-1]})')

# --- SMA(4): real_qty de 4 semanas previas. Variante CON exclusion salta previas con quiebre ---
real_wide = df.pivot_table(index='combo', columns='target_week_start', values='real_qty', aggfunc='first')
real_wide = real_wide.reindex(columns=weeks)
sma_plain = (real_wide.T.rolling(4, min_periods=1).mean().shift(1).T).stack().rename('sma_plain').reset_index()

def sma4_excl(combo, w):
    """promedio de las <=4 previas, saltando semanas previas con quiebre."""
    i = idx[w]
    if i < 4:
        return np.nan
    var, t = combo.split('|'); var, t = int(var), int(t)
    vals = []
    for k in range(1, 5):
        wk = weeks[i - k]
        if (var, t, wk) in excl:
            continue
        v = real_wide.at[combo, wk] if combo in real_wide.index else np.nan
        if pd.notna(v):
            vals.append(v)
    return float(np.mean(vals)) if vals else np.nan

df = df.merge(sma_plain, on=['combo', 'target_week_start'], how='left')
df['week_i'] = df['target_week_start'].map(idx)
df['quiebre_target'] = [ (v, t, w) in excl for v, t, w in zip(df['var'], df['t'], df['target_week_start']) ]


def metrics(real_v, fcst):
    if real_v.sum() == 0:
        return float('nan'), float('nan')
    ae = (fcst - real_v).abs().sum()
    return 100*ae/real_v.sum(), 100*(fcst.sum()-real_v.sum())/real_v.sum()

def fva(ws, wh):
    return 100*(ws-wh)/ws if ws else float('nan')

def report(title, sub, fcol, scol):
    wh, bh = metrics(sub.real_qty, sub[fcol])
    ws, bs = metrics(sub.real_qty, sub[scol])
    print(f'\n{title}  (n={len(sub):,}, real={sub.real_qty.sum():,.0f})')
    print(f'  HM-SI       WAPE {wh:5.1f}%  BIAS {bh:+6.1f}%')
    print(f'  Naive SMA4  WAPE {ws:5.1f}%  BIAS {bs:+6.1f}%')
    print(f'  FVA {fva(ws,wh):+.1f}%  ({"HM-SI gana" if wh<ws else "Excel gana"})')

# universo: semanas target cubiertas por stockout, con >=4 previas
base = df[(df.target_week_start.isin(covered_weeks)) & (df.week_i >= 4)].copy()

print('\n' + '='*64)
print(f'UNIVERSO: semanas {covered_weeks[0]}..{covered_weeks[-1]} (cubiertas por stockout)')
print('='*64)

# A) SIN excluir quiebre (sma plain)
report('A) SIN excluir quiebre', base[base.sma_plain.notna()], 'forecast_qty', 'sma_plain')

# B) CON exclusion: fuera filas con quiebre en la semana target + SMA4 salta previas con quiebre
b = base[~base.quiebre_target].copy()
b['sma_excl'] = [sma4_excl(c, w) for c, w in zip(b['combo'], b['target_week_start'])]
b = b[b.sma_excl.notna()]
report('B) CON exclusion de quiebre', b, 'forecast_qty', 'sma_excl')

# desglose por regimen (variante CON exclusion)
print('\nPor regimen (CON exclusion):')
print(f'  {"reg":<7} {"HM-SI":>7} {"SMA4":>7} {"FVA":>7} {"real":>10}')
for r in sorted(b.regimen.dropna().unique()):
    g = b[b.regimen == r]
    if g.real_qty.sum() == 0:
        continue
    wh, _ = metrics(g.real_qty, g.forecast_qty)
    ws, _ = metrics(g.real_qty, g.sma_excl)
    print(f'  {r:<7} {wh:6.1f}% {ws:6.1f}% {fva(ws,wh):+6.1f}% {g.real_qty.sum():10,.0f}')
