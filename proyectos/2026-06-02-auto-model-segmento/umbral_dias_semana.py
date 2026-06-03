"""
Refina el trigger: una semana cuenta como QUIEBRE si tuvo >= min_dias dias de
quiebre (no 1). Mide cuantos combos quedan con varias definiciones:
  - semana-quiebre = >=1 dia / >=4 dias (mayoria) / =7 dias (completa)
  - combo gatilla si >= K semanas-quiebre
"""
import pandas as pd, numpy as np, json, re, datetime as dt

SES_EXP='OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SO_JSON='proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'

e=pd.read_csv(SES_EXP,encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
mm=e[[c for c in e.columns if 'escrip' in c][0]].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
e['t']=pd.to_numeric(mm[0],errors='coerce'); e['pv']=pd.to_numeric(mm[1],errors='coerce')
e=e.dropna(subset=['t','pv'])
cigp=set(e[e.categ_id.astype(str).str.contains('Cigarr|Tabaco',case=False,na=False)][['pv','t']].apply(lambda r:(int(r['pv']),int(r['t'])),axis=1))

so=json.load(open(SO_JSON))
# dias de quiebre por (combo, semana)
days=pd.DataFrame(so)  # cols p,t,d
days['wk']=pd.to_datetime(days['d']).dt.to_period('W-SUN').dt.start_time
dpw=days.groupby(['p','t','wk']).size().rename('ndays').reset_index()   # dias de quiebre esa semana

def combos_for(min_dias, min_weeks):
    qw=dpw[dpw.ndays>=min_dias]
    cnt=qw.groupby(['p','t']).size()
    combos=set(cnt[cnt>=min_weeks].index)
    return combos

print('=== Combos que gatillan SMA12 segun definicion de semana-quiebre ===')
print('%-32s %8s %8s'%('definicion','combos','cigarros'))
for md,mw,lab in [(1,1,'>=1 dia, >=1 sem (actual orig)'),
                  (1,2,'>=1 dia, >=2 sem'),
                  (4,1,'>=4 dias (mayoria), >=1 sem'),
                  (4,2,'>=4 dias, >=2 sem'),
                  (7,1,'7 dias (semana COMPLETA), >=1 sem'),
                  (7,2,'7 dias, >=2 sem')]:
    cb=combos_for(md,mw); cg=len(cb & cigp)
    print('  %-30s %8d %8d'%(lab,len(cb),cg))

print('\n=== Distribucion dias-de-quiebre por semana (todas las combo-sem con quiebre) ===')
print(dpw.ndays.value_counts().sort_index().to_string())
print('\ntotal combo-semanas con algun quiebre:', len(dpw))
print('combo-semanas con 7 dias (completa):', (dpw.ndays==7).sum(), '(%.0f%%)'%(100*(dpw.ndays==7).mean()))
