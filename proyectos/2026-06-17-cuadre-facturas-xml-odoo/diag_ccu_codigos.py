"""DIAG read-only: codigos de producto de CCU + su impuesto adicional (CodImpAdic
= ILA) para configurar. CCU trae EAN13 -> cruza maestro por default_code y barcode.
Salida: ccu_codigos_config.csv"""
from __future__ import annotations

import base64
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'
VAT = '99554560'


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def items(xml):
    hdr = []
    i = 0
    while True:
        a = xml.find('<ImptoReten>', i)
        if a == -1:
            break
        b = xml.find('</ImptoReten>', a)
        hdr.append(_seg(xml[a:b], '<TipoImp>', '</TipoImp>'))
        i = b
    out = []
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
        imp = _seg(blk, '<CodImpAdic>', '</CodImpAdic>')
        cod = ''
        ean = ''
        j = 0
        while True:
            ca = blk.find('<CdgItem>', j)
            if ca == -1:
                break
            cb = blk.find('</CdgItem>', ca)
            cblk = blk[ca:cb]
            tpo = _seg(cblk, '<TpoCodigo>', '</TpoCodigo>')
            vlr = _seg(cblk, '<VlrCodigo>', '</VlrCodigo>')
            if vlr:
                if 'EAN' in tpo.upper():
                    ean = vlr
                elif not cod:
                    cod = vlr
            j = cb
        out.append({'codigo': cod, 'ean': ean, 'nombre': nmb, 'imp': imp,
                    'hdr': ','.join([h for h in hdr if h])})
        i = b
    return out


def main():
    o = OdooReader()
    moves = o.search_read('account.move',
        [('move_type', '=', 'in_invoice'), ('partner_id.vat', 'like', VAT),
         ('invoice_date', '>=', '2026-01-01'), ('l10n_cl_dte_file', '!=', False)],
        ['l10n_cl_dte_file'])
    print(f"CCU 2026 con DTE: {len(moves)}")
    att_ids = [m['l10n_cl_dte_file'][0] for m in moves]
    datas = {}
    for i in range(0, len(att_ids), 80):
        for a in o.search_read('ir.attachment', [('id', 'in', att_ids[i:i+80])], ['datas']):
            datas[a['id']] = a['datas']

    agg = {}
    for m in moves:
        raw = datas.get(m['l10n_cl_dte_file'][0])
        if not raw:
            continue
        for it in items(base64.b64decode(raw).decode('latin-1', 'ignore')):
            if not it['codigo']:
                continue
            k = it['codigo']
            if k not in agg:
                agg[k] = {'nombre': it['nombre'], 'ean': it['ean'],
                          'imp': set(), 'hdr': set(), 'n': 0}
            if it['imp']:
                agg[k]['imp'].add(it['imp'])
            if it['hdr']:
                agg[k]['hdr'].add(it['hdr'])
            if it['ean'] and not agg[k]['ean']:
                agg[k]['ean'] = it['ean']
            agg[k]['n'] += 1

    # cruce maestro: por default_code y por barcode(EAN)
    codes = list(agg)
    eans = [v['ean'] for v in agg.values() if v['ean']]
    dc_hit, bc_hit = set(), set()
    for i in range(0, len(codes), 80):
        for p in o.search_read('product.product', [('default_code', 'in', codes[i:i+80]),
                               ('active', 'in', [True, False])], ['default_code']):
            dc_hit.add(p['default_code'])
    for i in range(0, len(eans), 80):
        for p in o.search_read('product.product', [('barcode', 'in', eans[i:i+80]),
                               ('active', 'in', [True, False])], ['barcode']):
            bc_hit.add(p['barcode'])

    rows = []
    for c, v in agg.items():
        en_mae = 'default_code' if c in dc_hit else ('barcode' if v['ean'] in bc_hit else 'NO')
        rows.append({'codigo_ccu': c, 'ean': v['ean'], 'nombre': v['nombre'],
                     'cod_imp_adic': '|'.join(sorted(v['imp'])),
                     'imp_encabezado': '|'.join(sorted(v['hdr'])),
                     'en_maestro': en_mae, 'n_facturas': v['n']})
    rows.sort(key=lambda r: -r['n_facturas'])
    with open(OUT / 'ccu_codigos_config.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['codigo_ccu', 'ean', 'nombre', 'cod_imp_adic',
                           'imp_encabezado', 'en_maestro', 'n_facturas'], delimiter=';')
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"codigos CCU distintos: {len(rows)}")
    print("  CodImpAdic:", dict(Counter(r['cod_imp_adic'] or '(ninguno)' for r in rows)))
    print("  en maestro:", dict(Counter(r['en_maestro'] for r in rows)))
    print(f"\n{'codigo':10} {'imp':6} {'mae':12} {'nombre'}")
    for r in rows[:25]:
        print(f"  {r['codigo_ccu']:10} {r['cod_imp_adic']:6} {r['en_maestro']:12} {r['nombre'][:38]}")


if __name__ == '__main__':
    main()
