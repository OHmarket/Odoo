# -*- coding: utf-8 -*-
"""
DIAG read-only #3: series crudas de las categorias con curva patologica
(amp 8.75 tocando ambos clamps tras v1.1). Hipotesis a discriminar:
  (a) volumen bajo -> ln ruidoso -> harmonicos salvajes
  (b) categoria creada/discontinuada a mitad de historia -> quiebre
      estructural que el trend lineal no captura y absorben los harmonicos
  (c) estacionalidad real extrema (improbable en Limpieza/Cafeteria)
"""
import datetime
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

PATTERNS = ['cafeter', 'limpieza y hogar', 'jarabes']

odoo = OdooReader()
cats = odoo.search_read('product.category', fields=['id', 'complete_name'])
targets = {c['id']: c['complete_name'] for c in cats
           if any(p in c['complete_name'].lower() for p in PATTERNS)}

rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_categ_id', 'in', list(targets))],
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_qty_sold'],
)
series = defaultdict(lambda: defaultdict(float))
for r in rows:
    series[r['x_studio_categ_id'][0]][r['x_studio_week_start']] += r['x_studio_qty_sold'] or 0.0

for cid, weekly in series.items():
    nm = targets.get(cid, '?')
    wks = sorted(weekly)
    vals = [weekly[w] for w in wks]
    d0 = datetime.date.fromisoformat(wks[0][:10])
    d1 = datetime.date.fromisoformat(wks[-1][:10])
    span = (d1 - d0).days // 7 + 1
    print('\n=== %s (cid %s) ===' % (nm, cid))
    print('semanas con venta: %d | span calendario: %d | huecos: %d' % (
        len(wks), span, span - len(wks)))
    print('qty/sem: min %.0f | mediana %.0f | max %.0f' % (
        min(vals), sorted(vals)[len(vals) // 2], max(vals)))
    # mitades: nivel primera mitad vs segunda (quiebre estructural)
    h = len(wks) // 2
    m1 = sum(weekly[w] for w in wks[:h]) / h
    m2 = sum(weekly[w] for w in wks[h:]) / (len(wks) - h)
    print('nivel 1a mitad %.0f vs 2a mitad %.0f (ratio %.2f)' % (m1, m2, m2 / max(m1, 1e-9)))
    print('serie completa (semana: qty):')
    line = []
    for w in wks:
        line.append('%s:%.0f' % (w[2:10], weekly[w]))
        if len(line) == 6:
            print('  ' + '  '.join(line)); line = []
    if line:
        print('  ' + '  '.join(line))
