# Mide stock TOTAL de la cadena (CD + sala) bajo dos politicas CD->sala.
# Dos escalones: proveedor -> CD -> sala.
#
# CLAVE: la cadena ordena al proveedor con el MISMO target total en ambas
# politicas (cada `delay` dias, order-up-to S_chain sobre la posicion total).
# Asi el suministro total es identico y aislo el REPARTO CD<->sala.
#
# Politicas CD->sala (review cada 3d, cadencia real):
#   LEAN (actual): sala target = 1 semana, base-stock (topa cada vez).
#   FULL (nuevo) : sala target = delay (15d), safety sobre 7d, s,S (drena).
#
# Mide: stock prom total, split CD vs sala, fill en sala, eventos CD-limitado.
# READ-ONLY, cache cervezas agregada (1 sala agregada -> NO captura de-pooling
# de safety por N salas; eso necesita pull por sala, item aparte).
import pandas as pd, numpy as np

DELAY_D=15; L_SUP=3; REVIEW_D=3; Z=1.28; MIN_VOL=30; TOPN=60
WARMUP=20
df=pd.read_parquet(r'd:/Desarrollo/Odoo/proyectos/2026-06-01-demand-sensing/pos_daily_cerv.parquet')
df['day']=pd.to_datetime(df['day']); days=pd.date_range(df['day'].min(),df['day'].max(),freq='D'); H=len(days)
piv=df.groupby(['product_id','day'])['qty'].sum().unstack(fill_value=0).reindex(columns=days,fill_value=0)
vol=piv.sum(axis=1); piv=piv.loc[vol[vol>=MIN_VOL].sort_values(ascending=False).head(TOPN).index]

def run(demand, policy):
    mu=demand.mean(); sg=demand.std(ddof=0)
    # target total de la cadena vs proveedor (igual en ambas politicas)
    S_chain = DELAY_D*mu + Z*sg*np.sqrt(DELAY_D+L_SUP)
    # target sala segun politica
    if policy=='LEAN':
        sala_work=7;       sala_safety=Z*sg*np.sqrt(7)
    else: # FULL
        sala_work=DELAY_D; sala_safety=Z*sg*np.sqrt(7)   # safety sobre 7d (Marco)
    S_sala = sala_work*mu + sala_safety

    # init: total en S_chain, sala a su target, resto en CD
    sala = min(S_sala, S_chain); cd = max(S_chain - sala, 0.0)
    intransit=[]  # (arrival_day, qty)
    cd_path=[]; sala_path=[]; unmet=0.0; cd_limited=0
    for t in range(H):
        # llega pedido del proveedor
        arr=[q for (d,q) in intransit if d==t]; cd+=sum(arr)
        intransit=[(d,q) for (d,q) in intransit if d>t]
        # CD ordena al proveedor cada DELAY (echelon: posicion total)
        if t%DELAY_D==0:
            pos = cd + sala + sum(q for _,q in intransit)
            order=max(0.0, S_chain - pos)
            if order>1e-9: intransit.append((t+L_SUP, order))
        # review sala -> pide al CD
        if t%REVIEW_D==0:
            if policy=='LEAN':
                need = max(0.0, S_sala - sala)
            else:
                need = max(0.0, S_sala - sala) if (sala - mu*REVIEW_D) < sala_safety else 0.0
            ship=min(need, cd)
            if need>1e-9 and ship < need - 1e-9: cd_limited+=1
            cd-=ship; sala+=ship
        # venta
        d=demand.iloc[t]; served=min(d,sala); unmet+=d-served; sala-=served
        cd_path.append(cd); sala_path.append(sala)
    tot=demand.sum()
    sl=slice(WARMUP,None)
    return dict(cd=np.mean(cd_path[sl]), sala=np.mean(sala_path[sl]),
                total=np.mean(np.array(cd_path[sl])+np.array(sala_path[sl])),
                fill=(1-unmet/tot if tot>0 else 1.0), cd_lim=cd_limited)

rows=[]
for pid,row in piv.iterrows():
    L=run(row,'LEAN'); F=run(row,'FULL')
    rows.append(dict(L_cd=L['cd'],L_sala=L['sala'],L_tot=L['total'],L_fill=L['fill'],L_lim=L['cd_lim'],
                     F_cd=F['cd'],F_sala=F['sala'],F_tot=F['total'],F_fill=F['fill'],F_lim=F['cd_lim']))
R=pd.DataFrame(rows)
print(f"=== Dos escalones: stock TOTAL cadena (CD+sala) | delay={DELAY_D}d sup_lead={L_SUP}d z={Z} | {len(R)} SKUs ===\n")
print(f"{'':28s} {'CD':>7s} {'Sala':>7s} {'TOTAL':>7s} {'fill':>8s}")
print('-'*60)
print(f"{'LEAN (actual, sala=1sem)':28s} {R.L_cd.mean():>7.0f} {R.L_sala.mean():>7.0f} {R.L_tot.mean():>7.0f} {R.L_fill.mean()*100:>7.2f}%")
print(f"{'FULL (nuevo, sala=15d s,S)':28s} {R.F_cd.mean():>7.0f} {R.F_sala.mean():>7.0f} {R.F_tot.mean():>7.0f} {R.F_fill.mean()*100:>7.2f}%")
print(f"{'Δ':28s} {(R.F_cd.mean()/R.L_cd.mean()-1)*100:>+6.0f}% {(R.F_sala.mean()/R.L_sala.mean()-1)*100:>+6.0f}% {(R.F_tot.mean()/R.L_tot.mean()-1)*100:>+6.0f}%")
print(f"\n  Stock total cadena: LEAN {R.L_tot.mean():.0f}  vs  FULL {R.F_tot.mean():.0f}  -> {(R.F_tot.mean()/R.L_tot.mean()-1)*100:+.1f}%")
print(f"  Reparto: hoy CD={R.L_cd.mean()/R.L_tot.mean()*100:.0f}% / sala={R.L_sala.mean()/R.L_tot.mean()*100:.0f}%   ->   nuevo CD={R.F_cd.mean()/R.F_tot.mean()*100:.0f}% / sala={R.F_sala.mean()/R.F_tot.mean()*100:.0f}%")
print(f"  Eventos CD-limitado (no pudo surtir): LEAN {int(R.L_lim.sum())}  FULL {int(R.F_lim.sum())}")
