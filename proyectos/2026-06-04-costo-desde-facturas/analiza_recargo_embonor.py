"""analiza_recargo_embonor.py — READ-ONLY.
Para armar una regla de flete de Embonor: mide, por factura, el RECARGO contra
los 3 drivers fisicos/valor y su ESTABILIDAD (CV); y lista los tipos de caja
(cc x pack) presentes con el recargo/litro implicito.
  - recargo/litro  -> regla 'Tipo de Caja' (tarifa por litro)
  - recargo/caja   -> regla 'Tarifa Fija Caja'
  - recargo/%neto  -> por valor (sin regla fisica)
El driver con menor CV es el mas consistente = el que conviene para la regla.
"""
import sys
from statistics import mean, pstdev
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR = 306
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _norm(s):
    return (s or '').strip().lower()


def is_charge(label):
    lab = _norm(label)
    return any(w in lab for w in CHARGE_WORDS) if lab else False


def cv(xs):
    xs = [x for x in xs if x > 0]
    if len(xs) < 2:
        return 0.0, (xs[0] if xs else 0.0)
    m = mean(xs)
    return (pstdev(xs) / m if m else 0.0), m


def main():
    o = OdooReader()
    uom_cache, cc_cache = {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]

    def prod_cc(pid):
        if pid not in cc_cache:
            r = o.search_read('product.product', [('id', '=', pid)],
                              fields=['volume', 'product_tmpl_id'], limit=1)
            cc = 0.0
            if r:
                cc = f(r[0].get('volume'))
                if cc == 0 and r[0].get('product_tmpl_id'):
                    tr = o.search_read('product.template', [('id', '=', r[0]['product_tmpl_id'][0])],
                                       fields=['volume'], limit=1)
                    cc = f(tr[0].get('volume')) if tr else 0.0
            cc_cache[pid] = cc
        return cc_cache[pid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', EMBONOR),
                           ('invoice_date', '>=', '2026-01-01'), ('invoice_date', '<=', '2026-04-30')],
                          fields=['id'], order='id', limit=400)

    r_litro, r_caja, r_pct = [], [], []
    caja_recargo = {}   # (cc,pack) -> [recargo/litro de esa caja en cada factura]
    n_ok = 0
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal'])
        prods, rec_net = [], 0.0
        for l in lines:
            qty = f(l['quantity'])
            if qty <= 0:
                continue
            if not l['product_id']:
                if is_charge(l['name']):
                    rec_net += f(l['price_subtotal'])
                continue
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            cc = prod_cc(l['product_id'][0])
            ueq = qty * ratio
            prods.append({'qty': qty, 'cc': cc, 'pack': ratio, 'ueq': ueq,
                          'lit': ueq * cc / 1000.0, 'net': f(l['price_subtotal'])})
        if rec_net <= 0 or not prods:
            continue
        sum_lit = sum(p['lit'] for p in prods)
        sum_caja = sum(p['qty'] for p in prods)
        sum_net = sum(p['net'] for p in prods)
        if sum_lit > 0:
            r_litro.append(rec_net / sum_lit)
        if sum_caja > 0:
            r_caja.append(rec_net / sum_caja)
        if sum_net > 0:
            r_pct.append(rec_net / sum_net)
        # recargo/litro implicito por tipo de caja (asumiendo driver litros)
        if sum_lit > 0:
            rpl = rec_net / sum_lit
            for p in prods:
                if p['cc'] > 0:
                    caja_recargo.setdefault((p['cc'], p['pack']), []).append(rpl)
        n_ok += 1

    print("Embonor facturas con recargo: %s\n" % n_ok)
    print("%-12s  CV      media" % "driver")
    for name, xs in (('recargo/litro', r_litro), ('recargo/caja', r_caja), ('recargo/%neto', r_pct)):
        c, m = cv(xs)
        print("  %-12s  %.3f   %.3f" % (name, c, m))

    print("\nTipos de caja (cc, pack) en Embonor: %s distintos" % len(caja_recargo))
    rows = sorted(caja_recargo.items(), key=lambda kv: -len(kv[1]))
    print("  cc     pack   vol_caja   n_fact   rec/litro_prom")
    for (cc, pack), vals in rows[:25]:
        print("  %-6.0f %-5.0f %-9.0f %-7s %.1f" % (cc, pack, cc * pack, len(vals), mean(vals)))


if __name__ == '__main__':
    main()
