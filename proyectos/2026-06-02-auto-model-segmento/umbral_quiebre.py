"""
Umbral para gatillar SMA12: cuantas SEMANAS con quiebre debe tener un combo
(y/o que sean recientes) antes de pasar a SMA largo. 1 dia no deberia bastar.
Mide distribucion de semanas-quiebre por combo y el efecto de varios umbrales.
"""
import pandas as pd, numpy as np, json, re, datetime as dt

VENTAS='proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SO_JSON='proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'
MIN_HIST=6

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
weeks=sorted(v.semana.unique())
real_wide=v.pivot_table(index='combo',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)
meta=v.dropna(subset=['var','t']).drop_duplicates('combo').set_index('combo')
var_of=meta['var'].astype(int).to_dict(); t_of=meta['t'].astype(int).to_dict()
cig_of={c:(v.loc[v.combo==c,'product_id'].iloc[0] in cigprods) for c in real_wide.index}

# semanas con quiebre por combo (var,t)
so=json.load(open(SO_JSON))
wdates=[dt.date.fromisoformat(w) for w in weeks]
combo_qweeks={}   # (var,t) -> set de semanas con quiebre
recent_set=set(weeks[-8:])   # ultimas 8 semanas del historico
for r in so:
    dd=dt.date.fromisoformat(r['d'])
    for w in wdates:
        if w<=dd<=w+dt.timedelta(days=6):
            combo_qweeks.setdefault((r['p'],r['t']),set()).add(w.isoformat())

# por combo de venta: cuantas semanas-quiebre, y si tiene quiebre reciente
rows=[]
for c in real_wide.index:
    key=(var_of.get(c),t_of.get(c))
    qw=combo_qweeks.get(key,set())
    nqw=len(qw)
    recent=len(qw & recent_set)
    rows.append((c,cig_of.get(c,False),nqw,recent))
df=pd.DataFrame(rows,columns=['combo','cig','nqw','recent'])

print('=== Distribucion de SEMANAS con quiebre por combo ===')
print('combos totales:', len(df))
for thr in [1,2,3,4]:
    print('  >=%d sem-quiebre: %5d combos (%.0f%%)  | cigarros: %4d (%.0f%%)'%(
        thr,(df.nqw>=thr).sum(),100*(df.nqw>=thr).mean(),
        (df[df.cig].nqw>=thr).sum(),100*(df[df.cig].nqw>=thr).mean()))
print('  con quiebre en ult.8 sem: %5d (%.0f%%)  | cigarros: %4d'%(
    (df.recent>=1).sum(),100*(df.recent>=1).mean(),(df[df.cig].recent>=1).sum()))
print('  >=2 sem Y reciente:       %5d (%.0f%%)  | cigarros: %4d'%(
    ((df.nqw>=2)&(df.recent>=1)).sum(),100*((df.nqw>=2)&(df.recent>=1)).mean(),
    ((df.cig)&(df.nqw>=2)&(df.recent>=1)).sum()))
print()
print('cigarros: distribucion nqw'); print(df[df.cig].nqw.value_counts().sort_index().to_string())
