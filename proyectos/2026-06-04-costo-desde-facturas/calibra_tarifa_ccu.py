"""calibra_tarifa_ccu.py — READ-ONLY.
Ingenieria inversa de la tarifa de flete de CCU desde facturas MONO-CODIGO
(1 solo producto + linea de flete): ahi el flete no esta mezclado, asi que
  flete/caja  = costo de flete por caja de ese tipo
  flete/litro = costo de flete por litro
Agrupa por tipo de caja (cc, pack) y mide cual es mas consistente (CV menor),
y compara contra la tarifa actual de la regla 3.
"""
import sys
from collections import defaultdict
from statistics import mean, pstdev
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

CCU_VAT = '99554560'
FREIGHT_WORDS = ('flete', 'mercaderia')


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _norm(s):
    return (s or '').strip().lower()


def is_freight(label):
    lab = _norm(label)
    return any(w in lab for w in FREIGHT_WORDS) if lab else False


def cv(xs):
    xs = [x for x in xs if x > 0]
    if not xs:
        return 0.0, 0.0, 0
    m = mean(xs)
    c = (pstdev(xs) / m) if (len(xs) > 1 and m) else 0.0
    return c, m, len(xs)


def main():
    o = OdooReader()
    p = o.search_read('res.partner', [('vat', 'like', CCU_VAT)], fields=['id', 'name'], limit=1)
    if not p:
        print("CCU no encontrado"); return
    pid = p[0]['id']
    print("CCU partner: %s %s" % (pid, p[0]['name']))

    # tarifa actual de la regla CCU
    reglas = o.search_read('x_vendor_freight_rule', [('x_studio_partner_id', '=', pid)], fields=['id'])
    tar_regla = {}
    if reglas:
        for t in o.search_read('x_vendor_freight_rule_', [('x_studio_rule_id', '=', reglas[0]['id'])],
                               fields=['x_studio_cc_unit', 'x_studio_pack_qty', 'x_studio_tariff_case']):
            tar_regla[(f(t['x_studio_cc_unit']), f(t['x_studio_pack_qty']))] = f(t['x_studio_tariff_case'])

    uom_cache, cc_cache = {}, {}
    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]
    def prod_cc(pdid):
        if pdid not in cc_cache:
            r = o.search_read('product.product', [('id', '=', pdid)], fields=['volume', 'product_tmpl_id'], limit=1)
            cc = f(r[0].get('volume')) if r else 0.0
            cc_cache[pdid] = cc
        return cc_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2026-01-01'), ('invoice_date', '<=', '2026-04-30')],
                          fields=['id'], order='id', limit=600)

    by_caja = defaultdict(lambda: {'fc': [], 'fl': []})  # (cc,pack) -> flete/caja, flete/litro
    n_mono = 0
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal'])
        prods, flete = [], 0.0
        for l in lines:
            qty = f(l['quantity'])
            if qty <= 0:
                continue
            if is_freight(l['name']) and not l['product_id']:
                flete += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            prods.append({'cc': prod_cc(l['product_id'][0]), 'pack': ratio, 'qty': qty})
        if flete <= 0 or len(prods) != 1:   # MONO-codigo
            continue
        p0 = prods[0]
        if p0['cc'] <= 0:
            continue
        n_mono += 1
        cajas = p0['qty']
        litros = p0['qty'] * p0['pack'] * p0['cc'] / 1000.0
        key = (p0['cc'], p0['pack'])
        if cajas > 0:
            by_caja[key]['fc'].append(flete / cajas)
        if litros > 0:
            by_caja[key]['fl'].append(flete / litros)

    print("facturas CCU mono-codigo con flete: %s\n" % n_mono)
    print("  cc    pack  n   flete/caja(CV)        flete/litro(CV)      tarifa_regla")
    for key in sorted(by_caja, key=lambda k: -len(by_caja[k]['fc'])):
        cc, pack = key
        cvc, mc, nc = cv(by_caja[key]['fc'])
        cvl, ml, nl = cv(by_caja[key]['fl'])
        tr = tar_regla.get(key, None)
        print("  %-5.0f %-4.0f %-3s  %8.0f (CV %.2f)   %7.1f (CV %.2f)   %s" % (
            cc, pack, nc, mc, cvc, ml, cvl, ('%.0f' % tr) if tr is not None else '-'))

    # consistencia global: CV promedio ponderado por n
    allc = [(cv(v['fc']), cv(v['fl'])) for v in by_caja.values() if len(v['fc']) >= 2]
    if allc:
        cvc_avg = mean([c[0][0] for c in allc])
        cvl_avg = mean([c[1][0] for c in allc])
        print("\nCV promedio (tipos con >=2 fact): flete/caja=%.3f  flete/litro=%.3f" % (cvc_avg, cvl_avg))
        print("=> el de MENOR CV describe mejor la tarifa de CCU.")


if __name__ == '__main__':
    main()
