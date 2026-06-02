"""
FVA: HM-SI vs naive SMA(4). Mide si el motor le gana al Excel de promedio-4.

Vara unica: ambos metodos se evaluan contra el mismo real_qty, mismo universo
(core, sin San Jose, sin quiebre en semana target), mismas semanas (05-18, 05-25).
SMA(4) = promedio del real_qty de las 4 semanas previas (replica el Excel).
"""
import json, re, datetime as dt
import pandas as pd, numpy as np

CSV = 'OH Forecast Backtest (x_forecast_backtest) (3).csv'
SO = 'proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'
CORE = ['hm_si_core', 'hm_si_core_a_low_mu', 'hm_si_core_az', 'fair_share_canon']
TARGETS = ['2026-05-18', '2026-05-25']

df = pd.read_csv(CSV)
pat = re.compile(r'\|\s*T(\d+)\s*\|\s*P(\d+)')
m = df['Descripción'].str.extract(pat)
df['team_oid'] = pd.to_numeric(m[0], errors='coerce')
df['prod_oid'] = pd.to_numeric(m[1], errors='coerce')

weeks = sorted(df.target_week_start.unique())
idx = {w: i for i, w in enumerate(weeks)}

# real_qty historico por (prod, team, week) — desde TODO el CSV (venta real, sin
# importar que modelo la pronostico). Una fila por SKUxsalaxsemana.
real = df.groupby(['prod_oid', 'team_oid', 'target_week_start']).real_qty.first()
real_d = real.to_dict()

# set de quiebre por (prod, team, week_start): quiebre cualquier dia de la ventana
so = json.load(open(SO))
wlist = [dt.date.fromisoformat(w) for w in weeks]
excl = set()
for r in so:
    dd = dt.date.fromisoformat(r['d'])
    for w in wlist:
        if w <= dd <= w + dt.timedelta(days=6):
            excl.add((r['p'], r['t'], w.isoformat()))
            break

def sma4(p, t, w):
    """Promedio de las 4 semanas previas, EXCLUYENDO semanas con quiebre
    (censuradas hacia abajo). Requiere >=1 semana limpia con dato."""
    i = idx[w]
    if i < 4:
        return None
    vals = []
    for k in range(1, 5):
        wk = weeks[i - k]
        if (p, t, wk) in excl:        # semana previa con quiebre -> no promedia
            continue
        v = real_d.get((p, t, wk))
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return float(np.mean(vals))

# universo de evaluacion
u = df[df.forecast_model_code.isin(CORE)].copy()
u = u[~u.team_id.str.contains('San Jos', case=False, na=False)]
u = u[u.target_week_start.isin(TARGETS)]
u['sma4'] = u.apply(lambda r: sma4(int(r.prod_oid), int(r.team_oid), r.target_week_start), axis=1)
u['quiebre'] = list(zip(u.prod_oid.astype(int), u.team_oid.astype(int), u.target_week_start))
u['quiebre'] = u['quiebre'].isin(excl)

n0 = len(u)
u = u[u.sma4.notna()]          # solo donde SMA(4) tiene 4 previas
n_sma = len(u)
u = u[~u.quiebre]              # sin quiebre en target
n_final = len(u)

def metrics(real_v, fcst):
    ae = (fcst - real_v).abs().sum()
    wape = 100 * ae / real_v.sum()
    bias = 100 * (fcst.sum() - real_v.sum()) / real_v.sum()
    return wape, bias

w_hm, b_hm = metrics(u.real_qty, u.forecast_qty)
w_sm, b_sm = metrics(u.real_qty, u.sma4)
fva = 100 * (w_sm - w_hm) / w_sm

print(f'Universo: {n0} filas core/target -> {n_sma} con SMA(4) -> {n_final} sin quiebre')
print(f'Real total: {u.real_qty.sum():,.0f}  |  semanas: {TARGETS}')
print()
print(f'{"Metodo":<14} {"WAPE":>8} {"BIAS":>8}')
print(f'{"HM-SI":<14} {w_hm:>7.1f}% {b_hm:>+7.1f}%')
print(f'{"Naive SMA(4)":<14} {w_sm:>7.1f}% {b_sm:>+7.1f}%')
print()
print(f'FVA (WAPE): {fva:+.1f}%  ({"HM-SI gana" if fva>0 else "Excel gana"})')
print()
# agregado SIN REG-1 (regimenes "dificiles": intermitente / erratico / lento)
o = u[u.regimen != 'REG-1']
wh2, bh2 = metrics(o.real_qty, o.forecast_qty)
ws2, bs2 = metrics(o.real_qty, o.sma4)
print(f'SIN REG-1 ({len(o)} obs, real {o.real_qty.sum():,.0f}):')
print(f'  HM-SI       WAPE {wh2:.1f}%  BIAS {bh2:+.1f}%')
print(f'  Naive SMA4  WAPE {ws2:.1f}%  BIAS {bs2:+.1f}%')
print(f'  FVA {100*(ws2-wh2)/ws2:+.1f}%')
print()
# desglose por regimen
print('Por regimen (WAPE HM-SI vs SMA4):')
for r in sorted(u.regimen.unique()):
    g = u[u.regimen == r]
    if g.real_qty.sum() == 0:
        continue
    wh, _ = metrics(g.real_qty, g.forecast_qty)
    ws, _ = metrics(g.real_qty, g.sma4)
    print(f'  {r}: HM-SI {wh:5.1f}% | SMA4 {ws:5.1f}% | FVA {100*(ws-wh)/ws:+5.1f}% | real {g.real_qty.sum():6.0f}')
