"""
DIAG read-only: valida la taxonomia precio/uom/linea_descuadrada sobre facturas reales.

Logica revisada (2026-06-18):
- subtotal calza  -> OK (si qty calza) | UOM (si qty difiere: representacion pack)
- subtotal NO calza:
    - QtyItem == quantity  -> PRECIO (seguro, qty identica => la dif es precio)
    - qty difiere          -> LINEA_DESCUADRADA (ambiguo: no sabemos UoM vs error real)

Corre: python proyectos/2026-06-17-cuadre-facturas-xml-odoo/diag_precio_cantidad.py [estado]
  estado = draft (default) | posted | todo
"""
from __future__ import annotations
import sys, base64
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


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
            'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
            'prc': _num(_seg(blk, '<PrcItem>', '</PrcItem>')),
            'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>')),
        })
        i = b
    return items


def main():
    estado = sys.argv[1] if len(sys.argv) > 1 else 'draft'
    o = OdooReader()
    dom = [('move_type', 'in', ['in_invoice', 'in_refund'])]
    if estado != 'todo':
        dom.append(('state', '=', estado))
    moves = o.search_read('account.move', dom,
        ['name', 'partner_id', 'invoice_line_ids', 'l10n_cl_dte_file'],
        order='invoice_date desc', limit=300)

    # batch adjuntos
    att_ids = [m['l10n_cl_dte_file'][0] for m in moves if m.get('l10n_cl_dte_file')]
    att = {}
    for i in range(0, len(att_ids), 25):
        for a in o.search_read('ir.attachment', [('id', 'in', att_ids[i:i+25])], ['datas']):
            if a.get('datas'):
                att[a['id']] = base64.b64decode(a['datas']).decode('latin-1', 'ignore')

    # batch lineas
    all_lids = [lid for m in moves for lid in m['invoice_line_ids']]
    lmap = {}
    for i in range(0, len(all_lids), 200):
        for l in o.search_read('account.move.line', [('id', 'in', all_lids[i:i+200])],
                ['quantity', 'price_unit', 'price_subtotal', 'tax_ids', 'sequence',
                 'display_type', 'name']):
            lmap[l['id']] = l

    # batch taxes (price_include + amount)
    tids = set()
    for l in lmap.values():
        tids.update(l.get('tax_ids') or [])
    tax = {t['id']: t for t in o.search_read('account.tax', [('id', 'in', list(tids))],
            ['price_include', 'amount'])} if tids else {}

    cnt = Counter()
    ejemplos = {'PRECIO': [], 'LINEA_DESCUADRADA': [], 'UOM': []}
    n_moves_align = 0
    for m in moves:
        aid = m['l10n_cl_dte_file'][0] if m.get('l10n_cl_dte_file') else None
        xml = att.get(aid)
        if not xml:
            continue
        items = parse_items(xml)
        ol = [lmap[lid] for lid in m['invoice_line_ids'] if lid in lmap]
        ol = [l for l in ol if l.get('display_type') not in ('line_section', 'line_note')]
        ol.sort(key=lambda l: (l.get('sequence') or 0))
        if len(items) != len(ol) or not items:
            cnt['NO_ALINEADA'] += 1
            continue
        n_moves_align += 1
        for it, l in zip(items, ol):
            factor = 1.0
            for tid in (l.get('tax_ids') or []):
                t = tax.get(tid)
                if t and t.get('price_include'):
                    factor += (t.get('amount') or 0) / 100.0
            sub = l['price_subtotal']
            tol = max(2.0, abs(it['monto']) * 0.01)
            d_sub = abs(sub - it['monto'])
            qty_match = abs(l['quantity'] - it['qty']) <= 0.001
            if d_sub <= tol:
                if qty_match:
                    cnt['OK'] += 1
                else:
                    cnt['UOM'] += 1
                    if len(ejemplos['UOM']) < 6:
                        ejemplos['UOM'].append('%s | %s | qtyDTE=%g qtyOdoo=%g sub=%g' % (
                            m['name'], (l['name'] or '')[:28], it['qty'], l['quantity'], sub))
            else:
                if qty_match:
                    cnt['PRECIO'] += 1
                    if len(ejemplos['PRECIO']) < 8:
                        ejemplos['PRECIO'].append(
                            '%s | %s | qty=%g | puOdoo=%g prcDTE=%g x%.3f=%g | subOdoo=%g subDTE=%g' % (
                            m['name'], (l['name'] or '')[:24], l['quantity'], l['price_unit'],
                            it['prc'], factor, it['prc']*factor, sub, it['monto']))
                else:
                    cnt['LINEA_DESCUADRADA'] += 1
                    if len(ejemplos['LINEA_DESCUADRADA']) < 8:
                        ejemplos['LINEA_DESCUADRADA'].append(
                            '%s | %s | qtyDTE=%g qtyOdoo=%g | subOdoo=%g subDTE=%g' % (
                            m['name'], (l['name'] or '')[:24], it['qty'], l['quantity'], sub, it['monto']))

    print('Estado: %s | moves: %d | alineadas (mismo n lineas): %d' % (estado, len(moves), n_moves_align))
    print('Lineas por caso:', dict(cnt))
    tot_lineas = sum(v for k, v in cnt.items() if k != 'NO_ALINEADA')
    for k in ['PRECIO', 'LINEA_DESCUADRADA', 'UOM']:
        print('\n=== %s (%d) ===' % (k, cnt[k]))
        for e in ejemplos[k]:
            print(' ', e)


if __name__ == '__main__':
    main()
