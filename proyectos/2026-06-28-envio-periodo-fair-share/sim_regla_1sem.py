# Test: que pasa al eliminar la regla de 1 semana CD. 3 escenarios.
#   A) ACTUAL          : base-stock target=1sem (sala_H=1.0), topa cada visita.
#   B) SOLO QUITAR REGLA: base-stock target=periodo (sala_H=period), MISMO reorden
#                         pegado al target -> topa igual de seguido. (cambio de 1 linea)
#   C) (s,S) PERIODICO : target=periodo PERO reorden bajo (drena el periodo, recarga).
#                         = quitar regla + abrir hueco s<<S. (el diseno completo)
# READ-ONLY, cache cervezas. review=3d (cadencia real camion).
import pandas as pd, numpy as np

PERIOD_D=15; REVIEW_D=3; Z=1.28; MIN_VOL=30; TOPN=60
df = pd.read_parquet('proyectos/2026-06-01-demand-sensing/pos_daily_cerv.parquet')
df['day']=pd.to_datetime(df['day'])
days=pd.date_range(df['day'].min(),df['day'].max(),freq='D'); H=len(days)
piv=(df.groupby(['product_id','day'])['qty'].sum().unstack(fill_value=0).reindex(columns=days,fill_value=0))
vol=piv.sum(axis=1); piv=piv.loc[vol[vol>=MIN_VOL].sort_values(ascending=False).head(TOPN).index]

def sim(demand, work_d, react_d, mode):
    # mode 'base' = topa a S cuando stock<S (reorden pegado al target).
    # mode 'ssS'  = solo recarga a S cuando proyeccion a prox review < safety (hueco).
    mu=demand.mean(); sg=demand.std(ddof=0)
    safety=Z*sg*np.sqrt(react_d); S=work_d*mu+safety
    stock=S; unmet=0.0; ev=0; path=[]
    for t in range(len(demand)):
        if t>0 and t%REVIEW_D==0:
            if mode=='base':
                if S-stock>1e-9: ev+=1; stock=S            # topa siempre que baje del target
            else:
                if stock-mu*REVIEW_D<safety and S-stock>1e-9: ev+=1; stock=S
        d=demand.iloc[t]; s=min(d,stock); unmet+=d-s; stock-=s; path.append(stock)
    tot=demand.sum()
    return ev, (1-unmet/tot if tot>0 else 1.0), float(np.mean(path))

scen = {
 'A_actual_1sem'   : dict(work=7,        react=7, mode='base'),
 'B_solo_quita_regla':dict(work=PERIOD_D, react=3, mode='base'),
 'C_ssS_periodico' : dict(work=PERIOD_D, react=3, mode='ssS'),
}
agg={k:dict(ev=0,fill=[],stk=[]) for k in scen}
for _,row in piv.iterrows():
    for k,p in scen.items():
        e,f,s=sim(row,p['work'],p['react'],p['mode'])
        agg[k]['ev']+=e; agg[k]['fill'].append(f); agg[k]['stk'].append(s)

base_ev=agg['A_actual_1sem']['ev']; base_stk=np.mean(agg['A_actual_1sem']['stk'])
print(f"=== Eliminar regla 1 semana CD | period={PERIOD_D}d review={REVIEW_D}d | {len(piv)} SKUs, {H}d ===\n")
print(f"{'escenario':22s} {'envios':>7s} {'vs A':>6s} | {'fill':>7s} | {'stock':>7s} {'vs A':>6s}")
print('-'*64)
for k in scen:
    ev=agg[k]['ev']; fl=np.mean(agg[k]['fill'])*100; st=np.mean(agg[k]['stk'])
    print(f"{k:22s} {ev:>7} {(ev/base_ev-1)*100:>+5.0f}% | {fl:>6.2f}% | {st:>7.0f} {(st/base_stk-1)*100:>+5.0f}%")
print("\nLectura:")
print("  B vs A = SOLO eliminar la regla de 1 semana (cambio de 1 linea)")
print("  C vs A = eliminar regla + abrir hueco reorden<<target (diseno completo)")
