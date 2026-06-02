"""
NIVEL de forecast de la categoria Cigarros: crudo (SES censurado) vs de-censurado,
comparado con la venta promedio. Objetivo: ver cuanto sub-estima el SES por quiebre
(no es error de modelo, es demanda no observada). Para REABASTECER importa el nivel,
no el WAPE (el real del backtest tambien esta censurado).
"""
import pandas as pd, numpy as np, json, re, datetime as dt

VENTAS='proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SO_JSON='proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'
MIN_ACTIVE,ADI_TH,CV2_TH=4,1.32,0.49

e=pd.read_csv(SES_EXP, encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
dcol=[c for c in e.columns if 'escrip' in c][0]
mm=e[dcol].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
e['t']=pd.to_numeric(mm[0],errors='coerce'); e['pv']=pd.to_numeric(mm[1],errors='coerce')
e=e.dropna(subset=['t','pv'])
def mode(s):
    s=s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
prod2var=e.groupby('product_id')['pv'].agg(lambda s:int(mode(s))).to_dict()
team2t=e.groupby('team_id')['t'].agg(lambda s:int(mode(s))).to_dict()
# set de combos cigarros (var|t) por categoria
cig=e[e.categ_id.astype(str).str.contains('Cigarr|Tabaco', case=False, na=False)].copy()
cig_ck=set(cig['pv'].astype(int).astype(str)+'|'+cig['t'].astype(int).astype(str))
print('combos cigarros:', len(cig_ck))

v=pd.read_csv(VENTAS); v.columns=[c.strip() for c in v.columns]
v=v[~v.team_id.str.contains('San Jos',case=False,na=False)].copy()
v['var']=v.product_id.map(prod2var); v['t']=v.team_id.map(team2t)
v=v.dropna(subset=['var','t']); v['var']=v['var'].astype(int); v['t']=v['t'].astype(int)
v['ck']=v['var'].astype(str)+'|'+v['t'].astype(str)
weeks=sorted(v.semana.unique())
pivot=v.pivot_table(index='ck',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)

so=json.load(open(SO_JSON))
wdates=[dt.date.fromisoformat(w) for w in weeks]
so_week=set()
for r in so:
    dd=dt.date.fromisoformat(r['d'])
    for w in wdates:
        if w<=dd<=w+dt.timedelta(days=6): so_week.add(('%d|%d'%(r['p'],r['t']),w.isoformat()))

def classify(vals):
    pos=[x for x in vals if x>0]; act=len(pos); n=len(vals)
    if act<MIN_ACTIVE: return 'no_signal'
    adi=n/act; mu=sum(pos)/act
    if mu<=0: return 'no_signal'
    cv2=(sum((x-mu)**2 for x in pos)/act)/(mu*mu)
    if adi>=ADI_TH: return 'lumpy' if cv2>=CV2_TH else 'intermittent'
    return 'erratic' if cv2>=CV2_TH else 'smooth'
def ses(vals,a):
    lvl=None
    for y in vals: lvl=y if lvl is None else a*y+(1-a)*lvl
    return lvl or 0.0
def med(seq):
    s=sorted(seq); k=len(s)
    return 0.0 if k==0 else (s[k//2] if k%2 else (s[k//2-1]+s[k//2])/2)
def a_for(st):
    if st=='smooth': return 0.6
    if st=='erratic': return 0.7
    return None

# forecast al ultimo cutoff: input = TODAS las semanas (cierra 05-25 -> pronostica sig)
cig_in=[ck for ck in pivot.index if ck in cig_ck]
tot_avg=tot_raw=tot_locf=tot_medns=0.0
n_so_weeks=tot_weeks=0
for ck in cig_in:
    full=[(w,pivot.loc[ck,w]) for w in weeks]
    vals=[y for _,y in full]
    avg=sum(vals)/len(vals)
    # crudo
    st=classify(vals); a=a_for(st)
    raw=ses(vals,a) if a is not None else med(vals[-4:])
    # de-censura LOCF
    vl=[]; last=None
    for (w,y) in full:
        if (ck,w) in so_week: vl.append(last if last is not None else y)
        else: vl.append(y); last=y
    stl=classify(vl); al=a_for(stl)
    locf=ses(vl,al) if al is not None else med(vl[-4:])
    # de-censura mediana de no-quiebre (estima demanda no restringida, sin arrastrar el pico)
    obs=[y for (w,y) in full if (ck,w) not in so_week and y>0]
    fill=med(obs) if obs else 0.0
    vm=[(fill if (ck,w) in so_week else y) for (w,y) in full]
    stm=classify(vm); am=a_for(stm)
    medns=ses(vm,am) if am is not None else med(vm[-4:])
    tot_avg+=avg; tot_raw+=raw; tot_locf+=locf; tot_medns+=medns
    for (w,y) in full:
        tot_weeks+=1
        if (ck,w) in so_week: n_so_weeks+=1

print('\\n%% semanas-combo en quiebre (cigarros): %.1f%%'%(100*n_so_weeks/tot_weeks))
print('\\n=== NIVEL de forecast categoria Cigarros (u/semana, %d combos) ==='%len(cig_in))
print('  venta PROMEDIO historica   : %8.0f'%tot_avg)
print('  forecast SES crudo         : %8.0f   (%.0f%% de la venta prom)'%(tot_raw,100*tot_raw/tot_avg))
print('  forecast LOCF (de-censura) : %8.0f   (%.0f%%)'%(tot_locf,100*tot_locf/tot_avg))
print('  forecast Mediana-noQuiebre : %8.0f   (%.0f%%)'%(tot_medns,100*tot_medns/tot_avg))
print('\\n  lift de-censura vs crudo: LOCF %+.0f u (%+.0f%%) | Med-noQ %+.0f u (%+.0f%%)'%(
    tot_locf-tot_raw,100*(tot_locf-tot_raw)/tot_raw, tot_medns-tot_raw,100*(tot_medns-tot_raw)/tot_raw))