"""DIAG read-only: BAT - descuadre Odoo vs DTE (patron tabaco).
Lee el DTE adjunto a CADA factura (no busca por folio) y compara totales.
Salida: bat_descuadre.csv"""
from __future__ import annotations

import base64
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402
from dte_totales import totales_dte  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'


def main():
    o = OdooReader()
    moves = o.search_read('account.move',
        [('move_type', '=', 'in_invoice'), ('partner_id.vat', 'like', '88502900'),
         ('invoice_date', '>=', '2026-01-01'), ('l10n_cl_dte_file', '!=', False)],
        ['name', 'state', 'amount_total', 'l10n_cl_dte_file'], order='invoice_date desc')
    print(f"BAT 2026 con DTE: {len(moves)}")

    att_ids = [m['l10n_cl_dte_file'][0] for m in moves]
    datas = {}
    for i in range(0, len(att_ids), 80):
        for a in o.search_read('ir.attachment', [('id', 'in', att_ids[i:i+80])], ['datas']):
            datas[a['id']] = a['datas']

    rows, n_desc, monto_desc = [], 0, 0
    for m in moves:
        raw = datas.get(m['l10n_cl_dte_file'][0])
        if not raw:
            continue
        t = totales_dte(base64.b64decode(raw).decode('latin-1', 'ignore'))
        if t['total'] is None:
            continue
        d = m['amount_total'] - t['total']
        desc = abs(d) > 1
        if desc:
            n_desc += 1
            monto_desc += abs(d)
        rows.append({'factura': m['name'], 'state': m['state'],
                     'odoo_total': m['amount_total'], 'dte_total': t['total'],
                     'descuadre': round(d), 'es_descuadre': 'si' if desc else 'no'})

    rows.sort(key=lambda r: -abs(r['descuadre']))
    with open(OUT / 'bat_descuadre.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['factura', 'state', 'odoo_total', 'dte_total',
                                          'descuadre', 'es_descuadre'], delimiter=';')
        w.writeheader()
        w.writerows(rows)

    print(f"con descuadre: {n_desc}/{len(rows)} | $ total descuadre: {monto_desc:,.0f}")
    print(f"\n{'factura':16} {'state':8} {'odoo':>10} {'dte':>10} {'descuadre':>10}")
    for r in rows[:20]:
        print(f"  {r['factura']:16} {r['state']:8} {r['odoo_total']:>10,.0f} {r['dte_total']:>10,.0f} {r['descuadre']:>10,.0f}")


if __name__ == '__main__':
    main()
