"""compara_reparto_embonor.py — READ-ONLY.
Para las facturas de Embonor (RECARGO global), reparte el recargo por 3 metodos
y mide cual deja el equiv (neto+IVA+ILA+recargo, unitario) mas cerca del raw:
  - valor   : w = neto de la linea
  - cajas   : w = qty facturada (UoM de compra = cajas)
  - unidades: w = qty * uom_ratio (piezas)
Metrica: mediana de |equiv/raw - 1| sobre las lineas con raw>0.
ueq comun (qty*ratio) en los 3 -> la diferencia es SOLO el reparto.
"""
import sys
from statistics import median
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


def main():
    o = OdooReader()
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

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', EMBONOR),
                           ('invoice_date', '>=', '2026-01-01'), ('invoice_date', '<=', '2026-04-30')],
                          fields=['id'], order='id', limit=400)
    print("Embonor moves ene-abr: %s" % len(moves))

    # cache raw por product_id (product.product -> template.raw_product_price)
    raw_cache = {}
    def get_raw(pid):
        if pid not in raw_cache:
            rec = o.search_read('product.product', [('id', '=', pid)],
                                fields=['product_tmpl_id'], limit=1)
            raw = 0.0
            if rec and rec[0].get('product_tmpl_id'):
                tr = o.search_read('product.template', [('id', '=', rec[0]['product_tmpl_id'][0])],
                                   fields=['raw_product_price'], limit=1)
                raw = f(tr[0].get('raw_product_price')) if tr else 0.0
            raw_cache[pid] = raw
        return raw_cache[pid]

    gaps = {'valor': [], 'cajas': [], 'unidades': []}
    n_lines = 0
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id',
                                      'price_subtotal', 'price_total', 'tax_ids'])
        prods, rec_gross = [], 0.0
        for l in lines:
            qty = f(l['quantity'])
            if qty <= 0:
                continue
            if not l['product_id']:
                if is_charge(l['name']):
                    rec_gross += f(l['price_total'])   # recargo bruto a repartir
                continue
            ratio = 1.0
            if l['product_uom_id']:
                ur = o.search_read('uom.uom', [('id', '=', l['product_uom_id'][0])], fields=['ratio'], limit=1)
                ratio = (f(ur[0]['ratio']) if ur else 1.0) or 1.0
            net = f(l['price_subtotal'])
            vat, ila = split_tax(l['tax_ids'])
            prods.append({'pid': l['product_id'][0], 'net': net, 'qty': qty,
                          'ueq': qty * ratio, 'gross_nf': net * (1 + vat + ila),
                          'raw': get_raw(l['product_id'][0])})
        if rec_gross <= 0 or not prods:
            continue
        for method, key in (('valor', 'net'), ('cajas', 'qty'), ('unidades', 'ueq')):
            wsum = sum(p[key] for p in prods) or 1.0
            for p in prods:
                if p['raw'] <= 0 or p['ueq'] <= 0:
                    continue
                alloc = rec_gross * p[key] / wsum
                equiv = (p['gross_nf'] + alloc) / p['ueq']
                gaps[method].append(abs(equiv / p['raw'] - 1.0))
        n_lines += sum(1 for p in prods if p['raw'] > 0)

    print("lineas con raw evaluadas: %s\n" % n_lines)
    print("%-10s  mediana|gap|  prom|gap|  <=10%%  <=5%%" % "metodo")
    for method in ('valor', 'cajas', 'unidades'):
        g = gaps[method]
        if not g:
            continue
        med = median(g)
        prom = sum(g) / len(g)
        p10 = 100.0 * sum(1 for x in g if x <= 0.10) / len(g)
        p5 = 100.0 * sum(1 for x in g if x <= 0.05) / len(g)
        print("%-10s  %10.3f  %9.3f  %4.0f%%  %4.0f%%" % (method, med, prom, p10, p5))


if __name__ == '__main__':
    main()
