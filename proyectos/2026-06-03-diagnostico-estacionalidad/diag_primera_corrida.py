# -*- coding: utf-8 -*-
"""
DIAG read-only: validacion de la primera corrida de OH Factor Semanal v1.0.

Checks canonicos del diseno (§7.3):
  1. Cervezas: factor 1.5-1.9 ene-feb / ~1.0 invierno
  2. Espumantes: alto semana 29-dic
  3. Abarrotes: plano ~1.0
  4. Semana 14-sep-2026: factor de evento presente
+ sanidad global: filas, rango, distribucion, semanas-evento.
"""
import datetime
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

rows = odoo.search_read(
    'x_forecast_factor_week',
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_iso_week',
            'x_studio_factor_verano', 'x_studio_factor_evento',
            'x_studio_evento', 'x_studio_factor_total',
            'x_studio_source_version'],
)
print('=== SANIDAD GLOBAL ===')
print('filas: %d' % len(rows))
if not rows:
    sys.exit('Tabla vacia.')

versions = set(r['x_studio_source_version'] for r in rows)
weeks = sorted(set(r['x_studio_week_start'] for r in rows))
categs = {}
for r in rows:
    if r['x_studio_categ_id']:
        categs[r['x_studio_categ_id'][0]] = r['x_studio_categ_id'][1]
print('versiones: %s' % versions)
print('semanas: %d (%s a %s)' % (len(weeks), weeks[0], weeks[-1]))
print('categorias: %d' % len(categs))

fv = [r['x_studio_factor_verano'] for r in rows]
fe = [r['x_studio_factor_evento'] for r in rows]
ft = [r['x_studio_factor_total'] for r in rows]
def q(v, p):
    s = sorted(v)
    return s[int(p * (len(s) - 1))]
print('factor_verano: min %.2f | p25 %.2f | p50 %.2f | p75 %.2f | max %.2f'
      % (min(fv), q(fv, .25), q(fv, .5), q(fv, .75), max(fv)))
print('factor_total : min %.2f | p50 %.2f | max %.2f' % (min(ft), q(ft, .5), max(ft)))

n_flat = sum(1 for c in categs
             if all(abs(r['x_studio_factor_verano'] - 1.0) < 1e-9
                    for r in rows if r['x_studio_categ_id'] and r['x_studio_categ_id'][0] == c))
print('categs con curva TODA plana (=1.0): %d de %d' % (n_flat, len(categs)))

print('\n=== SEMANAS-EVENTO (factor_evento > 1) ===')
ev = defaultdict(lambda: [0, 0.0, 0.0])   # (week, code) -> [n_categs, max, sum]
for r in rows:
    if r['x_studio_factor_evento'] > 1.0:
        k = (r['x_studio_week_start'], r['x_studio_evento'])
        ev[k][0] += 1
        ev[k][1] = max(ev[k][1], r['x_studio_factor_evento'])
        ev[k][2] += r['x_studio_factor_evento']
if not ev:
    print('  (ninguna fila con factor_evento > 1)  <<< REVISAR')
for (wk, code), (n, mx, sm) in sorted(ev.items()):
    print('  %s  %-24s categs=%3d  max=%.2f  prom=%.2f' % (wk, code, n, mx, sm / n))

print('\n=== CHECKS CANONICOS ===')
def curve_of(pat):
    ids = [c for c, nm in categs.items() if pat.lower() in nm.lower()]
    out = {}
    for cid in ids:
        rs = [r for r in rows if r['x_studio_categ_id'] and r['x_studio_categ_id'][0] == cid]
        out[categs[cid]] = {r['x_studio_week_start']: r for r in rs}
    return out

def avg_fv(per_week, months):
    vals = [r['x_studio_factor_verano'] for w, r in per_week.items()
            if int(w[5:7]) in months]
    return sum(vals) / len(vals) if vals else None

for pat, label in [('cervez', 'CERVEZAS'), ('espum', 'ESPUMANTES'),
                   ('abarrot', 'ABARROTES')]:
    print('\n-- %s --' % label)
    cs = curve_of(pat)
    if not cs:
        print('  sin categoria que matchee %r  <<< REVISAR nombre' % pat)
    for nm, per_week in cs.items():
        ene_feb = avg_fv(per_week, {1, 2})
        invierno = avg_fv(per_week, {6, 7, 8})
        dic = avg_fv(per_week, {12})
        print('  %-38s ene-feb %.2f | jun-ago %.2f | dic %.2f' % (
            nm[:38],
            ene_feb if ene_feb is not None else float('nan'),
            invierno if invierno is not None else float('nan'),
            dic if dic is not None else float('nan')))

print('\n-- SEMANA 2026-09-14 (18-19 sep) --')
sep = [r for r in rows if r['x_studio_week_start'] == '2026-09-14'
       and r['x_studio_factor_evento'] > 1.0]
print('  categs con factor evento: %d | codigos: %s | max %.2f' % (
    len(sep), set(r['x_studio_evento'] for r in sep) or '-',
    max([r['x_studio_factor_evento'] for r in sep], default=0)))
