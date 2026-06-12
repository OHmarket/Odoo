# -*- coding: utf-8 -*-
"""DIAG read-only: estado post-migracion carbon. Existe la categoria
nueva? El fact re-categorizo la historia? Factor Semanal ya la tomo?"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CARBON_IDS = [20192, 19652, 18719, 10658, 18549, 10657, 19093, 21168, 19972, 19973]

odoo = OdooReader()

# 1. categoria nueva
cats = odoo.search_read('product.category',
                        domain=['|', ('complete_name', 'ilike', 'parri'),
                                ('complete_name', 'ilike', 'carb')],
                        fields=['complete_name'])
print('1. categorias nuevas: %s' % {c['id']: c['complete_name'] for c in cats})

# 2. donde apuntan los SKUs hoy (incluye archivados)
pp = odoo.execute('product.product', 'search_read',
                  [('id', 'in', CARBON_IDS), ('active', 'in', [True, False])],
                  fields=['name', 'categ_id'])
by_cat = defaultdict(list)
for p in pp:
    by_cat[(p['categ_id'][1] if p['categ_id'] else '?')].append(p['name'][:40])
print('\n2. categoria actual de los SKUs carbon:')
for c, sk in by_cat.items():
    print('   %s: %d SKUs' % (c, len(sk)))

# 3. fact re-categorizado?
if cats:
    cids = [c['id'] for c in cats]
    rows = odoo.search_read('x_pos_week_sku_sale',
                            domain=[('x_studio_categ_id', 'in', cids)],
                            fields=['x_studio_week_start', 'x_studio_qty_sold'])
    wk = defaultdict(float)
    for r in rows:
        wk[r['x_studio_week_start'][:10]] += r['x_studio_qty_sold'] or 0.0
    if wk:
        ws = sorted(wk)
        print('\n3. fact con categoria nueva: %d semanas (%s a %s), %.0f u' % (
            len(ws), ws[0], ws[-1], sum(wk.values())))
    else:
        print('\n3. fact: SIN filas con la categoria nueva (backfill pendiente?)')

    # 4. factor semanal
    fac = odoo.search_read('x_forecast_factor_week',
                           domain=[('x_studio_categ_id', 'in', cids)],
                           fields=['x_studio_week_start', 'x_studio_iso_week',
                                   'x_studio_factor_verano', 'x_studio_factor_evento',
                                   'x_studio_evento', 'x_studio_factor_total',
                                   'x_studio_source_version'])
    print('\n4. filas en x_forecast_factor_week: %d' % len(fac))
    if fac:
        print('   version: %s' % set(r['x_studio_source_version'] for r in fac))
        print('   semana       iso  fv    fe    ft    evento')
        for r in sorted(fac, key=lambda x: x['x_studio_week_start']):
            if r['x_studio_factor_evento'] > 1.0 or abs(r['x_studio_factor_verano'] - 1.0) > 0.25:
                print('   %s %3d %5.2f %5.2f %5.2f  %s' % (
                    r['x_studio_week_start'], r['x_studio_iso_week'],
                    r['x_studio_factor_verano'], r['x_studio_factor_evento'],
                    r['x_studio_factor_total'], r['x_studio_evento'] or ''))
