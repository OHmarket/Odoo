"""calcular_ccu.py — READ-ONLY, gentil (pocas facturas CCU).

Calcula el costo LANDED ALL-IN por unidad para CCU y lo compara con raw_product_price.
  landed_unit = (price_total_producto + flete_bruto_asignado) / unidades_base
  price_total = neto + IVA + ILA   |   flete repartido por litros x $/L (tarifa)
Objetivo (def. B): raw = valor a pagar = neto+IVA+ILA+flete -> ratio landed/raw ~1.

Uso: python proyectos/2026-06-04-costo-desde-facturas/calcular_ccu.py [n_facturas]
"""
import sys
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

CCU = 315
RULE_PARTNER = 315


def main():
    nfac = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    o = OdooReader()

    # tarifa CCU -> rates ($/L) por volumen de caja (cc*pack)
    rule = o.search_read('x_vendor_freight_rule', [('x_studio_partner_id', '=', RULE_PARTNER), ('x_studio_active', '=', True)],
                         fields=['id', 'x_studio_freight_patterns'], limit=1)
    pats = ['flete']
    rates = []
    avg_rate = 0.0
    if rule:
        pats = [p.strip().lower() for p in (rule[0].get('x_studio_freight_patterns') or 'flete').split(',') if p.strip()]
        for tl in o.search_read('x_vendor_freight_rule_', [('x_studio_rule_id', '=', rule[0]['id'])],
                                fields=['x_studio_cc_unit', 'x_studio_pack_qty', 'x_studio_tariff_case']):
            cc = float(tl['x_studio_cc_unit'] or 0); pk = float(tl['x_studio_pack_qty'] or 0); tar = float(tl['x_studio_tariff_case'] or 0)
            cv = cc * pk
            if cv > 0 and tar > 0:
                rates.append((cv, tar / (cv / 1000.0)))
        avg_rate = (sum(r for _, r in rates) / len(rates)) if rates else 0.0

    def rate_for(case_vol):
        if not rates:
            return avg_rate
        ex = [r for mv, r in rates if abs(mv - case_vol) < 1.0]
        return ex[0] if ex else avg_rate

    moves = o.search_read('account.move', [('partner_id', '=', CCU), ('move_type', '=', 'in_invoice'), ('state', '=', 'posted')],
                          fields=['id', 'name', 'invoice_date'], limit=nfac, order='invoice_date desc')
    print("CCU: %d facturas" % len(moves))

    uom_c, vol_c, raw_c = {}, {}, {}
    def uratio(uid):
        if uid not in uom_c:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_c[uid] = float(r[0]['ratio']) if r else 1.0
        return uom_c[uid] or 1.0
    def pvol(pid):
        if pid not in vol_c:
            r = o.search_read('product.product', [('id', '=', pid)], fields=['volume', 'product_tmpl_id'], limit=1)
            vol_c[pid] = (float(r[0].get('volume') or 0.0), r[0]['product_tmpl_id'][0] if r and r[0].get('product_tmpl_id') else 0) if r else (0.0, 0)
        return vol_c[pid]
    def praw(tid):
        if tid not in raw_c:
            r = o.search_read('product.template', [('id', '=', tid)], fields=['raw_product_price', 'standard_price'], limit=1)
            raw_c[tid] = (float(r[0].get('raw_product_price') or 0.0), float(r[0].get('standard_price') or 0.0)) if r else (0.0, 0.0)
        return raw_c[tid]

    agg = {}   # tid -> latest dict
    for m in moves:
        ls = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                           fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal', 'price_total'])
        prods, freight_gross = [], 0.0
        for l in ls:
            nm = (l['name'] or '').lower()
            if any(p in nm for p in pats):
                freight_gross += float(l['price_total'] or 0.0)
                continue
            if not l['product_id']:
                continue
            qty = float(l['quantity'] or 0.0)
            if qty <= 0:
                continue
            ratio = uratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            units = qty * ratio
            vol, tid = pvol(l['product_id'][0])
            liters = units * vol / 1000.0 if vol > 0 else 0.0
            case_vol = vol * ratio
            prods.append({'name': l['name'], 'tid': tid, 'units': units, 'liters': liters,
                          'rate': rate_for(case_vol), 'ptot': float(l['price_total'] or 0.0),
                          'pid': l['product_id'][0]})
        # repartir flete bruto por litros x rate
        wsum = sum(p['liters'] * p['rate'] for p in prods)
        lknown = sum(p['liters'] for p in prods if p['liters'] > 0)
        netknown = sum(p['ptot'] for p in prods if p['liters'] > 0)
        lpn = (lknown / netknown) if netknown > 0 else 0.0
        for p in prods:
            lit = p['liters'] if p['liters'] > 0 else p['ptot'] * lpn
            w = lit * p['rate']
            p['flete'] = (freight_gross * w / wsum) if wsum > 0 else 0.0
            p['landed_unit'] = (p['ptot'] + p['flete']) / p['units'] if p['units'] else 0.0
            raw, std = praw(p['tid'])
            p['raw'] = raw; p['std'] = std
            p['date'] = m['invoice_date']
            cur = agg.get(p['tid'])
            if cur is None or p['date'] >= cur['date']:
                agg[p['tid']] = p

    print("\n%-34s %10s %10s %7s %8s" % ("producto", "landed/u", "raw", "ratio", "flete/u"))
    rows = sorted(agg.values(), key=lambda r: -r['raw'])
    for p in rows[:30]:
        ratio = (p['landed_unit'] / p['raw']) if p['raw'] else 0.0
        fu = p['flete'] / p['units'] if p['units'] else 0.0
        print("  %-32s %10.0f %10.0f %6.2f %8.0f" % (p['name'][:32], p['landed_unit'], p['raw'], ratio, fu))
    oks = sum(1 for p in rows if p['raw'] and 0.9 <= p['landed_unit']/p['raw'] <= 1.1)
    print("\nproductos con ratio landed/raw en 0.9-1.1: %d de %d" % (oks, len(rows)))


if __name__ == '__main__':
    main()
