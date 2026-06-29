"""valida_ponderado.py — READ-ONLY. Mide el efecto de la tabla (formato,cc)+net/std
PONDERADO POR DINERO comprado (no por SKU ni por factura):
  - sesgo en $:  Sum(predicho)/Sum(real) del recargo
  - error en $:  Sum|predicho-real| / Sum(real)  (% del recargo mal asignado)
  - % del $ comprado (neto) que cae en celdas (formato,cc) bien calibradas (CV<0.15)
"""
import sys
import re
from collections import defaultdict
from statistics import median, mean, pstdev
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

    facturas = []
    cell_net = defaultdict(float)   # $ neto comprado por (fmt,cc)
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'price_subtotal'])
        plist, rec = [], 0.0
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
            if std <= 0 or ccn <= 0 or fmt == '(vacio)' or net <= 0:
                plist.append(None)
                continue
            cell_net[(fmt, ccn)] += net
            plist.append({'fmt': fmt, 'cc': ccn, 'unid': net/std, 'net': net})
        if rec > 0 and plist:
            facturas.append((rec, plist))

    tab = defaultdict(list)
    for rec, plist in facturas:
        v = [p for p in plist if p]
        if len(v) == 1:
            tab[(v[0]['fmt'], v[0]['cc'])].append(rec / v[0]['unid'])
    table = {k: median(x) for k, x in tab.items()}
    cv = {k: (pstdev(x)/mean(x) if len(x) > 1 and mean(x) else 0.0) for k, x in tab.items()}

    # prediccion ponderada por $ (sobre facturas 100% cubiertas)
    sum_pred = sum_real = sum_abs = 0.0
    for rec, plist in facturas:
        ls = [p for p in plist if p]
        if ls and rec > 0 and all((p['fmt'], p['cc']) in table for p in ls):
            pred = sum(table[(p['fmt'], p['cc'])] * p['unid'] for p in ls)
            sum_pred += pred
            sum_real += rec
            sum_abs += abs(pred - rec)

    total_net = sum(cell_net.values())
    net_calib = sum(v for k, v in cell_net.items() if k in table)
    net_cv_ok = sum(v for k, v in cell_net.items() if k in table and cv.get(k, 9) < 0.15)

    print("=== PONDERADO POR DINERO (neto comprado a Embonor) ===\n")
    print("Cobertura en $: celdas calibradas = %.0f%% del neto | de ellas CV<0.15 = %.0f%% del neto"
          % (100*net_calib/total_net if total_net else 0, 100*net_cv_ok/total_net if total_net else 0))
    if sum_real:
        print("\nPrediccion recargo (facturas 100%% cubiertas), ponderado por $:")
        print("  sesgo  Sum(pred)/Sum(real) = %.3f   (1.00 = insesgado en plata)" % (sum_pred/sum_real))
        print("  error  Sum|pred-real|/Sum(real) = %.1f%%  (%% del recargo total mal asignado)"
              % (100*sum_abs/sum_real))

    print("\n=== celdas por peso en $ (neto comprado) ===")
    print("  formato   cc     %%_del_neto   CV_tarifa")
    rows = sorted(cell_net.items(), key=lambda kv: -kv[1])
    for (fmt, cc), net in rows[:18]:
        c = cv.get((fmt, cc))
        ctxt = ("%.2f" % c) if (fmt, cc) in table else "SIN CALIB"
        print("  %-8s %-6.0f %6.1f%%       %s" % (fmt, cc, 100*net/total_net, ctxt))


if __name__ == '__main__':
    main()
