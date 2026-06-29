"""
validar_reconciliacion.py — READ-ONLY.

Replica en Python la logica de "OH Costo desde Facturas.py" (Server Action) y
verifica, contra facturas reales, que:
  1. La suma del flete asignado a las lineas producto == flete neto de la factura.
  2. El costo cash landed por unidad es creible (no inflado por IVA, no negativo).

No escribe nada en Odoo (usa OdooReader, whitelist read-only).

Uso (desde la raiz del repo):
    python proyectos/2026-06-04-costo-desde-facturas/validar_reconciliacion.py [YYYY-MM-DD YYYY-MM-DD]
Default: el dia de hoy (rango de 1 dia) si no se pasan fechas.
"""

import sys
from datetime import date

sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

DTE_CODE = '33'


def _norm(s):
    return (s or '').strip().lower()


def _is_recoverable_iva(name):
    nm = _norm(name)
    if 'iva' not in nm:
        return False
    if 'no recup' in nm or 'no rec.' in nm:
        return False
    return True


def main():
    if len(sys.argv) >= 3:
        d_from, d_to = sys.argv[1], sys.argv[2]
    else:
        t = date.today().isoformat()
        d_from = d_to = t

    o = OdooReader()

    # ---- reglas + tarifas ----
    rules = {}
    for r in o.search_read('x_vendor_freight_rule', [('x_studio_active', '=', True)],
                           fields=['id', 'x_studio_partner_id', 'x_studio_rule_type',
                                   'x_studio_freight_patterns']):
        pid = r['x_studio_partner_id'][0] if r['x_studio_partner_id'] else None
        if not pid:
            continue
        pats = [p.strip().lower() for p in (r['x_studio_freight_patterns'] or '').split(',') if p.strip()]
        rules[pid] = {
            'rule_id': r['id'],
            'name': r['x_studio_partner_id'][1],
            'rtype': _norm(r['x_studio_rule_type']),
            'patterns': pats,
            'tariffs': [],
        }
    rid_to_pid = {v['rule_id']: pid for pid, v in rules.items()}
    for tl in o.search_read('x_vendor_freight_rule_', [],
                            fields=['x_studio_rule_id', 'x_studio_cc_unit',
                                    'x_studio_pack_qty', 'x_studio_tariff_case']):
        rid = tl['x_studio_rule_id'][0] if tl['x_studio_rule_id'] else None
        pid = rid_to_pid.get(rid)
        if pid:
            rules[pid]['tariffs'].append((
                float(tl['x_studio_cc_unit'] or 0), float(tl['x_studio_pack_qty'] or 0),
                float(tl['x_studio_tariff_case'] or 0)))

    # ---- precompute tarifa-por-litro por tipo de caja ----
    # rates: [(match_vol_cc, rate_$_por_L)] ; caja -> match_vol = cc*pack ; botella -> cc
    for pid, rl in rules.items():
        rtype = rl['rtype']
        rates, fija_tar = [], 0.0
        for cc, pack, tar in rl['tariffs']:
            if tar <= 0:
                continue
            if 'fija' in rtype:
                fija_tar = fija_tar or tar
                continue
            mvol = cc if 'botella' in rtype else cc * pack
            if mvol > 0:
                rates.append((mvol, tar / (mvol / 1000.0)))
        rl['rates'] = rates
        rl['avg_rate'] = (sum(x[1] for x in rates) / len(rates)) if rates else 0.0
        rl['fija_tar'] = fija_tar

    partner_ids = list(rules.keys())

    # ---- impuestos de compra ----
    taxmap = {t['id']: t for t in o.search_read('account.tax', [('type_tax_use', '=', 'purchase')],
                                                 fields=['id', 'name', 'amount', 'amount_type'])}

    def split_tax(tax_ids):
        vat = ila = 0.0
        for tid in tax_ids:
            t = taxmap.get(tid)
            if not t or t.get('amount_type') != 'percent':
                continue
            amt = float(t.get('amount') or 0.0)
            if amt <= 0:
                continue
            if _is_recoverable_iva(t.get('name')):
                vat += amt / 100.0
            else:
                ila += amt / 100.0
        return vat, ila

    def line_rate(pid, cc, pack):
        # tarifa-por-litro del tipo de caja. basis: 'L' (litros x rate), 'flat'
        # (tarifa fija x n_cajas), 'none' (sin tarifa). miss=True si no fue match exacto.
        rule = rules.get(pid) or {}
        rtype = rule.get('rtype') or ''
        if 'fija' in rtype:
            ft = rule.get('fija_tar') or 0.0
            return (ft, 'flat', ft <= 0)
        rates = rule.get('rates') or []
        if not rates:
            return (0.0, 'none', True)
        key = cc if 'botella' in rtype else cc * pack
        exact = [r for mv, r in rates if abs(mv - key) < 1.0]
        if exact:
            return (exact[0], 'L', False)
        return (rule.get('avg_rate') or 0.0, 'L', True)  # no exacto -> $/L promedio del proveedor

    # ---- moves ----
    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', 'in', partner_ids),
                           ('l10n_latam_document_type_id.code', '=', DTE_CODE),
                           ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)],
                          fields=['id', 'name', 'partner_id', 'invoice_date'], order='id')

    print("=== Validacion costo desde facturas | %s..%s | %s moves ===" % (d_from, d_to, len(moves)))
    if not moves:
        print("(sin facturas en el rango para proveedores con regla)")
        return

    # cache uom ratio y cc producto
    uom_cache, cc_cache = {}, {}

    def uom_ratio(uid):
        if uid not in uom_cache:
            rec = o.search_read('uom.uom', [('id', '=', uid)], fields=['ratio'], limit=1)
            uom_cache[uid] = float(rec[0]['ratio']) if rec else 1.0
        return uom_cache[uid] or 1.0

    def prod_cc(pid):
        if pid not in cc_cache:
            rec = o.search_read('product.product', [('id', '=', pid)],
                                fields=['volume', 'product_tmpl_id'], limit=1)
            cc = 0.0
            if rec:
                cc = float(rec[0].get('volume') or 0.0)
                if cc == 0.0 and rec[0].get('product_tmpl_id'):
                    tr = o.search_read('product.template', [('id', '=', rec[0]['product_tmpl_id'][0])],
                                       fields=['volume'], limit=1)
                    cc = float(tr[0].get('volume') or 0.0) if tr else 0.0
            cc_cache[pid] = cc
        return cc_cache[pid]

    n_ok = n_bad = 0
    for m in moves:
        pid = m['partner_id'][0]
        rule = rules.get(pid, {})
        lines = o.search_read('account.move.line',
                              [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['id', 'name', 'product_id', 'quantity',
                                      'product_uom_id', 'price_subtotal', 'tax_ids'])
        prod, freight_net = [], 0.0
        for l in lines:
            qty = float(l['quantity'] or 0.0)
            if qty <= 0:
                continue
            label = (l['name'] or '')
            is_fr = any(p in _norm(label) for p in rule.get('patterns', []))
            net = float(l['price_subtotal'] or 0.0)
            if is_fr:
                freight_net += net
                continue
            if not l['product_id']:
                continue
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            ueq = qty * ratio
            cc = prod_cc(l['product_id'][0])
            liters = ueq * cc / 1000.0 if cc > 0 else 0.0
            rate, basis, miss = line_rate(pid, cc, ratio)
            _, ila = split_tax(l['tax_ids'] or [])
            prod.append({'label': label[:32], 'net': net, 'ila': ila, 'ueq': ueq,
                         'cc': cc, 'pack': ratio, 'liters': liters, 'rate': rate,
                         'basis': basis, 'qty': qty, 'miss': miss})

        # imputar litros a SKUs con volume=0 (misma densidad L/$ de la factura) para
        # mantener el reparto en escala de litros y no romper con units.
        known_l = sum(p['liters'] for p in prod if p['liters'] > 0)
        known_net = sum(p['net'] for p in prod if p['liters'] > 0)
        l_per_net = (known_l / known_net) if known_net > 0 else 0.0
        for p in prod:
            if p['basis'] == 'flat':
                p['w'] = max(p['rate'] * p['qty'], 0.0)
            elif p['basis'] == 'none':
                p['w'] = max(p['ueq'], 0.0)
            else:  # 'L'
                lit = p['liters'] if p['liters'] > 0 else (p['net'] * l_per_net)
                if p['liters'] <= 0:
                    p['miss'] = True
                p['w'] = max(lit * p['rate'], 0.0)

        wsum = sum(p['w'] for p in prod)
        alloc_sum = 0.0
        for i, p in enumerate(prod):
            if freight_net <= 0 or wsum <= 0:
                p['alloc'] = 0.0
            elif i == len(prod) - 1:
                p['alloc'] = freight_net - alloc_sum
            else:
                p['alloc'] = freight_net * (p['w'] / wsum)
                alloc_sum += p['alloc']
            p['cash_unit'] = (p['net'] * (1 + p['ila']) + p['alloc']) / p['ueq'] if p['ueq'] else 0.0

        total_alloc = sum(p['alloc'] for p in prod)
        diff = round(total_alloc - freight_net, 4)
        ok = (abs(diff) < 0.01) or (freight_net <= 0)
        n_ok += int(ok)
        n_bad += int(not ok)

        print("\n%s | %s | %s" % (m['name'], m['invoice_date'], m['partner_id'][1][:30]))
        print("  flete_factura_neto=%.1f  Sum_asignado=%.1f  diff=%.4f  %s"
              % (freight_net, total_alloc, diff, 'OK' if ok else '*** NO CUADRA ***'))
        for p in prod:
            flag = ' [tariff_miss]' if p['miss'] else ''
            print("   - %-32s net=%9.1f ila=%.3f ueq=%6.1f flete=%8.1f cash_unit=%9.2f%s"
                  % (p['label'], p['net'], p['ila'], p['ueq'], p['alloc'], p['cash_unit'], flag))

    print("\n=== RESUMEN: %s OK, %s NO CUADRAN ===" % (n_ok, n_bad))


if __name__ == '__main__':
    main()
