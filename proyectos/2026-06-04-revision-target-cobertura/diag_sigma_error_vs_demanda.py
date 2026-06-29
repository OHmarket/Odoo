# DIAG READ-ONLY (correr en Odoo, Server Action) — NO escribe nada, solo log().
# Compara, sobre las series reales de 26 sem, el SAFETY que sale de:
#   sigma_demanda  = std(4 ult sem)         <- proxy de HOY (motor v1.5)
#   sigma_error    = 1.25 * MAD in-sample   <- metodo SAP (error del modelo SES/SMA)
# y agrega el efecto por ABCXYZ con el z productivo. H=1 (safety = z*sigma).
# Reusa el query de venta combo-expandido del OH Forecast Base. Venta CRUDA
# (sin cleansing) para que la comparacion demanda-vs-error sea sobre el mismo input.
# ============================================================
TZ_NAME = 'America/Santiago'
DEMAND_WINDOW_WEEKS = 26
MEDIAN_K = 4
SMA_TAIL_WEEKS = 6
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49
MIN_ACTIVE_WEEKS = 4
ALPHA_SMOOTH_A = 0.5
ALPHA_SMOOTH_BC = 0.6
ALPHA_ERRATIC = 0.7
MAD_TO_SIGMA = 1.25
FILTERED_TEAM_IDS = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
Z = {'AX':2.05,'BX':2.05,'AY':2.05,'BY':1.28,'AZ':1.04,
     'BZ':0.35,'CX':0.84,'CY':0.35,'CZ':0.0}

def _sf(v, d=0.0):
    try: return float(v)
    except Exception: return d
def _si(v, d=0):
    try: return int(v)
    except Exception: return d
def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())

def classify(vals):
    n=0; active=0; total=0.0
    for x in vals:
        n+=1
        if x>0.0: active+=1; total+=x
    if active < MIN_ACTIVE_WEEKS: return 'no_signal'
    adi = float(n)/active if active else 0.0
    if adi<=0: return 'no_signal'
    mu = total/active
    if mu<=0: return 'no_signal'
    sq=0.0
    for x in vals:
        if x>0.0:
            d=x-mu; sq+=d*d
    cv2=(sq/active)/(mu*mu)
    interm = adi>=ADI_THRESHOLD; hv = cv2>=CV2_THRESHOLD
    if interm: return 'lumpy' if hv else 'intermittent'
    return 'erratic' if hv else 'smooth'

def mad_ses(vals, alpha):
    # |error| 1-paso in-sample del SES
    level=None; errs=[]
    for y in vals:
        if level is None:
            level=y
        else:
            errs.append(abs(y-level))
            level=alpha*y+(1.0-alpha)*level
    return (sum(errs)/len(errs)) if errs else 0.0

def mad_sma(vals, k):
    # |error| 1-paso in-sample del SMA(k): forecast = media de las k previas
    errs=[]
    for t in range(1, len(vals)):
        prev = vals[max(0,t-k):t]
        f = sum(prev)/len(prev) if prev else 0.0
        errs.append(abs(vals[t]-f))
    return (sum(errs)/len(errs)) if errs else 0.0

company = env.company
env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
today_local = env.cr.fetchone()[0]
cur_ws = _week_start(today_local)
last_closed_monday = cur_ws - datetime.timedelta(weeks=1)
window_weeks = [last_closed_monday - datetime.timedelta(weeks=k)
                for k in range(DEMAND_WINDOW_WEEKS-1, -1, -1)]
window_from = window_weeks[0]
date_to = last_closed_monday + datetime.timedelta(days=6)

pt_fields = env['product.template']._fields or {}
dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'
pc_fields = env['pos.config']._fields or {}
team_col = 'pc.crm_team_id' if (pc_fields.get('crm_team_id') and pc_fields['crm_team_id'].comodel_name=='crm.team') else 'pc.team_id'

params = {'company_id': company.id, 'date_from': window_from, 'date_to': date_to,
          'tz': TZ_NAME, 'team_ids': FILTERED_TEAM_IDS}
sql = """
WITH base AS (
  SELECT {tc} AS team_id, pol.id AS line_id, pol.combo_parent_id,
         pp.id AS product_id, {dt} AS dtype,
         date_trunc('week', po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS week,
         COALESCE(pol.qty,0.0) AS qty
  FROM pos_order_line pol
  JOIN pos_order po ON po.id=pol.order_id
  LEFT JOIN pos_session ps ON ps.id=po.session_id
  LEFT JOIN pos_config pc ON pc.id=ps.config_id
  JOIN product_product pp ON pp.id=pol.product_id
  JOIN product_template pt ON pt.id=pp.product_tmpl_id
  WHERE po.company_id=%(company_id)s AND po.state IN ('paid','done','invoiced')
    AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(date_from)s
    AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
    AND pp.active=TRUE AND pt.sale_ok=TRUE AND pt.active=TRUE
    AND {tc} IS NOT NULL AND {tc} = ANY(%(team_ids)s)
),
standalone AS (
  SELECT team_id, product_id, week, SUM(qty) AS units FROM base
  WHERE combo_parent_id IS NULL AND COALESCE(dtype,'') NOT IN ('combo','service')
  GROUP BY 1,2,3),
combo_children AS (
  SELECT c.team_id, c.product_id, c.week, SUM(c.qty) AS units
  FROM base c JOIN base p ON p.line_id=c.combo_parent_id
  WHERE c.combo_parent_id IS NOT NULL AND COALESCE(c.dtype,'')<>'service'
  GROUP BY 1,2,3)
SELECT team_id, product_id, week, SUM(units) AS units
FROM (SELECT * FROM standalone UNION ALL SELECT * FROM combo_children) su
GROUP BY 1,2,3
""".format(tc=team_col, dt=dtype_sql)
env.cr.execute(sql, params)
sales={}
for tid,pid,wk,q in env.cr.fetchall():
    tid=_si(tid); pid=_si(pid)
    if not tid or not pid or not wk: continue
    qv=_sf(q); qv=0.0 if qv<0 else qv
    sales.setdefault((tid,pid),{})[wk]=sales.get((tid,pid),{}).get(wk,0.0)+qv

