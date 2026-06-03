"""
Idea Marco: combo con quiebre en el periodo -> SMA largo (12 o 16) en vez del
estimador corto. El SMA largo alcanza la venta normal pre-quiebre y diluye los
ceros censurados, sin Croston ni LOCF. El resto queda en el modelo base.
Mide: % ceros y nivel en cigarros, e impacto global. Solo cigarros marcados con
quiebre vs total.
"""
import pandas as pd, numpy as np, json, re, datetime as dt

VENTAS='proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SO_JSON='proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'
MIN_HIST=6; MIN_ACTIVE,ADI_TH,CV2_TH=4,1.32,0.49

# bridge product_id(name)->var, team->t, y set cigarros, desde el export
e=pd.read_csv(SES_EXP,encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
mm=e[[c for c in e.columns if 'escrip' in c][0]].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
e['t']=pd.to_numeric(mm[0],errors='coerce'); e['pv']=pd.to_numeric(mm[1],errors='coerce')
e=e.dropna(subset=['t','pv'])
def mode(s):
    s=s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
prod2var=e.groupby('product_id')['pv'].agg(lambda s:int(mode(s))).to_dict()
team2t=e.groupby('team_id')['t'].agg(lambda s:int(mode(s))).to_dict()
cigprods=set(e[e.categ_id.astype(str).str.contains('Cigarr|Tabaco',case=False,na=False)].product_id)

v=pd.read_csv(VENTAS); v.columns=[c.strip() for c in v.columns]
v=v[~v.team_id.str.contains('San Jos',case=False,na=False)].copy()
v['combo']=v.product_id.astype(str)+'|'+v.team_id.astype(str)
v['var']=v.product_id.map(prod2var); v['t']=v.team_id.map(team2t)
weeks=sorted(v.semana.unique()); idx={w:i for i,w in enumerate(weeks)}
real_wide=v.pivot_table(index='combo',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)
Wt=real_wide.T

# combo -> (var,t) y cig
meta=v.dropna(subset=['var','t']).drop_duplicates('combo').set_index('combo')
var_of=meta['var'].astype(int).to_dict(); t_of=meta['t'].astype(int).to_dict()
cig_of={c:(v.loc[v.combo==c,'product_id'].iloc[0] in cigprods) for c in real_wide.index}

# combos con quiebre EN EL PERIODO (cualquier sem del window con quiebre)
so=json.load(open(SO_JSON))
so_combos=set()  # (var,t) con algun quiebre en ene-may
for r in so:
    so_combos.add((r['p'],r['t']))
def has_quiebre(combo):
    return (var_of.get(combo), t_of.get(combo)) in so_combos

def median(k): return Wt.rolling(k,min_periods=k).median().shift(1)
def sma(k): return Wt.rolling(k,min_periods=1).mean().shift(1)   # min_periods=1: usa lo que haya
MED4=median(4); S4=sma(4); S12=sma(12); S16=sma(16)

# modelo base simplificado: smooth/erratic ~ SMA4 (proxy reactivo), resto Mediana4
# (para aislar el efecto del override por quiebre; el SES exacto no cambia la lectura)
def classify(s):
    vals=s.values; pos=vals[vals>0]; act=len(pos); n=len(vals)
    if act<MIN_ACTIVE: return 'no_signal'
    adi=n/act; mu=pos.mean(); cv2=(pos.var()/(mu*mu)) if mu>0 else 0
    if adi>=ADI_TH: return 'lumpy' if cv2>=CV2_TH else 'intermittent'
    return 'erratic' if cv2>=CV2_TH else 'smooth'
stype=real_wide.apply(classify,axis=1)

base=v[v.semana.map(idx)>=MIN_HIST][['combo','semana','ventas']].rename(columns={'ventas':'real'}).copy()
for nm,fw in {'MED4':MED4,'S4':S4,'S12':S12,'S16':S16}.items():
    s=fw.stack().rename(nm).reset_index(); s.columns=['semana','combo',nm]
    base=base.merge(s,on=['semana','combo'],how='left')
base['st']=base['combo'].map(stype).fillna('no_signal')
base['cig']=base['combo'].map(cig_of).fillna(False)
base['q']=base['combo'].map(has_quiebre).fillna(False)

# estimador base (sin override): SMA4 si smooth/erratic, Mediana4 resto
base['BASE']=np.where(base.st.isin(['smooth','erratic']),base['S4'],base['MED4'])
# con override: combo con quiebre -> SMA largo
base['OV12']=np.where(base.q,base['S12'],base['BASE'])
base['OV16']=np.where(base.q,base['S16'],base['BASE'])

def stats(g,col):
    gg=g.dropna(subset=[col]); z=100*(gg[col]==0).mean(); return z,gg[col].sum()
print('=== Cigarros: %% ceros y nivel (combos-sem con MIN_HIST) ===')
cg=base[base.cig]
print('combos-sem cigarros:', len(cg), '| con quiebre en periodo:', cg.q.sum(), '(%.0f%%)'%(100*cg.q.mean()))
for col,lab in [('BASE','base (sin override)'),('OV12','quiebre->SMA12'),('OV16','quiebre->SMA16')]:
    z,n=stats(cg,col); print('  %-22s %%cero %5.1f%%  nivel %6.0f'%(lab,z,n))
print()
print('=== Cigarros CON quiebre (los que el override toca) ===')
cq=base[base.cig & base.q]
for col,lab in [('MED4','Mediana4'),('S4','SMA4'),('S12','SMA12'),('S16','SMA16')]:
    z,n=stats(cq,col); print('  %-10s %%cero %5.1f%%  nivel %6.0f'%(lab,z,n))
print()
print('=== Global (todos los productos) ===')
def wb(r,f):
    m=r.notna()&f.notna(); r=r[m]; f=f[m]; s=r.sum(); return (np.nan,np.nan) if s==0 else (100*(f-r).abs().sum()/s,100*(f.sum()-s)/s)
for col,lab in [('BASE','base'),('OV12','quiebre->SMA12'),('OV16','quiebre->SMA16')]:
    w,b=wb(base.real,base[col]); print('  %-18s WAPE %.1f%%  BIAS %+.1f%%'%(lab,w,b))
print('  combos con quiebre en periodo: %d / %d (%.0f%%)'%(base.q.sum(),len(base),100*base.q.mean()))
