# -*- coding: utf-8 -*-
"""
DIAG read-only: uplift REAL de la semana del 18-sep (2025-09-15) vs
baseline de semanas limpias +/-6, total red y por categoria, cruzado con
el factor_evento que v1.3 escribio para 2026-09-14.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

EVENT_WEEK = '2025-09-15'
# semanas sucias en la ventana +/-6 (Asuncion 11-ago, Dos Mundos 6-oct,
# Evangelicas/Santos 27-oct) — no entran al baseline
DIRTY = {'2025-08-11', '2025-09-15', '2025-10-06', '2025-10-27'}
WIN_LO, WIN_HI = '2025-08-04', '2025-10-27'

odoo = OdooReader()
rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_week_start', '>=', WIN_LO),
            ('x_studio_week_start', '<=', WIN_HI)],
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_qty_sold'],
)
qty = defaultdict(lambda: defaultdict(float))   # categ -> week -> qty
names = {}
for r in rows:
    if not r['x_studio_categ_id']:
        continue
    cid = r['x_studio_categ_id'][0]
    names[cid] = r['x_studio_categ_id'][1]
    qty[cid][r['x_studio_week_start'][:10]] += r['x_studio_qty_sold'] or 0.0

# factor_evento guardado para 2026-09-14
fac = odoo.search_read(
    'x_forecast_factor_week',
    domain=[('x_studio_week_start', '=', '2026-09-14')],
    fields=['x_studio_categ_id', 'x_studio_factor_evento'],
)
f_by_cid = {r['x_studio_categ_id'][0]: r['x_studio_factor_evento']
            for r in fac if r['x_studio_categ_id']}

def median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

print('%-44s %9s %9s %7s %8s' % ('categoria', 'sem_18', 'base_med', 'real', 'modelo'))
tot_ev, tot_bl = 0.0, 0.0
pairs = []
for cid in sorted(qty, key=lambda c: -qty[c].get(EVENT_WEEK, 0)):
    ev = qty[cid].get(EVENT_WEEK, 0.0)
    clean = [q for w, q in qty[cid].items() if w not in DIRTY]
    if len(clean) < 4 or ev <= 0:
        continue
    bl = median(clean)
    if bl < 10:
        continue
    ratio = ev / bl
    tot_ev += ev
    tot_bl += bl
    pairs.append(ratio)
    if ev >= 1000:   # solo imprime las grandes
        print('%-44s %9.0f %9.0f %6.2fx %7.2fx' % (
            names[cid][:44], ev, bl, ratio, f_by_cid.get(cid, 1.0)))

print('-' * 80)
print('TOTAL RED (suma):   semana 18 = %.0f u | baseline = %.0f u | uplift %.2fx'
      % (tot_ev, tot_bl, tot_ev / tot_bl))
print('mediana de ratios por categoria: %.2fx (n=%d)' % (median(pairs), len(pairs)))
fs = [f for f in f_by_cid.values() if f > 1.0]
print('modelo 2026-09-14: %d categs con factor, prom %.2fx, mediana %.2fx'
      % (len(fs), sum(fs) / len(fs), median(fs)))
