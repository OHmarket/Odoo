"""test_uplift_math — tests OFFLINE de la matematica del indice de evento.

No toca Odoo: series sinteticas con la respuesta conocida (casos canonicos
del diseno.md, seccion 7).

    python proyectos/2026-09-01-crecimiento-compras-embonor/test_uplift_math.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from diag_embonor_uplift import (baseline_level, event_week_start,  # noqa: E402
                                 level_recent, ly_364, mad, median,
                                 neighbour_indices, oh_week_start,
                                 uplift_index, week_offset)

fails = []


def check(nombre, got, exp):
    ok = got == exp
    print('  %-4s %-62s got=%s' % ('OK' if ok else 'FAIL', nombre, got))
    if not ok:
        fails.append('%s: esperado %r, obtenido %r' % (nombre, exp, got))


def check_close(nombre, got, exp, tol=1e-9):
    ok = got is not None and abs(got - exp) <= tol
    print('  %-4s %-62s got=%s' % ('OK' if ok else 'FAIL', nombre, got))
    if not ok:
        fails.append('%s: esperado %r +-%s, obtenido %r' % (nombre, exp, tol, got))


def serie(week_event, fn, lo=-10, hi=10):
    """Construye {week_start: valor} con fn(k) para k semanas del evento."""
    return {week_offset(week_event, k): fn(k) for k in range(lo, hi + 1)}


D = datetime.date

print('1. Calendario — la semana del evento se resuelve por fecha, no por ISO fijo')
check('2026: 18-sep es viernes -> semana lun 14-sep', event_week_start(2026), D(2026, 9, 14))
check('2026: ISO de esa semana', event_week_start(2026).isocalendar()[1], 38)
check('2023: 18-sep es lunes -> semana arranca el mismo 18', event_week_start(2023), D(2023, 9, 18))
check('2024: 18-sep es miercoles -> semana lun 16-sep', event_week_start(2024), D(2024, 9, 16))
check('2025: 18-sep es jueves -> semana lun 15-sep', event_week_start(2025), D(2025, 9, 15))
check('2021 borde: 18-sep sabado -> ISO 37, no 38', event_week_start(2021).isocalendar()[1], 37)
check('oh_week_start de un domingo devuelve el lunes previo', oh_week_start(D(2026, 9, 20)), D(2026, 9, 14))
check('LY -364d cae en el mismo weekday', ly_364(D(2026, 9, 14)).weekday(), D(2026, 9, 14).weekday())

print()
print('2. Serie plana con evento 1.5x -> indice exacto 1.50')
we = event_week_start(2025)
plana = serie(we, lambda k: 150.0 if k == 0 else 100.0)
idx = uplift_index(plana, we)
check_close('indice', idx['index'], 1.5)
check_close('baseline', idx['base'], 100.0)
check('semanas de baseline usadas (+-3..+-8)', idx['n_base'], 12)
check_close('borde inferior del rango = indice (serie sin dispersion)', idx['lo'], 1.5)

print()
print('3. Tendencia lineal — la ventana simetrica la cancela; la solo-pre no')
trend = serie(we, lambda k: (100.0 + 2.0 * k) if k != 0 else 150.0)
idx_sim = uplift_index(trend, we)
check_close('indice con ventana simetrica', idx_sim['index'], 1.5)
base_pre = baseline_level(trend, we, symmetric=False)
check_close('baseline solo-pre queda bajo (mediana 89)', base_pre['level'], 89.0)
check('solo-pre sobre-estima el indice (sesgo conocido y documentado)',
      (150.0 / base_pre['level']) > idx_sim['index'], True)

print()
print('4. Robustez — un camion doble en el baseline no mueve la mediana')
outlier = dict(plana)
outlier[week_offset(we, -5)] = 10000.0
check_close('indice con outlier x100 en el baseline', uplift_index(outlier, we)['index'], 1.5)
check_close('mediana ignora el outlier', median([100, 100, 100, 100, 10000]), 100.0)
check_close('mad de serie plana = 0', mad([100, 100, 100]), 0.0)
check('median de lista vacia', median([]), None)

print()
print('5. Reparto pre/post — el peak de compra se adelanta y despues hay payback')
reparto = serie(we, lambda k: {-1: 130.0, 0: 150.0, 1: 70.0}.get(k, 100.0))
nb = neighbour_indices(reparto, we)
check_close('semana previa (llenado)', nb[-1], 1.3)
check_close('semana del evento', nb[0], 1.5)
check_close('semana siguiente (payback)', nb[1], 0.7)

print()
print('6. Guards — sin baseline suficiente no se inventa un indice')
corta = {week_offset(we, 0): 150.0, week_offset(we, -3): 100.0, week_offset(we, -4): 100.0}
check('menos de 4 semanas de baseline -> None', uplift_index(corta, we), None)
check('sin la semana del evento -> None', uplift_index({week_offset(we, -3): 100.0}, we), None)
check('baseline todo en cero -> None (no divide por cero)',
      baseline_level(serie(we, lambda k: 0.0), we), None)

print()
print('7. Nivel base del ano objetivo — solo semanas previas ya cerradas')
ws_target = event_week_start(2026)
actual = {week_offset(ws_target, -k): 120.0 for k in range(3, 9)}
lvl = level_recent(actual, ws_target)
check_close('nivel base = mediana de las 6 semanas previas limpias', lvl['level'], 120.0)
check('no usa semanas futuras', lvl['n'], 6)
check('la ventana parte 3 semanas antes del evento',
      min(lvl['weeks']), week_offset(ws_target, -8))

print()
if fails:
    print('%d TEST(S) FALLARON:' % len(fails))
    for x in fails:
        print('  - %s' % x)
    sys.exit(1)
print('TODOS LOS TESTS PASARON')
