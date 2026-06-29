"""DEBUG: detalle de los descuadres restantes. Muestra neto/iva/total Odoo vs XML
para entender si son reales (ILA mal en Odoo) u otro borde de parseo."""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402
from dte_totales import totales_dte  # noqa: E402

odoo = OdooReader()
moves = odoo.search_read('account.move',
    [('move_type', '=', 'in_invoice'),
     ('invoice_date', '>=', '2026-06-01'), ('invoice_date', '<=', '2026-06-30'),
     ('l10n_cl_dte_file', '!=', False)],
    ['name', 'partner_id', 'amount_total', 'amount_untaxed', 'amount_tax',
     'l10n_cl_dte_file'], order='amount_total desc')

att_ids = [m['l10n_cl_dte_file'][0] for m in moves]
datas = {}
for i in range(0, len(att_ids), 80):
    for a in odoo.search_read('ir.attachment', [('id', 'in', att_ids[i:i+80])], ['datas']):
        datas[a['id']] = a['datas']

TOL = 1
n = 0
for m in moves:
    raw = datas.get(m['l10n_cl_dte_file'][0])
    if not raw:
        continue
    xml = base64.b64decode(raw).decode('latin-1', 'ignore')
    t = totales_dte(xml)
    if t['total'] is None:
        continue
    d_total = abs(t['total'] - m['amount_total'])
    d_base = abs((t['neto'] + t['exento']) - m['amount_untaxed'])
    d_tax = abs((t['iva'] + t['otros_imp']) - m['amount_tax'])
    if d_total > TOL or d_base > TOL or d_tax > TOL:
        n += 1
        if n <= 20:
            print(f"{m['name'][:18]:18} {str(m['partner_id'][1])[:28]:28} "
                  f"dT={d_total:>9} dBase={d_base:>9} dTax={d_tax:>9} | "
                  f"Odoo(t={m['amount_total']:.0f} n={m['amount_untaxed']:.0f} iva={m['amount_tax']:.0f}) "
                  f"XML(t={t['total']} n={t['neto']} iva={t['iva']} oi={t['otros_imp']} ex={t['exento']})")
print(f"\nTOTAL descuadres: {n}")
