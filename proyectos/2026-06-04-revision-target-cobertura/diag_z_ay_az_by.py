# DIAG read-only: ¿conviene bajar z en AY / AZ / BY? (propuesta Marco 2026-06-10)
# Mismo metodo de diag_simulacion.py: snapshot vivo de x_analisis_de_stock,
# escala el safety por z_nuevo/z_actual y mide inventario objetivo $ y
# servicio implicito phi(z_eff) por segmento, para una grilla de candidatos.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd, numpy as np
from math import erf, sqrt
from shared.odoo_xmlrpc import OdooReader

def phi(z):
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))
phi_v = np.vectorize(phi)

Z_HOY = {'AX': 1.68, 'BX': 1.68, 'AY': 1.68, 'BY': 1.28, 'AZ': 1.04,
         'BZ': 0.35, 'CX': 0.84, 'CY': 0.35, 'CZ': 0.0}
CANDIDATOS = {                       # grilla por segmento propuesto
    'AY': [1.68, 1.28, 1.04, 0.84],
    'AZ': [1.04, 0.84, 0.52, 0.35],
    'BY': [1.28, 1.04, 0.84, 0.52],
}

o = OdooReader()
FLOOR = 1.0 / 4.345
fields = ['x_studio_abcxyz', 'x_studio_mu_week', 'x_studio_sigma_week',
          'x_studio_safety_stock_units', 'x_studio_reorder_target_weeks',
          'x_studio_target_units', 'x_studio_purchase_price_cash_unit']
dom = [('x_studio_mu_week', '>', FLOOR), ('x_studio_reorder_target_weeks', '>', 0.0),
       ('x_studio_abcxyz', 'in', list(CANDIDATOS.keys()))]
rows, off = [], 0
while True:
    b = o.search_read('x_analisis_de_stock', dom, fields, limit=5000, offset=off)
    rows += b
    if len(b) < 5000:
        break
    off += 5000
df = pd.DataFrame(rows)
for c in fields[1:]:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
df['seg'] = df['x_studio_abcxyz']
mu, sig = df['x_studio_mu_week'], df['x_studio_sigma_week']
safe, tgtw = df['x_studio_safety_stock_units'], df['x_studio_reorder_target_weeks']
price = df['x_studio_purchase_price_cash_unit']
df['cob_w'] = tgtw - np.where(mu > 0, safe / mu, 0.0)
rootH = np.sqrt(df['cob_w'].clip(lower=0.01))
denom = (sig * rootH).replace(0, np.nan)

pd.set_option('display.width', 170)
print(f'filas (sala x SKU con demanda): {len(df):,}')
print('Servicio implicito = phi(safety / (sigma*sqrt(H))), mediano del segmento.')
print('Inv = inventario objetivo total $ del segmento (target_units x costo).\n')

for seg, zs in CANDIDATOS.items():
    sub = df[df['seg'] == seg]
    if sub.empty:
        continue
    z_hoy = Z_HOY[seg]
    out = []
    for z in zs:
        f = z / z_hoy if z_hoy > 0 else 0.0
        safe_n = sub['x_studio_safety_stock_units'] * f
        tgt_n = (sub['cob_w'] * sub['x_studio_mu_week'] + safe_n).clip(lower=0)
        inv = (tgt_n * sub['x_studio_purchase_price_cash_unit']).sum()
        zeff = (safe_n / denom.loc[sub.index]).fillna(5).clip(-5, 5)
        svc = np.where(sub['x_studio_sigma_week'] <= 0, 1.0, phi_v(zeff))
        safety_inv = (safe_n * sub['x_studio_purchase_price_cash_unit']).sum()
        out.append(dict(z=z, inv_M=inv / 1e6, safety_M=safety_inv / 1e6,
                        svc_mediano=float(np.median(svc)) * 100,
                        svc_p25=float(np.percentile(svc, 25)) * 100))
    T = pd.DataFrame(out)
    T['ahorro_vs_hoy_M'] = T['inv_M'].iloc[0] - T['inv_M']
    print(f"=== {seg}  (n={len(sub):,} | z hoy {z_hoy}) ===")
    print(T.round(2).to_string(index=False))
    print()
