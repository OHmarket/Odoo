"""
DIAG read-only: replica la logica del detector v1.1 sobre draft reales y verifica
que cada fila de error trae lo necesario para corregir despues.

Emite por error: factura | line_id | tipo | descripcion | valor_correcto |
tax_sugerido(id/nombre) | producto_recomendado. NO escribe en Odoo.

Corre: python proyectos/2026-06-17-cuadre-facturas-xml-odoo/diag_detector_v11.py
"""
from __future__ import annotations
import sys, base64
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared.odoo_xmlrpc import OdooReader
from clasifica_linea import clasificar_linea

PROV_TABACO = {'885029000'}          # BAT CHILE 88502900-0 (solo digitos)
TAX_TABACO = 17                      # IVA Compra 19% No Recup.
ILA_CODES = {'24', '25', '26', '27', '271'}
SII_IVA = 14
FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por')
OUT = Path(__file__).resolve().parent / 'resultados'


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def _num(t):
    try:
        return float(t)
    except Exception:
        return 0.0


def _norm(s):
    return ' '.join((s or '').lower().split())


def _es_flete(n):
    nl = (n or '').lower()
    return any(t in nl for t in FLETE)


def parse_items(xml):
    items, i = [], 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        cod = ean = ''
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
        items.append({
            'nombre': _seg(blk, '<NmbItem>', '</NmbItem>'),
            'codigo': cod, 'ean': ean,
            'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
            'prc': _num(_seg(blk, '<PrcItem>', '</PrcItem>')),
            'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>')),
            'imp': _seg(blk, '<CodImpAdic>', '</CodImpAdic>'),
        })
        i = b
    return items


