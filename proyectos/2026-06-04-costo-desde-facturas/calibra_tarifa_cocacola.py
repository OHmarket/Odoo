"""calibra_tarifa_cocacola.py — READ-ONLY.
Ingenieria inversa del RECARGO de Embonor/Coca Cola desde facturas MONO-CODIGO
(1 solo producto + linea RECARGO): ahi el recargo queda AISLADO por tipo de caja.
  recargo/caja  = $ por caja de ese tipo
  recargo/litro = $ por litro
Agrupa por tipo de caja (cc, pack) y mide cual es consistente DENTRO del tipo
(CV menor). Si recargo/caja tiene CV bajo por tipo -> se puede tabular como CCU.
"""
import sys
from collections import defaultdict
from statistics import mean, pstdev
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')


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


def cv(xs):
    xs = [x for x in xs if x > 0]
    if not xs:
        return 0.0, 0.0, 0
    m = mean(xs)
    c = (pstdev(xs) / m) if (len(xs) > 1 and m) else 0.0
    return c, m, len(xs)


def main():
    o = OdooReader()
    p = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id', 'name'], limit=1)
    if not p:
        print("Embonor no encontrado"); return
    pid = p[0]['id']
    print("Embonor partner: %s %s" % (pid, p[0]['name']))

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

    by_caja = defaultdict(lambda: {'rc': [], 'rl': [], 'pct': []})
    n_mono = 0
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
            prods.append({'cc': prod_cc(l['product_id'][0]), 'pack': ratio, 'qty': qty,
                          'net': f(l['price_subtotal'])})
        if rec <= 0 or len(prods) != 1:   # MONO-codigo
            continue
        p0 = prods[0]
        if p0['cc'] <= 0:
            continue
        n_mono += 1
        cajas = p0['qty']
        litros = p0['qty'] * p0['pack'] * p0['cc'] / 1000.0
        key = (p0['cc'], p0['pack'])
        if cajas > 0:
            by_caja[key]['rc'].append(rec / cajas)
        if litros > 0:
            by_caja[key]['rl'].append(rec / litros)
        if p0['net'] > 0:
            by_caja[key]['pct'].append(rec / p0['net'])

    print("facturas Embonor mono-codigo con recargo: %s\n" % n_mono)
    if not by_caja:
        print("(no hay facturas mono-codigo; habria que usar mono-TIPO-de-caja)")
        return
    print("  cc    pack  n   recargo/caja(CV)     recargo/litro(CV)    recargo/%neto(CV)")
    for key in sorted(by_caja, key=lambda k: -len(by_caja[k]['rc'])):
        cc, pack = key
        cvc, mc, nc = cv(by_caja[key]['rc'])
        cvl, ml, nl = cv(by_caja[key]['rl'])
        cvp, mp, npc = cv(by_caja[key]['pct'])
        print("  %-5.0f %-4.0f %-3s  %8.0f (CV %.2f)  %7.1f (CV %.2f)  %5.3f (CV %.2f)" % (
            cc, pack, nc, mc, cvc, ml, cvl, mp, cvp))

    allc = [(cv(v['rc']), cv(v['rl']), cv(v['pct'])) for v in by_caja.values() if len(v['rc']) >= 2]
    if allc:
        print("\nCV promedio (tipos con >=2 fact mono):")
        print("  recargo/caja=%.3f  recargo/litro=%.3f  recargo/%%neto=%.3f" % (
            mean([c[0][0] for c in allc]), mean([c[1][0] for c in allc]), mean([c[2][0] for c in allc])))
        print("=> el de MENOR CV describe mejor; si es /caja o /litro se puede tabular como regla.")


if __name__ == '__main__':
    main()
