"""
Cleansing por semana (reemplaza semana de quiebre por baseline in-stock trailing,
solo-levanta) y compara el forecast resultante: SES vs SMA vs promedio simple.
Cigarros. Muestra nivel total y reactividad sobre serie LIMPIA vs cruda.
"""
import pandas as pd, numpy as np, json, re, datetime as dt

VENTAS='proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SO_JSON='proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'
MIN_DIAS_SEM=4        # semana cuenta como quiebre si >= 4 dias sin stock
BASE_K=4             # baseline = media de las ultimas K semanas CON stock antes

e=pd.read_csv(SES_EXP,encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
mm=e[[c for c in e.columns if 'escrip' in c][0]].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
e['t']=pd.to_numeric(mm[0],errors='coerce'); e['pv']=pd.to_numeric(mm[1],errors='coerce'); e=e.dropna(subset=['t','pv'])
def mode(s):
    s=s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
prod2var=e.groupby('product_id')['pv'].agg(lambda s:int(mode(s))).to_dict()
team2t=e.groupby('team_id')['t'].agg(lambda s:int(mode(s))).to_dict()
cigprods=set(e[e.categ_id.astype(str).str.contains('Cigarr|Tabaco',case=False,na=False)].product_id)

v=pd.read_csv(VENTAS); v.columns=[c.strip() for c in v.columns]
v=v[~v.team_id.str.contains('San Jos',case=False,na=False)].copy()
v['combo']=v.product_id.astype(str)+'|'+v.team_id.astype(str)
v['var']=v.product_id.map(prod2var); v['t']=v.team_id.map(team2t)
v['cig']=v.product_id.isin(cigprods)
weeks=sorted(v.semana.unique())
rw=v.pivot_table(index='combo',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)
meta=v.dropna(subset=['var','t']).drop_duplicates('combo').set_index('combo')
var_of=meta['var'].astype(int).to_dict(); t_of=meta['t'].astype(int).to_dict()
cig_combos=set(v[v.cig].combo.unique())

# dias de quiebre por (combo,semana)
so=json.load(open(SO_JSON))
d=pd.DataFrame(so)
# semana lunes (W-SUN.start_time = lunes), igual que las semanas de ventas
d['wk']=pd.to_datetime(d['d']).dt.to_period('W-SUN').dt.start_time.dt.strftime('%Y-%m-%d')
dpw=d.groupby(['p','t','wk']).size().rename('nd').reset_index()
print('debug: semanas stock', sorted(dpw.wk.unique())[:3], '... ventas', weeks[:3])
qweek=set((int(r['p']),int(r['t']),r['wk']) for _,r in dpw.iterrows() if r['nd']>=MIN_DIAS_SEM)

qdays={(int(r['p']),int(r['t']),r['wk']):int(r['nd']) for _,r in dpw.iterrows()}
def cleanse(combo, min_dias):
    vals=list(rw.loc[combo].values); key=(var_of.get(combo),t_of.get(combo))
    out=[]; instock=[]; nlift=0
    for i,w in enumerate(weeks):
        is_q=qdays.get((key[0],key[1],w),0)>=min_dias
        if is_q and instock:
            base=np.mean(instock[-BASE_K:])
            nv=max(base, vals[i])
            if nv>vals[i]: nlift+=1
            out.append(nv)
        else:
            out.append(vals[i])
            if not is_q: instock.append(vals[i])
    return out,nlift

def ses(vals,a):
    lvl=None
    for y in vals: lvl=y if lvl is None else a*y+(1-a)*lvl
    return lvl or 0.0
def sma(vals,k):
    w=vals[-k:]; return sum(w)/len(w) if w else 0.0
def prom(vals): return sum(vals)/len(vals) if vals else 0.0

cigs=[c for c in rw.index if c in cig_combos]
raw={c:list(rw.loc[c].values) for c in cigs}
EST=[('SES(0.5)',lambda v:ses(v,0.5)),('SES(0.3)',lambda v:ses(v,0.3)),
     ('SMA(4)',lambda v:sma(v,4)),('SMA(8)',lambda v:sma(v,8)),('Promedio',prom)]

print('=== Nivel forecast cigarros (u/sem): CRUDA vs LIMPIA por umbral de dias/sem ===')
print('cruda (sin cleansing):')
for lab,est in EST: print('  %-10s %.0f'%(lab,sum(est(v) for v in raw.values())))
for md in [1,2,3]:
    res={}; nlift_tot=0
    for c in cigs:
        cl,nl=cleanse(c,md); res[c]=cl; nlift_tot+=nl
    print('\\n--- cleansing semana con >=%d dia(s) de quiebre (semanas levantadas: %d) ---'%(md,nlift_tot))
    for lab,est in EST:
        r=sum(est(v) for v in raw.values()); c=sum(est(v) for v in res.values())
        print('  %-10s %8.0f  (lift %+.0f%% vs cruda)'%(lab,c,100*(c-r)/r if r else 0))
