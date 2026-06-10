# -*- coding: utf-8 -*-
"""
DIAG read-only: candidatos SKU-evento por concentracion (regla opcion B).

Regla universal: share de venta historica en semanas-evento >= 50% y
volumen total >= MIN_TOTAL -> el SKU es "evento-only": se excluye de la
medicion del factor de categoria y es candidato a flag Fase C / ancla LY.

Output: resultados/sku_evento_excluidos.csv (formato Excel es-CL) con
share, evento dominante, venta en su semana-evento, baseline limpia y
factor propio implicito.
"""
import csv
import datetime
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SHARE_MIN = 0.50
MIN_TOTAL = 50.0          # u historicas minimas para juzgar
COMMERCIAL_EVENTS = [('SAN_VALENTIN', 2, 14), ('HALLOWEEN', 10, 31)]
B_CODES = {c for c, _m, _d in COMMERCIAL_EVENTS}
EXCLUDED_CODES = {'MOTHERS_DAY', 'FATHERS_DAY'}

odoo = OdooReader()
today = datetime.date.today()
monday_now = today - datetime.timedelta(days=today.weekday())

def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())

# --- calendario historico de semanas-evento (mismo criterio del script) ---
occs = odoo.search_read(
    'x_holiday_occurrence',
    domain=[('x_studio_holiday_id', '!=', False), ('x_studio_holiday_date', '!=', False)],
    fields=['x_studio_holiday_id', 'x_studio_holiday_date'])
masters = odoo.search_read('x_holiday_master', fields=['x_studio_code'])
code_by_id = {m['id']: (m.get('x_studio_code') or '').strip().upper() for m in masters}

events = []
for r in occs:
    code = code_by_id.get(r['x_studio_holiday_id'][0], '')
    if not code or code in EXCLUDED_CODES:
        continue
    d = datetime.date.fromisoformat(str(r['x_studio_holiday_date'])[:10])
    events.append((code, d))
for code, m, dd in COMMERCIAL_EVENTS:
    for y in range(2024, today.year + 1):
        events.append((code, datetime.date(y, m, dd)))

week_event = {}                     # monday -> codigo (semana objetivo)
dirty = set()
for code, d in sorted(set(events)):
    tgt = d if code in B_CODES else d - datetime.timedelta(days=1)
    tw = monday_of(tgt)
    if tw < monday_now:
        week_event.setdefault(tw.isoformat(), code)
    dirty.add(monday_of(d).isoformat())
    dirty.add(monday_of(d - datetime.timedelta(days=1)).isoformat())
dirty = {w for w in dirty if w < monday_now.isoformat()}
print('semanas-evento historicas: %d (%d con codigo objetivo)' % (len(dirty), len(week_event)))

# --- venta por SKU: total vs en semanas-evento (2 read_group) ---
tot = odoo.execute('x_pos_week_sku_sale', 'read_group',
                   [('x_studio_week_start', '<', monday_now.isoformat())],
                   ['x_studio_qty_sold'],
                   ['x_studio_product_id'], lazy=False)
din = odoo.execute('x_pos_week_sku_sale', 'read_group',
                   [('x_studio_week_start', 'in', sorted(dirty))],
                   ['x_studio_qty_sold'],
                   ['x_studio_product_id'], lazy=False)
t_by, d_by, names = {}, {}, {}
for r in tot:
    if r['x_studio_product_id']:
        pid = r['x_studio_product_id'][0]
        t_by[pid] = r['x_studio_qty_sold'] or 0.0
        names[pid] = r['x_studio_product_id'][1]
for r in din:
    if r['x_studio_product_id']:
        d_by[r['x_studio_product_id'][0]] = r['x_studio_qty_sold'] or 0.0

cands = []
for pid, t in t_by.items():
    de = d_by.get(pid, 0.0)
    if t >= MIN_TOTAL and de / t >= SHARE_MIN:
        cands.append((pid, t, de, de / t))
print('SKUs totales con venta: %d | candidatos evento-only: %d' % (len(t_by), len(cands)))

