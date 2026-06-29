"""DIAG read-only: TODAS las facturas de compra del mes -> productos con ILA
(CodImpAdic 24/25/26/27/271) -> impuesto ACTUAL vs RECOMENDADO. Todos los proveedores.
Salida: impuesto_reco_mes.csv"""
from __future__ import annotations

import base64
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'
P_INI, P_FIN = '2026-06-01', '2026-06-30'
RATE = {'24': '31.5%', '25': '20.5%', '26': '20.5%', '27': '10%', '271': '18%'}


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def main():
    o = OdooReader()
    moves = o.search_read('account.move',
        [('move_type', '=', 'in_invoice'), ('invoice_date', '>=', P_INI),
         ('invoice_date', '<=', P_FIN), ('l10n_cl_dte_file', '!=', False)],
        ['name', 'partner_id', 'l10n_cl_dte_file'])
    att = [m['l10n_cl_dte_file'][0] for m in moves]
    datas = {}
    for i in range(0, len(att), 80):
        for a in o.search_read('ir.attachment', [('id', 'in', att[i:i+80])], ['datas']):
            datas[a['id']] = a['datas']

    # recolectar productos con ILA (dedup por codigo)
    prods = {}   # codigo -> {ean, nombre, imp, prov}
    for m in moves:
        raw = datas.get(m['l10n_cl_dte_file'][0])
        if not raw:
            continue
        xml = base64.b64decode(raw).decode('latin-1', 'ignore')
        prov = m['partner_id'][1] if m['partner_id'] else ''
        i = 0
        while True:
            a = xml.find('<Detalle>', i)
            if a == -1:
                break
            b = xml.find('</Detalle>', a)
            if b == -1:
                break
            blk = xml[a:b]
            imp = _seg(blk, '<CodImpAdic>', '</CodImpAdic>')
            i = b
            if imp not in RATE:
                continue
            cod = _seg(blk, '<VlrCodigo>', '</VlrCodigo>')
            ean = ''
            j = 0
            while True:
                ca = blk.find('<CdgItem>', j)
                if ca == -1:
                    break
                cb = blk.find('</CdgItem>', ca)
                cb2 = blk[ca:cb]
                if 'EAN' in _seg(cb2, '<TpoCodigo>', '</TpoCodigo>').upper():
                    ean = _seg(cb2, '<VlrCodigo>', '</VlrCodigo>')
                j = cb
            key = cod or ean
            if key and key not in prods:
                prods[key] = {'cod': cod, 'ean': ean,
                              'nombre': _seg(blk, '<NmbItem>', '</NmbItem>'),
                              'imp': imp, 'prov': prov}
    print(f"productos distintos con ILA en el mes: {len(prods)}")

    # resolver product.product (default_code o barcode) + impuestos
    codes = [v['cod'] for v in prods.values() if v['cod']]
    eans = [v['ean'] for v in prods.values() if v['ean']]
    by_dc, by_bc = {}, {}
    for i in range(0, len(codes), 80):
        for p in o.search_read('product.product', [('default_code', 'in', codes[i:i+80]),
                ('active', 'in', [True, False])], ['default_code', 'name', 'supplier_taxes_id']):
            by_dc[p['default_code']] = p
    for i in range(0, len(eans), 80):
        for p in o.search_read('product.product', [('barcode', 'in', eans[i:i+80]),
                ('active', 'in', [True, False])], ['barcode', 'name', 'supplier_taxes_id']):
            by_bc[p['barcode']] = p
    tax_ids = set()
    for p in list(by_dc.values()) + list(by_bc.values()):
        tax_ids.update(p.get('supplier_taxes_id') or [])
    taxes = {}
    tl = list(tax_ids)
    for i in range(0, len(tl), 80):
        for t in o.search_read('account.tax', [('id', 'in', tl[i:i+80])], ['name', 'amount']):
            taxes[t['id']] = '%s(%.1f%%)' % (t['name'][:14], t['amount'])

    out = []
    cnt = {'OK': 0, 'falta_ILA': 0, 'sin_producto': 0}
    for v in prods.values():
        p = by_dc.get(v['cod']) or by_bc.get(v['ean'])
        if not p:
            cnt['sin_producto'] += 1
            out.append({'proveedor': v['prov'][:22], 'codigo': v['cod'], 'producto': v['nombre'][:30],
                        'impuesto_actual': '(sin producto)', 'impuesto_recomendado': 'ILA ' + RATE[v['imp']],
                        'estado': 'sin_producto'})
            continue
        actual = ' + '.join(taxes.get(t, str(t)) for t in (p.get('supplier_taxes_id') or [])) or '(sin imp)'
        rate_txt = RATE[v['imp']]
        estado = 'OK' if rate_txt in actual else 'falta_ILA'
        cnt[estado] += 1
        out.append({'proveedor': v['prov'][:22], 'codigo': v['cod'], 'producto': p['name'][:30],
                    'impuesto_actual': actual, 'impuesto_recomendado': 'IVA 19% + ILA ' + rate_txt + ' (cod ' + v['imp'] + ')',
                    'estado': estado})

    out.sort(key=lambda x: (x['estado'] == 'OK', x['proveedor']))
    with open(OUT / 'impuesto_reco_mes.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['proveedor', 'codigo', 'producto', 'impuesto_actual',
                           'impuesto_recomendado', 'estado'], delimiter=';')
        w.writeheader()
        w.writerows(out)

    print("resumen:", cnt)
    print("\n== A CONFIGURAR (falta_ILA / sin_producto) ==")
    for r in out:
        if r['estado'] != 'OK':
            print(f"  {r['proveedor']:22} {str(r['codigo']):9} {r['impuesto_recomendado'][:24]:24} {r['producto']}")


if __name__ == '__main__':
    main()
