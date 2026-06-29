"""calibra_formato_embonor.py — READ-ONLY.
Usa el campo estructurado product.template.x_studio_formato (lata/vidrio/pet/tetra)
como PACKING (en vez de heuristica de nombre) y cc de la UNIDAD desde el nombre
(volume tiene errores). Mide recargo/unidad por (formato, cc) en facturas
mono-codigo (qty normalizada por ancla a std). Reporta cobertura del campo.
"""
import sys
import re
from collections import defaultdict
from statistics import mean, pstdev
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


def cv(xs):
    xs = [x for x in xs if x > 0]
    if not xs:
        return 0.0, 0.0, 0
    m = mean(xs)
    return ((pstdev(xs) / m) if (len(xs) > 1 and m) else 0.0), m, len(xs)


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    uom_cache, info_cache, tmpl_cache = {}, {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]

    def tmpl_formato(tid):
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
            fmt = tmpl_formato(tid) if tid else '(vacio)'
            info_cache[pdid] = (std, nm, fmt, cc_from_name(nm))
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    by = defaultdict(list)
    seen, con_fmt = set(), set()
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
            std, nm, fmt, ccn = prod_info(l['product_id'][0])
            seen.add(l['product_id'][0])
            if fmt != '(vacio)':
                con_fmt.add(l['product_id'][0])
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            prods.append({'std': std, 'cc': ccn, 'fmt': fmt, 'qty': qty, 'pack': ratio, 'net': f(l['price_subtotal'])})
        if rec <= 0 or len(prods) != 1:
            continue
        p = prods[0]
        if p['std'] <= 0 or p['cc'] <= 0:
            continue
        u_unit, u_pack = p['qty'], p['qty'] * p['pack']
        unidades = u_unit if abs(p['net']/u_unit - p['std']) <= abs(p['net']/u_pack - p['std']) else u_pack
        if abs(p['net']/unidades - p['std']) / p['std'] > 0.15:
            continue
        by[(p['fmt'], p['cc'])].append(rec / unidades)

    print("productos Embonor vistos: %s | con x_studio_formato: %s (%.0f%%)\n"
          % (len(seen), len(con_fmt), 100.0*len(con_fmt)/len(seen) if seen else 0))
    print("=== recargo/unidad por (FORMATO, cc) ===")
    print("  formato   cc     n    media   CV")
    allc = []
    for key in sorted(by, key=lambda k: (str(k[0]), k[1])):
        fmt, cc = key
        c, mu, n = cv(by[key])
        if n >= 2:
            allc.append(c)
            print("  %-8s %-6.0f %-3s %8.1f  %.2f" % (fmt, cc, n, mu, c))
    if allc:
        print("\nCV promedio (formato,cc): %.3f   (packing-nombre=0.081 | cat x cc=0.118)" % mean(allc))


if __name__ == '__main__':
    main()
