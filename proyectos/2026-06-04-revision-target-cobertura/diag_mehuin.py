# DIAG read-only: descompone target de cobertura para Mehuin Express.
# target_weeks = cobertura(H) + seguridad(z*sigma*sqrt(H)/mu) + display, clamp a ceiling.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# 1) Encontrar el crm_team de Mehuin Express via pos.config.name
pos = odoo.search_read('pos.config', [('name', 'ilike', 'mehuin')],
                       ['name', 'crm_team_id'])
print('=== pos.config que matchean "mehuin" ===')
for p in pos:
    print(p['id'], '|', p['name'], '|', p.get('crm_team_id'))

team_ids = sorted({p['crm_team_id'][0] for p in pos if p.get('crm_team_id')})
print('team_ids:', team_ids)
if not team_ids:
    sys.exit('No se encontro crm_team para Mehuin')

# 2) Traer analisis de stock de ese team (solo campos que existan en el modelo)
wanted = [
    'x_studio_product_id', 'x_studio_abcxyz',
    'x_studio_mu_week', 'x_studio_sigma_week',
    'x_studio_lead_weeks', 'x_studio_periodo_repos_weeks',
    'x_studio_safety_stock_units', 'x_studio_target_units',
    'x_studio_reorder_target_weeks', 'x_studio_cover_weeks',
    'x_studio_cover_label', 'x_studio_stock_proyectado',
    'x_studio_buy_action',
]
existing = set(odoo.fields_get('x_analisis_de_stock').keys())
fields = [f for f in wanted if f in existing]
missing = [f for f in wanted if f not in existing]
if missing:
    print('campos ausentes (se omiten):', missing)
rows = odoo.search_read('x_analisis_de_stock',
                        [('x_studio_team_id', 'in', team_ids)],
                        fields, order='x_studio_mu_week desc', limit=25)
print('\n=== filas:', len(rows), '(top 25 por mu_week) ===\n')

def f(r, k):
    v = r.get(k)
    return v if isinstance(v, (int, float)) else 0.0

hdr = f"{'SKU':<34} {'seg':<4} {'mu':>6} {'sig':>6} {'H':>5} {'z*':>5} {'safe_u':>7} {'tgt_u':>7} {'tgt_w':>6} {'cob':>5} {'+seg':>5} {'cover':>6} {'label':<10}"
print(hdr)
print('-' * len(hdr))
for r in rows:
    name = (r['x_studio_product_id'][1] if r.get('x_studio_product_id') else '?')[:33]
    mu = f(r, 'x_studio_mu_week'); sig = f(r, 'x_studio_sigma_week')
    safe = f(r, 'x_studio_safety_stock_units')
    tgtw = f(r, 'x_studio_reorder_target_weeks')
    # Derivado de campos confiables (no del periodo_repos persistido, que esta stale):
    seg_w = safe / mu if mu > 0 else 0.0     # semanas que aporta el safety
    cob = tgtw - seg_w                        # cobertura base real = H
    z = safe / (sig * cob ** 0.5) if sig > 0 and cob > 0 else 0.0   # z derivado
    print(f"{name:<34} {r.get('x_studio_abcxyz',''):<4} {mu:>6.2f} "
          f"{sig:>6.2f} {cob:>5.2f} {z:>5.2f} {safe:>7.1f} "
          f"{f(r,'x_studio_target_units'):>7.1f} {tgtw:>6.2f} "
          f"{cob:>5.2f} {seg_w:>5.2f} {f(r,'x_studio_cover_weeks'):>6.2f} "
          f"{r.get('x_studio_cover_label',''):<10}")
