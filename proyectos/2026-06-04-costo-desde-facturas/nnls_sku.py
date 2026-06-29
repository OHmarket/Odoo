"""nnls_sku.py — READ-ONLY. Descompone el recargo global de Embonor en tarifa por
SKU via NNLS: resuelve  A x = b  con x>=0, donde A[factura,sku]=unidades(net/std),
b[factura]=recargo. Valida out-of-sample (train/test 80/20) y ponderado por $.
Compara contra formato x cc (error 11.1%).
"""
import sys
import random
from collections import defaultdict
import numpy as np
from scipy.optimize import nnls
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
    info_cache = {}

    def prod_info(pdid):
        if pdid not in info_cache:
            r = o.search_read('product.product', [('id', '=', pdid)],
                              fields=['standard_price', 'display_name', 'default_code'], limit=1)
            info_cache[pdid] = (f(r[0].get('standard_price')) if r else 0.0,
                                (r[0].get('display_name') or '') if r else '',
                                (r[0].get('default_code') or str(pdid)) if r else str(pdid))
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    rows = []   # (recargo, {sku: unidades}, {sku: net})
    sku_name = {}
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'price_subtotal'])
        units, nets, rec, bad = defaultdict(float), defaultdict(float), 0.0, False
        for l in lines:
            if f(l['quantity']) <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            std, nm, code = prod_info(l['product_id'][0])
            net = f(l['price_subtotal'])
            if std <= 0 or net <= 0:
                bad = True
                break
            units[code] += net / std
            nets[code] += net
            sku_name[code] = nm
        if (not bad) and rec > 0 and units:
            rows.append((rec, dict(units), dict(nets)))

    skus = sorted({s for _, u, _ in rows for s in u})
    idx = {s: j for j, s in enumerate(skus)}
    n, p = len(rows), len(skus)
    print("facturas usables: %s | SKUs: %s" % (n, p))

    A = np.zeros((n, p))
    b = np.zeros(n)
    netvec = defaultdict(float)
    for i, (rec, u, nets) in enumerate(rows):
        b[i] = rec
        for s, un in u.items():
            A[i, idx[s]] = un
        for s, nt in nets.items():
            netvec[s] += nt

    random.seed(42)
    order = list(range(n))
    random.shuffle(order)
    cut = int(0.8 * n)
    tr, te = order[:cut], order[cut:]
    x, _ = nnls(A[tr], b[tr])

    def wmetrics(rowsidx):
        sp = sr = sa = 0.0
        for i in rowsidx:
            pred = float(A[i] @ x)
            sp += pred; sr += b[i]; sa += abs(pred - b[i])
        return sp/sr, sa/sr
    bias_in, err_in = wmetrics(tr)
    bias_te, err_te = wmetrics(te)
    print("\nNNLS por SKU (tarifa_sku >= 0), ponderado por $:")
    print("  IN-SAMPLE (train):     sesgo %.3f | error %.1f%%" % (bias_in, 100*err_in))
    print("  OUT-OF-SAMPLE (test):  sesgo %.3f | error %.1f%%" % (bias_te, 100*err_te))
    print("  (formato x cc daba: error 11.1%% en $)")

    print("\nTop 15 SKU por $ comprado, con tarifa_recargo/unidad estimada:")
    top = sorted(skus, key=lambda s: -netvec[s])[:15]
    print("  code        tarifa/u   %_del_$   producto")
    tot = sum(netvec.values())
    for s in top:
        print("  %-10s %8.1f   %5.1f%%   %s" % (s, x[idx[s]], 100*netvec[s]/tot, (sku_name.get(s) or '')[:32]))


if __name__ == '__main__':
    main()
