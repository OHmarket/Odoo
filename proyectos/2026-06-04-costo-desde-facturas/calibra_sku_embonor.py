"""calibra_sku_embonor.py — READ-ONLY.
Mide recargo/unidad por SKU (default_code) de Embonor desde facturas mono-codigo
(qty normalizada a unidad por ancla a std). Evalua si por SKU el recargo es
estable (CV bajo) -> tabla por SKU seria FIEL. Reporta cobertura: cuantos SKU
comprados tienen calibracion mono-codigo.
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
                              fields=['standard_price', 'default_code'], limit=1)
            info_cache[pdid] = (f(r[0].get('standard_price')) if r else 0.0,
                                (r[0].get('default_code') or '') if r else '')
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    by_sku = defaultdict(list)
    all_skus = set()
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
            std, code = prod_info(l['product_id'][0])
            if code:
                all_skus.add(code)
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            prods.append({'code': code, 'std': std, 'qty': qty, 'pack': ratio, 'net': f(l['price_subtotal'])})
        if rec <= 0 or len(prods) != 1:
            continue
        p = prods[0]
        if p['std'] <= 0 or not p['code']:
            continue
        u_unit, u_pack = p['qty'], p['qty'] * p['pack']
        unidades = u_unit if abs(p['net']/u_unit - p['std']) <= abs(p['net']/u_pack - p['std']) else u_pack
        if abs(p['net']/unidades - p['std']) / p['std'] > 0.15:
            continue
        by_sku[p['code']].append(rec / unidades)

    cvs = []
    estables = 0
    print("SKU con calibracion mono-codigo: %s  (de %s SKU comprados a Embonor)\n"
          % (len(by_sku), len(all_skus)))
    print("  SKU con >=2 facturas mono:")
    print("  code        n    recargo/unid   CV")
    multi = {k: v for k, v in by_sku.items() if len(v) >= 2}
    for code in sorted(multi, key=lambda k: -len(multi[k]))[:25]:
        v = multi[code]
        m = mean(v); c = pstdev(v) / m if m else 0
        cvs.append(c)
        if c <= 0.10:
            estables += 1
        print("  %-10s %-4s %10.1f   %.2f" % (code, len(v), m, c))
    if cvs:
        print("\n  SKU con >=2 fact: %s | CV<=0.10: %s (%.0f%%) | CV promedio: %.3f"
              % (len(cvs), estables, 100.0*estables/len(cvs), mean(cvs)))
    print("\n  COBERTURA: %s/%s SKU calibrables mono (%.0f%%); el resto necesitaria"
          " regresion multi-factura o fallback envase/categoria."
          % (len(by_sku), len(all_skus), 100.0*len(by_sku)/len(all_skus) if all_skus else 0))


if __name__ == '__main__':
    main()
