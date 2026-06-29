"""inspect_flete.py — READ-ONLY. Como queda el flete por codigo/proveedor."""
import sys
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_vendor_bill_cost_lin'
CODES = ['0332', '0125', '0929', '447082']  # cocas/fanta + sierra morena


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def main():
    o = OdooReader()
    flds = ['x_studio_doc_date', 'x_studio_partner_id', 'x_studio_line_net',
            'x_studio_freight_alloc_net', 'x_studio_freight_invoice_net',
            'x_studio_total_gross_with_freight', 'x_studio_qty_units_equiv',
            'x_studio_unit_gross_no_freight', 'x_studio_raw_snapshot']
    for code in CODES:
        rows = o.search_read(MODEL, [('x_studio_default_code', '=', code)], fields=flds,
                             order='x_studio_doc_date asc, id asc', limit=5)
        print("\n=== %s (%s filas) ===" % (code, len(rows)))
        print("  fecha  proveedor                    net    flete_lin  flete_fact  tot_cfl   ueq   equiv   raw")
        for r in rows:
            ueq = f(r.get('x_studio_qty_units_equiv'))
            tg = f(r.get('x_studio_total_gross_with_freight'))
            equiv = tg / ueq if ueq else 0.0
            pn = r.get('x_studio_partner_id') or [0, '']
            name = pn[1] if isinstance(pn, (list, tuple)) and len(pn) > 1 else str(pn)
            print("  %-6s %-26s %7.0f %9.0f %10.0f %9.0f %5.0f %6.0f %6.0f" % (
                (r.get('x_studio_doc_date') or '')[5:], name[:26],
                f(r.get('x_studio_line_net')),
                f(r.get('x_studio_freight_alloc_net')),
                f(r.get('x_studio_freight_invoice_net')),
                tg, ueq, equiv, f(r.get('x_studio_raw_snapshot'))))


if __name__ == '__main__':
    main()
