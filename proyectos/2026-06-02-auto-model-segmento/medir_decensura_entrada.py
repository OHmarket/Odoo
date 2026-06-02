"""
Impacto de la DE-CENSURA DE ENTRADA: el modelo base con input censurado (venta
cruda, incluye semanas de quiebre) vs input de-censurado (excluye semanas de
quiebre del SES/Mediana/clasificacion = trata el quiebre como dato faltante).
Walk-forward sobre las 3 sem target, evaluado SOLO en target SIN quiebre (medicion
limpia, de salida). Limite: stockout cubre Abr20-May31 (afecta input reciente).
"""
import pandas as pd, numpy as np, json, re, datetime as dt

VENTAS = 'proyectos/2026-06-01-fva-vs-sma4/resultados/ventas_semanal.csv'
SES_EXP = 'OH Forecast Backtest (x_forecast_backtest) SES 02-06.csv'
SRV_M   = 'OH Forecast Backtest (x_forecast_backtest) 2026-06-01 SMA4 M.csv'
SO_JSON = 'proyectos/2026-06-01-fva-vs-sma4/stockout_full.json'
MIN_ACTIVE, ADI_TH, CV2_TH = 4, 1.32, 0.49

# ---- puente product_id(str)->var, team_label->t, y regimen, desde el export SES ----
e = pd.read_csv(SES_EXP, encoding='latin-1'); e.columns=[c.strip() for c in e.columns]
dcol=[c for c in e.columns if 'escrip' in c][0]
mm=e[dcol].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
e['t']=pd.to_numeric(mm[0],errors='coerce'); e['pv']=pd.to_numeric(mm[1],errors='coerce')
e=e.dropna(subset=['t','pv'])
def mode(s):
    s=s.dropna(); return s.mode().iloc[0] if len(s) else np.nan
prod2var = e.groupby('product_id')['pv'].agg(lambda s:int(mode(s))).to_dict()
team2t   = e.groupby('team_id')['t'].agg(lambda s:int(mode(s))).to_dict()

m=pd.read_csv(SRV_M, encoding='latin-1'); m.columns=[c.strip() for c in m.columns]
mc=[c for c in m.columns if 'escrip' in c][0]
mm2=m[mc].str.extract(re.compile(r'T(\d+)\s*\|\s*P(\d+)'))
m['t']=pd.to_numeric(mm2[0],errors='coerce'); m['pv']=pd.to_numeric(mm2[1],errors='coerce')
m=m.dropna(subset=['t','pv']); m['ck']=m['pv'].astype(int).astype(str)+'|'+m['t'].astype(int).astype(str)
reg_by_ck = m.groupby('ck').regimen.agg(mode)
abc_by_ck = m.groupby('ck').abcxyz.agg(mode).str[0]

# ---- venta semanal -> bridge a (var,t) ----
v=pd.read_csv(VENTAS); v.columns=[c.strip() for c in v.columns]
v=v[~v.team_id.str.contains('San Jos',case=False,na=False)].copy()
v['var']=v.product_id.map(prod2var); v['t']=v.team_id.map(team2t)
v=v.dropna(subset=['var','t']); v['var']=v['var'].astype(int); v['t']=v['t'].astype(int)
v['ck']=v['var'].astype(str)+'|'+v['t'].astype(str)
weeks=sorted(v.semana.unique()); widx={w:i for i,w in enumerate(weeks)}
pivot=v.pivot_table(index='ck',columns='semana',values='ventas',aggfunc='first').reindex(columns=weeks).fillna(0.0)

# ---- quiebre por (var,t,week) ----
so=json.load(open(SO_JSON))
wdates=[dt.date.fromisoformat(w) for w in weeks]
so_week=set()  # (ck, week_iso)
for r in so:
    dd=dt.date.fromisoformat(r['d'])
    for w in wdates:
        if w<=dd<=w+dt.timedelta(days=6):
            so_week.add(('%d|%d'%(r['p'],r['t']), w.isoformat()))

# ---- modelos ----
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
def alpha_for(st,abc):
    if st=='smooth': return 0.5 if abc=='A' else 0.6
    if st=='erratic': return 0.7
    return None

