"""DEBUG read-only: por que el prototipo marca descuadre en 294 facturas.
Toma 3 moves de junio, muestra montos Odoo vs totales parseados + snippet del XML."""
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
    ['name', 'amount_total', 'amount_untaxed', 'amount_tax', 'l10n_cl_dte_file'],
    limit=3, order='amount_total desc')

for m in moves:
    att = odoo.search_read('ir.attachment', [('id', '=', m['l10n_cl_dte_file'][0])],
                           ['datas', 'name'])
    raw = att[0]['datas'] if att else None
    print("=" * 70)
    print(f"{m['name']}  att={att[0]['name'] if att else None}")
    print(f"  Odoo: total={m['amount_total']} neto={m['amount_untaxed']} iva={m['amount_tax']}")
    if not raw:
        print("  sin datas")
        continue
    xml = base64.b64decode(raw).decode('latin-1', 'ignore')
    print(f"  xml len={len(xml)}")
    t = totales_dte(xml)
    print(f"  parseado: {t}")
    # snippet alrededor de <Totales>
    i = xml.find('<Totales>')
    j = xml.find('</Totales>', i)
    print("  <Totales> snippet:", xml[i:j + 10][:400] if i != -1 else "NO HAY <Totales>")
    # buscar variantes de tag (namespaces?)
    for tag in ('MntNeto', 'MntTotal', 'IVA'):
        print(f"    count <{tag}>: {xml.count('<' + tag + '>')}  "
              f"otra forma {tag}>: {xml.count(tag + '>')}")
