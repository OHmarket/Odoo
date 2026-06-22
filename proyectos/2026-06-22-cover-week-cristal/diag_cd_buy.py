"""DIAG read-only: reconstruye la compra CD de 450237.
target_cd = mu_red * period_weeks + safety ; qty = target_cd - stock_proy_cd."""
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
tid = 10829  # CERVEZA CRISTAL LATA 6X470 CC

FLDS = [
    'x_studio_team_id',
    'x_studio_mu_week',
    'x_studio_demanda_semanal',
    'x_studio_stock_proyectado',
    'x_studio_target_units',
    'x_studio_qty_a_pedir',
    'x_studio_qty_a_pedir_cajas',
    'x_studio_cover_weeks',
    'x_studio_reorder_target_weeks',
    'x_studio_periodo_repos_weeks',
    'x_studio_valor_orden_compra',
]
rows = odoo.search_read('x_analisis_de_stock',
                        domain=[('x_studio_product_id', '=', tid)], fields=FLDS)

mu_red = 0.0
stock_red = 0.0
print('team | mu_week | stock_proy | target_u | qty_pedir | cajas | cover_w | tgt_w')
for r in sorted(rows, key=lambda x: (x['x_studio_team_id'] or [0])[0]):
    t = r['x_studio_team_id']
    mu = r['x_studio_mu_week']
    sp = r['x_studio_stock_proyectado']
    is_cd = t and 'Central' in (t[1] or '')
    if not is_cd:
        mu_red += mu
        stock_red += sp
    print('%-22s mu=%6.2f stock=%7.2f tgt_u=%7.2f pedir=%7.2f cajas=%5s cov=%5.2f tgtw=%5.2f' % (
        (t[1] if t else '?')[:22], mu, sp,
        r['x_studio_target_units'], r['x_studio_qty_a_pedir'],
        r['x_studio_qty_a_pedir_cajas'], r['x_studio_cover_weeks'],
        r['x_studio_reorder_target_weeks']))

print('\n--- Red (suma salas, sin CD) ---')
print('mu_red (u/sem)      =', round(mu_red, 2))
print('stock_red salas     =', round(stock_red, 2))
P = 15/7
print('period_weeks (15d)  =', round(P, 3))
print('target_cd base mu*P =', round(mu_red * P, 2), '(sin safety)')
