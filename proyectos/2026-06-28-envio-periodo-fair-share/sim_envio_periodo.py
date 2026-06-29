# Simulador POC: politica "envio del periodo (s,S)" vs "rellenar cada semana" (actual)
# READ-ONLY. Usa cache diario pos_daily_cerv.parquet (cervezas, 93 dias, demanda
# agregada cadena por producto). NO toca produccion.
#
# Objetivo: medir si la politica nueva baja el numero de ENVIOS (preparaciones)
# manteniendo el fill rate, vs el modelo actual que topa la sala cada semana.
#
# Modelos (canon revision periodica / min-max):
#   ACTUAL  : base-stock continuo. Cada review (7d) topa hasta S = period*mu + safety.
#   NUEVO   : (s,S) periodico. En cada review solo dispara envio si la proyeccion
#             a la proxima review perfora el safety. Si no, no manda nada.
#   safety = z * sigma_d * sqrt(period_d)
#
# Parametros de la corrida (las palancas reales):
PERIOD_D   = 15      # periodo de compra del producto (dias) -- ejemplo de Marco
REVIEW_D   = 3       # cadencia REAL del camion (medida: 2-3d). Comprometida = 3d.
Z          = 1.28    # nivel de servicio (~90% ciclo). Palanca. ABCXYZ no esta en este cache.
MIN_VOL    = 30      # solo SKUs con venta total >= esto (comparacion significativa)
TOPN       = 60      # top productos por volumen

import pandas as pd, numpy as np

df = pd.read_parquet('proyectos/2026-06-01-demand-sensing/pos_daily_cerv.parquet')
df['day'] = pd.to_datetime(df['day'])
days = pd.date_range(df['day'].min(), df['day'].max(), freq='D')
H = len(days)

# grilla completa producto x dia (dias sin fila = 0 demanda)
piv = (df.groupby(['product_id','day'])['qty'].sum()
         .unstack(fill_value=0).reindex(columns=days, fill_value=0))

# filtro volumen + top N
vol = piv.sum(axis=1)
keep = vol[vol >= MIN_VOL].sort_values(ascending=False).head(TOPN).index
piv = piv.loc[keep]

def simulate(demand, work_d, react_d, review_d, z, policy, lead_d=0):
    # work_d  = horizonte de stock de trabajo (cuanto cubre el target)
    # react_d = horizonte del safety (intervalo de reaccion)
    # BASELINE REAL: work_d=7 (sala_H=1sem), react_d=7 (safety sqrt(1sem)).
    # NUEVO       : work_d=period (15d), react_d=3 (cadencia real camion).
    mu_d  = demand.mean()
    sig_d = demand.std(ddof=0)
    safety = z * sig_d * np.sqrt(lead_d + react_d)
    S = work_d * mu_d + safety
    stock = S
    unmet = 0.0
    events = 0
    units = 0.0
    stock_path = []
    for t in range(len(demand)):
        # review al inicio del dia (cada review_d dias, incluido dia 0 ya pre-cargado)
        if t > 0 and t % review_d == 0:
            if policy == 'actual':
                q = max(0.0, S - stock)
                if q > 1e-9:
                    events += 1; units += q; stock = S
            else:  # nuevo (s,S): solo si no llega a la proxima review
                proj_next = stock - mu_d * review_d
                if proj_next < safety:
                    q = max(0.0, S - stock)
                    if q > 1e-9:
                        events += 1; units += q; stock = S
        d = demand.iloc[t]
        served = min(d, stock)
        unmet += (d - served)
        stock -= served
        stock_path.append(stock)
    tot = demand.sum()
    fill = 1.0 - unmet / tot if tot > 0 else 1.0
    return dict(events=events, units=units, fill=fill,
                stockout_days=int(((demand.values > 0) & (np.array(stock_path) <= 0)).sum()),
                avg_stock=float(np.mean(stock_path)), S=S, safety=safety, mu_d=mu_d)

rows = []
for pid, row in piv.iterrows():
    # actual real: target 1 semana, safety sqrt(1sem), topa cada visita (3d)
    a = simulate(row, 7,        7, REVIEW_D, Z, 'actual')
    # nuevo: target periodo (15d), safety sqrt(3d), envio del periodo
    n = simulate(row, PERIOD_D, 3, REVIEW_D, Z, 'nuevo')
    rows.append(dict(product_id=pid, vol=row.sum(),
        ev_act=a['events'], ev_new=n['events'],
        fill_act=a['fill'], fill_new=n['fill'],
        stk_act=a['avg_stock'], stk_new=n['avg_stock']))
R = pd.DataFrame(rows)

print(f"=== POC envio del periodo vs actual | period={PERIOD_D}d review={REVIEW_D}d z={Z} | {len(R)} SKUs ===\n")
print("ENVIOS (preparaciones) en {} dias:".format(H))
print(f"  Actual (topa cada semana) : {R.ev_act.sum():>6.0f}  (prom {R.ev_act.mean():.1f}/SKU)")
print(f"  Nuevo  (envio del periodo): {R.ev_new.sum():>6.0f}  (prom {R.ev_new.mean():.1f}/SKU)")
red = 1 - R.ev_new.sum()/R.ev_act.sum()
print(f"  -> reduccion de envios     : {red*100:.0f}%\n")
print("FILL RATE (servicio):")
print(f"  Actual: {R.fill_act.mean()*100:.2f}%   Nuevo: {R.fill_new.mean()*100:.2f}%   delta {(R.fill_new.mean()-R.fill_act.mean())*100:+.2f}pp\n")
print("STOCK PROMEDIO en sala (unidades):")
print(f"  Actual: {R.stk_act.mean():.1f}   Nuevo: {R.stk_new.mean():.1f}   ({(R.stk_new.mean()/R.stk_act.mean()-1)*100:+.0f}%)\n")

print("Detalle top 12 por volumen:")
det = R.sort_values('vol', ascending=False).head(12).copy()
det['fill_act'] = (det.fill_act*100).round(1); det['fill_new'] = (det.fill_new*100).round(1)
det['stk_act'] = det.stk_act.round(0); det['stk_new'] = det.stk_new.round(0); det['vol']=det.vol.round(0)
print(det.to_string(index=False))

R.to_csv('proyectos/2026-06-28-envio-periodo-fair-share/resultados/poc_envio_periodo.csv', index=False)
