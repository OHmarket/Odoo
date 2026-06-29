# DIAG read-only: reconstruye demanda + safety + envio desde CD del SKU 9843
# en Panguipulli 763 (team_id=9). Lee x_analisis_de_stock, x_hm_si_forecast,
# x_calculo_abc_xyz via XML-RPC. No escribe nada.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CODE = '9843'
TEAM_ID = 9  # Panguipulli 763

odoo = OdooReader()

# 1) Resolver product.template / product.product por default_code
prod = odoo.search_read(
    'product.product',
    domain=['|', ('default_code', '=', CODE), ('barcode', '=', CODE)],
    fields=['id', 'default_code', 'name', 'product_tmpl_id', 'categ_id'],
)
print('=== product.product match por code', CODE, '===')
for p in prod:
    print(p)

tmpl_ids = sorted({p['product_tmpl_id'][0] for p in prod if p.get('product_tmpl_id')})
print('tmpl_ids:', tmpl_ids)

# 2) Fila de analisis de stock en ese team
fields_anal = [
    'x_studio_product_id', 'x_studio_team_id', 'x_studio_abcxyz', 'x_studio_rank_abcxyz',
    'x_studio_demanda_semanal', 'x_studio_mu_week', 'x_studio_sigma_week',
    'x_studio_safety_stock_units',
    'x_studio_periodo_repos_weeks', 'x_studio_lead_weeks',
    'x_studio_target_units', 'x_studio_reorder_target_weeks',
    'x_studio_stock_real', 'x_studio_stock_effective', 'x_studio_cover_weeks', 'x_studio_cover_label',
    'x_studio_stock_central', 'x_studio_qty_transferir', 'x_studio_supply_source',
    'x_studio_stock_pedido_transfer', 'x_studio_stock_pedido_compra',
    'x_studio_qty_a_pedir', 'x_studio_moq', 'x_studio_buy_action', 'x_studio_decision_reason',
    'x_studio_share_of_pool', 'x_studio_banda_actual',
]
dom_anal = [('x_studio_team_id', '=', TEAM_ID)]
if tmpl_ids:
    dom_anal.append(('x_studio_product_id', 'in', tmpl_ids))
rows = odoo.search_read('x_analisis_de_stock', domain=dom_anal, fields=fields_anal)
print('\n=== x_analisis_de_stock team', TEAM_ID, '===')
for r in rows:
    for k in fields_anal:
        print(f'  {k}: {r.get(k)}')
    print('  ---')

# 3) Misma fila en la Bodega Central (team_id=26) para ver origen del transfer
rows_cd = odoo.search_read('x_analisis_de_stock',
    domain=[('x_studio_team_id', '=', 26)] + ([('x_studio_product_id', 'in', tmpl_ids)] if tmpl_ids else []),
    fields=fields_anal)
print('\n=== x_analisis_de_stock CENTRAL (team 26) ===')
for r in rows_cd:
    for k in ('x_studio_stock_real','x_studio_stock_effective','x_studio_demanda_semanal','x_studio_qty_transferir','x_studio_buy_action','x_studio_qty_a_pedir'):
        print(f'  {k}: {r.get(k)}')
    print('  ---')

# 4) Forecast crudo del SKU en ese team
fwd_fields = ['x_studio_team_id', 'x_studio_product_id', 'x_studio_mu_week', 'x_studio_sigma_week',
              'x_studio_xyz_local', 'x_name']
fwd = odoo.search_read('x_hm_si_forecast',
    domain=[('x_studio_team_id', '=', TEAM_ID)] + ([('x_studio_product_id', 'in', tmpl_ids)] if tmpl_ids else []),
    fields=fwd_fields)
print('\n=== x_hm_si_forecast team', TEAM_ID, '===')
for r in fwd:
    print(' ', {k: r.get(k) for k in fwd_fields})
