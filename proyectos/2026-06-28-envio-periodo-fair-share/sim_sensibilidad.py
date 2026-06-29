# Barrido de sensibilidad: periodo de compra x z (nivel servicio)
# Mide como se mueve el trade-off envios <-> servicio <-> stock.
# READ-ONLY, mismo cache cervezas.
import pandas as pd, numpy as np

REVIEW_D = 7; MIN_VOL = 30; TOPN = 60
df = pd.read_parquet('proyectos/2026-06-01-demand-sensing/pos_daily_cerv.parquet')
df['day'] = pd.to_datetime(df['day'])
days = pd.date_range(df['day'].min(), df['day'].max(), freq='D')
piv = (df.groupby(['product_id','day'])['qty'].sum().unstack(fill_value=0)
         .reindex(columns=days, fill_value=0))
vol = piv.sum(axis=1)
piv = piv.loc[vol[vol>=MIN_VOL].sort_values(ascending=False).head(TOPN).index]

def sim(demand, period_d, z, policy, review_d=REVIEW_D, lead_d=0):
    mu=demand.mean(); sg=demand.std(ddof=0)
    safety=z*sg*np.sqrt(lead_d+review_d); S=period_d*mu+safety
    stock=S; unmet=0.0; ev=0; path=[]
    for t in range(len(demand)):
        if t>0 and t%review_d==0:
            if policy=='actual':
                q=max(0.0,S-stock)
                if q>1e-9: ev+=1; stock=S
            else:
                if stock-mu*review_d<safety:
                    q=max(0.0,S-stock)
                    if q>1e-9: ev+=1; stock=S
        d=demand.iloc[t]; s=min(d,stock); unmet+=d-s; stock-=s; path.append(stock)
    tot=demand.sum()
    return ev, (1-unmet/tot if tot>0 else 1.0), float(np.mean(path))

print("periodo  z    | env_act env_new  red%  | fill_act fill_new  | stock_new vs act")
print("-"*78)
for period_d in [7,15,21,30]:
    for z in [0.84,1.28,1.65]:
        ea=en=0; fa=[]; fn=[]; sa=[]; sn=[]
        for _,row in piv.iterrows():
            e1,f1,s1=sim(row,period_d,z,'actual')
            e2,f2,s2=sim(row,period_d,z,'nuevo')
            ea+=e1; en+=e2; fa.append(f1); fn.append(f2); sa.append(s1); sn.append(s2)
        red=1-en/ea if ea else 0
        print(f"  {period_d:>2}d  {z:>4} | {ea:>6} {en:>7}  {red*100:>3.0f}%  | "
              f"{np.mean(fa)*100:>6.2f}% {np.mean(fn)*100:>6.2f}%  | "
              f"{(np.mean(sn)/np.mean(sa)-1)*100:>+4.0f}%")
    print("-"*78)
