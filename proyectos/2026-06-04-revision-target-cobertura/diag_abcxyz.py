# DIAG read-only: target de cobertura por ABCXYZ.
# Descompone cobertura(H) vs seguridad y mide donde mordria el cap freq+3d.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd, numpy as np
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
FLOOR = 1.0 / 4.345
BUFFER_W = 3.0 / 7.0   # 3 dias en semanas

fields = ['x_studio_abcxyz', 'x_studio_mu_week', 'x_studio_sigma_week',
          'x_studio_safety_stock_units', 'x_studio_reorder_target_weeks',
          'x_studio_target_units', 'x_studio_stock_proyectado',
          'x_studio_purchase_price_cash_unit']
dom = [('x_studio_mu_week', '>', FLOOR),
       ('x_studio_reorder_target_weeks', '>', 0.0)]
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
mu = df['x_studio_mu_week']; sig = df['x_studio_sigma_week']
safe = df['x_studio_safety_stock_units']; tgtw = df['x_studio_reorder_target_weeks']

df['seg_w'] = np.where(mu > 0, safe / mu, 0.0)          # safety en semanas
df['cob_w'] = tgtw - df['seg_w']                         # cobertura base (H ~ freq)
df['z_der'] = np.where((sig > 0) & (df['cob_w'] > 0),
                       safe / (sig * np.sqrt(df['cob_w'].clip(lower=0.01))), 0.0)
df['cap_w'] = df['cob_w'] + BUFFER_W                     # cap propuesto = freq + 3d
df['tgt_new'] = np.minimum(tgtw, df['cap_w'])            # target capado
df['recorta'] = tgtw > df['cap_w'] + 1e-6               # se recorta?
df['recorte_w'] = (tgtw - df['tgt_new'])                # semanas recortadas

ORD = ['AX','AY','AZ','BX','BY','BZ','CX','CY','CZ','sin']
def agg(g):
    return pd.Series({
        'n': len(g),
        'z_med': g['z_der'].median(),
        'cob_med': g['cob_w'].median(),
        'safety_med_w': g['seg_w'].median(),
        'tgt_p50': g['x_studio_reorder_target_weeks'].median(),
        'tgt_p90': g['x_studio_reorder_target_weeks'].quantile(.90),
        'cap_med': g['cap_w'].median(),
        'pct_recorta': 100.0 * g['recorta'].mean(),
        'recorte_med_w': g.loc[g['recorta'], 'recorte_w'].median() if g['recorta'].any() else 0.0,
    })

t = df.groupby('seg').apply(agg, include_groups=False)
t = t.reindex([s for s in ORD if s in t.index])
pd.set_option('display.width', 170, 'display.float_format', lambda x: f'{x:7.2f}')
print('=== TARGET DE COBERTURA por ABCXYZ (semanas) ===')
print('z_med=z derivado | cob=cobertura base(~freq) | safety_med_w=colchon actual')
print('cap_med=freq+3d propuesto | pct_recorta=%SKUs sobre el cap | recorte_med_w=cuanto baja\n')
print(t.to_string())

print('\n=== TOTAL ===')
print(f"SKUs activos: {len(df)}  |  target p50: {tgtw.median():.2f} sem  |  "
      f"safety mediano: {df['seg_w'].median():.2f} sem")
print(f"% que el cap freq+3d recortaria: {100*df['recorta'].mean():.1f}%  |  "
      f"recorte mediano (afectados): {df.loc[df['recorta'],'recorte_w'].median():.2f} sem")
