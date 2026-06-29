"""inspect_caso.py — READ-ONLY. Filas crudas de codigos sospechosos para confirmar UoM."""
import sys
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_vendor_bill_cost_lin'
CODES = ['870402', '6244', '2118', '450684']  # REDBULL355, GRAN120, AGUA VITAL, ROYAL GUARD


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def main():
    o = OdooReader()
    flds = ['x_studio_doc_date', 'x_studio_partner_id', 'x_studio_qty_invoice',
            'x_studio_units_per_uom', 'x_studio_qty_units_equiv', 'x_studio_line_net',
            'x_studio_unit_net', 'x_studio_unit_gross_no_freight',
            'x_studio_std_snapshot', 'x_studio_raw_snapshot']
    for code in CODES:
        rows = o.search_read(MODEL, [('x_studio_default_code', '=', code)],
                             fields=flds, order='x_studio_doc_date asc, id asc')
        print("\n=== %s (%s filas) ===" % (code, len(rows)))
        print("  fecha      prov  qty  ratio  ueq     net      net/ueq  unit_net  bruto/u   std    raw")
        for r in rows:
            qty = f(r.get('x_studio_qty_invoice'))
            ratio = f(r.get('x_studio_units_per_uom'))
            ueq = f(r.get('x_studio_qty_units_equiv'))
            net = f(r.get('x_studio_line_net'))
            nu = net / ueq if ueq else 0.0
            print("  %-10s %-4s %4.0f %5.1f %6.0f %9.0f %8.1f %9.1f %8.1f %6.0f %6.0f" % (
                (r.get('x_studio_doc_date') or '')[5:],
                str((r.get('x_studio_partner_id') or [0])[0])[:4],
                qty, ratio, ueq, net, nu,
                f(r.get('x_studio_unit_net')),
                f(r.get('x_studio_unit_gross_no_freight')),
                f(r.get('x_studio_std_snapshot')),
                f(r.get('x_studio_raw_snapshot'))))


if __name__ == '__main__':
    main()
