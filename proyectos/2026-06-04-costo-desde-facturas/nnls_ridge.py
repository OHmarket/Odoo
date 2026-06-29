"""nnls_ridge.py — READ-ONLY. NNLS regularizado anclado a formato x cc.
Resuelve  min ||A x - b||^2 + lambda||x - x_prior||^2 , x>=0, con x_prior = tarifa
formato x cc del SKU. Sistema aumentado: [A; sqrt(l) I] x = [b; sqrt(l) x_prior].
Barre lambda y valida out-of-sample ponderado por $. Compara vs formato x cc (11.1%)
y NNLS puro (14.4%).
"""
import sys
import re
import random
from collections import defaultdict
from statistics import median
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
                              fields=['standard_price', 'display_name', 'default_code', 'product_tmpl_id'], limit=1)
            std = f(r[0].get('standard_price')) if r else 0.0
            nm = (r[0].get('display_name') or '') if r else ''
            code = (r[0].get('default_code') or str(pdid)) if r else str(pdid)
            tid = r[0]['product_tmpl_id'][0] if (r and r[0].get('product_tmpl_id')) else None
            fmt = tmpl_fmt(tid) if tid else '(vacio)'
            if 'cooler' in nm.lower() and fmt == 'vidrio':
                fmt = 'cooler'
            info_cache[pdid] = (std, nm, code, fmt, cc_from_name(nm))
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    rows = []
    sku_fmtcc = {}
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'price_subtotal'])
        units, rec, bad = defaultdict(float), 0.0, False
        for l in lines:
            if f(l['quantity']) <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            std, nm, code, fmt, ccn = prod_info(l['product_id'][0])
            net = f(l['price_subtotal'])
            if std <= 0 or net <= 0:
                bad = True
                break
            units[code] += net / std
            sku_fmtcc[code] = (fmt, ccn)
        if (not bad) and rec > 0 and units:
            rows.append((rec, dict(units)))

    skus = sorted({s for _, u in rows for s in u})
    idx = {s: j for j, s in enumerate(skus)}
    n, p = len(rows), len(skus)

    A = np.zeros((n, p)); b = np.zeros(n)
    for i, (rec, u) in enumerate(rows):
        b[i] = rec
        for s, un in u.items():
            A[i, idx[s]] = un

    # prior formato x cc (mediana recargo/unid de facturas mono-codigo)
    cell = defaultdict(list)
    for rec, u in rows:
        if len(u) == 1:
            s, un = next(iter(u.items()))
            cell[sku_fmtcc[s]].append(rec / un)
    celltab = {k: median(v) for k, v in cell.items()}
    x_prior = np.array([celltab.get(sku_fmtcc.get(s), 0.0) for s in skus])

    random.seed(42)
    order = list(range(n)); random.shuffle(order)
    cut = int(0.8 * n); tr, te = order[:cut], order[cut:]
    Atr, btr = A[tr], b[tr]

    def err(x, ridx):
        sp = sr = sa = 0.0
        for i in ridx:
            pr = float(A[i] @ x)
            sp += pr; sr += b[i]; sa += abs(pr - b[i])
        return sp/sr, sa/sr

    print("facturas %s | SKUs %s | prior formato x cc: %s celdas\n" % (n, p, len(celltab)))
    print("  lambda     test_sesgo  test_error")
    best = None
    for lam in [0.0, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0]:
        if lam == 0.0:
            x, _ = nnls(Atr, btr)
        else:
            sl = np.sqrt(lam)
            Aaug = np.vstack([Atr, sl * np.eye(p)])
            baug = np.concatenate([btr, sl * x_prior])
            x, _ = nnls(Aaug, baug)
        bias, e = err(x, te)
        flag = ''
        if best is None or e < best[1]:
            best = (lam, e); flag = ' <-'
        print("  %-8.1f   %.3f       %.1f%%%s" % (lam, bias, 100*e, flag))
    print("\nmejor lambda=%.1f -> test_error %.1f%%  (formato x cc=11.1%% | NNLS puro=14.4%%)" % (best[0], 100*best[1]))


if __name__ == '__main__':
    main()
