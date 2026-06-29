"""Banco de pruebas read-only del monitor (Fase 1). NO escribe en Odoo.
Solo junio 2026. Lectura batcheada para no castigar el POS.

Integra:
  - tipo de proveedor (res.partner.x_studio_tipo_proveedor): el chequeo de SKU
    solo aplica a proveedores 'Mercaderia'; servicios quedan fuera.
  - regla de cuenta: producto almacenable -> cuenta 210230. sin_sku = linea en
    210230 sin product_id y que NO sea flete/transporte.
Corre: python monitor_prototipo.py"""
from __future__ import annotations

import base64
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402
from dte_totales import totales_dte  # noqa: E402
from reglas_registro import evaluar_move  # noqa: E402
from concilia_sii import clave  # noqa: E402

P_INI, P_FIN = '2026-06-01', '2026-06-30'
OUT = Path(__file__).resolve().parent / 'resultados'
CHUNK = 80
CUENTA_ALMACENABLE = '210230'
FLETE_TERMS = ('flete', 'transport', 'despacho', 'reparto', 'acarreo')


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _es_flete(nombre):
    n = (nombre or '').lower()
    return any(t in n for t in FLETE_TERMS)


def main():
    odoo = OdooReader()

    # id de la cuenta de almacenable (210230)
    acc = odoo.search_read('account.account',
                           [('code', '=', CUENTA_ALMACENABLE)], ['id'])
    acc_alm = acc[0]['id'] if acc else None

    dom = [('move_type', '=', 'in_invoice'),
           ('invoice_date', '>=', P_INI), ('invoice_date', '<=', P_FIN)]
    moves = odoo.search_read('account.move', dom, fields=[
        'name', 'state', 'partner_id', 'amount_total', 'amount_untaxed',
        'amount_tax', 'l10n_latam_document_type_id_code',
        'l10n_latam_document_number', 'l10n_cl_dte_file', 'invoice_line_ids'],
        order='amount_total desc')
    print(f"moves junio: {len(moves)}")

    # proveedor: vat + tipo (batch)
    pids = sorted({m['partner_id'][0] for m in moves if m['partner_id']})
    partners = {}
    for ch in _chunks(pids, CHUNK):
        for p in odoo.search_read('res.partner', [('id', 'in', ch)],
                                  ['vat', 'x_studio_tipo_proveedor']):
            partners[p['id']] = {'vat': p.get('vat'),
                                 'tipo': p.get('x_studio_tipo_proveedor') or ''}

    # duplicados por (rut,tipo,folio)
    cont, keys = Counter(), {}
    for m in moves:
        pid = m['partner_id'][0] if m['partner_id'] else 0
        k = clave(partners.get(pid, {}).get('vat'),
                  m.get('l10n_latam_document_type_id_code'),
                  m.get('l10n_latam_document_number') or '0')
        keys[m['id']] = k
        cont[k] += 1

    # lineas (batch): incluye account_id para la regla de cuenta
    line_ids = sorted({lid for m in moves for lid in m['invoice_line_ids']})
    lines = {}
    for ch in _chunks(line_ids, CHUNK):
        for l in odoo.search_read('account.move.line', [('id', 'in', ch)],
                                  ['move_id', 'display_type', 'product_id',
                                   'account_id', 'price_total', 'name']):
            lines[l['id']] = l

    # adjuntos DTE (batch)
    att_ids = sorted({m['l10n_cl_dte_file'][0] for m in moves
                      if m.get('l10n_cl_dte_file')})
    datas = {}
    for ch in _chunks(att_ids, CHUNK):
        for a in odoo.search_read('ir.attachment', [('id', 'in', ch)], ['datas']):
            datas[a['id']] = a.get('datas')
    print(f"adjuntos: {len(datas)} | lineas: {len(lines)}")

    filas, codigos_sin_vinculo = [], []
    n_flete = 0
    for m in moves:
        pid = m['partner_id'][0] if m['partner_id'] else 0
        pinfo = partners.get(pid, {})
        rut, tipo = pinfo.get('vat'), pinfo.get('tipo', '')
        es_merc = (tipo == 'Mercaderia')

        mlines = [lines[i] for i in m['invoice_line_ids'] if i in lines]
        prod = [l for l in mlines if l.get('display_type') == 'product']
        en_alm = [l for l in prod
                  if l.get('account_id') and l['account_id'][0] == acc_alm]
        flete = [l for l in en_alm if not l.get('product_id') and _es_flete(l.get('name'))]
        sin_sku = [l for l in en_alm
                   if not l.get('product_id') and not _es_flete(l.get('name'))]
        n_flete += len(flete)

        # gate por tipo: el chequeo de SKU solo aplica a Mercaderia
        n_sin_sku = len(sin_sku) if es_merc else 0
        if es_merc:
            for l in sin_sku:
                codigos_sin_vinculo.append((rut, m['name'], l.get('name'),
                                            l.get('price_total')))

        tiene_xml = bool(m.get('l10n_cl_dte_file'))
        tot = {'total': None, 'neto': 0, 'iva': 0, 'otros_imp': 0, 'exento': 0}
        if tiene_xml:
            raw = datas.get(m['l10n_cl_dte_file'][0])
            if raw:
                try:
                    xml = base64.b64decode(raw).decode('latin-1', 'ignore')
                    tot = totales_dte(xml)
                except Exception:
                    pass

        v = evaluar_move(dict(
            state=m['state'], amount_total=m['amount_total'],
            amount_untaxed=m['amount_untaxed'], amount_tax=m['amount_tax'],
            tiene_xml=tiene_xml, tipo_code=m.get('l10n_latam_document_type_id_code'),
            xml_total=tot['total'], xml_neto=tot['neto'], xml_iva=tot['iva'],
            xml_otros=tot['otros_imp'], xml_exento=tot['exento'],
            n_lineas_prod=len(prod), n_lineas_sin_sku=n_sin_sku,
            es_duplicado=cont[keys[m['id']]] > 1))
        filas.append((v['color'], m['name'],
                      m['partner_id'][1] if m['partner_id'] else '',
                      tipo, m.get('l10n_latam_document_type_id_code'),
                      m.get('l10n_latam_document_number'), v['error'],
                      v['monto_riesgo'], v['accion'], m['amount_total'],
                      tot['total']))

    OUT.mkdir(exist_ok=True)
    with open(OUT / 'monitor_junio.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['color', 'factura', 'proveedor', 'tipo_proveedor', 'tipo_doc',
                    'folio', 'error', 'monto_riesgo', 'accion', 'total_odoo',
                    'total_xml'])
        for row in sorted(filas, key=lambda r: -r[7]):
            w.writerow(row)
    with open(OUT / 'codigos_sin_vinculo.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['rut_proveedor', 'factura', 'descripcion_linea', 'monto'])
        for row in codigos_sin_vinculo:
            w.writerow(row)

    c = Counter(r[0] for r in filas)

    def cnt(code):
        return sum(code in r[6].split(',') for r in filas)

    print("por color:", dict(c))
    print("no_contabilizado:", cnt('no_contabilizado'), "| sin_xml:", cnt('sin_xml'))
    print("descuadre_total:", cnt('descuadre_total'), "| impuesto_mal:", cnt('impuesto_mal'))
    print("sin_sku (facturas mercaderia):", cnt('sin_sku'),
          "| lineas:", len(codigos_sin_vinculo))
    print("flete/transporte en 210230 (no error):", n_flete)
    sin_tipo = sum(1 for r in filas if not r[3])
    print("facturas con proveedor SIN tipo cargado:", sin_tipo)


if __name__ == '__main__':
    main()
