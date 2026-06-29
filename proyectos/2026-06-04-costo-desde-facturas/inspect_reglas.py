"""inspect_reglas.py — READ-ONLY. Reglas de flete (x_vendor_freight_rule) + tarifas; busca Coca Cola."""
import sys
from collections import defaultdict
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def pname(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else str(v)


def main():
    o = OdooReader()
    reglas = o.search_read('x_vendor_freight_rule', [],
                           fields=['id', 'x_studio_partner_id', 'x_studio_rule_type',
                                   'x_studio_active', 'x_studio_freight_patterns'], order='id')
    print("=== REGLAS x_vendor_freight_rule (%s total) ===" % len(reglas))
    by_id = {}
    for r in reglas:
        nm = pname(r.get('x_studio_partner_id'))
        by_id[r['id']] = nm
        print("  id=%-3s active=%-5s  %-42s type=%-16s patterns=%s" % (
            r['id'], r.get('x_studio_active'), nm[:42],
            r.get('x_studio_rule_type'), r.get('x_studio_freight_patterns')))

    tarifas = o.search_read('x_vendor_freight_rule_', [],
                            fields=['x_studio_rule_id', 'x_studio_cc_unit',
                                    'x_studio_pack_qty', 'x_studio_tariff_case'])
    byrule = defaultdict(list)
    for t in tarifas:
        rid = (t.get('x_studio_rule_id') or [0])[0]
        byrule[rid].append(t)
    print("\n=== TARIFAS por regla (%s lineas) ===" % len(tarifas))
    for rid, ts in byrule.items():
        print("  regla %s (%s): %s tarifas" % (rid, by_id.get(rid, '?')[:32], len(ts)))
        for t in ts[:10]:
            print("     cc=%-6s pack=%-4s tarifa=%s" % (
                f(t.get('x_studio_cc_unit')), f(t.get('x_studio_pack_qty')),
                f(t.get('x_studio_tariff_case'))))

    print("\n=== regla para Coca Cola / Embonor (partner 306) ===")
    hits = [r for r in reglas if 'embonor' in pname(r.get('x_studio_partner_id')).lower()
            or 'coca' in pname(r.get('x_studio_partner_id')).lower()
            or (isinstance(r.get('x_studio_partner_id'), (list, tuple)) and r['x_studio_partner_id'][0] == 306)]
    if hits:
        for r in hits:
            print("  ENCONTRADA:", r)
    else:
        print("  NINGUNA regla para Embonor/Coca Cola.")


if __name__ == '__main__':
    main()
