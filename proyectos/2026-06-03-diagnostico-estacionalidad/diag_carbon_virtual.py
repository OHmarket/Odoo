# -*- coding: utf-8 -*-
"""DIAG read-only: 'categoria virtual' carbon = suma de todos los SKUs de
carbon (activos + archivados, marcas rotan). Patron semanal, uplift 18-sep
y peso dentro de Despensa. El carbon NO tiene categoria propia."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CARBON_IDS = [20192, 19652, 18719, 10658, 18549, 10657, 19093, 21168, 19972, 19973]
# 18346 (carbonada Wasil) excluido: es conserva, no carbon

odoo = OdooReader()
rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_product_id', 'in', CARBON_IDS)],
    fields=['x_studio_week_start', 'x_studio_qty_sold'])
wk = defaultdict(float)
for r in rows:
    wk[r['x_studio_week_start'][:10]] += r['x_studio_qty_sold'] or 0.0

ws = sorted(wk)
print('semanas con venta: %d (%s a %s) | total %.0f u' % (
    len(ws), ws[0], ws[-1], sum(wk.values())))
for w in ws:
    bar = '#' * int(wk[w] / 5)
    print('  %s %5.0f %s' % (w, wk[w], bar))

DIRTY = {'2025-08-11', '2025-09-15', '2025-10-06', '2025-10-27'}
ev = wk.get('2025-09-15', 0.0)
clean = [q for w, q in wk.items() if '2025-08-04' <= w <= '2025-10-27' and w not in DIRTY]
clean_s = sorted(clean)
bl = clean_s[len(clean_s) // 2] if clean_s else 0
print('\n18-sep-2025: %.0f u | baseline mediana ventana: %.0f | ratio %.2fx' % (
    ev, bl, ev / bl if bl else 0))