# --- detalle por candidato: serie semanal, evento dominante, baseline ---
rows = odoo.search_read(
    'x_pos_week_sku_sale',
    domain=[('x_studio_product_id', 'in', [c[0] for c in cands])],
    fields=['x_studio_product_id', 'x_studio_categ_id',
            'x_studio_week_start', 'x_studio_qty_sold'])
serie = defaultdict(lambda: defaultdict(float))
categ = {}
for r in rows:
    pid = r['x_studio_product_id'][0]
    serie[pid][r['x_studio_week_start'][:10]] += r['x_studio_qty_sold'] or 0.0
    if r['x_studio_categ_id']:
        categ[pid] = r['x_studio_categ_id'][1]

def med(v):
    s = sorted(v)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)

out = []
for pid, t, de, share in sorted(cands, key=lambda c: -c[3]):
    wk = serie[pid]
    ev_weeks = {w: q for w, q in wk.items() if w in dirty}
    top_w = max(ev_weeks, key=ev_weeks.get) if ev_weeks else ''
    code = week_event.get(top_w, '(bloque)')
    clean = [q for w, q in wk.items() if w not in dirty]
    bl = med(clean)
    peak = ev_weeks.get(top_w, 0.0)
    factor = peak / bl if bl > 0 else None
    out.append({
        'product_id': pid, 'sku': names[pid], 'categoria': categ.get(pid, ''),
        'share_evento': round(share, 3), 'venta_total': round(t, 1),
        'venta_sem_evento': round(de, 1), 'evento_dominante': code,
        'semana_peak': top_w, 'qty_peak': round(peak, 1),
        'baseline_mediana': round(bl, 1),
        'factor_propio': round(factor, 1) if factor is not None else 'inf',
    })

dst = Path(__file__).parent / 'resultados' / 'sku_evento_excluidos.csv'
with open(dst, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()), delimiter=';')
    w.writeheader()
    for r in out:
        w.writerow({k: (str(v).replace('.', ',') if isinstance(v, float) else v)
                    for k, v in r.items()})
print('CSV: %s (%d SKUs)' % (dst, len(out)))

# --- CSV de CARGA al maestro: solo los que pasan la regla doble v1.4
#     (share >= 50% Y factor propio >= 5), con template_id y default_code
#     para importar el flag en product.template (Fase C) ---
FACTOR_MIN = 5.0
flag = [r for r in out
        if r['factor_propio'] == 'inf' or float(r['factor_propio']) >= FACTOR_MIN]
pp = odoo.search_read('product.product',
                      domain=[('id', 'in', [r['product_id'] for r in flag])],
                      fields=['product_tmpl_id', 'default_code', 'name'])
info = {p['id']: p for p in pp}
rows_carga = []
for r in flag:
    p = info.get(r['product_id'], {})
    rows_carga.append({
        'product_template_id': p.get('product_tmpl_id') and p['product_tmpl_id'][0] or '',
        'default_code': p.get('default_code') or '',
        'nombre': p.get('name') or r['sku'],
        'evento_codigo': r['evento_dominante'],
        'semana_peak': r['semana_peak'],
        'share_evento': r['share_evento'],
        'factor_propio': r['factor_propio'],
        'qty_peak': r['qty_peak'],
    })
dst2 = Path(__file__).parent / 'resultados' / 'sku_evento_flag_carga.csv'
with open(dst2, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(rows_carga[0].keys()), delimiter=';')
    w.writeheader()
    for r in rows_carga:
        w.writerow({k: (str(v).replace('.', ',') if isinstance(v, float) else v)
                    for k, v in r.items()})
print('CSV carga maestro: %s (%d SKUs, regla doble v1.4)' % (dst2, len(rows_carga)))
for r in rows_carga:
    print('  tmpl=%-6s %-14s %-22s %s' % (
        r['product_template_id'], r['default_code'][:14],
        r['evento_codigo'][:22], r['nombre'][:48]))

print('\nTOP 25 por share:')
print('%-46s %6s %9s %-22s %8s' % ('sku', 'share', 'baseline', 'evento', 'factor'))
for r in out[:25]:
    print('%-46s %5.0f%% %9s %-22s %8s' % (
        r['sku'][:46], 100 * r['share_evento'], r['baseline_mediana'],
        r['evento_dominante'][:22], r['factor_propio']))
