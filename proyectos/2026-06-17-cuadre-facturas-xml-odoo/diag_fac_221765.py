"""DIAG read-only: FAC 221765 Odoo vs XML del DTE.
Compara totales (neto/iva/otros/total) y linea a linea (qty/precio/subtotal)."""
from __future__ import annotations
import sys, base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader       # noqa: E402
from dte_totales import totales_dte             # noqa: E402

FOLIO = sys.argv[1] if len(sys.argv) > 1 else '221765'


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
        items.append({
            'cod': _seg(blk, '<VlrCodigo>', '</VlrCodigo>'),
            'nmb': _seg(blk, '<NmbItem>', '</NmbItem>'),
            'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
            'prc': _num(_seg(blk, '<PrcItem>', '</PrcItem>')),
            'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>')),
        })
        i = b
    return items


o = OdooReader()
FIELDS = ['name', 'ref', 'partner_id', 'invoice_date', 'state', 'move_type',
          'amount_total', 'amount_untaxed', 'amount_tax',
          'invoice_line_ids', 'l10n_cl_dte_file', 'l10n_latam_document_number']
# exacto por numero de documento (AND explicito)
moves = o.search_read('account.move',
    ['&', ('move_type', 'in', ['in_invoice', 'in_refund']),
     ('l10n_latam_document_number', '=', FOLIO)], FIELDS)
if not moves:  # fallback ilike sobre name
    moves = o.search_read('account.move',
        ['&', ('move_type', 'in', ['in_invoice', 'in_refund']),
         ('name', 'ilike', FOLIO)], FIELDS)

print('Folio buscado:', FOLIO, '| matches:', len(moves))
for m in moves:
    print('=' * 78)
    print('%s | ref=%s | docnum=%s | %s | %s | %s' % (
        m['name'], m.get('ref'), m.get('l10n_latam_document_number'),
        m['partner_id'][1] if m.get('partner_id') else '-',
        m.get('invoice_date'), m.get('state')))
    print('ODOO   neto=%s iva=%s total=%s' % (
        m['amount_untaxed'], m['amount_tax'], m['amount_total']))

    aid = m['l10n_cl_dte_file'][0] if m.get('l10n_cl_dte_file') else None
    xml = None
    if aid:
        att = o.search_read('ir.attachment', [('id', '=', aid)], ['datas', 'name'])
        if att and att[0].get('datas'):
            xml = base64.b64decode(att[0]['datas']).decode('latin-1', 'ignore')
    if not xml:
        print('  >> SIN XML adjunto')
        continue

    t = totales_dte(xml)
    print('DTE    neto=%s iva=%s otros=%s total=%s' % (
        t['neto'], t['iva'], t['otros_imp'], t['total']))
    print('DELTA  total Odoo-DTE = %s' % (m['amount_total'] - (t['total'] or 0)))

    # lineas
    items = parse_items(xml)
    ol = o.search_read('account.move.line',
        [('id', 'in', m['invoice_line_ids'])],
        ['quantity', 'price_unit', 'price_subtotal', 'tax_ids',
         'sequence', 'display_type', 'name', 'product_id'])
    ol = [l for l in ol if l.get('display_type') not in ('line_section', 'line_note')]
    ol.sort(key=lambda l: (l.get('sequence') or 0))
    print('\nLINEAS  DTE=%d  Odoo=%d' % (len(items), len(ol)))
    n = max(len(items), len(ol))
    for k in range(n):
        it = items[k] if k < len(items) else None
        l = ol[k] if k < len(ol) else None
        sit = ('DTE  q=%g pu=%g mto=%g  %s' % (
            it['qty'], it['prc'], it['monto'], it['nmb'][:30])) if it else 'DTE  --'
        sol = ('ODOO q=%g pu=%g sub=%g  %s' % (
            l['quantity'], l['price_unit'], l['price_subtotal'],
            (l['name'] or '')[:30])) if l else 'ODOO --'
        flag = ''
        if it and l:
            if abs(l['price_subtotal'] - it['monto']) > max(2.0, abs(it['monto']) * 0.01):
                flag = '  <-- SUBTOTAL'
            elif abs(l['quantity'] - it['qty']) > 0.001:
                flag = '  <-- QTY/UoM'
        print('  [%d] %s | %s%s' % (k, sit, sol, flag))
