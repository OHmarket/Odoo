"""DIAG read-only #3: facturas de compra de JUNIO 2026 (mes en curso).

Dimensiona el set de trabajo de Fase 1: cuantas facturas, estado, XML presente,
hueco de SKU, montos. Read-only, agregado server-side.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

JUN = [('move_type', '=', 'in_invoice'),
       ('invoice_date', '>=', '2026-06-01'),
       ('invoice_date', '<=', '2026-06-30')]


def grp(odoo, domain, gb, agg=('amount_total:sum',)):
    return odoo.execute('account.move', 'read_group', domain, list(agg), [gb], lazy=False)


def main() -> None:
    odoo = OdooReader()
    print(odoo, "\n")

    total = odoo.search_count('account.move', JUN)
    print(f"=== in_invoice JUNIO 2026: {total} facturas ===\n")

    print("--- por state ---")
    for r in grp(odoo, JUN, 'state'):
        print(f"  {str(r.get('state')):8} count={r['__count']:5} monto={r.get('amount_total',0):,.0f}")

    print("\n--- XML del DTE ---")
    con = odoo.search_count('account.move', JUN + [('l10n_cl_dte_file', '!=', False)])
    print(f"  con l10n_cl_dte_file: {con} | sin: {total - con}")

    print("\n--- acuse SII ---")
    for r in grp(odoo, JUN, 'l10n_cl_dte_acceptation_status'):
        print(f"  {str(r.get('l10n_cl_dte_acceptation_status')):14} count={r['__count']:5}")

    print("\n--- tipos doc ---")
    for r in grp(odoo, JUN, 'l10n_latam_document_type_id'):
        print(f"  {str(r.get('l10n_latam_document_type_id')):42} count={r['__count']:5}")

    print("\n--- proveedores top (por monto) ---")
    for r in grp(odoo, JUN, 'partner_id')[:12]:
        print(f"  {str(r.get('partner_id')):45} count={r['__count']:4} monto={r.get('amount_total',0):,.0f}")

    print("\n--- hueco SKU en lineas de junio ---")
    LB = [('move_id.move_type', '=', 'in_invoice'),
          ('move_id.invoice_date', '>=', '2026-06-01'),
          ('move_id.invoice_date', '<=', '2026-06-30'),
          ('display_type', '=', 'product')]
    tot = odoo.search_count('account.move.line', LB)
    sinp = odoo.search_count('account.move.line', LB + [('product_id', '=', False)])
    print(f"  lineas producto: {tot} | sin product_id: {sinp} ({(sinp/tot*100 if tot else 0):.1f}%)")


if __name__ == '__main__':
    main()
