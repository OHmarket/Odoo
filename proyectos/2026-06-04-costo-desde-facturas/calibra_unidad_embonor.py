"""calibra_unidad_embonor.py — READ-ONLY.
Re-mide el RECARGO de Embonor NORMALIZANDO la qty a UNIDADES BASE (ancla a
standard_price: la factura trae 'qty' a veces en unidades y a veces en cajas).
Solo facturas mono-codigo. Agrupa por cc (formato fisico) y mide:
  recargo/unidad  (driver fisico por unidad/caja)  vs  recargo/%neto (valor)
Si recargo/unidad por cc es CONSTANTE (CV bajo) -> es tabulable como CCU.
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


def is_charge(label):
    lab = (label or '').strip().lower()
    return any(w in lab for w in CHARGE_WORDS) if lab else False


def cv(xs):
    xs = [x for x in xs if x > 0]
    if not xs:
        return 0.0, 0.0, 0
    m = mean(xs)
    return ((pstdev(xs) / m) if (len(xs) > 1 and m) else 0.0), m, len(xs)


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
                              fields=['volume', 'standard_price'], limit=1)
            info_cache[pdid] = (f(r[0].get('volume')) if r else 0.0,
                                f(r[0].get('standard_price')) if r else 0.0)
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    by_cc = defaultdict(lambda: {'ru': [], 'pct': []})
    n_mono = n_dudosa = 0
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
            cc, std = prod_info(l['product_id'][0])
            prods.append({'cc': cc, 'pack': ratio, 'qty': qty, 'net': f(l['price_subtotal']), 'std': std})
        if rec <= 0 or len(prods) != 1:
            continue
        p0 = prods[0]
        if p0['cc'] <= 0 or p0['std'] <= 0:
            continue
        # ANCLA: unidades reales = qty o qty*pack, la que acerque neto/u a std
        u_unit, u_pack = p0['qty'], p0['qty'] * p0['pack']
        if abs(p0['net'] / u_unit - p0['std']) <= abs(p0['net'] / u_pack - p0['std']):
            unidades = u_unit
        else:
            unidades = u_pack
        best = p0['net'] / unidades
        if abs(best - p0['std']) / p0['std'] > 0.15:   # ni asi cuadra -> dudosa, fuera
            n_dudosa += 1
            continue
        n_mono += 1
        by_cc[p0['cc']]['ru'].append(rec / unidades)
        if p0['net'] > 0:
            by_cc[p0['cc']]['pct'].append(rec / p0['net'])

    print("facturas mono-codigo usadas: %s  (dudosas descartadas: %s)\n" % (n_mono, n_dudosa))
    print("  cc     n    recargo/UNIDAD(CV)   recargo/%%neto(CV)")
    for cc in sorted(by_cc, key=lambda k: -len(by_cc[k]['ru'])):
        cvu, mu, nu = cv(by_cc[cc]['ru'])
        cvp, mp, npc = cv(by_cc[cc]['pct'])
        if nu < 2:
            continue
        print("  %-6.0f %-4s %8.1f (CV %.2f)    %5.3f (CV %.2f)" % (cc, nu, mu, cvu, mp, cvp))

    allc = [(cv(v['ru']), cv(v['pct'])) for v in by_cc.values() if len(v['ru']) >= 2]
    if allc:
        print("\nCV promedio (cc con >=2): recargo/UNIDAD=%.3f  recargo/%%neto=%.3f" % (
            mean([c[0][0] for c in allc]), mean([c[1][0] for c in allc])))
        print("=> menor CV = driver real (unidad fisica vs valor).")


if __name__ == '__main__':
    main()
