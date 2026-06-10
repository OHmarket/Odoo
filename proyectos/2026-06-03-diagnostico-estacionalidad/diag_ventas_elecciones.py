# -*- coding: utf-8 -*-
"""
DIAG read-only: venta en dias de eleccion 2025 (16-nov primera vuelta,
14-dic balotaje) vs domingos de referencia.

Pregunta: con el cambio legal, las salas atienden en elecciones?
Cuanto venden vs un domingo normal? Decide si ELECTION entra al calendario
como semana sucia (cierre = venta deprimida) o como dia normal/evento.
"""
import datetime
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

ELECTIONS = [datetime.date(2025, 11, 16), datetime.date(2025, 12, 14)]
N_REF = 4   # domingos de referencia antes y despues (excluyendo eventos)

odoo = OdooReader()

# Domingos de referencia: 4 antes y 4 despues de cada eleccion, excluyendo
# la otra eleccion y domingos pegados a feriados conocidos de nov-dic.
skip = set(ELECTIONS) | {datetime.date(2025, 11, 2), datetime.date(2025, 12, 7),
                         datetime.date(2025, 12, 21), datetime.date(2025, 12, 28)}
ref_days = set()
for e in ELECTIONS:
    got, k = 0, 1
    while got < N_REF:
        d = e - datetime.timedelta(weeks=k)
        if d not in skip:
            ref_days.add(d); got += 1
        k += 1
    got, k = 0, 1
    while got < N_REF:
        d = e + datetime.timedelta(weeks=k)
        if d not in skip:
            ref_days.add(d); got += 1
        k += 1

all_days = sorted(ref_days | set(ELECTIONS))
d0, d1 = all_days[0], all_days[-1] + datetime.timedelta(days=1)

rows = odoo.execute(
    'pos.order', 'read_group',
    [('date_order', '>=', d0.isoformat()), ('date_order', '<', d1.isoformat()),
     ('state', 'in', ['paid', 'done', 'invoiced'])],
    ['amount_total'],
    ['config_id', 'date_order:day'],
    lazy=False,
)

# (config, date) -> (monto, n_ordenes)
sales = {}
for r in rows:
    cfg = r['config_id'][1] if r['config_id'] else '?'
    raw = r['date_order:day']  # ej '16 nov 2025' (locale es)
    MES = {'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
           'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
           'jan': 1, 'apr': 4, 'aug': 8, 'dec': 12}
    p = raw.split()
    d = datetime.date(int(p[2]), MES[p[1][:3].lower()], int(p[0]))
    sales[(cfg, d)] = (r['amount_total'], r['__count'])

configs = sorted(set(c for c, _ in sales))
target_days = sorted(set(d for _, d in sales) & (ref_days | set(ELECTIONS)))

print('Ventana: %s a %s | salas con venta: %d' % (d0, d1, len(configs)))
print('Domingos referencia: %s' % ', '.join(str(d) for d in sorted(ref_days)))

for e in ELECTIONS:
    print('\n=== ELECCION %s ===' % e)
    print('%-28s %12s %12s %7s %6s' % ('sala', 'venta_elec', 'med_ref_dom', 'ratio', 'n_ref'))
    tot_e, tot_r = 0.0, 0.0
    abiertas = 0
    for cfg in configs:
        ev = sales.get((cfg, e), (0.0, 0))
        refs = [sales[(cfg, d)][0] for d in sorted(ref_days) if (cfg, d) in sales]
        if not refs:
            continue
        refs_s = sorted(refs)
        med = refs_s[len(refs_s) // 2] if len(refs_s) % 2 else (
            (refs_s[len(refs_s)//2 - 1] + refs_s[len(refs_s)//2]) / 2)
        ratio = ev[0] / med if med > 0 else 0.0
        if ev[0] > 0:
            abiertas += 1
        tot_e += ev[0]
        tot_r += med
        print('%-28s %12.0f %12.0f %7.2f %6d' % (cfg[:28], ev[0], med, ratio, len(refs)))
    print('-' * 70)
    print('%-28s %12.0f %12.0f %7.2f   salas con venta: %d/%d' % (
        'TOTAL', tot_e, tot_r, tot_e / tot_r if tot_r else 0, abiertas, len(configs)))
