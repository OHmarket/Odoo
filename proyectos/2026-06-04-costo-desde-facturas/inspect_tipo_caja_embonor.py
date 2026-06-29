"""inspect_tipo_caja_embonor.py — READ-ONLY.
Filas CRUDAS de facturas mono-codigo de Embonor para tipos de caja elegidos.
Muestra por factura: cajas, neto, recargo, recargo/caja y recargo/%neto.
Si dentro de un MISMO tipo de caja el recargo/caja SALTA pero el %neto se
mantiene -> el recargo sigue al VALOR, no a la caja.
"""
import sys
from collections import defaultdict
from statistics import mean, pstdev
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')
TARGETS = {(2000.0, 8.0), (710.0, 12.0), (1000.0, 6.0)}  # testigo, grande, contraste


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _norm(s):
    return (s or '').strip().lower()


def is_charge(label):
    lab = _norm(label)
    return any(w in lab for w in CHARGE_WORDS) if lab else False


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    uom_cache, cc_cache, name_cache = {}, {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]

    def prod_info(pdid):
        if pdid not in cc_cache:
            r = o.search_read('product.product', [('id', '=', pdid)], fields=['volume', 'display_name'], limit=1)
            cc_cache[pdid] = f(r[0].get('volume')) if r else 0.0
            name_cache[pdid] = (r[0].get('display_name') if r else '') or ''
        return cc_cache[pdid], name_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id', 'invoice_date'], order='invoice_date', limit=1500)

    rows_by_type = defaultdict(list)
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal'])
        prods, rec = [], 0.0
        for l in lines:
            qty = f(l['quantity'])
            if qty <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            cc, nm = prod_info(l['product_id'][0])
            prods.append({'cc': cc, 'pack': ratio, 'qty': qty, 'net': f(l['price_subtotal']), 'nm': nm})
        if rec <= 0 or len(prods) != 1:
            continue
        p0 = prods[0]
        key = (p0['cc'], p0['pack'])
        if key in TARGETS:
            rows_by_type[key].append((m['invoice_date'], p0['qty'], p0['net'], rec, p0['nm']))

    for key in TARGETS:
        rows = rows_by_type.get(key, [])
        if not rows:
            continue
        cc, pack = key
        print("\n=== tipo de caja cc=%.0f pack=%.0f  (%s facturas mono) ===" % (cc, pack, len(rows)))
        print("  fecha       cajas     neto    recargo  rec/caja  rec/%%neto  producto")
        rc, pct = [], []
        for d, qty, net, rec, nm in rows:
            r_caja = rec / qty if qty else 0
            r_pct = rec / net if net else 0
            rc.append(r_caja); pct.append(r_pct)
            print("  %-10s %5.0f %8.0f %8.0f %8.0f   %5.1f%%   %s" % (
                d, qty, net, rec, r_caja, 100 * r_pct, (nm or '')[:30]))
        def cv(xs):
            m = mean(xs)
            return (pstdev(xs) / m) if (len(xs) > 1 and m) else 0.0
        print("  --> rec/caja: media %.0f  CV %.2f   |   rec/%%neto: media %.1f%%  CV %.2f" % (
            mean(rc), cv(rc), 100 * mean(pct), cv(pct)))


if __name__ == '__main__':
    main()
