# -*- coding: utf-8 -*-
"""DIAG read-only: series semanales + promos de los 2 candidatos dudosos
(Sanpellegrino Ginger Beer -> SAN_VALENTIN; Coctel 120 tinto frutilla ->
ARMY_DAY). Evento real, promo, o historia corta?"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
pp = odoo.search_read(
    'product.product',
    domain=['|',
            ('name', 'ilike', 'sanpellegrino ginger'),
            ('name', 'ilike', '120 sabores tinto frutilla')],
    fields=['name'])
ids = [p['id'] for p in pp]
print('productos: %s' % {p['id']: p['name'][:60] for p in pp})

rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_product_id', 'in', ids)],
    fields=['x_studio_product_id', 'x_studio_week_start', 'x_studio_qty_sold'])
serie = defaultdict(lambda: defaultdict(float))
for r in rows:
    serie[r['x_studio_product_id'][0]][r['x_studio_week_start'][:10]] += r['x_studio_qty_sold'] or 0.0

for pid, wk in serie.items():
    nm = [p['name'] for p in pp if p['id'] == pid][0]
    ws = sorted(wk)
    print('\n=== %s ===' % nm[:70])
    print('semanas con venta: %d | primera %s | ultima %s' % (len(ws), ws[0], ws[-1]))
    for w in ws:
        print('  %s: %.0f' % (w, wk[w]))

ev = odoo.search_read(
    'x_loyalty_promo_event',
    domain=[('x_studio_product_variant_id', 'in', ids)],
    fields=['x_studio_product_variant_id', 'x_studio_period_start',
            'x_studio_weeks_active', 'x_studio_lift_qty', 'x_studio_program_name'])
print('\npromos registradas: %d' % len(ev))
for e in sorted(ev, key=lambda x: str(x.get('x_studio_period_start'))):
    nm = e['x_studio_product_variant_id'][1] if e['x_studio_product_variant_id'] else '?'
    print('  %s lift=%.2f %s | %s' % (
        e.get('x_studio_period_start'), e.get('x_studio_lift_qty') or 0,
        (e.get('x_studio_program_name') or '')[:30], nm[:50]))
