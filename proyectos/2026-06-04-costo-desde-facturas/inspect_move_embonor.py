"""inspect_move_embonor.py — READ-ONLY.
Diagnostico: como viene el flete/recargo global en una factura de Embonor.
Mira cabecera (amount_*), todas las lineas, la diferencia total vs lineas, campos
candidatos de account.move y si hay XML adjunto del DTE.
"""
import sys
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def main():
    o = OdooReader()

    # 1) partner Embonor
    parts = o.search_read('res.partner', ['|', ('vat', 'like', '93281000'),
                                          ('name', 'ilike', 'embonor')],
                          fields=['id', 'name', 'vat'], limit=5)
    print("Partners Embonor:", [(p['id'], p['name'], p.get('vat')) for p in parts])
    if not parts:
        print("no encontrado"); return
    pids = [p['id'] for p in parts]

    # 2) campos candidatos en account.move (recargo/descuento/flete global)
    fg = o.fields_get('account.move')
    cand = sorted([k for k in fg if any(t in k.lower() for t in
                  ('global', 'recargo', 'descuento', 'discount', 'flete', 'freight', 'charge'))])
    print("\nCampos account.move candidatos:", cand)

    # 3) 2 facturas
    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', 'in', pids)],
                          fields=['id', 'name', 'invoice_date', 'l10n_latam_document_number',
                                  'amount_untaxed', 'amount_tax', 'amount_total'],
                          order='invoice_date desc', limit=2)
    for m in moves:
        print("\n" + "=" * 70)
        print("MOVE %s | %s | DTE %s | %s" % (m['id'], m['name'],
              m.get('l10n_latam_document_number'), m['invoice_date']))
        print("  amount_untaxed=%.0f  amount_tax=%.0f  amount_total=%.0f"
              % (f(m['amount_untaxed']), f(m['amount_tax']), f(m['amount_total'])))
        lines = o.search_read('account.move.line', [('move_id', '=', m['id'])],
                              fields=['display_type', 'name', 'quantity', 'price_subtotal',
                                      'price_total', 'product_id', 'account_id'])
        sum_prod_sub = 0.0
        sum_prod_tot = 0.0
        print("  --- lineas (invoice_line_ids) ---")
        for l in lines:
            dt = l.get('display_type') or 'entry'
            if dt not in ('product', 'line_section', 'line_note', False, 'entry'):
                continue
            nm = (l.get('name') or '')[:38]
            pid = (l.get('product_id') or [0, ''])
            pn = pid[1][:18] if isinstance(pid, (list, tuple)) and len(pid) > 1 else ''
            print("   [%-8s] %-38s qty=%6.1f sub=%9.0f tot=%9.0f %s" % (
                dt, nm, f(l.get('quantity')), f(l.get('price_subtotal')),
                f(l.get('price_total')), pn))
            if dt == 'product':
                sum_prod_sub += f(l.get('price_subtotal'))
                sum_prod_tot += f(l.get('price_total'))
        print("  SUMA lineas product: subtotal=%.0f  total=%.0f" % (sum_prod_sub, sum_prod_tot))
        print("  DIFERENCIA amount_total - Sum_total_lineas = %.0f" % (f(m['amount_total']) - sum_prod_tot))
        print("  DIFERENCIA amount_untaxed - Sum_sub_lineas = %.0f" % (f(m['amount_untaxed']) - sum_prod_sub))

        # 4) XML adjunto del DTE
        att = o.search_read('ir.attachment',
                            [('res_model', '=', 'account.move'), ('res_id', '=', m['id'])],
                            fields=['name', 'mimetype'], limit=10)
        print("  adjuntos:", [(a['name'], a.get('mimetype')) for a in att])


if __name__ == '__main__':
    main()
