# ITEM 1 — Efecto AISLADO de eliminar la regla de 1 semana CD.
# Fiel al codigo: sala_H gobierna target Y safety (lineas 1991-1992).
#   target = mu*sala_H + z*sigma*sqrt(sala_H)
# Eliminar la regla = sala_H: 1.0sem -> period. Infla ambos. Nada mas cambia:
#   reorden pegado al target (base-stock), cadencia actual ~3d.
# READ-ONLY, cache cervezas. Aisla SOLO este cambio (no toca cadencia ni hueco).
import pandas as pd, numpy as np

REVIEW_D=3; Z=1.28; MIN_VOL=30; TOPN=60
df=pd.read_parquet(r'd:/Desarrollo/Odoo/proyectos/2026-06-01-demand-sensing/pos_daily_cerv.parquet')
df['day']=pd.to_datetime(df['day']); days=pd.date_range(df['day'].min(),df['day'].max(),freq='D'); H=len(days)
piv=df.groupby(['product_id','day'])['qty'].sum().unstack(fill_value=0).reindex(columns=days,fill_value=0)
vol=piv.sum(axis=1); piv=piv.loc[vol[vol>=MIN_VOL].sort_values(ascending=False).head(TOPN).index]

def sim(demand, salaH_d):
    # salaH_d en DIAS gobierna target y safety. base-stock: topa a S cuando stock<S.
    mu=demand.mean(); sg=demand.std(ddof=0)
    safety=Z*sg*np.sqrt(salaH_d); S=mu*salaH_d+safety
    stock=S; unmet=0.0; ev=0; path=[]
    for t in range(len(demand)):
        if t>0 and t%REVIEW_D==0 and S-stock>1e-9: ev+=1; stock=S
        d=demand.iloc[t]; s=min(d,stock); unmet+=d-s; stock-=s; path.append(stock)
    tot=demand.sum()
    return dict(ev=ev, fill=(1-unmet/tot if tot>0 else 1.0), stk=float(np.mean(path)),
                work=mu*salaH_d, safety=safety, S=S, mu=mu, sg=sg)

PERIOD_D=15  # delay tipico cerveza (ejemplo). Sensibilidad abajo.
A=[sim(r,7)        for _,r in piv.iterrows()]          # actual: sala_H=1sem
B=[sim(r,PERIOD_D) for _,r in piv.iterrows()]          # regla eliminada: sala_H=period

def agg(L,key): return np.mean([x[key] for x in L])
def tot(L,key): return sum(x[key] for x in L)

print(f"=== ITEM 1: eliminar regla 1sem CD (aislado) | period={PERIOD_D}d, review={REVIEW_D}d, z={Z} | {len(piv)} SKUs ===\n")
print(f"{'':24s} {'envios':>7s} {'fill':>8s} {'stock':>7s} {'  work':>7s} {'safety':>7s}")
print('-'*64)
print(f"{'A actual (sala_H=1sem)':24s} {tot(A,'ev'):>7} {agg(A,'fill')*100:>7.2f}% {agg(A,'stk'):>7.0f} {agg(A,'work'):>7.0f} {agg(A,'safety'):>7.0f}")
print(f"{'B regla eliminada(=15d)':24s} {tot(B,'ev'):>7} {agg(B,'fill')*100:>7.2f}% {agg(B,'stk'):>7.0f} {agg(B,'work'):>7.0f} {agg(B,'safety'):>7.0f}")
print(f"\n  Viajes:  {(tot(B,'ev')/tot(A,'ev')-1)*100:+.0f}%   Stock: {(agg(B,'stk')/agg(A,'stk')-1)*100:+.0f}%   Fill: {(agg(B,'fill')-agg(A,'fill'))*100:+.2f}pp")

# descomposicion del aumento de stock: cuanto es working, cuanto safety
dwork=agg(B,'work')-agg(A,'work'); dsafe=agg(B,'safety')-agg(A,'safety')
print(f"\n  Descomposicion del target extra: working +{dwork:.0f}u  |  safety +{dsafe:.0f}u")

print("\n--- Sensibilidad: efecto segun el periodo (delay del SKU) ---")
print(f"{'period':>7s} {'viajes vsA':>11s} {'stock vsA':>10s} {'fill':>8s}")
for pd_ in [7,10,15,21,30]:
    Bx=[sim(r,pd_) for _,r in piv.iterrows()]
    print(f"{pd_:>6}d {(tot(Bx,'ev')/tot(A,'ev')-1)*100:>+10.0f}% {(agg(Bx,'stk')/agg(A,'stk')-1)*100:>+9.0f}% {agg(Bx,'fill')*100:>7.2f}%")
