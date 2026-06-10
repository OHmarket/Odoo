# -*- coding: utf-8 -*-
"""
DIAG read-only: auditoria del calendario de eventos para OH Factor Semanal.

Pregunta: que codigos existen en x_holiday_master, que ocurrencias hay en
x_holiday_occurrence (pasadas y futuras), y cuales codigos con historia NO
tienen ocurrencia futura dentro del horizonte de 52 semanas (falla silenciosa
del factor de evento).
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

HORIZON_WEEKS = 52
EXCLUDED_CODES = {'MOTHERS_DAY', 'FATHERS_DAY'}
COMMERCIAL_EVENTS = [('SAN_VALENTIN', 2, 14), ('HALLOWEEN', 10, 31)]

odoo = OdooReader()
today = datetime.date.today()
monday_now = today - datetime.timedelta(days=today.weekday())
horizon_end = monday_now + datetime.timedelta(weeks=HORIZON_WEEKS)

# Master
masters = odoo.search_read('x_holiday_master', fields=['x_name', 'x_studio_code'])
code_by_id = {m['id']: (m.get('x_studio_code') or '').strip().upper() for m in masters}
print('=== x_holiday_master (%d registros) ===' % len(masters))
for m in sorted(masters, key=lambda r: r.get('x_studio_code') or ''):
    print('  id=%-4s code=%-28s name=%s' % (m['id'], m.get('x_studio_code'), m.get('x_name')))

# Occurrences
occs = odoo.search_read(
    'x_holiday_occurrence',
    domain=[('x_studio_holiday_id', '!=', False), ('x_studio_holiday_date', '!=', False)],
    fields=['x_studio_holiday_id', 'x_studio_holiday_date'],
)
print('\n=== x_holiday_occurrence: %d filas ===' % len(occs))

by_code = {}
for r in occs:
    code = code_by_id.get(r['x_studio_holiday_id'][0], '?')
    d = datetime.date.fromisoformat(str(r['x_studio_holiday_date'])[:10])
    by_code.setdefault(code, []).append(d)

print('\n%-28s %5s %5s  %-12s %-12s  %s' % ('codigo', 'past', 'fut', 'primera', 'ultima', 'futuras en horizonte'))
missing_future = []
for code in sorted(by_code):
    dates = sorted(by_code[code])
    past = [d for d in dates if d < monday_now]
    futu = [d for d in dates if monday_now <= d <= horizon_end]
    flag = ''
    if code in EXCLUDED_CODES:
        flag = ' [EXCLUIDO por diseno]'
    elif past and not futu:
        flag = ' <<< SIN OCURRENCIA FUTURA'
        missing_future.append(code)
    print('%-28s %5d %5d  %-12s %-12s  %s%s' % (
        code, len(past), len(futu), dates[0], dates[-1],
        ', '.join(str(d) for d in futu) or '-', flag))

print('\n=== Comerciales fijos (generados en el script, no dependen del master) ===')
for code, m, dd in COMMERCIAL_EVENTS:
    nxt = datetime.date(today.year, m, dd)
    if nxt < today:
        nxt = datetime.date(today.year + 1, m, dd)
    print('  %-20s proxima: %s' % (code, nxt))

print('\n=== RESUMEN ===')
print('Horizonte: %s a %s' % (monday_now, horizon_end))
if missing_future:
    print('CODIGOS CON HISTORIA PERO SIN FECHA FUTURA (factor NO se proyectara):')
    for c in missing_future:
        print('  - %s' % c)
else:
    print('OK: todo codigo con historia tiene ocurrencia futura en el horizonte.')
