# DIAG read-only: compara 3 politicas de target sobre el snapshot actual.
#   BASE  = z actual
#   Z168  = los segmentos con z=2.05 bajan a 1.68
#   CAP   = cap freq+3d (techo duro)
# Mide: inventario objetivo $ y nivel de servicio implitico por segmento.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd, numpy as np
from math import erf, sqrt
from shared.odoo_xmlrpc import OdooReader

def phi(z):  # normal CDF
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))
phi_v = np.vectorize(phi)

Z_HOY = {'AX':2.05,'BX':2.05,'AY':2.05,'BY':1.28,'AZ':1.04,
         'BZ':0.35,'CX':0.84,'CY':0.35,'CZ':0.0}
Z_DOWN = 1.68          # nuevo z para los que hoy estan en 2.05
BUFFER_W = 3.0/7.0

o = OdooReader()
FLOOR = 1.0/4.345
fields = ['x_studio_abcxyz','x_studio_mu_week','x_studio_sigma_week',
          'x_studio_safety_stock_units','x_studio_reorder_target_weeks',
          'x_studio_target_units','x_studio_purchase_price_cash_unit']
dom = [('x_studio_mu_week','>',FLOOR),('x_studio_reorder_target_weeks','>',0.0)]
rows, off = [], 0
while True:
    b = o.search_read('x_analisis_de_stock', dom, fields, limit=5000, offset=off)
    rows += b
    if len(b) < 5000: break
    off += 5000

df = pd.DataFrame(rows)
for c in fields[1:]:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
df['seg'] = df['x_studio_abcxyz'].replace('', 'sin')
mu, sig = df['x_studio_mu_week'], df['x_studio_sigma_week']
safe, tgtw = df['x_studio_safety_stock_units'], df['x_studio_reorder_target_weeks']
price = df['x_studio_purchase_price_cash_unit']
df['cob_w'] = tgtw - np.where(mu>0, safe/mu, 0.0)   # H ~ freq
df['z_hoy'] = df['seg'].map(Z_HOY).fillna(0.84)
rootH = np.sqrt(df['cob_w'].clip(lower=0.01))

# safety en unidades por escenario
df['safe_base'] = safe
df['safe_z168'] = np.where(df['z_hoy']>=2.04, safe*(Z_DOWN/2.05), safe)  # solo baja los 2.05
df['tgt_base_u'] = df['x_studio_target_units']
df['tgt_z168_u'] = (df['cob_w']*mu + df['safe_z168']).clip(lower=0)
cap_u = (df['cob_w'] + BUFFER_W) * mu
df['tgt_cap_u'] = np.minimum(df['tgt_base_u'], cap_u)
df['safe_cap']  = (df['tgt_cap_u'] - df['cob_w']*mu).clip(lower=0)

# nivel de servicio implicito por escenario: phi(safety_u / (sigma*sqrt(H)))
denom = (sig*rootH).replace(0, np.nan)
for sc, scol in [('base','safe_base'),('z168','safe_z168'),('cap','safe_cap')]:
    zeff = (df[scol]/denom)
    df['svc_'+sc] = np.where(sig<=0, 1.0, phi_v(zeff.fillna(5).clip(-5,5)))

def fmt_m(x): return f'{x/1e6:7.2f}'  # millones
print('=== INVENTARIO OBJETIVO (millones $, costo) por escenario ===')
inv = pd.DataFrame({
    'BASE': df['tgt_base_u']*price,
    'Z168': df['tgt_z168_u']*price,
    'CAP':  df['tgt_cap_u']*price,
}).groupby(df['seg']).sum()
inv = inv.reindex(['AX','AY','BX','BY','AZ','CX','BZ','CY','CZ'])
inv.loc['TOTAL'] = inv.sum()
inv['z168_vs_base_%'] = 100*(inv['Z168']/inv['BASE']-1)
inv['cap_vs_base_%']  = 100*(inv['CAP']/inv['BASE']-1)
pd.set_option('display.width',170,'display.float_format', lambda x:f'{x:9.2f}')
print((inv[['BASE','Z168','CAP']]/1e6).round(2).to_string())
print('\nVariacion % vs BASE:')
print(inv[['z168_vs_base_%','cap_vs_base_%']].round(1).to_string())

print('\n=== NIVEL DE SERVICIO mediano por escenario (%) ===')
svc = df.groupby('seg')[['svc_base','svc_z168','svc_cap']].median()*100
svc = svc.reindex(['AX','AY','BX','BY','AZ','CX','BZ','CY','CZ'])
print(svc.round(1).to_string())

print('\n=== % SKUs con servicio < 90% (riesgo de quiebre) ===')
risk = df.assign(
    r_base=df['svc_base']<0.90, r_z168=df['svc_z168']<0.90, r_cap=df['svc_cap']<0.90
).groupby('seg')[['r_base','r_z168','r_cap']].mean()*100
risk = risk.reindex(['AX','AY','BX','BY','AZ','CX','BZ','CY','CZ'])
print(risk.round(1).to_string())

print('\n=== TOTALES ===')
tb,tz,tc = (df['tgt_base_u']*price).sum(),(df['tgt_z168_u']*price).sum(),(df['tgt_cap_u']*price).sum()
print(f"Inventario objetivo:  BASE {tb/1e6:.1f}M  |  Z168 {tz/1e6:.1f}M ({100*(tz/tb-1):+.1f}%)  |  CAP {tc/1e6:.1f}M ({100*(tc/tb-1):+.1f}%)")
print(f"Servicio mediano:     BASE {df['svc_base'].median()*100:.1f}%  |  Z168 {df['svc_z168'].median()*100:.1f}%  |  CAP {df['svc_cap'].median()*100:.1f}%")
print(f"SKUs servicio <90%:   BASE {100*(df['svc_base']<.9).mean():.1f}%  |  Z168 {100*(df['svc_z168']<.9).mean():.1f}%  |  CAP {100*(df['svc_cap']<.9).mean():.1f}%")
