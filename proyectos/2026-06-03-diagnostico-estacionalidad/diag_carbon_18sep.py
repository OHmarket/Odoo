# -*- coding: utf-8 -*-
"""DIAG read-only: categoria Carbon en la semana del 18-sep — factor
asignado v1.4, uplift real 2025 y descomposicion por SKU (concentrado
tipo helado-pina o parejo tipo cervezas?)."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
cats = odoo.search_read('product.category',
                        domain=[('complete_name', 'ilike', 'carb')],
                        fields=['complete_name'])
print('categorias match: %s' % {c['id']: c['complete_name'] for c in cats})
cids = [c['id'] for c in cats]

fac = odoo.search_read(
    'x_forecast_factor_week',
    domain=[('x_studio_categ_id', 'in', cids)],
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_iso_week',
            'x_studio_factor_verano', 'x_studio_factor_evento',
            'x_studio_evento', 'x_studio_factor_total'])
print('\nfactores con evento o |verano-1|>0.3:')
for r in sorted(fac, key=lambda x: x['x_studio_week_start']):
    if r['x_studio_factor_evento'] > 1.0 or abs(r['x_studio_factor_verano'] - 1.0) > 0.3:
        print('  %s iso%2d fv=%.2f fe=%.2f ft=%.2f %s | %s' % (
            r['x_studio_week_start'], r['x_studio_iso_week'],
            r['x_studio_factor_verano'], r['x_studio_factor_evento'],
            r['x_studio_factor_total'], r['x_studio_evento'] or '',
            r['x_studio_categ_id'][1][:35]))

EVENT_WEEK = '2025-09-15'
DIRTY = {'2025-08-11', '2025-09-15', '2025-10-06', '2025-10-27'}
rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_categ_id', 'in', cids),
            ('x_studio_week_start', '>=', '2025-08-04'),
            ('x_studio_week_start', '<=', '2025-10-27')],
    fields=['x_studio_product_id', 'x_studio_week_start', 'x_studio_qty_sold'])
ev = defaultdict(float)
clean = defaultdict(lambda: defaultdict(float))
names = {}
for r in rows:
    if not r['x_studio_product_id']:
        continue
    pid = r['x_studio_product_id'][0]
    names[pid] = r['x_studio_product_id'][1]
    w = r['x_studio_week_start'][:10]
    q = r['x_studio_qty_sold'] or 0.0
    if w == EVENT_WEEK:
        ev[pid] += q
    elif w not in DIRTY:
        clean[pid][w] += q

def med(v):
    s = sorted(v)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)

tot_ev = sum(ev.values())
print('\nsemana 18-sep-2025 por SKU (total categ %.0f u):' % tot_ev)
print('%-52s %7s %8s %7s %7s' % ('sku', 'sem_18', 'base_med', 'ratio', '%sem18'))
for pid in sorted(set(list(ev) + list(clean)), key=lambda p: -ev.get(p, 0)):
    bl = med(list(clean[pid].values()))
    e = ev.get(pid, 0.0)
    rtxt = ('%6.2fx' % (e / bl)) if bl > 0 else '    new'
    print('%-52s %7.0f %8.1f %s %6.1f%%' % (
        names[pid][:52], e, bl, rtxt, 100 * e / tot_ev if tot_ev else 0))
