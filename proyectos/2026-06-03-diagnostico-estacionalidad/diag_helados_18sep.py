# -*- coding: utf-8 -*-
"""DIAG read-only: descomposicion por SKU del uplift de Helados en la
semana del 18-sep-2025. Cuanto pone helado pina vs el resto?"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

flds = odoo.fields_get('x_pos_week_sku_sale')
prod_f = [f for f in flds if 'product' in f.lower()]
print('campos producto: %s' % {f: flds[f].get('relation') for f in prod_f})
PF = prod_f[0]

cats = odoo.search_read('product.category', domain=[('complete_name', 'ilike', 'helados')],
                        fields=['complete_name'])
cid = cats[0]['id']
print('categoria: %s (cid %s)' % (cats[0]['complete_name'], cid))

EVENT_WEEK = '2025-09-15'
DIRTY = {'2025-08-11', '2025-09-15', '2025-10-06', '2025-10-27'}
rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_categ_id', '=', cid),
            ('x_studio_week_start', '>=', '2025-08-04'),
            ('x_studio_week_start', '<=', '2025-10-27')],
    fields=[PF, 'x_studio_week_start', 'x_studio_qty_sold'],
)
ev = defaultdict(float)
base = defaultdict(list)
names = {}
weeks_clean = set()
for r in rows:
    if not r[PF]:
        continue
    pid = r[PF][0]
    names[pid] = r[PF][1]
    w = r['x_studio_week_start'][:10]
    q = r['x_studio_qty_sold'] or 0.0
    if w == EVENT_WEEK:
        ev[pid] += q
    elif w not in DIRTY:
        base[pid].append((w, q))
        weeks_clean.add(w)

n_clean = len(weeks_clean)
def med_weekly(pid):
    by_w = defaultdict(float)
    for w, q in base.get(pid, []):
        by_w[w] += q
    vals = list(by_w.values()) + [0.0] * (n_clean - len(by_w))
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

tot_ev = sum(ev.values())
print('\nsemana 18 total categ: %.0f u | semanas limpias baseline: %d' % (tot_ev, n_clean))
print('%-52s %7s %8s %7s %7s' % ('sku', 'sem_18', 'base_med', 'ratio', '%sem18'))
acc = []
for pid in sorted(ev, key=lambda p: -ev[p]):
    bl = med_weekly(pid)
    ratio = ev[pid] / bl if bl > 0 else float('inf')
    acc.append((pid, ev[pid], bl, ratio))
for pid, e, bl, ratio in acc[:15]:
    rtxt = '%6.2fx' % ratio if ratio != float('inf') else '   inf'
    print('%-52s %7.0f %8.1f %s %6.1f%%' % (names[pid][:52], e, bl, rtxt, 100 * e / tot_ev))

pina = [pid for pid in names if 'pi' in names[pid].lower() and ('a' in names[pid].lower())]
pina = [pid for pid in names if 'piña' in names[pid].lower() or 'pina' in names[pid].lower()]
e_pina = sum(ev[p] for p in pina)
bl_pina = sum(med_weekly(p) for p in pina)
e_rest = tot_ev - e_pina
bl_tot = sum(med_weekly(p) for p in ev)
bl_rest = bl_tot - bl_pina
print('\nPIÑA (%d SKUs):  sem18 %.0f | base %.1f | ratio %.2fx | %.0f%% de la semana'
      % (len(pina), e_pina, bl_pina, e_pina / bl_pina if bl_pina else float('inf'),
         100 * e_pina / tot_ev))
print('RESTO helados:  sem18 %.0f | base %.1f | ratio %.2fx'
      % (e_rest, bl_rest, e_rest / bl_rest if bl_rest else float('inf')))
