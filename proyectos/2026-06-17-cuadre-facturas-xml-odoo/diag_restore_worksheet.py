"""DIAG read-only: worksheet de restauracion de las 13 facturas infladas.
Por linea inflada muestra price_unit actual vs PrcItem del DTE (precio correcto).
Match linea<->Detalle por nombre. Salida: restore_worksheet.csv. NO escribe."""
from __future__ import annotations

import base64
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'

# (folio, vat) de las 13 infladas (DICALLA excluida)
TARGETS = [
    ('007088', '77659607'), ('007087', '77659607'), ('007086', '77659607'),
    ('007005', '77659607'),
    ('2368496', '76484106'), ('2368497', '76484106'), ('2368970', '76484106'),
    ('2368971', '76484106'), ('2368972', '76484106'), ('2368498', '76484106'),
    ('2376293', '76484106'),
    ('2293523', '79576940'), ('1809791', '76706610'),
]


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def _norm(s):
    return ' '.join((s or '').lower().split())


def detalle(xml):
    out = {}
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        nmb = _seg(blk, '<NmbItem>', '</NmbItem>')
        try:
            prc = float(_seg(blk, '<PrcItem>', '</PrcItem>') or 0)
        except ValueError:
            prc = 0
        try:
            monto = float(_seg(blk, '<MontoItem>', '</MontoItem>') or 0)
        except ValueError:
            monto = 0
        out[_norm(nmb)] = {'prc': prc, 'monto': monto}
        i = b
    return out


def main():
    o = OdooReader()
    rows = []
    for folio, vat in TARGETS:
        m = o.search_read('account.move',
            [('move_type', '=', 'in_invoice'), ('name', '=', 'FAC ' + folio),
             ('partner_id.vat', 'like', vat)],
            ['name', 'state', 'amount_total', 'invoice_line_ids', 'l10n_cl_dte_file'])
        if not m:
            print("no encontrada:", folio, vat)
            continue
        mv = m[0]
        det = {}
        if mv.get('l10n_cl_dte_file'):
            att = o.search_read('ir.attachment', [('id', '=', mv['l10n_cl_dte_file'][0])], ['datas'])
            if att and att[0].get('datas'):
                det = detalle(base64.b64decode(att[0]['datas']).decode('latin-1', 'ignore'))
        lines = o.search_read('account.move.line',
            [('id', 'in', mv['invoice_line_ids']), ('display_type', '=', 'product')],
            ['name', 'quantity', 'price_unit', 'price_subtotal', 'product_id'])
        for l in lines:
            d = det.get(_norm(l['name']))
            monto_dte = d['monto'] if d else None   # total neto de la linea (verdad)
            qty = l['quantity'] or 1
            # inflada = subtotal actual MATERIALMENTE mayor al MontoItem del DTE
            inflada = monto_dte is not None and l['price_subtotal'] > monto_dte * 1.5
            price_correcto = round(monto_dte / qty) if (monto_dte and qty) else ''
            rows.append({
                'factura': mv['name'], 'state': mv['state'],
                'linea': l['name'][:40], 'qty': qty,
                'price_actual': round(l['price_unit']),
                'sub_actual': round(l['price_subtotal']),
                'monto_dte': round(monto_dte) if monto_dte is not None else 'SIN_MATCH',
                'price_correcto': price_correcto,
                'inflada': 'SI' if inflada else '',
                'vinculada': 'OK' if l['product_id'] else '-'})

    with open(OUT / 'restore_worksheet.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['factura', 'state', 'linea', 'qty',
                           'price_actual', 'sub_actual', 'monto_dte', 'price_correcto',
                           'inflada', 'vinculada'], delimiter=';')
        w.writeheader()
        w.writerows(rows)

    infl = [r for r in rows if r['inflada'] == 'SI']
    fac_st = {}
    for r in rows:
        fac_st[r['factura']] = r['state']
    fac_infl = {}
    for r in infl:
        fac_infl[r['factura']] = fac_infl.get(r['factura'], 0) + 1
    print(f"lineas totales: {len(rows)} | infladas (material): {len(infl)}")
    print("\nfactura            estado    lineas_infladas")
    for fac in sorted(fac_st):
        print(f"  {fac:16} {fac_st[fac]:8} {fac_infl.get(fac, 0)}")
    print(f"\n{'factura':14} {'linea':30} {'sub_actual':>12} {'monto_dte':>11}")
    for r in infl[:18]:
        print(f"  {r['factura']:14} {r['linea']:30} {r['sub_actual']:>12,} {str(r['monto_dte']):>11}")


if __name__ == '__main__':
    main()
