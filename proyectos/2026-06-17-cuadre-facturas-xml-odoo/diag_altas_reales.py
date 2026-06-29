"""DIAG read-only: de los 33 'no_existe', separa altas REALES de:
  - existe_por_barcode (EAN del DTE matchea product.barcode -> reproceso, no crear)
  - junk (descripcion numerica / delivery / bonificacion -> no es producto)
Salida: altas_reales.csv"""
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
JUNK_DESC = re.compile(r'^\s*[\d.,]+\s*$')
JUNK_KW = re.compile(r'deliver|bonificac|flete|transport|despacho', re.I)


def _norm(s):
    return ' '.join((s or '').lower().split())


def detalle_eans(xml):
    idx = {}
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        m = re.search(r'<NmbItem>(.*?)</NmbItem>', blk, re.S)
        nmb = m.group(1).strip() if m else ''
        eans = []
        for cd in re.findall(r'<CdgItem>(.*?)</CdgItem>', blk, re.S):
            tpo = re.search(r'<TpoCodigo>(.*?)</TpoCodigo>', cd)
            vlr = re.search(r'<VlrCodigo>(.*?)</VlrCodigo>', cd)
            if vlr and tpo and 'EAN' in tpo.group(1).upper():
                eans.append(vlr.group(1).strip())
        idx[_norm(nmb)] = eans
        i = b
    return idx


def main():
    odoo = OdooReader()
    no_existe = [r for r in csv.DictReader(
        open(OUT / 'cruce_codigos_maestro.csv', encoding='utf-8-sig'), delimiter=';')
        if r['estado'] == 'no_existe']
    # factura ejemplo por (rut,codigo) desde el detalle
    linmap = defaultdict(list)
    for r in csv.DictReader(open(OUT / 'codigos_dte_sin_producto.csv',
                                 encoding='utf-8-sig'), delimiter=';'):
        linmap[(r['rut_proveedor'], r['codigo_dte'])].append(r['factura'])
    facturas = sorted({f for r in no_existe
                       for f in linmap.get((r['rut_proveedor'], r['codigo_dte']), [])})

    # DTEs de esas facturas -> nombre->eans
    moves = {}
    for i in range(0, len(facturas), 80):
        for m in odoo.search_read('account.move',
                [('move_type', '=', 'in_invoice'), ('name', 'in', facturas[i:i+80])],
                ['name', 'l10n_cl_dte_file']):
            moves[m['name']] = m
    att_ids = [m['l10n_cl_dte_file'][0] for m in moves.values() if m.get('l10n_cl_dte_file')]
    datas = {}
    for i in range(0, len(att_ids), 80):
        for a in odoo.search_read('ir.attachment', [('id', 'in', att_ids[i:i+80])], ['datas']):
            datas[a['id']] = a['datas']
    fac_idx = {}
    for name, m in moves.items():
        raw = datas.get(m['l10n_cl_dte_file'][0]) if m.get('l10n_cl_dte_file') else None
        if raw:
            fac_idx[name] = detalle_eans(base64.b64decode(raw).decode('latin-1', 'ignore'))

    # EAN por target + junk
    all_eans = set()
    for r in no_existe:
        eans = []
        for fac in linmap.get((r['rut_proveedor'], r['codigo_dte']), []):
            eans = fac_idx.get(fac, {}).get(_norm(r['descripcion']), [])
            if eans:
                break
        r['_eans'] = eans
        all_eans.update(eans)

    # buscar barcodes
    bc = {}
    el = list(all_eans)
    for i in range(0, len(el), 80):
        for p in odoo.search_read('product.product',
                [('barcode', 'in', el[i:i+80]), ('active', 'in', [True, False])],
                ['barcode', 'default_code', 'name']):
            bc[p['barcode']] = p

    rows = []
    cnt = defaultdict(int)
    for r in no_existe:
        desc = r['descripcion']
        prod = next((bc[e] for e in r['_eans'] if e in bc), None)
        if JUNK_DESC.match(desc) or JUNK_KW.search(desc):
            estado = 'junk'
        elif prod:
            estado = 'existe_por_barcode'
        else:
            estado = 'ALTA_REAL'
        cnt[estado] += 1
        rows.append({'rut': r['rut_proveedor'], 'codigo_dte': r['codigo_dte'],
                     'descripcion': desc, 'n_lineas': r['n_lineas'], 'estado': estado,
                     'producto_existente': '%s / %s' % (prod['default_code'], prod['name']) if prod else ''})

    with open(OUT / 'altas_reales.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['rut', 'codigo_dte', 'descripcion',
                           'n_lineas', 'estado', 'producto_existente'], delimiter=';')
        w.writeheader()
        w.writerows(rows)

    print("resumen de los 33 no_existe:", dict(cnt), "\n")
    print("== ALTAS REALES (crear en maestro) ==")
    for r in rows:
        if r['estado'] == 'ALTA_REAL':
            print(f"   {r['rut'][:10]:10} {r['codigo_dte']:12} {r['descripcion'][:46]}")
    print("\n== junk (no crear) ==")
    for r in rows:
        if r['estado'] == 'junk':
            print(f"   {r['codigo_dte']:12} {r['descripcion'][:46]}")


if __name__ == '__main__':
    main()
