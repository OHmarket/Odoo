"""valida_cc_cooler.py — READ-ONLY. Prueba la hipotesis "recargo por cc, con
cooler como unica excepcion": tabla[ (es_cooler, cc) ] = mediana(recargo/unidad),
unidades = net/std, cc del nombre. Valida predicho/real en facturas 100% cubiertas
y lo compara contra la version (formato,cc). Si es ~igual, gana por simple.
"""
import sys
import re
from collections import defaultdict
from statistics import mean, median, pstdev
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


def report(name, ratios):
    if not ratios:
        print("  (sin datos)")
        return
    r = sorted(ratios)
    m = mean(r)
    print("  %-18s mediana %.3f | media %.3f | CV %.2f | +-10%%: %.0f%% | p10/p90 %.2f/%.2f" % (
        name, median(r), m, pstdev(r)/m if m else 0,
        100.0*sum(1 for x in r if 0.9 <= x <= 1.1)/len(r), r[int(0.1*len(r))], r[int(0.9*len(r))]))


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    info_cache = {}

    def prod_info(pdid):
        if pdid not in info_cache:
            r = o.search_read('product.product', [('id', '=', pdid)],
                              fields=['standard_price', 'display_name'], limit=1)
            std = f(r[0].get('standard_price')) if r else 0.0
            nm = (r[0].get('display_name') or '') if r else ''
            info_cache[pdid] = (std, nm, 'cooler' in nm.lower(), cc_from_name(nm))
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    facturas = []
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
            std, nm, cooler, ccn = prod_info(l['product_id'][0])
            net = f(l['price_subtotal'])
            if std <= 0 or ccn <= 0 or net <= 0:
                plist.append(None)
                continue
            plist.append({'cc': ccn, 'cooler': cooler, 'unid': net/std})
        if rec > 0 and plist:
            facturas.append((rec, plist))

    # clave por hipotesis: 'cc' -> solo cc (cooler comparte) ; 'cc_cooler' -> cc + flag cooler
    def keyfun(p, mode):
        if mode == 'cc':
            return p['cc']
        return ('C', p['cc']) if p['cooler'] else ('G', p['cc'])

    for mode in ('cc', 'cc_cooler'):
        tab = defaultdict(list)
        for rec, plist in facturas:
            v = [p for p in plist if p]
            if len(v) == 1:
                tab[keyfun(v[0], mode)].append(rec / v[0]['unid'])
        table = {k: median(x) for k, x in tab.items()}
        ratios = []
        for rec, plist in facturas:
            ls = [p for p in plist if p]
            if ls and rec > 0 and all(keyfun(p, mode) in table for p in ls):
                pred = sum(table[keyfun(p, mode)] * p['unid'] for p in ls)
                if pred > 0:
                    ratios.append(pred / rec)
        print("\nMODO=%s  (tabla %s entradas, %s facturas cubiertas)" % (mode, len(table), len(ratios)))
        report(mode, ratios)

    print("\n(referencia formato x cc + net/std: media 0.982 | CV 0.34 | +-10%: 67%)")


if __name__ == '__main__':
    main()
