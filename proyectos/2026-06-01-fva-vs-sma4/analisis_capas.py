"""
Analisis de capas del motor (4 semanas may-04..may-25, backtest fresco XLSX).

Pregunta 1: las capas de correccion (trend v3.43 + bias-outlier v3.48) AYUDAN o
            EMPEORAN? -> comparar forecast_qty (final) vs mu_week_pre_bias
            (antes de trend+bias-outlier) contra real.
Pregunta 2: el motor CORE le gana al SMA(4) en estas 4 semanas?
Pregunta 3: apagar las capas (usar mu_week_pre_bias) le ganaria al SMA(4)?

SMA(4) se calcula desde el CSV (4) (tiene historia ene->abr). Motor y capas desde
el XLSX fresco. Join por (product_id, team_id, semana). Solo CORE, sin San Jose.
"""
import pandas as pd, numpy as np

XLSX = 'OH Forecast Backtest (x_forecast_backtest).xlsx'
CSV4 = 'OH Forecast Backtest (x_forecast_backtest) (4).csv'
CORE = ['hm_si_core', 'hm_si_core_a_low_mu', 'hm_si_core_az', 'fair_share_canon']

# --- motor fresco (4 sem) ---
x = pd.read_excel(XLSX)
x.columns = [c.strip() for c in x.columns]
x['semana'] = pd.to_datetime(x['target_week_start']).dt.strftime('%Y-%m-%d')
x = x[['product_id', 'team_id', 'semana', 'real_qty', 'forecast_qty',
       'mu_week_pre_bias', 'forecast_model_code', 'regimen']].copy()

# --- SMA(4) desde el CSV (4) con historia larga ---
c = pd.read_csv(CSV4, usecols=['product_id', 'team_id', 'target_week_start', 'real_qty'])
c['combo'] = c['product_id'].astype(str) + '|' + c['team_id'].astype(str)
weeks = sorted(c['target_week_start'].unique())
rw = c.pivot_table(index='combo', columns='target_week_start', values='real_qty', aggfunc='first').reindex(columns=weeks)
sma = (rw.T.rolling(4, min_periods=4).mean().shift(1).T).stack().rename('sma4').reset_index()
sma.columns = ['combo', 'semana', 'sma4']

x['combo'] = x['product_id'].astype(str) + '|' + x['team_id'].astype(str)
x = x.merge(sma, on=['combo', 'semana'], how='left')

# universo: core, sin San Jose, con SMA4 disponible
u = x[x.forecast_model_code.isin(CORE)].copy()
u = u[~u['team_id'].str.contains('San Jos', case=False, na=False)]
print(f'core (4 sem): {len(u):,} filas | con SMA4: {u.sma4.notna().sum():,}')
u = u[u.sma4.notna()]
print(f'real total: {u.real_qty.sum():,.0f}  semanas: {sorted(u.semana.unique())}\n')


def metrics(real_v, fcst):
    m = real_v.notna() & fcst.notna()
    r = real_v[m]; f = fcst[m]; s = r.sum()
    if s == 0:
        return np.nan, np.nan
    return 100 * (f - r).abs().sum() / s, 100 * (f.sum() - s) / s


def fva(ws, wh):
    return 100 * (ws - wh) / ws if ws and not np.isnan(ws) else np.nan


ws, bs = metrics(u.real_qty, u.sma4)
wp, bp = metrics(u.real_qty, u.mu_week_pre_bias)
wf, bf = metrics(u.real_qty, u.forecast_qty)
print(f'{"":30}{"WAPE":>8}{"BIAS":>8}{"FVA vs SMA4":>13}')
print(f'{"SMA(4) [campeon]":30}{ws:>7.1f}%{bs:>+7.1f}%{0.0:>+12.1f}%')
print(f'{"Motor SIN capas (pre_bias)":30}{wp:>7.1f}%{bp:>+7.1f}%{fva(ws,wp):>+12.1f}%')
print(f'{"Motor FINAL (forecast_qty)":30}{wf:>7.1f}%{bf:>+7.1f}%{fva(ws,wf):>+12.1f}%')
print()
print(f'Efecto de las capas (trend + bias-outlier): BIAS {bp:+.1f}% -> {bf:+.1f}%  '
      f'({"INFLA" if bf>bp else "desinfla"} {bf-bp:+.1f}pp)')
delta = (u.forecast_qty - u.mu_week_pre_bias)
print(f'  suma delta forecast-pre_bias: {delta.sum():+,.0f} u ({100*delta.sum()/u.mu_week_pre_bias.sum():+.1f}%)')
print(f'  filas que INFLA: {(delta>0.01).sum():,} | desinfla: {(delta<-0.01).sum():,} | igual: {(delta.abs()<=0.01).sum():,}')
print()

print('Por modelo (FVA vs SMA4):')
print(f'  {"modelo":<22}{"WAPE_f":>8}{"BIAS_f":>8}{"FVA_final":>10}{"FVA_sin_capas":>14}{"real":>9}')
for mc in CORE:
    g = u[u.forecast_model_code == mc]
    if len(g) == 0 or g.real_qty.sum() == 0:
        continue
    wsg, _ = metrics(g.real_qty, g.sma4)
    wfg, bfg = metrics(g.real_qty, g.forecast_qty)
    wpg, _ = metrics(g.real_qty, g.mu_week_pre_bias)
    print(f'  {mc:<22}{wfg:>7.1f}%{bfg:>+7.1f}%{fva(wsg,wfg):>+9.1f}%{fva(wsg,wpg):>+13.1f}%{g.real_qty.sum():>9,.0f}')
print()
print('Por regimen (FVA vs SMA4):')
print(f'  {"reg":<7}{"FVA_final":>10}{"FVA_sin_capas":>14}{"BIAS_final":>11}{"real":>9}')
for r in sorted(u.regimen.dropna().unique()):
    g = u[u.regimen == r]
    if g.real_qty.sum() == 0:
        continue
    wsg, _ = metrics(g.real_qty, g.sma4)
    wfg, bfg = metrics(g.real_qty, g.forecast_qty)
    wpg, _ = metrics(g.real_qty, g.mu_week_pre_bias)
    print(f'  {r:<7}{fva(wsg,wfg):>+9.1f}%{fva(wsg,wpg):>+13.1f}%{bfg:>+10.1f}%{g.real_qty.sum():>9,.0f}')
