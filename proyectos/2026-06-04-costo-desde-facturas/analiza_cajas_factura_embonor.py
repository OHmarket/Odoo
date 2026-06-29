"""analiza_cajas_factura_embonor.py — READ-ONLY.
Por factura COMPLETA de Embonor: cajas, LITROS, neto, recargo y ratios.
Responde si el recargo se mantiene constante por %neto, por caja o por litro a
traves de tamanos de factura. Constante en uno de ellos = ese es el driver.
"""
import sys
from statistics import mean, median
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')


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
    uom_cache, cc_cache = {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]

    def prod_cc(pdid):
        if pdid not in cc_cache:
            r = o.search_read('product.product', [('id', '=', pdid)], fields=['volume'], limit=1)
            cc_cache[pdid] = f(r[0].get('volume')) if r else 0.0
        return cc_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    facturas = []   # (cajas, litros, neto, recargo)
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal'])
        cajas = litros = neto = rec = 0.0
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
            cc = prod_cc(l['product_id'][0])
            cajas += qty
            litros += qty * ratio * cc / 1000.0
            neto += f(l['price_subtotal'])
        if rec > 0 and cajas > 0 and neto > 0 and litros > 0:
            facturas.append((cajas, litros, neto, rec))

    print("facturas Embonor con recargo: %s\n" % len(facturas))
    cajas_all = [x[0] for x in facturas]
    lit_all = [x[1] for x in facturas]
    print("CAJAS  por factura: mediana %.0f  media %.0f  max %.0f" % (median(cajas_all), mean(cajas_all), max(cajas_all)))
    print("LITROS por factura: mediana %.0f  media %.0f  max %.0f\n" % (median(lit_all), mean(lit_all), max(lit_all)))

    print("=== por rango de CAJAS ===")
    print("rango       n     %%neto   $/caja   $/litro")
    for lo, hi in [(1, 1), (2, 5), (6, 20), (21, 100), (101, 10**9)]:
        sub = [x for x in facturas if lo <= x[0] <= hi]
        if not sub:
            continue
        print("  %4s-%-5s %4s  %5.1f%%  %7.0f  %6.1f" % (
            lo, (hi if hi < 10**8 else '+'), len(sub),
            100*mean([x[3]/x[2] for x in sub]), mean([x[3]/x[0] for x in sub]), mean([x[3]/x[1] for x in sub])))

    print("\n=== por rango de LITROS ===")
    print("rango        n     %%neto   $/caja   $/litro")
    for lo, hi in [(0, 50), (50, 150), (150, 500), (500, 2000), (2000, 10**9)]:
        sub = [x for x in facturas if lo <= x[1] < hi]
        if not sub:
            continue
        print("  %5s-%-6s %4s  %5.1f%%  %7.0f  %6.1f" % (
            lo, (hi if hi < 10**8 else '+'), len(sub),
            100*mean([x[3]/x[2] for x in sub]), mean([x[3]/x[0] for x in sub]), mean([x[3]/x[1] for x in sub])))


if __name__ == '__main__':
    main()