def main():
    o = OdooReader()
    moves = o.search_read('account.move',
        [('move_type', 'in', ['in_invoice', 'in_refund']), ('state', '=', 'draft')],
        ['name', 'partner_id', 'invoice_line_ids', 'l10n_cl_dte_file'],
        order='invoice_date desc', limit=300)

    # partners: vat + tipo_proveedor
    pids = list({m['partner_id'][0] for m in moves if m['partner_id']})
    pmap = {p['id']: p for p in o.search_read('res.partner', [('id', 'in', pids)],
            ['vat', 'x_studio_tipo_proveedor'])}

    # adjuntos
    att_ids = [m['l10n_cl_dte_file'][0] for m in moves if m.get('l10n_cl_dte_file')]
    att = {}
    for i in range(0, len(att_ids), 25):
        for a in o.search_read('ir.attachment', [('id', 'in', att_ids[i:i+25])], ['datas']):
            if a.get('datas'):
                att[a['id']] = base64.b64decode(a['datas']).decode('latin-1', 'ignore')

    # lineas
    all_lids = [lid for m in moves for lid in m['invoice_line_ids']]
    lmap = {}
    for i in range(0, len(all_lids), 200):
        for l in o.search_read('account.move.line', [('id', 'in', all_lids[i:i+200])],
                ['quantity', 'price_unit', 'price_subtotal', 'tax_ids', 'sequence',
                 'display_type', 'name', 'product_id', 'account_id']):
            lmap[l['id']] = l

    # catalogo de taxes de compra: sii_code -> [taxes], y datos por id
    taxes = o.search_read('account.tax',
        [('type_tax_use', '=', 'purchase')],
        ['name', 'amount', 'price_include', 'l10n_cl_sii_code'])
    # tax_by_id en el formato que espera la funcion pura ('sii_code')
    tax_by_id = {t['id']: {'sii_code': t['l10n_cl_sii_code'], 'price_include': t['price_include'],
                           'amount': t['amount'], 'name': t['name']} for t in taxes}
    # rate_to_tax: tasa -> tax id de compra no-IVA, variante "(2024)" (no price_include).
    # A igual tasa, gana el sii_code mas bajo (20,5% -> 25 Vinos, no 26 Cervezas).
    rate_to_tax = {}
    for t in sorted(taxes, key=lambda x: (x['l10n_cl_sii_code'] or 0)):
        if t['l10n_cl_sii_code'] != SII_IVA and not t['price_include']:
            rate_to_tax.setdefault(round(t['amount'], 1), t['id'])

    def find_product(cod, ean, nombre):
        if ean:
            p = o.search_read('product.product', [('barcode', '=', ean)], ['name', 'default_code'], limit=2)
            if len(p) == 1:
                return p[0], 'ean'
        if cod:
            p = o.search_read('product.product', [('default_code', '=', cod)], ['name', 'default_code'], limit=2)
            if len(p) == 1:
                return p[0], 'codigo'
        if nombre:
            p = o.search_read('product.product', [('name', '=ilike', nombre)], ['name', 'default_code'], limit=3)
            if len(p) == 1:
                return p[0], 'nombre'
        return None, 'ambiguo'

    filas = []
    cnt = Counter()
    for m in moves:
        aid = m['l10n_cl_dte_file'][0] if m.get('l10n_cl_dte_file') else None
        xml = att.get(aid)
        if not xml:
            continue
        part = pmap.get(m['partner_id'][0]) if m['partner_id'] else {}
        vat = ''.join(c for c in (part.get('vat') or '') if c.isdigit())
        es_merc = (part.get('x_studio_tipo_proveedor') == 'Mercaderia')
        es_tabaco = vat in PROV_TABACO

        items = parse_items(xml)
        ol = [lmap[lid] for lid in m['invoice_line_ids'] if lid in lmap]
        ol = [l for l in ol if l.get('display_type') not in ('line_section', 'line_note')]
        ol.sort(key=lambda l: (l.get('sequence') or 0))
        alineada = (len(items) == len(ol) and len(items) > 0)

        ctx = {'es_merc': es_merc, 'es_tabaco': es_tabaco,
               'tax_by_id': tax_by_id, 'rate_to_tax': rate_to_tax}
        for idx, l in enumerate(ol):
            it = items[idx] if alineada else None
            ld = {'name': l['name'] or '', 'has_product': bool(l.get('product_id')),
                  'quantity': l['quantity'], 'price_subtotal': l['price_subtotal'],
                  'tax_ids': set(l.get('tax_ids') or [])}
            r = clasificar_linea(ld, it, ctx)
            if not r:
                continue
            tipo = r['tipo']
            valor = r['valor'] if r['valor'] is not None else ''
            tax_sug = ''
            if r['tax_sug']:
                tax_sug = '%s | %s' % (r['tax_sug'], tax_by_id.get(r['tax_sug'], {}).get('name', '?'))
            prod_rec = ''
            if tipo == 'codigo_no_vinculado':
                cod = it['codigo'] if it else ''
                ean = it['ean'] if it else ''
                p, via = find_product(cod, ean, it['nombre'] if it else l['name'])
                prod_rec = ('[%s] %s (via %s)' % (p.get('default_code') or '-', p['name'][:30], via)) \
                    if p else 'revisar (ambiguo/no encontrado)'

            if tipo:
                cnt[tipo] += 1
                filas.append({
                    'factura': m['name'], 'line_id': l['id'],
                    'producto': (l['name'] or '')[:30], 'tipo': tipo,
                    'valor_correcto': valor, 'tax_sugerido': tax_sug,
                    'prod_recomendado': prod_rec,
                    'subOdoo': round(l['price_subtotal']),
                    'subDTE': round(it['monto']) if it else '',
                })

    print('Errores por tipo:', dict(cnt), '| total filas:', len(filas))
    # muestra: que cada tipo trae lo necesario para corregir
    for tp in ['precio', 'impuesto_mal_clasificado', 'codigo_no_vinculado', 'uom_no_cuadra', 'linea_descuadrada']:
        ej = [f for f in filas if f['tipo'] == tp][:5]
        if not ej:
            continue
        print('\n=== %s (%d) ===' % (tp, cnt[tp]))
        for f in ej:
            print('  %s L%s %s | valor=%s | tax=%s | prod=%s | sub O/DTE %s/%s' % (
                f['factura'], f['line_id'], f['producto'], f['valor_correcto'],
                f['tax_sugerido'], f['prod_recomendado'], f['subOdoo'], f['subDTE']))

    OUT.mkdir(exist_ok=True)
    import csv
    with open(OUT / 'detector_v11_draft.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()) if filas else ['tipo'], delimiter=';')
        w.writeheader()
        for f in filas:
            w.writerow(f)
    print('\n[CSV: resultados/detector_v11_draft.csv]')


if __name__ == '__main__':
    main()
