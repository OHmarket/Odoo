"""
Cola intermittent/lumpy/no_signal: reemplazar Mediana(4) por SMA largo (como el
motor, que nunca daba ceros). Probar SMA 4/6/8/12 -> % ceros, nivel, WAPE, bias.
Elegir la ventana que mata los ceros sin sobre-stockear. Global y cigarros.
"""
import pandas as pd, numpy as np, re

VENTAS='proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
MIN_HIST=6; MIN_ACTIVE,ADI_TH,CV2_TH=4,1.32,0.49

v=pd.read_csv(VENTAS); v.columns=[c.strip() for c in v.columns]
v=v[~v.team_id.str.contains('San Jos',case=False,na=False)].copy()
v['combo']=v.product_id.astype(str)+'|'+v.team_id.astype(str)
weeks=sorted(v.semana.unique()); idx={w:i for i,w in enumerate(weeks)}
real_wide=v.pivot_table(index='combo',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)
Wt=real_wide.T

def classify(s):
    vals=s.values; pos=vals[vals>0]; act=len(pos); n=len(vals)
    if act<MIN_ACTIVE: return 'no_signal'
    adi=n/act; mu=pos.mean(); cv2=(pos.var()/(mu*mu)) if mu>0 else 0
    if adi>=ADI_TH: return 'lumpy' if cv2>=CV2_TH else 'intermittent'
    return 'erratic' if cv2>=CV2_TH else 'smooth'
stype=real_wide.apply(classify,axis=1)
def median(k): return Wt.rolling(k,min_periods=k).median().shift(1)
def sma(k): return Wt.rolling(k,min_periods=1).mean().shift(1)
M={'MED4':median(4),'SMA4':sma(4),'SMA6':sma(6),'SMA8':sma(8),'SMA12':sma(12)}

e=pd.read_csv(SES_EXP,encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
cigprods=set(e[e.categ_id.astype(str).str.contains('Cigarr|Tabaco',case=False,na=False)].product_id)

base=v[v.semana.map(idx)>=MIN_HIST][['combo','semana','ventas','product_id']].rename(columns={'ventas':'real'}).copy()
for nm,fw in M.items():
    s=fw.stack().rename(nm).reset_index(); s.columns=['semana','combo',nm]
    base=base.merge(s,on=['semana','combo'],how='left')
base['st']=base['combo'].map(stype).fillna('no_signal')
base['cig']=base.product_id.isin(cigprods)
TAIL={'intermittent','lumpy','no_signal'}
tail=base[base.st.isin(TAIL)]
def wb(r,f):
    m=r.notna()&f.notna(); r=r[m]; f=f[m]; s=r.sum(); return (np.nan,np.nan) if s==0 else (100*(f-r).abs().sum()/s,100*(f.sum()-s)/s)

print('=== Cola (intermittent/lumpy/no_signal) — estimador para reabastecer ===')
print('%-8s %8s %8s %8s %9s'%('modelo','%cero','WAPE','BIAS','nivel'))
for nm in ['MED4','SMA4','SMA6','SMA8','SMA12']:
    g=tail.dropna(subset=[nm]); z=100*(g[nm]==0).mean(); w,b=wb(g.real,g[nm])
    print('%-8s %7.1f%% %7.1f%% %+7.1f%% %9.0f'%(nm,z,w,b,g[nm].sum()))

print('\n=== Cola CIGARROS ===')
ct=tail[tail.cig]
print('%-8s %8s %9s'%('modelo','%cero','nivel'))
for nm in ['MED4','SMA4','SMA6','SMA8','SMA12']:
    g=ct.dropna(subset=[nm]); print('%-8s %7.1f%% %9.0f'%(nm,100*(g[nm]==0).mean(),g[nm].sum()))

# desglose por tipo dentro de la cola (que no_signal no se infle de mas)
print('\n=== %cero por series_type (global) MED4 -> SMA8 ===')
for st in ['intermittent','lumpy','no_signal']:
    g=base[base.st==st]
    z0=100*(g['MED4']==0).mean(); z8=100*(g.dropna(subset=['SMA8'])['SMA8']==0).mean()
    n0=g['MED4'].sum(); n8=g['SMA8'].sum()
    print('  %-12s %%cero %4.0f->%4.0f  nivel %6.0f->%6.0f'%(st,z0,z8,n0,n8))
