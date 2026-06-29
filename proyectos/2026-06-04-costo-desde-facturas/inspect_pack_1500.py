"""inspect_pack_1500.py — READ-ONLY.
Para cc problematicos (1500, 2838), desglosa las facturas mono-codigo de Embonor
por PACK (cantidad por caja) y muestra recargo/unidad y recargo/caja, para ver si
el driver es (cc,pack)=tipo de caja en vez de cc=unidad.
"""
import sys
from collections import defaultdict
from statistics import mean, pstdev
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')
TARGET_CC = {1500.0, 2838.0}


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def is_charge(label):
    lab = (label or '').strip().lower()
    return any(w in lab for w in CHARGE_WORDS) if lab else False


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    uom_cache, info_cache = {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]

    def prod_info(pdid):
        if pdid not in info_cache:
            r = o.search_read('product.product', [('id', '=', pdid)],
                              fields=['volume', 'standard_price', 'display_name'], limit=1)
            info_cache[pdid] = (f(r[0].get('volume')) if r else 0.0,
                                f(r[0].get('standard_price')) if r else 0.0,
                                (r[0].get('display_name') if r else '') or '')
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id', 'invoice_date'], order='invoice_date', limit=1500)

    rows = defaultdict(list)
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
            cc, std, nm = prod_info(l['product_id'][0])
            prods.append({'cc': cc, 'pack': ratio, 'qty': qty, 'net': f(l['price_subtotal']), 'std': std, 'nm': nm})
        if rec <= 0 or len(prods) != 1:
            continue
        p0 = prods[0]
        if p0['cc'] not in TARGET_CC or p0['std'] <= 0:
            continue
        u_unit, u_pack = p0['qty'], p0['qty'] * p0['pack']
        if abs(p0['net'] / u_unit - p0['std']) <= abs(p0['net'] / u_pack - p0['std']):
            unidades = u_unit
        else:
            unidades = u_pack
        rows[(p0['cc'], p0['pack'])].append((m['invoice_date'], p0['qty'], unidades, p0['net'], rec, p0['std'], p0['nm']))

    for key in sorted(rows):
        cc, pack = key
        rs = rows[key]
        print("\n=== cc=%.0f  pack=%.0f  (%s facturas mono) ===" % (cc, pack, len(rs)))
        print("  fecha      qty  unidades  std    neto   recargo  rec/unid  rec/caja  producto")
        ru, rc = [], []
        for d, qty, un, net, rec, std, nm in rs:
            r_u = rec / un if un else 0
            n_cajas = un / pack if pack else un
            r_c = rec / n_cajas if n_cajas else 0
            ru.append(r_u); rc.append(r_c)
            print("  %-10s %3.0f %7.0f %6.0f %7.0f %7.0f %8.1f %8.0f  %s" % (
                d, qty, un, std, net, rec, r_u, r_c, (nm or '')[:24]))
        def cv(xs):
            m = mean(xs); return (pstdev(xs)/m) if (len(xs) > 1 and m) else 0.0
        print("  --> rec/unid media %.1f CV %.2f   |   rec/caja media %.0f CV %.2f" % (
            mean(ru), cv(ru), mean(rc), cv(rc)))


if __name__ == '__main__':
    main()
