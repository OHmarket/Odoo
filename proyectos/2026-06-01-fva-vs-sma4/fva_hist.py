"""
FVA historico ene->may: motor HM-SI (forecast_qty, salida unica) vs naive SMA(4).

Version SIMPLE (primer corte): SIN analisis de quiebre, SIN filtro de modelo.
- Universo: todas las filas del backtest, excluyendo solo Ventas San Jose.
- forecast_qty = salida final del motor para cada (SKU, sala, semana), sea cual
  sea la rama interna (core / min_stock / secondary). Es el "motor complejo".
- SMA(4) = promedio del real_qty de las 4 semanas calendario previas del mismo
  combo (replica el Excel de promedio-4). min_periods=1.
- Solo se evaluan semanas con >=4 semanas previas en el historico.
- Se reporta el total, el desglose por regimen, y una linea aparte para las
  filas con forecast_qty=0 (motor que no pronostico) para no confundir
  "pronostica mal" con "no pronostica".

Vara unica: ambos metodos contra el mismo real_qty, mismo universo, mismas semanas.
"""
import re
import pandas as pd
import numpy as np

CSV = 'OH Forecast Backtest (x_forecast_backtest) (4).csv'

df = pd.read_csv(CSV, usecols=['product_id', 'team_id', 'target_week_start',
                               'real_qty', 'forecast_qty', 'regimen'])

# id de SKU desde "[6253] NOMBRE"; combo = SKU x sala
df['prod_oid'] = pd.to_numeric(df['product_id'].str.extract(r'\[(\d+)\]')[0], errors='coerce')
df['combo'] = df['prod_oid'].astype('Int64').astype(str) + '|' + df['team_id'].astype(str)

# excluir San Jose (guia estandar de lectura del backtest)
df = df[~df['team_id'].str.contains('San Jos', case=False, na=False)].copy()

# orden de semanas
weeks = sorted(df['target_week_start'].unique())
idx = {w: i for i, w in enumerate(weeks)}

# --- SMA(4) vectorizado: pivot combo x semana sobre real_qty, rolling 4 shift 1 ---
real_wide = df.pivot_table(index='combo', columns='target_week_start',
                           values='real_qty', aggfunc='first')
real_wide = real_wide.reindex(columns=weeks)           # asegura orden cronologico
# rolar sobre el eje de semanas: transpongo (semanas en el index), rolling, shift, vuelvo
sma_wide = real_wide.T.rolling(window=4, min_periods=1).mean().shift(1).T
sma_long = sma_wide.stack().rename('sma4').reset_index()
df = df.merge(sma_long, on=['combo', 'target_week_start'], how='left')

# universo evaluable: semanas con >=4 previas (desde la 5a semana del historico)
df['week_i'] = df['target_week_start'].map(idx)
u = df[(df['week_i'] >= 4) & df['sma4'].notna()].copy()


def metrics(real_v, fcst):
    if real_v.sum() == 0:
        return float('nan'), float('nan')
    ae = (fcst - real_v).abs().sum()
    wape = 100 * ae / real_v.sum()
    bias = 100 * (fcst.sum() - real_v.sum()) / real_v.sum()
    return wape, bias


def fva(ws, wh):
    return 100 * (ws - wh) / ws if ws else float('nan')


n_total = len(df)
n_eval = len(u)
print(f'Filas totales (sin San Jose): {n_total:,}')
print(f'Evaluables (>=4 previas, con SMA4): {n_eval:,}')
print(f'Semanas: {weeks[0]} -> {weeks[-1]}  ({len(weeks)} semanas, evaluables {len(weeks)-4})')
print(f'Real total: {u.real_qty.sum():,.0f}')
print()

w_hm, b_hm = metrics(u.real_qty, u.forecast_qty)
w_sm, b_sm = metrics(u.real_qty, u.sma4)
print(f'{"Metodo":<14} {"WAPE":>8} {"BIAS":>8}')
print(f'{"HM-SI (motor)":<14} {w_hm:>7.1f}% {b_hm:>+7.1f}%')
print(f'{"Naive SMA(4)":<14} {w_sm:>7.1f}% {b_sm:>+7.1f}%')
print(f'\nFVA (WAPE): {fva(w_sm, w_hm):+.1f}%  ({"HM-SI gana" if w_hm < w_sm else "Excel gana"})')
print()

# filas donde el motor entrego 0 (no pronostico) — reportadas aparte
z = u[u.forecast_qty == 0]
nz = u[u.forecast_qty != 0]
print(f'--- forecast_qty=0 (motor no pronostico): {len(z):,} filas, real {z.real_qty.sum():,.0f} ---')
if len(z):
    wz, bz = metrics(z.real_qty, z.sma4)
    print(f'  En esas filas el SMA(4) daria WAPE {wz:.1f}% BIAS {bz:+.1f}% (el motor pierde {z.real_qty.sum():,.0f} u de venta)')
print()
print(f'--- excluyendo forecast_qty=0 ({len(nz):,} filas, real {nz.real_qty.sum():,.0f}) ---')
wh2, bh2 = metrics(nz.real_qty, nz.forecast_qty)
ws2, bs2 = metrics(nz.real_qty, nz.sma4)
print(f'  HM-SI       WAPE {wh2:5.1f}%  BIAS {bh2:+6.1f}%')
print(f'  Naive SMA4  WAPE {ws2:5.1f}%  BIAS {bs2:+6.1f}%')
print(f'  FVA {fva(ws2, wh2):+.1f}%')
print()

# desglose por regimen
print('Por regimen (universo completo):')
print(f'  {"reg":<7} {"HM-SI":>7} {"SMA4":>7} {"FVA":>7} {"real":>10}')
for r in sorted(u.regimen.dropna().unique()):
    g = u[u.regimen == r]
    if g.real_qty.sum() == 0:
        continue
    wh, _ = metrics(g.real_qty, g.forecast_qty)
    ws, _ = metrics(g.real_qty, g.sma4)
    print(f'  {r:<7} {wh:6.1f}% {ws:6.1f}% {fva(ws, wh):+6.1f}% {g.real_qty.sum():10,.0f}')
