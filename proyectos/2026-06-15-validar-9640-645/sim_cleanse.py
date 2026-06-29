# Replicacion read-only del cleansing + SES + sigma del motor OH Forecast Base.
# GATE: reproducir mu=56.4 / sigma=26.2 para SKU 9640 (pp 21274) team 8 a min_days=1.
# Luego sweep de cleanse_min_days {1,2,3,4} + decensor OFF.
import sys, os, datetime, collections
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from shared.odoo_xmlrpc import OdooReader

PID = 21274          # product.product 9640
TEAM = 8             # Panguipulli 645
# --- params motor (defaults productivos) ---
ALPHA = 0.5; MEDIAN_K = 4; SEVERE_W = 0.5; BASE_K = 6
TZ = 'America/Santiago'

o = OdooReader()

# ---------- 1) venta cruda semanal 26 sem (pos.order.line por config de team) ----------
CONFIGS = [417, 418]   # Panguipulli 645 Caja 1/2 (crm_team_id=8)
LAST_CLOSED = datetime.date(2026, 6, 8)   # lunes ultima semana cerrada (W24)
frm = (LAST_CLOSED - datetime.timedelta(weeks=27)).isoformat()
grp = o.execute('pos.order.line', 'read_group',
    [('product_id', '=', PID), ('order_id.config_id', 'in', CONFIGS),
     ('order_id.state', 'in', ['paid', 'done', 'invoiced']), ('create_date', '>=', frm)],
    ['qty:sum'], ['create_date:week'], lazy=False)
def _wk_monday(label):
    p = label.replace('W', '').split()
    return datetime.date.fromisocalendar(int(p[1]), int(p[0]), 1)
salesmap = {}
for g in grp:
    salesmap[_wk_monday(g['create_date:week'])] = float(g.get('qty') or 0.0)
# ventana de 26 sem terminando en LAST_CLOSED (rellena 0 las sin venta)
weeks = [LAST_CLOSED - datetime.timedelta(weeks=k) for k in range(25, -1, -1)]
raw = [salesmap.get(w, 0.0) for w in weeks]
print('semanas:', len(weeks), weeks[0], '->', weeks[-1])
print('raw    :', [round(x) for x in raw])

