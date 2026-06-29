"""
wac_preview.py — READ-ONLY.

Costo PROMEDIO PONDERADO (WAC) desde FACTURAS de proveedor (precio real pagado),
para mantener al dia raw_product_price (que esta CON IVA). Solo proveedores SIN
ILA (camino simple, sin flete). No escribe nada: muestra que cambiaria.

Por SKU, sobre una ventana de N dias:
    raw_wac = sum(price_total de las lineas) / sum(unidades_equiv)
            = promedio ponderado por cantidad del costo unitario CON IVA

Compara raw_wac vs raw_product_price actual y lista los cambios mas grandes.

Por que NO usar standard_price de Odoo: su AVCO se calcula desde las ORDENES DE
COMPRA, no desde la factura final; el precio real puede diferir. Aca usamos la
factura.

Uso:  python proyectos/2026-06-04-costo-desde-facturas/wac_preview.py [dias] [YYYY-MM-DD_hoy]
Default: ventana 90 dias, hoy=2026-06-04.
"""

import sys
from datetime import date, timedelta

sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

ILA_TAX_IDS = [5, 9, 10, 11, 12, 26, 31, 33, 34]


def main():
    days = int(sys.argv[1]) if len(sys.argv) >= 2 else 90
    today = sys.argv[2] if len(sys.argv) >= 3 else '2026-06-04'
    d_to = today
    y, m, dd = (int(x) for x in today.split('-'))
    d_from = (date(y, m, dd) - timedelta(days=days)).isoformat()

    o = OdooReader()

    # proveedores CON ILA -> excluir
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
                          fields=['id', 'partner_id'], limit=200000)
    ids = [m['id'] for m in moves if m['partner_id'] and m['partner_id'][0] not in ila_partners]

    print("=== WAC desde facturas (proveedores sin ILA) | ventana %sd | %s..%s ===" % (days, d_from, d_to))
    print("facturas: %d" % len(ids))

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

    std_cache = {}

    def std_net(pid):
        if pid not in std_cache:
            r = o.search_read('product.product', [('id', '=', pid)], fields=['standard_price'], limit=1)
            std_cache[pid] = float(r[0]['standard_price']) if r else 0.0
        return std_cache[pid]

    def base_units(pid, qty, rat, net_sub):
        # resuelve la ambiguedad de UoM: qty puede venir en unidades base (ratio
        # decorativo, GALLETA) o en packs (CHICLE). Elige la base cuyo costo neto
        # unitario quede mas cerca de standard_price (anclaje de magnitud).
        s = std_net(pid)
        cand = [qty, qty * rat] if rat and rat != 1.0 else [qty]
        if s <= 0 or net_sub <= 0:
            return qty, False
        best, miss = qty, True
        bestdev = None
        for bu in cand:
            if bu <= 0:
                continue
            dev = abs((net_sub / bu) - s) / s
            if (bestdev is None) or (dev < bestdev):
                bestdev = dev
                best = bu
        miss = (bestdev is None) or (bestdev > 0.15)  # ninguna base cuadra con std
        return best, miss

    # acumular sum(price_total) y sum(unidades_equiv) por producto
    acc = {}   # pid -> {'sum_gross':, 'sum_units':, 'name':, 'n_lines':, 'last_unit':, 'last_date':}
    for i in range(0, len(ids), 300):
        chunk = ids[i:i + 300]
        ls = o.search_read('account.move.line',
                           [('move_id', 'in', chunk), ('display_type', '=', 'product')],
                           fields=['name', 'product_id', 'quantity', 'product_uom_id',
                                   'price_subtotal', 'price_total', 'date'])
        for l in ls:
            if not l['product_id'] or not is_storable(l['product_id'][0]):
                continue
            qty = float(l['quantity'] or 0.0)
            if qty <= 0:
                continue
            pid = l['product_id'][0]
            rat = ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            net = float(l['price_subtotal'] or 0.0)
            gross = float(l['price_total'] or 0.0)
            ueq, miss = base_units(pid, qty, rat, net)
            if ueq <= 0:
                continue
            a = acc.setdefault(pid, {'sum_gross': 0.0, 'sum_units': 0.0,
                                     'name': l['product_id'][1], 'n_lines': 0,
                                     'last_unit': 0.0, 'last_date': '', 'miss': 0})
            a['sum_gross'] += gross
            a['sum_units'] += ueq
            a['n_lines'] += 1
            if miss:
                a['miss'] += 1
            if (l['date'] or '') >= a['last_date']:
                a['last_date'] = l['date'] or ''
                a['last_unit'] = gross / ueq

    # raw actual + std + codigo
    pids = list(acc.keys())
    for i in range(0, len(pids), 300):
        for p in o.search_read('product.product', [('id', 'in', pids[i:i + 300])],
                               fields=['id', 'raw_product_price', 'standard_price', 'default_code']):
            acc[p['id']]['raw_now'] = float(p.get('raw_product_price') or 0.0)
            acc[p['id']]['std'] = float(p.get('standard_price') or 0.0)
            acc[p['id']]['code'] = p.get('default_code') or ''

    MAX_CHANGE = 30.0
    rows = []
    for pid, a in acc.items():
        wac = a['sum_gross'] / a['sum_units'] if a['sum_units'] else 0.0
        raw_now = a.get('raw_now', 0.0) or 0.0
        dev = ((wac - raw_now) / raw_now * 100.0) if raw_now else float('nan')
        miss = a.get('miss', 0)
        if miss:
            decision = 'EXCLUIDO_UoM'
        elif raw_now and abs(dev) > MAX_CHANGE:
            decision = 'BLOQUEADO_tope30%'
        elif raw_now and abs(dev) <= 5.0:
            decision = 'OK_sin_cambio'
        else:
            decision = 'ESCRIBIRIA'
        rows.append({'code': a.get('code', ''), 'name': a['name'], 'wac': wac,
                     'raw_now': raw_now, 'std': a.get('std', 0.0), 'dev': dev,
                     'n': a['n_lines'], 'last_unit': a['last_unit'], 'units': a['sum_units'],
                     'miss': miss, 'decision': decision})

    # ---- CSV comparacion (es-CL: sep=';', decimal=',', utf-8-sig) ----
    import os
    outdir = os.path.join('proyectos', '2026-06-04-costo-desde-facturas', 'resultados')
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    csv_path = os.path.join(outdir, 'comparacion_costo_wac_%sd.csv' % days)

    def _num(x):
        return ('%.2f' % x).replace('.', ',')

    with open(csv_path, 'w', encoding='utf-8-sig') as fh:
        fh.write('codigo;producto;raw_actual;wac_facturas;standard_price;desvio_pct;n_facturas;flag_uom;decision\n')
        for r in sorted(rows, key=lambda x: (x['decision'], -abs(x['dev']) if x['dev'] == x['dev'] else 0)):
            dev_s = _num(r['dev']) if r['dev'] == r['dev'] else ''
            fh.write('%s;%s;%s;%s;%s;%s;%d;%s;%s\n' % (
                r['code'], (r['name'] or '').replace(';', ','), _num(r['raw_now']),
                _num(r['wac']), _num(r['std']), dev_s, r['n'],
                'DUDOSA' if r['miss'] else '', r['decision']))

    from collections import Counter
    dec = Counter(r['decision'] for r in rows)
    print("SKUs con WAC: %d" % len(rows))
    print("  OK_sin_cambio (<=5%%) : %d" % dec.get('OK_sin_cambio', 0))
    print("  ESCRIBIRIA           : %d" % dec.get('ESCRIBIRIA', 0))
    print("  BLOQUEADO_tope30%%    : %d" % dec.get('BLOQUEADO_tope30%', 0))
    print("  EXCLUIDO_UoM         : %d" % dec.get('EXCLUIDO_UoM', 0))
    print("\nCSV comparacion -> %s\n" % csv_path)

    esc = [r for r in rows if r['decision'] == 'ESCRIBIRIA']
    print("Cambios que ESCRIBIRIA (muestra):")
    print("%-38s %10s %10s %8s %5s" % ("SKU", "raw_actual", "WAC_nuevo", "cambio%", "nfac"))
    for r in sorted(esc, key=lambda x: -abs(x['dev']))[:25]:
        print("  %-36s %10.1f %10.1f %+7.1f %5d" % (r['name'][:36], r['raw_now'], r['wac'], r['dev'], r['n']))


if __name__ == '__main__':
    main()
