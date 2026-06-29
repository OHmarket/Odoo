"""calibra_categoria_embonor.py — READ-ONLY.
Mide recargo/unidad de Embonor (mono-codigo, qty normalizada a unidad por ancla
a std) agrupado por (categoria, cc). Si el CV por (categoria,cc) es bajo, el
recargo es tabulable por categoria -> confirma 'cambia por categoria'.
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
    pfields = set(o.fields_get('product.product', ['type']).keys())
    cat_field = 'x_studio_categoria_l1_id' if 'x_studio_categoria_l1_id' in pfields else 'categ_id'
    print("campo categoria:", cat_field)

    uom_cache, info_cache = {}, {}
    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]
    def prod_info(pdid):
        if pdid not in info_cache:
            r = o.search_read('product.product', [('id', '=', pdid)],
                              fields=['volume', 'standard_price', cat_field], limit=1)
            cc = f(r[0].get('volume')) if r else 0.0
            std = f(r[0].get('standard_price')) if r else 0.0
            cat = '(sin)'
            if r and r[0].get(cat_field):
                v = r[0][cat_field]
                cat = v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else str(v)
            info_cache[pdid] = (cc, std, cat)
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    by_catcc = defaultdict(list)
    by_cat = defaultdict(list)
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
            cc, std, cat = prod_info(l['product_id'][0])
            prods.append({'cc': cc, 'pack': ratio, 'qty': qty, 'net': f(l['price_subtotal']), 'std': std, 'cat': cat})
        if rec <= 0 or len(prods) != 1:
            continue
        p = prods[0]
        if p['cc'] <= 0 or p['std'] <= 0:
            continue
        u_unit, u_pack = p['qty'], p['qty'] * p['pack']
        unidades = u_unit if abs(p['net']/u_unit - p['std']) <= abs(p['net']/u_pack - p['std']) else u_pack
        if abs(p['net']/unidades - p['std']) / p['std'] > 0.15:
            continue
        ru = rec / unidades
        by_catcc[(p['cat'], p['cc'])].append(ru)
        by_cat[p['cat']].append(ru)

    print("\n=== recargo/unidad por CATEGORIA (todas las cc juntas) ===")
    print("  categoria                         n    media   CV")
    for cat in sorted(by_cat, key=lambda k: -len(by_cat[k])):
        c, mu, n = cv(by_cat[cat])
        if n >= 2:
            print("  %-32s %-4s %7.1f  %.2f" % (cat[:32], n, mu, c))

    print("\n=== recargo/unidad por (CATEGORIA, cc) ===")
    print("  categoria                    cc     n   media   CV")
    for key in sorted(by_catcc, key=lambda k: -len(by_catcc[k])):
        cat, cc = key
        c, mu, n = cv(by_catcc[key])
        if n >= 2:
            print("  %-26s %-6.0f %-3s %7.1f  %.2f" % (cat[:26], cc, n, mu, c))

    allc = [cv(v)[0] for v in by_catcc.values() if len(v) >= 2]
    if allc:
        print("\nCV promedio por (categoria,cc): %.3f" % mean(allc))


if __name__ == '__main__':
    main()
