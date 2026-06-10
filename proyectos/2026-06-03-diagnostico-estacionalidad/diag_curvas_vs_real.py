# -*- coding: utf-8 -*-
"""
DIAG read-only #2: curvas fiteadas vs venta cruda real.

Anomalias de la corrida v1.0 a explicar:
  A. 60/61 categorias pasan el gate de amplitud (esperado: una fraccion).
  B. Espumantes con ene-feb 2.38 > dic 1.61 (peak esperado: fin de dic).
  C. Curvas tocando SI_CLAMP en ambos extremos (0.40 / 3.50) = overfit.

Estrategia: por categoria canonica, imprimir lado a lado el factor_verano
fiteado (de x_forecast_factor_week) y la venta real promedio por iso_week
(de x_pos_week_sku_sale), para ver si la FORMA fiteada sigue la forma real
o esta corrida/inventada.
"""
import datetime
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# --- factores fiteados ---
rows = odoo.search_read(
    'x_forecast_factor_week',
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_iso_week',
            'x_studio_factor_verano'],
)
categs = {}
fitted = defaultdict(dict)   # cid -> iso -> fv
for r in rows:
    if not r['x_studio_categ_id']:
        continue
    cid = r['x_studio_categ_id'][0]
    categs[cid] = r['x_studio_categ_id'][1]
    fitted[cid][r['x_studio_iso_week']] = r['x_studio_factor_verano']

# --- amplitud por categoria (top extremos) ---
print('=== AMPLITUD (max/min factor_verano) POR CATEGORIA — top 12 ===')
amps = []
for cid, by_iso in fitted.items():
    vs = list(by_iso.values())
    amps.append((max(vs) / max(min(vs), 1e-9), min(vs), max(vs), categs[cid]))
amps.sort(reverse=True)
for a, mn, mx, nm in amps[:12]:
    print('  amp %6.2f  [%.2f - %.2f]  %s' % (a, mn, mx, nm[:60]))
n_low = sum(1 for a, _m, _x, _n in amps if a < 1.30)
print('  categorias con amplitud fiteada < 1.30 (deberian ser planas): %d' % n_low)

# --- venta cruda semanal por categoria canonica ---
targets = {}
for cid, nm in categs.items():
    low = nm.lower()
    if 'espum' in low or 'cervez' in low:
        targets[cid] = nm

sale = odoo.execute(
    'x_pos_week_sku_sale', 'read_group',
    [('x_studio_categ_id', 'in', list(targets))],
    ['x_studio_qty_sold'],
    ['x_studio_categ_id', 'x_studio_week_start:week'],
    lazy=False,
)
raw = defaultdict(dict)   # cid -> monday -> qty
MES = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6, 'jul': 7,
       'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12, 'jan': 1,
       'apr': 4, 'aug': 8, 'dec': 12}
for r in sale:
    cid = r['x_studio_categ_id'][0]
    lbl = r['x_studio_week_start:week']          # ej 'S50 2025'
    raw[cid][lbl] = r['x_studio_qty_sold']

# read_group:week da etiqueta 'Wnn yyyy'; mejor pedir filas crudas (pocas categs)
sale2 = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_categ_id', 'in', list(targets))],
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_qty_sold'],
)
raw2 = defaultdict(lambda: defaultdict(float))   # cid -> date -> qty
for r in sale2:
    cid = r['x_studio_categ_id'][0]
    raw2[cid][r['x_studio_week_start']] += r['x_studio_qty_sold'] or 0.0

for cid, nm in sorted(targets.items(), key=lambda kv: kv[1]):
    wk_qty = raw2[cid]
    if not wk_qty:
        continue
    print('\n=== %s (cid %s) ===' % (nm, cid))
    print('historia: %d semanas (%s a %s)' % (
        len(wk_qty), min(wk_qty), max(wk_qty)))
    # promedio real por iso_week vs factor fiteado
    by_iso = defaultdict(list)
    for w, q in wk_qty.items():
        d = datetime.date.fromisoformat(w[:10])
        by_iso[min(d.isocalendar()[1], 52)].append(q)
    mean_all = sum(sum(v) for v in by_iso.values()) / max(
        sum(len(v) for v in by_iso.values()), 1)
    print('iso | n | venta_prom | ratio_real | factor_fit')
    for iso in range(1, 53):
        if iso not in by_iso:
            continue
        m = sum(by_iso[iso]) / len(by_iso[iso])
        print(' %2d | %d | %9.0f | %9.2f | %9.2f' % (
            iso, len(by_iso[iso]), m, m / mean_all if mean_all else 0,
            fitted[cid].get(iso, float('nan'))))
