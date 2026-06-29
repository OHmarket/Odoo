"""compara_flete_vs_raw.py — READ-ONLY.
Usa el raw como referencia del flete. Para facturas mono-codigo de Embonor:
  flete_implicito_raw_unit = raw_unit - neto_unit*(1+IVA+ILA)   (lo que el raw asume)
  recargo_real_unit        = recargo_factura / unidades         (lo que cobra la factura)
y compara ambos. unidades normalizadas con ancla a std (UoM mixta).
Si recargo_real ~ flete_raw -> el raw ya trae el flete correcto.
"""
import sys
from statistics import median
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
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


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    taxmap = {t['id']: t for t in o.search_read('account.tax', [('type_tax_use', '=', 'purchase')],
                                                fields=['id', 'name', 'amount', 'amount_type'])}

    def split_tax(tax_ids):
        vat = ila = 0.0
        for tid in tax_ids or []:
            t = taxmap.get(tid)
            if not t or t.get('amount_type') != 'percent':
                continue
            amt = f(t.get('amount'))
            if amt <= 0:
                continue
            nm = _norm(t.get('name'))
            if 'iva' in nm and 'no recup' not in nm:
                vat += amt / 100.0
            else:
                ila += amt / 100.0
        return vat, ila

    uom_cache, info_cache = {}, {}
    def uom_ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = (f(r[0]['ratio']) if r else 1.0) or 1.0
        return uom_cache[uid]
    def prod_info(pdid):
        if pdid not in info_cache:
            r = o.search_read('product.product', [('id', '=', pdid)],
                              fields=['standard_price', 'product_tmpl_id'], limit=1)
            std = f(r[0].get('standard_price')) if r else 0.0
            raw = 0.0
            if r and r[0].get('product_tmpl_id'):
                tr = o.search_read('product.template', [('id', '=', r[0]['product_tmpl_id'][0])],
                                   fields=['raw_product_price'], limit=1)
                raw = f(tr[0].get('raw_product_price')) if tr else 0.0
            info_cache[pdid] = (std, raw)
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    rows = []  # (nombre, raw, bruto_unit, flete_raw, recargo_unit)
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal', 'tax_ids'])
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
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            std, raw = prod_info(l['product_id'][0])
            vat, ila = split_tax(l['tax_ids'])
            prods.append({'pid': l['product_id'][0], 'net': f(l['price_subtotal']), 'qty': qty,
                          'pack': ratio, 'std': std, 'raw': raw, 'vat': vat, 'ila': ila,
                          'nm': (l['product_id'][1] if l['product_id'] else '')})
        if rec <= 0 or len(prods) != 1:
            continue
        p = prods[0]
        if p['std'] <= 0 or p['raw'] <= 0:
            continue
        u_unit, u_pack = p['qty'], p['qty'] * p['pack']
        unidades = u_unit if abs(p['net']/u_unit - p['std']) <= abs(p['net']/u_pack - p['std']) else u_pack
        neto_unit = p['net'] / unidades
        if abs(neto_unit - p['std']) / p['std'] > 0.15:
            continue
        bruto_unit = neto_unit * (1 + p['vat'] + p['ila'])
        flete_raw = p['raw'] - bruto_unit
        rec_unit = rec / unidades
        rows.append((p['nm'][:26], p['raw'], bruto_unit, flete_raw, rec_unit))

    print("lineas mono-codigo validas: %s\n" % len(rows))
    pos = [r for r in rows if r[3] > 0]
    print("con flete_raw>0 (raw > bruto): %s   |   flete_raw<=0 (raw no alcanza bruto): %s\n"
          % (len(pos), len(rows) - len(pos)))
    if pos:
        ratios = [r[4] / r[3] for r in pos if r[3] > 0]
        print("ratio recargo_real / flete_raw: mediana %.2f" % median(ratios))
        cuad = sum(1 for x in ratios if 0.8 <= x <= 1.2)
        print("dentro de 0.8-1.2 (cuadran): %.0f%%\n" % (100.0 * cuad / len(ratios)))
    print("  producto                     raw   bruto_u  flete_raw  recargo_real  ratio")
    for nm, raw, bu, fr, ru in sorted(rows, key=lambda r: -r[1])[:25]:
        ratio = (ru / fr) if fr > 0 else 0
        print("  %-26s %7.0f %7.0f %9.0f %11.0f  %5.2f" % (nm, raw, bu, fr, ru, ratio))


if __name__ == '__main__':
    main()
