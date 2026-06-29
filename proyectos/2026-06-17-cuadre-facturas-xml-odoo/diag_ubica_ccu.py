"""DIAG read-only: ubica los codigos CCU 'no_existe' en el maestro por su EAN13.
El DTE de CCU trae EAN13 ademas del codigo interno; el producto en OH vincula por
barcode. Para cada codigo target: saca el EAN del Detalle (match por nombre) y
busca product.product por barcode. Salida: ubica_ccu.csv."""
from __future__ import annotations

import base64
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'
RUT_CCU = '99554560'


def _norm(s):
    return ' '.join((s or '').lower().split())


def detalle_full(xml):
    """Lista de items: {nombre, eans:[...], codigos:[...]}."""
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
        nmb = ''
        m = re.search(r'<NmbItem>(.*?)</NmbItem>', blk, re.S)
        if m:
            nmb = m.group(1).strip()
        eans, cods = [], []
        for cd in re.findall(r'<CdgItem>(.*?)</CdgItem>', blk, re.S):
            tpo = re.search(r'<TpoCodigo>(.*?)</TpoCodigo>', cd)
            vlr = re.search(r'<VlrCodigo>(.*?)</VlrCodigo>', cd)
            if not vlr:
                continue
            v = vlr.group(1).strip()
            if tpo and 'EAN' in tpo.group(1).upper():
                eans.append(v)
            else:
                cods.append(v)
        out.append({'nombre': nmb, 'eans': eans, 'codigos': cods})
        i = b
    return out


def main():
    odoo = OdooReader()
    # targets: CCU no_existe
    targets = [r for r in csv.DictReader(
        open(OUT / 'cruce_codigos_maestro.csv', encoding='utf-8-sig'), delimiter=';')
        if r['rut_proveedor'].startswith(RUT_CCU) and r['estado'] == 'no_existe']
    print(f"targets CCU no_existe: {len(targets)}")

    # CCU June DTEs -> nombre_norm -> item
    moves = odoo.search_read('account.move',
        [('move_type', '=', 'in_invoice'), ('partner_id.vat', 'like', RUT_CCU),
         ('invoice_date', '>=', '2026-06-01'), ('invoice_date', '<=', '2026-06-30'),
         ('l10n_cl_dte_file', '!=', False)],
        ['l10n_cl_dte_file'])
    att_ids = [m['l10n_cl_dte_file'][0] for m in moves]
    datas = {}
    for i in range(0, len(att_ids), 80):
        for a in odoo.search_read('ir.attachment', [('id', 'in', att_ids[i:i+80])], ['datas']):
            datas[a['id']] = a['datas']
    idx = {}
    for m in moves:
        raw = datas.get(m['l10n_cl_dte_file'][0])
        if not raw:
            continue
        xml = base64.b64decode(raw).decode('latin-1', 'ignore')
        for it in detalle_full(xml):
            idx[_norm(it['nombre'])] = it

    # para cada target: EAN del Detalle + buscar producto por barcode
    enrich = []
    all_eans = set()
    for t in targets:
        it = idx.get(_norm(t['descripcion']), {})
        eans = it.get('eans', [])
        all_eans.update(eans)
        enrich.append({'codigo': t['codigo_dte'], 'desc': t['descripcion'],
                       'eans': eans})

    # buscar productos por barcode (batch)
    bc_map = {}
    eans = list(all_eans)
    for i in range(0, len(eans), 80):
        for p in odoo.search_read('product.product',
                [('barcode', 'in', eans[i:i+80]), ('active', 'in', [True, False])],
                ['barcode', 'default_code', 'name', 'active']):
            bc_map[p['barcode']] = p

    rows, found = [], 0
    for e in enrich:
        prod = next((bc_map[x] for x in e['eans'] if x in bc_map), None)
        if prod:
            found += 1
        rows.append({'codigo_dte': e['codigo'], 'descripcion': e['desc'],
                     'ean': ' | '.join(e['eans']) or '(sin EAN en DTE)',
                     'estado': 'EXISTE por barcode' if prod else 'no encontrado',
                     'producto_maestro': '%s / %s%s' % (
                         prod['default_code'], prod['name'],
                         '' if prod['active'] else ' [archivado]') if prod else ''})

    with open(OUT / 'ubica_ccu.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['codigo_dte', 'descripcion', 'ean',
                                          'estado', 'producto_maestro'], delimiter=';')
        w.writeheader()
        w.writerows(rows)

    print(f"\nde {len(targets)}: EXISTEN por barcode = {found} | no encontrados = {len(targets)-found}\n")
    for r in rows:
        print(f"  {r['codigo_dte']:12} {r['descripcion'][:34]:34} {r['estado']:20} {r['producto_maestro'][:40]}")


if __name__ == '__main__':
    main()