TARGETS=['2026-05-11','2026-05-18','2026-05-25']
cks=pivot.index.tolist()
rows=[]
for tw in TARGETS:
    ti=widx[tw]
    in_weeks=weeks[:ti]                    # cerradas antes del target
    for ck in cks:
        if (ck,tw) in so_week:             # target con quiebre -> excluir (de-censura SALIDA)
            continue
        real=pivot.loc[ck,tw]
        full=[(w,pivot.loc[ck,w]) for w in in_weeks]
        if real==0 and sum(y for _,y in full)==0:
            continue
        abc=abc_by_ck.get(ck,'');
        # A: censurado (todas las semanas)
        valsA=[y for _,y in full]
        stA=classify(valsA); aA=alpha_for(stA,abc)
        fA=ses(valsA,aA) if aA is not None else med(valsA[-4:])
        # B: de-censurado EXCLUYENDO semanas de quiebre del input
        valsB=[y for (w,y) in full if (ck,w) not in so_week]
        if len(valsB)<2: valsB=valsA
        stB=classify(valsB); aB=alpha_for(stB,abc)
        fB=ses(valsB,aB) if aB is not None else med(valsB[-4:])
        # C: imputa mediana de no-quiebre (>0)
        obs=[y for (w,y) in full if (ck,w) not in so_week and y>0]
        fill=med(obs) if obs else 0.0
        valsC=[(fill if ((ck,w) in so_week) else y) for (w,y) in full]
        stC=classify(valsC); aC=alpha_for(stC,abc)
        fC=ses(valsC,aC) if aC is not None else med(valsC[-4:])
        # D: LOCF - replica el ultimo valor observado ANTES del quiebre (naive estable)
        valsD=[]; last_obs=None
        for (w,y) in full:
            if (ck,w) in so_week:
                valsD.append(last_obs if last_obs is not None else y)
            else:
                valsD.append(y); last_obs=y
        stD=classify(valsD); aD=alpha_for(stD,abc)
        fD=ses(valsD,aD) if aD is not None else med(valsD[-4:])
        rows.append((ck,tw,real,max(fA,0),max(fB,0),max(fC,0),max(fD,0),reg_by_ck.get(ck,'sin_regimen')))

df=pd.DataFrame(rows,columns=['ck','tw','real','fA','fB','fC','fD','reg'])
def wb(r,f):
    s=r.sum(); return 100*np.abs(f-r).sum()/s, 100*(f.sum()-s)/s
wa,ba=wb(df.real,df.fA); wbb,bb=wb(df.real,df.fB); wc,bc=wb(df.real,df.fC); wd,bd=wb(df.real,df.fD)
print('=== De-censura ENTRADA (target SIN quiebre, %d obs, real %.0f) ==='%(len(df),df.real.sum()))
print('  A input CENSURADO        : WAPE %.2f%%  BIAS %+.2f%%'%(wa,ba))
print('  B excluye sem quiebre    : WAPE %.2f%%  BIAS %+.2f%%  (d %+.2f / %+.2f)'%(wbb,bb,wbb-wa,bb-ba))
print('  C imputa mediana         : WAPE %.2f%%  BIAS %+.2f%%  (d %+.2f / %+.2f)'%(wc,bc,wc-wa,bc-ba))
print('  D LOCF (valor pre-quiebre): WAPE %.2f%%  BIAS %+.2f%%  (d %+.2f / %+.2f)'%(wd,bd,wd-wa,bd-ba))
print()
print('por regimen (WAPE A->D | BIAS A->D):')
for rg in ['REG-1','REG-4','REG-8','REG-7','REG-0']:
    g=df[df.reg==rg]
    if not len(g) or g.real.sum()==0: continue
    wa,ba=wb(g.real,g.fA); wd,bd=wb(g.real,g.fD)
    print('  %-6s real %7.0f  WAPE %5.1f->%5.1f  BIAS %+6.1f->%+6.1f'%(rg,g.real.sum(),wa,wd,ba,bd))
