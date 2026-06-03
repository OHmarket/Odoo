"""
Cola intermitente: Mediana(4) da forecast 0 (mediana de ceros). Comparar contra
Croston(0.1) y SMA(4) en % de forecast cero, nivel, y WAPE — global y cigarros.
La pregunta: que estimador NO deja la demanda intermitente en cero para comprar.
"""
import pandas as pd, numpy as np, re

VENTAS='proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SRV_M='OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
MIN_HIST=6; MIN_ACTIVE,ADI_TH,CV2_TH=4,1.32,0.49

v=pd.read_csv(VENTAS); v.columns=[c.strip() for c in v.columns]
v=v[~v.team_id.str.contains('San Jos',case=False,na=False)].copy()
v['combo']=v.product_id.astype(str)+'|'+v.team_id.astype(str)
weeks=sorted(v.semana.unique()); idx={w:i for i,w in enumerate(weeks)}
real_wide=v.pivot_table(index='combo',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)
Wt=real_wide.T; Yv=Wt.values; n_w,n_c=Yv.shape
def as_df(a): return pd.DataFrame(a,index=Wt.index,columns=Wt.columns)

def classify(s):
    vals=s.values; pos=vals[vals>0]; act=len(pos); n=len(vals)
    if act<MIN_ACTIVE: return 'no_signal'
    adi=n/act; mu=pos.mean()
    cv2=(pos.var()/(mu*mu)) if mu>0 else 0
    if adi>=ADI_TH: return 'lumpy' if cv2>=CV2_TH else 'intermittent'
    return 'erratic' if cv2>=CV2_TH else 'smooth'
stype=real_wide.apply(classify,axis=1).rename('st')

def median(k): return Wt.rolling(k,min_periods=k).median().shift(1)
def sma(k): return Wt.rolling(k,min_periods=k).mean().shift(1)
def croston(alpha,sba=False):
    F=np.full_like(Yv,np.nan); z=np.full(n_c,np.nan); pp=np.full(n_c,np.nan); q=np.zeros(n_c); st=np.zeros(n_c,dtype=bool)
    for t in range(n_w):
        with np.errstate(invalid='ignore',divide='ignore'):
            F[t]=np.where(st&(pp>0),z/pp,np.nan)
        q+=1; y=Yv[t]; dem=y>0; first=dem&~st
        z[first]=y[first]; pp[first]=q[first]; st[first]=True; q[first]=0
        u=dem&st&~first; z[u]=alpha*y[u]+(1-alpha)*z[u]; pp[u]=alpha*q[u]+(1-alpha)*pp[u]; q[u]=0
    o=as_df(F); return o*(1-alpha/2) if sba else o
MED4=median(4); SMA4=sma(4); CRO=croston(0.1)

# cigarros set
e=pd.read_csv(SES_EXP,encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
mm=e[[c for c in e.columns if 'escrip' in c][0]].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
e['t']=pd.to_numeric(mm[0],errors='coerce'); e['pv']=pd.to_numeric(mm[1],errors='coerce')
cigprods=set(e[e.categ_id.astype(str).str.contains('Cigarr|Tabaco',case=False,na=False)].product_id)

base=v[v.semana.map(idx)>=MIN_HIST][['combo','semana','ventas','product_id']].rename(columns={'ventas':'real'}).copy()
for nm,fw in {'MED4':MED4,'SMA4':SMA4,'CRO':CRO}.items():
    s=fw.stack().rename(nm).reset_index(); s.columns=['semana','combo',nm]
    base=base.merge(s,on=['semana','combo'],how='left')
base['st']=base['combo'].map(stype).fillna('no_signal')
base['cig']=base.product_id.isin(cigprods)
TAIL={'intermittent','lumpy','no_signal'}
tail=base[base.st.isin(TAIL)]
def wb(r,f):
    m=r.notna()&f.notna(); r=r[m]; f=f[m]; s=r.sum()
    return (np.nan,np.nan) if s==0 else (100*(f-r).abs().sum()/s,100*(f.sum()-s)/s)

print('=== Cola intermitente/lumpy/no_signal (estimador para reabastecer) ===')
print('%-10s %8s %8s %8s %8s'%('modelo','%cero','WAPE','BIAS','nivel_u'))
for nm in ['MED4','SMA4','CRO']:
    g=tail.dropna(subset=[nm]); z=100*(g[nm]==0).mean(); w,b=wb(g.real,g[nm])
    print('%-10s %7.1f%% %7.1f%% %+7.1f%% %8.0f'%(nm,z,w,b,g[nm].sum()))

# combinacion: intermittent/lumpy -> Croston ; no_signal -> Mediana (cerca de 0, casi muerto)
def combo_est(row):
    return row['CRO'] if row['st'] in ('intermittent','lumpy') else row['MED4']
tail=tail.copy(); tail['SPLIT']=tail.apply(combo_est,axis=1)
print('\n=== Combinacion: intermittent/lumpy->Croston, no_signal->Mediana ===')
g=tail.dropna(subset=['SPLIT']); z=100*(g['SPLIT']==0).mean(); w,b=wb(g.real,g['SPLIT'])
print('  SPLIT: %%cero %.1f%%  WAPE %.1f%%  BIAS %+.1f%%  nivel %.0f'%(z,w,b,g['SPLIT'].sum()))

print('\n=== Solo CIGARROS cola ===')
ct=tail[tail.cig]
print('combos-sem cola cigarros:', len(ct))
print('%-10s %8s %8s'%('modelo','%cero','nivel_u'))
for nm in ['MED4','SMA4','CRO','SPLIT']:
    g=ct.dropna(subset=[nm]); print('%-10s %7.1f%% %8.0f'%(nm,100*(g[nm]==0).mean(),g[nm].sum()))
# desglose cola cigarros por tipo
print('\ncola cigarros por series_type:')
for st,gg in ct.groupby('st'):
    print('  %-13s combos-sem %5d  median_nivel %6.0f  croston_nivel %6.0f'%(st,len(gg),gg['MED4'].sum(),gg['CRO'].sum()))
