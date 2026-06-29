"""valida_packing.py — READ-ONLY. Prueba decisiva de la tabla (packing, cc).
1) Calibra tabla[packing,cc] = mediana(recargo/unidad) con facturas mono-codigo.
2) La aplica a TODAS las facturas (incl. multi-producto): predice recargo total =
   Sum tabla[pk,cc]*unidades, y lo compara con el recargo real de la factura.
3) Reporta cobertura (lineas/unidades con (pk,cc) en tabla) y error de prediccion.
Si el predicho ~ real con CV bajo, la tabla reparte fiel -> margen por producto OK.
"""
import sys
from collections import defaultdict
from statistics import mean, median, pstdev
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def is_charge(label):
    lab = (label or '').strip().lower()
    return any(w in lab for w in CHARGE_WORDS) if lab else False


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
            info_cache[pdid] = (f(r[0].get('standard_price')) if r else 0.0,
                                f(r[0].get('volume')) if r else 0.0,
                                (r[0].get('display_name') or '') if r else '')
        return info_cache[pdid]

    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)

    # un solo pase de queries: guardar (recargo, [lineas])
    facturas = []
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'product_uom_id', 'price_subtotal'])
        plist, rec = [], 0.0
        for l in lines:
            qty = f(l['quantity'])
            if qty <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if not l['product_id']:
                continue
            std, cc, nm = prod_info(l['product_id'][0])
            if std <= 0 or cc <= 0:
                plist.append(None)  # no normalizable
                continue
            ratio = uom_ratio(l['product_uom_id'][0]) if l['product_uom_id'] else 1.0
            net = f(l['price_subtotal'])
            u_unit, u_pack = qty, qty * ratio
            unid = u_unit if abs(net/u_unit - std) <= abs(net/u_pack - std) else u_pack
            ok = abs(net/unid - std) / std <= 0.15
            plist.append({'pk': packing_of(nm), 'cc': cc, 'unid': unid, 'net': net, 'ok': ok})
        if rec > 0 and plist:
            facturas.append((rec, plist))

    # 1) calibrar con mono-codigo (1 sola linea producto valida)
    tab = defaultdict(list)
    for rec, plist in facturas:
        valid = [p for p in plist if p and p['ok']]
        if len(valid) == 1 and len([p for p in plist if p]) == 1:
            p = valid[0]
            tab[(p['pk'], p['cc'])].append(rec / p['unid'])
    table = {k: median(v) for k, v in tab.items()}
    print("tabla (packing,cc) calibrada: %s entradas\n" % len(table))

    # 2) validar prediccion del total en TODAS las facturas
    ratios = []
    cov_lines = cov_lines_ok = 0
    for rec, plist in facturas:
        pred = 0.0
        any_line = False
        for p in plist:
            if not p:
                continue
            any_line = True
            cov_lines += 1
            t = table.get((p['pk'], p['cc']))
            if t is not None:
                pred += t * p['unid']
                cov_lines_ok += 1
        if any_line and pred > 0 and rec > 0:
            ratios.append(pred / rec)

    print("COBERTURA lineas con (packing,cc) en tabla: %s/%s (%.0f%%)"
          % (cov_lines_ok, cov_lines, 100.0*cov_lines_ok/cov_lines if cov_lines else 0))
    if ratios:
        ratios.sort()
        m = mean(ratios)
        cv = pstdev(ratios)/m if m else 0
        dentro = 100.0*sum(1 for x in ratios if 0.9 <= x <= 1.1)/len(ratios)
        print("\nPREDICCION recargo total por factura (predicho/real), %s facturas:" % len(ratios))
        print("  mediana %.2f | media %.2f | CV %.2f" % (median(ratios), m, cv))
        print("  p10/p90: %.2f / %.2f" % (ratios[int(0.1*len(ratios))], ratios[int(0.9*len(ratios))]))
        print("  dentro de 0.9-1.1: %.0f%%" % dentro)
        print("\n=> si predicho~real (ratio~1, CV bajo), la tabla packing x cc reparte FIEL.")


if __name__ == '__main__':
    main()
