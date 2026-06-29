"""calibra_packing_v2.py — READ-ONLY.
Igual que calibra_packing pero toma el cc de la UNIDAD desde el NOMBRE (el campo
volume tiene errores: a veces trae el volumen del pack). Recalibra recargo/unidad
por (packing, cc_nombre) y reporta cuantos productos tienen volume != cc_nombre.
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
    if unit.lower() in ('l', 'lt', 'lts', 'litro', 'litros'):
        x *= 1000.0
    return x


def cc_from_name(name):
    """cc de la UNIDAD desde el nombre. 'NxM CC' -> M ; 'M CC'/'X.Y L' -> ese."""
    n = name or ''
    m = RE_NXCC.search(n)
    if m:
        return _to_cc(m.group(2), m.group(3))
    m = RE_CC.search(n)
    if m:
        return _to_cc(m.group(1), m.group(2))
    return 0.0


def packing_of(name):
    n = ' ' + (name or '').lower() + ' '
    if 'tetra' in n:
        return 'TETRA'
    if 'cooler' in n:
        return 'COOLER'
    if 'lata' in n:
        return 'LATA'
    if 'vid' in n or 'retornable' in n or ' ret ' in n:
        return 'VIDRIO_RET'
    if 'desechable' in n or ' des ' in n or 'pet' in n or ' nr ' in n:
        return 'PET_DES'
    if 'botella' in n or ' bot ' in n or 'bot.' in n:
        return 'BOTELLA'
    return 'OTRO'


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
                              fields=['standard_price', 'volume', 'display_name'], limit=1)
            nm = (r[0].get('display_name') or '') if r else ''
            info_cache[pdid] = (f(r[0].get('standard_price')) if r else 0.0,
                                f(r[0].get('volume')) if r else 0.0, nm, cc_from_name(nm))
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    by_pkcc = defaultdict(list)
    vol_bad = set()
    seen_prod = set()
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
            std, vol, nm, ccn = prod_info(l['product_id'][0])
            seen_prod.add(l['product_id'][0])
            if vol > 0 and ccn > 0 and abs(vol - ccn) / ccn > 0.15:
                vol_bad.add(l['product_id'][0])
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            prods.append({'std': std, 'cc': ccn, 'nm': nm, 'qty': qty, 'pack': ratio, 'net': f(l['price_subtotal'])})
        if rec <= 0 or len(prods) != 1:
            continue
        p = prods[0]
        if p['std'] <= 0 or p['cc'] <= 0:
            continue
        u_unit, u_pack = p['qty'], p['qty'] * p['pack']
        unidades = u_unit if abs(p['net']/u_unit - p['std']) <= abs(p['net']/u_pack - p['std']) else u_pack
        if abs(p['net']/unidades - p['std']) / p['std'] > 0.15:
            continue
        by_pkcc[(packing_of(p['nm']), p['cc'])].append(rec / unidades)

    print("productos Embonor vistos: %s | con volume sucio (|vol-cc_nombre|>15%%): %s\n"
          % (len(seen_prod), len(vol_bad)))
    print("=== recargo/unidad por (PACKING, cc_NOMBRE) ===")
    print("  packing       cc     n    media   CV")
    allc = []
    for key in sorted(by_pkcc, key=lambda k: (-len(by_pkcc[k]))):
        pk, cc = key
        c, mu, n = cv(by_pkcc[key])
        if n >= 2:
            allc.append(c)
            print("  %-12s %-6.0f %-3s %8.1f  %.2f" % (pk, cc, n, mu, c))
    if allc:
        print("\nCV promedio (packing,cc_nombre): %.3f   (con volume era 0.081)" % mean(allc))


if __name__ == '__main__':
    main()