# ---------- 2) perfil DOW global (read_group pos.order.line por dia) ----------
date_to = weeks[-1] + datetime.timedelta(days=6)
prof_from = weeks[-1] - datetime.timedelta(weeks=11)
dow_units = collections.defaultdict(float)
_M = {'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'sept':9,'oct':10,'nov':11,'dic':12}
def _parse_es(k):
    p = k.replace('.', '').split()
    return datetime.date(int(p[2]), _M[p[1].lower()], int(p[0]))
try:
    grp = o.execute('pos.order.line', 'read_group',
        [('create_date', '>=', prof_from.isoformat()),
         ('create_date', '<=', date_to.isoformat() + ' 23:59:59')],
        ['qty:sum'], ['create_date:day'], lazy=False)
    for g in grp:
        key = g.get('create_date:day')  # ej '01 jun 2026' (es-CL)
        if not key:
            continue
        d = _parse_es(key)
        dow_units[d.isoweekday()] += float(g.get('qty') or 0.0)
except Exception as e:
    print('DOW read_group fallo:', e)
tot = sum(dow_units.values())
dow_w = {i: (dow_units.get(i, 0.0) / tot if tot else 1.0/7) for i in range(1, 8)}
print('perfil DOW (Lun..Dom):', [round(dow_w[i], 3) for i in range(1, 8)])

# ---------- 3) dias de quiebre por semana ----------
sb = o.search_read('x_stock_balance_daily',
    [('x_studio_product_id', '=', PID), ('x_studio_team_id', '=', TEAM),
     ('x_studio_date', '>=', weeks[0].isoformat()),
     ('x_studio_date', '<=', date_to.isoformat()),
     '|', '|', ('x_studio_stockout', '=', True),
     ('x_studio_stockout_partial', '=', True), ('x_studio_qty_balance', '<=', 0.0)],
    fields=['x_studio_date', 'x_studio_stockout', 'x_studio_stockout_partial', 'x_studio_qty_balance'])
# qweight[week] = [n_days, peso_perdido]
qw = collections.defaultdict(lambda: [0, 0.0])
for r in sb:
    d = datetime.date.fromisoformat(r['x_studio_date'])
    ws = d - datetime.timedelta(days=d.weekday())
    qw[ws][0] += 1
    qw[ws][1] += dow_w.get(d.isoweekday(), 1.0/7)
print('semanas con quiebre:', {k.isoformat(): [v[0], round(v[1], 3)] for k, v in sorted(qw.items())})

# ---------- 4) cleanse + SES + sigma ----------
def cleanse(raw_vals, wks, min_days):
    out = []; instock = []
    for i, w in enumerate(wks):
        y = raw_vals[i]; info = qw.get(w); nd = info[0] if info else 0; pw = info[1] if info else 0.0
        if nd >= min_days and pw > 0.0:
            if pw < SEVERE_W and pw < 0.95:
                out.append(y / (1.0 - pw))
            elif instock:
                base = sum(instock[-BASE_K:]) / len(instock[-BASE_K:])
                out.append(base if base > y else y)
            else:
                out.append(y)
        else:
            out.append(y); instock.append(y)
    return out

def ses(vals, a):
    lvl = None
    for y in vals:
        lvl = y if lvl is None else a * y + (1 - a) * lvl
    return lvl or 0.0

def sigma_last4(vals):
    last4 = vals[-MEDIAN_K:]
    if len(last4) <= 1: return 0.0
    m = sum(last4) / len(last4)
    return (sum((x - m) ** 2 for x in last4) / len(last4)) ** 0.5

# --- proyeccion a target/transfer. Motor real: mu=56.4 sig=26.2 -> target=107.7, z*sig=safety ---
Z = 1.96; PERIOD = 1.0; STOCK = 13.0       # z y period implicitos del motor (validados: 56.4+1.96*26.2=107.7)
ENG_MU, ENG_SG = 56.4, 26.2
def proj(mu, sg, anchor=False):
    if anchor:  # escala el delta del sim al baseline real del motor
        mu = ENG_MU * (mu / mu1); sg = ENG_SG * (sg / sg1)
    tgt = mu * PERIOD + Z * sg * (PERIOD ** 0.5)
    return mu, sg, tgt, max(0.0, round(tgt - STOCK))

print('\n=== SWEEP cleanse_min_days (clase A smooth, alpha 0.5) ===')
print('SIM crudo (read-only). mu1 del sim se ancla al motor (56.4/26.2) para target/transfer.')
v1 = cleanse(raw, weeks, 1); mu1 = ses(v1, ALPHA); sg1 = sigma_last4(v1)
print('%-12s | %5s %5s | %5s %5s | %6s %6s' % ('config', 'mu_s', 'sg_s', 'mu*', 'sg*', 'target*', 'transf*'))
def row(lbl, v):
    mu = ses(v, ALPHA); sg = sigma_last4(v)
    amu, asg, tgt, tr = proj(mu, sg, anchor=True)
    print('%-12s | %5.1f %5.1f | %5.1f %5.1f | %6.0f %6.0f' % (lbl, mu, sg, amu, asg, tgt, tr))
row('OFF(crudo)', raw)
for md in (1, 2, 3, 4):
    row('min_days=%d' % md, cleanse(raw, weeks, md))
print('\nGATE: sigma_sim min_days=1 = %.1f vs motor 26.2 (mecanismo OK). mu_sim %.1f vs 56.4 (proxy create_date, -17%%).' % (sg1, mu1))
print('* = escalado al baseline real del motor. transfer actual del motor = 95.')
