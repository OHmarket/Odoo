"""inspect_cola_formato.py — READ-ONLY. Detalle de las facturas donde la tabla
(formato,cc) predice MUY por debajo del recargo real (ratio<0.5), para ver la
causa: UoM rara (Display de N), unidades sub-contadas, o recargo extra real.
"""
import sys
import re
from collections import defaultdict
from statistics import median
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')
RE_NXCC = re.compile(r'(\d+)\s*[xX]\s*(\d+(?:[.,]\d+)?)\s*(cc|ml|l|lt|lts|litros?)\b', re.I)
RE_CC = re.compile(r'(\d+(?:[.,]\d+)?)\s*(cc|ml|l|lt|lts|litros?)\b', re.I)


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def is_charge(label):
    lab = (label or '').strip().lower()
    return any(w in lab for w in CHARGE_WORDS) if lab else False


def _to_cc(num, unit):
    x = float(str(num).replace(',', '.'))
    return x * 1000.0 if unit.lower() in ('l', 'lt', 'lts', 'litro', 'litros') else x


def cc_from_name(name):
    n = name or ''
    m = RE_NXCC.search(n)
    if m:
        return _to_cc(m.group(2), m.group(3))
    m = RE_CC.search(n)
    return _to_cc(m.group(1), m.group(2)) if m else 0.0


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    uom_cache, info_cache, tmpl_cache = {}, {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]

    def tmpl_fmt(tid):
        if tid not in tmpl_cache:
            r = o.search_read('product.template', [('id', '=', tid)], fields=['x_studio_formato'], limit=1)
            tmpl_cache[tid] = (r[0].get('x_studio_formato') or '(vacio)') if r else '(vacio)'
        return tmpl_cache[tid]

    def prod_info(pdid):
        if pdid not in info_cache:
            r = o.search_read('product.product', [('id', '=', pdid)],
                              fields=['standard_price', 'display_name', 'product_tmpl_id'], limit=1)
            std = f(r[0].get('standard_price')) if r else 0.0
            nm = (r[0].get('display_name') or '') if r else ''
            tid = r[0]['product_tmpl_id'][0] if (r and r[0].get('product_tmpl_id')) else None
            fmt = tmpl_fmt(tid) if tid else '(vacio)'
            if 'cooler' in nm.lower() and fmt == 'vidrio':
                fmt = 'cooler'
            info_cache[pdid] = (std, nm, fmt, cc_from_name(nm))
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id', 'name'], order='id', limit=1500)

    facturas = []
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal'])
        plist, rec = [], 0.0
        for l in lines:
            qty = f(l['quantity'])
            if qty <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            std, nm, fmt, ccn = prod_info(l['product_id'][0])
            uname = l['product_uom_id'][1] if l['product_uom_id'] else '?'
            if std <= 0 or ccn <= 0 or fmt == '(vacio)':
                plist.append(None)
                continue
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            net = f(l['price_subtotal'])
            u_unit, u_pack = qty, qty * ratio
            unid = u_unit if abs(net/u_unit - std) <= abs(net/u_pack - std) else u_pack
            plist.append({'fmt': fmt, 'cc': ccn, 'unid': unid, 'net': net, 'qty': qty,
                          'pack': ratio, 'uom': uname, 'nm': nm, 'std': std})
        if rec > 0 and plist:
            facturas.append((m['name'], rec, plist))

    tab = defaultdict(list)
    for _, rec, plist in facturas:
        valid = [p for p in plist if p]
        if len(valid) == 1 and abs(valid[0]['net']/valid[0]['unid'] - valid[0]['std'])/valid[0]['std'] <= 0.15:
            p = valid[0]
            tab[(p['fmt'], p['cc'])].append(rec / p['unid'])
    table = {k: median(v) for k, v in tab.items()}

    shown = 0
    for name, rec, plist in facturas:
        ls = [p for p in plist if p]
        if not ls or not all((p['fmt'], p['cc']) in table for p in ls):
            continue
        pred = sum(table[(p['fmt'], p['cc'])] * p['unid'] for p in ls)
        if rec <= 0 or pred <= 0 or pred / rec >= 0.5:
            continue
        shown += 1
        if shown > 12:
            break
        print("\n%s  recargo_real=%.0f  predicho=%.0f  ratio=%.2f" % (name, rec, pred, pred/rec))
        print("   qty pack  unid   net    std  fmt/cc      tarifa  pred_lin  uom | producto")
        for p in ls:
            t = table[(p['fmt'], p['cc'])]
            print("   %3.0f %4.0f %5.0f %7.0f %6.0f %-6s/%-5.0f %6.0f %8.0f  %-12s| %s" % (
                p['qty'], p['pack'], p['unid'], p['net'], p['std'], p['fmt'][:6], p['cc'],
                t, t*p['unid'], (p['uom'] or '')[:12], (p['nm'] or '')[:30]))


if __name__ == '__main__':
    main()