pids=list(set(p for (_t,p) in sales.keys()))
# ABCXYZ completo (codigo de 2 letras) y letra ABC, por producto
abcxyz={}; abc_letter={}
Seg=env['x_calculo_abc_xyz'].sudo()
if pids:
    for rec in Seg.search_read([('x_studio_product_id','in',pids)],
                               ['x_studio_product_id','x_studio_abcxyz']):
        pr=rec.get('x_studio_product_id')
        prid=_si(pr[0] if isinstance(pr,(list,tuple)) else pr)
        code=(str(rec.get('x_studio_abcxyz') or '')).strip().upper()[:2]
        if prid and code:
            abcxyz[prid]=code; abc_letter[prid]=code[:1]

# acumuladores por segmento (dict normal: safe_eval de Odoo prohibe imports)
agg={}
tot_old=0.0; tot_new=0.0
for (tid,pid),wkmap in sales.items():
    vals=[_sf(wkmap.get(w,0.0)) for w in window_weeks]
    last4=vals[-MEDIAN_K:]
    mean4=sum(last4)/len(last4) if last4 else 0.0
    # sigma_demanda sobre 4 sem (proxy de HOY)
    if len(last4)>1:
        sd=(sum((x-mean4)**2 for x in last4)/len(last4))**0.5
    else:
        sd=0.0
    # sigma_demanda sobre 26 sem (CONTROL de ventana: misma metrica, mas datos)
    nn=len(vals)
    m26=sum(vals)/nn if nn else 0.0
    sd26=(sum((x-m26)**2 for x in vals)/nn)**0.5 if nn>1 else 0.0
    # modelo del combo (igual que el motor) -> sigma_error in-sample
    st=classify(vals); abc=abc_letter.get(pid,'')
    if st=='smooth':
        a=ALPHA_SMOOTH_A if abc=='A' else ALPHA_SMOOTH_BC; mad=mad_ses(vals,a)
    elif st=='erratic':
        mad=mad_ses(vals,ALPHA_ERRATIC)
    else:  # intermittent/lumpy/no_signal -> SMA
        mad=mad_sma(vals,SMA_TAIL_WEEKS)
    se=MAD_TO_SIGMA*mad
    code=abcxyz.get(pid,'')
    if code not in Z:   # sin clasificacion -> fuera del comparativo de z
        continue
    z=Z[code]
    so=z*sd; s26=z*sd26; sn=z*se
    g=agg.get(code)
    if g is None:
        g={'n':0,'sd':[],'sd26':[],'se':[],'safe_old':0.0,'safe_26':0.0,'safe_new':0.0}
        agg[code]=g
    g['n']+=1; g['sd'].append(sd); g['sd26'].append(sd26); g['se'].append(se)
    g['safe_old']+=so; g['safe_26']+=s26; g['safe_new']+=sn
    tot_old+=so; tot_new+=sn

def med(xs):
    s=sorted(xs); k=len(s)
    return 0.0 if k==0 else (s[k//2] if k%2 else (s[k//2-1]+s[k//2])/2.0)

log('=== DIAG sigma | safety=z*sigma, H=1 | sd4=demanda4sem(HOY) sd26=demanda26sem(ctrl) se=error_MAD ===', level='info')
log('seg | n | sd4_med | sd26_med | se_med | sd26/sd4(ventana) | se/sd26(metodo) | safe4 | safe26 | safeErr', level='info')
tot26=0.0
for code in ['AX','AY','BX','BY','AZ','CX','BZ','CY','CZ']:
    if code not in agg: continue
    g=agg[code]
    sd4m=med(g['sd']); sd26m=med(g['sd26']); sem=med(g['se'])
    r_win=(sd26m/sd4m) if sd4m>0 else 0.0
    r_met=(sem/sd26m) if sd26m>0 else 0.0
    tot26+=g['safe_26']
    log('%s | %d | %.2f | %.2f | %.2f | %.2f | %.2f | %.0f | %.0f | %.0f' % (
        code, g['n'], sd4m, sd26m, sem, r_win, r_met,
        g['safe_old'], g['safe_26'], g['safe_new']), level='info')
totchg=100.0*(tot_new/tot_old-1) if tot_old>0 else 0.0
log('TOTAL safety  sd4=%.0f  sd26=%.0f  err=%.0f | ventana:%+.1f%% (sd4->sd26) | metodo:%+.1f%% (sd26->err)' % (
    tot_old, tot26, tot_new,
    100.0*(tot26/tot_old-1) if tot_old>0 else 0.0,
    100.0*(tot_new/tot26-1) if tot26>0 else 0.0), level='info')

action = {'type':'ir.actions.client','tag':'display_notification','params':{
    'title':'DIAG sigma_error vs demanda',
    'message':'safety sd4=%.0f -> sd26=%.0f (ventana %+.1f%%) -> err=%.0f (metodo %+.1f%%). Ver log() por segmento. Combos=%d' % (
        tot_old, tot26, 100.0*(tot26/tot_old-1) if tot_old>0 else 0.0,
        tot_new, 100.0*(tot_new/tot26-1) if tot26>0 else 0.0,
        sum(g['n'] for g in agg.values())),
    'type':'success','sticky':True}}
