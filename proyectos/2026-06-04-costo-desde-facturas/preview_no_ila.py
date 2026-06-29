"""
preview_no_ila.py — READ-ONLY.

Modo simple: proveedores que NO venden productos con ILA (sin flete).
Para sus facturas de compra trae el COSTO NETO de producto por unidad:

    costo_neto_unit = price_subtotal / (qty x uom_ratio)

y lo COMPARA contra el maestro: raw_product_price esta BRUTO con IVA, asi que
para productos sin ILA  raw / (1 + IVA)  deberia ~ costo neto de factura.
(standard_price es el neto Odoo.)

Muestra, por SKU, costo neto factura vs raw-sin-IVA y el desvio. No escribe nada.

Uso:  python proyectos/2026-06-04-costo-desde-facturas/preview_no_ila.py [YYYY-MM-DD YYYY-MM-DD]
Default: ultimos ~3 meses (desde el dia 1 de hace 2 meses no; usa 2026-03-01).
"""

import sys
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

ILA_TAX_IDS = [5, 9, 10, 11, 12, 26, 31, 33, 34]  # Especifico, Beb.Analc, Vinos, ILA*


def main():
    if len(sys.argv) >= 3:
        d_from, d_to = sys.argv[1], sys.argv[2]
    else:
        d_from, d_to = '2026-03-01', '2026-06-04'

    o = OdooReader()

    # proveedores CON ILA (a excluir)
    ila_lines = o.search_read('account.move.line',
                              [('parent_state', '=', 'posted'),
                               ('move_id.move_type', '=', 'in_invoice'),
                               ('date', '>=', d_from), ('date', '<=', d_to),
                               ('tax_ids', 'in', ILA_TAX_IDS)],
                              fields=['partner_id'], limit=300000)
    ila_partners = set(l['partner_id'][0] for l in ila_lines if l['partner_id'])

    moves = o.search_read('account.move',
                          [('state', '=', 'posted'), ('move_type', '=', 'in_invoice'),
                           ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)],
                          fields=['id', 'partner_id', 'invoice_date'], limit=200000)
    no_ila_moves = [m for m in moves if m['partner_id'] and m['partner_id'][0] not in ila_partners]
    move_date = {m['id']: m['invoice_date'] for m in no_ila_moves}
    move_partner = {m['id']: m['partner_id'][1] for m in no_ila_moves}
    ids = [m['id'] for m in no_ila_moves]

    print("=== Preview costo NETO (proveedores sin ILA) | %s..%s ===" % (d_from, d_to))
    print("facturas sin ILA: %d  | proveedores: %d"
          % (len(ids), len(set(m['partner_id'][0] for m in no_ila_moves))))

    uom_cache, type_cache = {}, {}

    def ratio(uid):
        if uid not in uom_cache:
            r = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = float(r[0]['ratio']) if r else 1.0
        return uom_cache[uid] or 1.0

    def is_storable(pid):
        if pid not in type_cache:
            r = o.search_read('product.product', [('id', '=', pid)], fields=['type'], limit=1)
            type_cache[pid] = (r[0]['type'] == 'product') if r else False
        return type_cache[pid]

    # ultimo costo por SKU (recorre por fecha; el ultimo gana)
    latest = {}   # tmpl_or_prod -> dict
    n_with, n_without = 0, 0
    for i in range(0, len(ids), 300):
        chunk = ids[i:i + 300]
        ls = o.search_read('account.move.line',
                           [('move_id', 'in', chunk), ('display_type', '=', 'product')],
                           fields=['move_id', 'name', 'product_id', 'quantity',
                                   'product_uom_id', 'price_subtotal', 'price_total'])
        for l in ls:
            if not l['product_id'] or not is_storable(l['product_id'][0]):
                n_without += 1
                continue
            n_with += 1
            qty = float(l['quantity'] or 0.0)
            if qty <= 0:
                continue
            r = ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            ueq = qty * r
            net = float(l['price_subtotal'] or 0.0)
            unit = net / ueq if ueq else 0.0
            mid = l['move_id'][0]
            pid = l['product_id'][0]
            d = move_date.get(mid, '')
            cur = latest.get(pid)
            if (cur is None) or (d >= cur['date']):
                latest[pid] = {'pid': pid, 'name': l['product_id'][1], 'date': d, 'unit': unit,
                               'net': net, 'ueq': ueq, 'partner': move_partner.get(mid, ''),
                               'uom': l['product_uom_id'][1] if l['product_uom_id'] else ''}

    # raw_product_price (BRUTO con IVA) por SKU, para comparar: raw/(1+IVA) ~ neto factura
    IVA = 1.19
    pids = list(latest.keys())
    for i in range(0, len(pids), 300):
        for p in o.search_read('product.product', [('id', 'in', pids[i:i + 300])],
                               fields=['id', 'raw_product_price']):
            latest[p['id']]['raw'] = float(p.get('raw_product_price') or 0.0)

    print("lineas producto: con product_id=%d  sin product_id=%d  (%.0f%% costeables)"
          % (n_with, n_without, 100 * n_with / max(n_with + n_without, 1)))
    print("SKUs distintos con costo: %d\n" % len(latest))

    print("%-40s %10s %10s %8s" % ("SKU", "neto_fact", "raw/1.19", "desvio%"))
    rows = sorted(latest.values(), key=lambda x: (-x['unit']))
    big = 0
    for r in rows:
        raw_net = (r.get('raw', 0.0) or 0.0) / IVA
        dev = ((r['unit'] - raw_net) / raw_net * 100.0) if raw_net else float('nan')
        if raw_net and abs(dev) > 5.0:
            big += 1
    for r in rows[:30]:
        raw_net = (r.get('raw', 0.0) or 0.0) / IVA
        dev = ((r['unit'] - raw_net) / raw_net * 100.0) if raw_net else 0.0
        dev_s = ("%+7.1f" % dev) if raw_net else "  sin raw"
        print("  %-38s %10.1f %10.1f %8s | %s"
              % (r['name'][:38], r['unit'], raw_net, dev_s, r['date']))
    print("\nSKUs con desvio |neto_fact vs raw/1.19| > 5%%: %d de %d" % (big, len(rows)))


if __name__ == '__main__':
    main()
