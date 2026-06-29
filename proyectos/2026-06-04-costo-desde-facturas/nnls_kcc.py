"""nnls_kcc.py — READ-ONLY. Modelo LINEAL: recargo/unidad = k(formato) * cc.
recargo_factura = sum_lineas k[formato] * cc * unidades(net/std). NNLS estima
k[formato] (~5 parametros). Valida out-of-sample ponderado por $. Compara contra
formato x cc tabla (11.1%) y NNLS SKU (14.4%).
"""
import sys
import re
import random
from collections import defaultdict
import numpy as np
from scipy.optimize import nnls
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
    info_cache, tmpl_cache = {}, {}

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
                          fields=['id'], order='id', limit=1500)

    rows = []   # (recargo, {formato: sum(cc*unid)})
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'price_subtotal'])
        fmtsum, rec, bad = defaultdict(float), 0.0, False
        for l in lines:
            if f(l['quantity']) <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            std, nm, fmt, ccn = prod_info(l['product_id'][0])
            net = f(l['price_subtotal'])
            if std <= 0 or net <= 0 or ccn <= 0 or fmt == '(vacio)':
                bad = True
                break
            fmtsum[fmt] += ccn * (net / std)     # cc * unidades = litros*1000 de la linea
        if (not bad) and rec > 0 and fmtsum:
            rows.append((rec, dict(fmtsum)))

    fmts = sorted({fm for _, d in rows for fm in d})
    idx = {fm: j for j, fm in enumerate(fmts)}
    n, p = len(rows), len(fmts)
    A = np.zeros((n, p)); b = np.zeros(n)
    for i, (rec, d) in enumerate(rows):
        b[i] = rec
        for fm, s in d.items():
            A[i, idx[fm]] = s

    random.seed(42)
    order = list(range(n)); random.shuffle(order)
    cut = int(0.8 * n); tr, te = order[:cut], order[cut:]
    k, _ = nnls(A[tr], b[tr])

    def err(ridx):
        sp = sr = sa = 0.0
        for i in ridx:
            pr = float(A[i] @ k); sp += pr; sr += b[i]; sa += abs(pr - b[i])
        return sp/sr, sa/sr
    bi, ei = err(tr); bo, eo = err(te)

    print("facturas usables: %s | formatos: %s\n" % (n, p))
    print("Modelo recargo/unidad = k(formato) x cc   (k en $/cc):")
    for fm in fmts:
        print("  %-10s k = %.4f  ($/cc)   -> ej 1500cc = %.0f/unid" % (fm, k[idx[fm]], k[idx[fm]]*1500))
    print("\nValidacion ponderada por $:")
    print("  IN-SAMPLE:     sesgo %.3f | error %.1f%%" % (bi, 100*ei))
    print("  OUT-OF-SAMPLE: sesgo %.3f | error %.1f%%" % (bo, 100*eo))
    print("  (formato x cc tabla=11.1%% | NNLS SKU=14.4%%)")


if __name__ == '__main__':
    main()
