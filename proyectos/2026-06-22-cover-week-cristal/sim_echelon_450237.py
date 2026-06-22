"""Simulacion read-only: compra CD echelon 15 dias para 450237 (CRISTAL).
Replica la formula nueva contra datos EN VIVO de x_analisis_de_stock.
NO escribe en Odoo. La validacion definitiva es correr el Server Action.
"""
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
TID = 10829

# Espejo de constantes del motor (OH Analisis de Stock.py)
_SAFETY_FACTOR = {
    'AX': 1.95, 'BX': 1.68, 'AY': 1.68, 'BY': 1.28,
    'AZ': 1.28, 'BZ': 0.35, 'CX': 0.84, 'CY': 0.35, 'CZ': 0.0,
}
_SF_DEFAULT = 0.84
CD_ELIGIBLE = ('AX', 'AY', 'AZ', 'BX', 'BY', 'BZ')
PURCHASE_CYCLE_WEEKS = 1.0

FLDS = ['x_studio_team_id', 'x_studio_mu_week', 'x_studio_sigma_week',
        'x_studio_stock_effective', 'x_studio_stock_real',
        'x_studio_stock_pedido_compra', 'x_studio_periodo_repos_weeks',
        'x_studio_abcxyz', 'x_studio_moq', 'x_studio_qty_a_pedir',
        'x_studio_qty_a_pedir_cajas']
rows = odoo.search_read('x_analisis_de_stock',
                        domain=[('x_studio_product_id', '=', TID)], fields=FLDS)

salas, cd = [], None
for r in rows:
    t = r['x_studio_team_id']
    if t and 'Central' in (t[1] or ''):
        cd = r
    else:
        salas.append(r)

mu_red = sum(max(s['x_studio_mu_week'], 0.0) for s in salas)
sigma_sq = sum(s['x_studio_sigma_week'] ** 2 for s in salas if s['x_studio_sigma_week'] > 0)
sigma_red = sigma_sq ** 0.5
sala_stock = sum(s['x_studio_stock_effective'] for s in salas)
period = next((s['x_studio_periodo_repos_weeks'] for s in salas
               if s['x_studio_periodo_repos_weeks'] > 0), PURCHASE_CYCLE_WEEKS)
abcxyz = (cd['x_studio_abcxyz'] if cd else salas[0]['x_studio_abcxyz']) or ''
moq = next((s['x_studio_moq'] for s in salas if s['x_studio_moq'] > 0), 1.0)

stock_cd = cd['x_studio_stock_real'] if cd else 0.0
transito = cd['x_studio_stock_pedido_compra'] if cd else 0.0

z = _SAFETY_FACTOR.get(abcxyz, _SF_DEFAULT)
safety = z * sigma_red * (period ** 0.5)
target_red = mu_red * period + safety
disponible = stock_cd + sala_stock + transito
qty_neta = max(target_red - disponible, 0.0)

import math
qty_caja = math.ceil(qty_neta / moq) if moq > 0 else qty_neta
qty_units = qty_caja * moq

elegible = abcxyz in CD_ELIGIBLE
actual_cajas = cd['x_studio_qty_a_pedir_cajas'] if cd else 0.0

print('SKU 450237 CERVEZA CRISTAL LATA 6X470  |  abcxyz =', abcxyz,
      '| CD-elegible =', elegible)
print('-' * 60)
print('mu_red (u/sem)        = %8.2f' % mu_red)
print('sigma_red (u)         = %8.2f' % sigma_red)
print('period_weeks (delay)  = %8.3f  (%.0f dias)' % (period, period * 7))
print('z (%s)               = %8.2f' % (abcxyz, z))
print('moq (u/caja)          = %8.2f' % moq)
print('-' * 60)
print('safety_red            = %8.2f' % safety)
print('target_red (15d)      = %8.2f u' % target_red)
print('  - stock_CD          = %8.2f' % stock_cd)
print('  - stock_salas       = %8.2f' % sala_stock)
print('  - transito (PO)     = %8.2f' % transito)
print('  = disponible_red    = %8.2f' % disponible)
print('-' * 60)
print('compra_CD echelon     = %8.2f u  = %.0f cajas' % (qty_units, qty_caja))
print('compra_CD ACTUAL hoy  = %8s cajas (diferencial pass-through)' % actual_cajas)
