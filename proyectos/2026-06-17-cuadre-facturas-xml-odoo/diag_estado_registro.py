"""DIAG read-only #2: salud del registro de facturas de compra HOY.

Mide el estado real del 'registro' que Marco quiere cuadrar:
  - distribucion por state (draft/posted/cancel) y monto
  - estado SII (l10n_cl_dte_status) y acuse (l10n_cl_dte_acceptation_status)
  - cuantas traen XML del DTE (l10n_cl_dte_file)
  - hueco de vinculacion: lineas de producto sin product_id

Todo con read_group / search_count (agregado server-side, barato). Solo lectura.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

IN = [('move_type', '=', 'in_invoice')]


def grp(odoo, model, domain, gb, agg=('amount_total:sum',)):
    return odoo.execute(model, 'read_group', domain, list(agg) + [], [gb], lazy=False)


def main() -> None:
    odoo = OdooReader()
    print(odoo, "\n")

    print("=== in_invoice por state (count + monto) ===")
    for r in grp(odoo, 'account.move', IN, 'state'):
        print(f"  {str(r.get('state')):10} count={r['__count']:7} monto={r.get('amount_total', 0):,.0f}")

    print("\n=== in_invoice por l10n_cl_dte_status (estado SII) ===")
    for r in grp(odoo, 'account.move', IN, 'l10n_cl_dte_status'):
        print(f"  {str(r.get('l10n_cl_dte_status')):14} count={r['__count']:7}")

    print("\n=== in_invoice por l10n_cl_dte_acceptation_status (acuse) ===")
    for r in grp(odoo, 'account.move', IN, 'l10n_cl_dte_acceptation_status'):
        print(f"  {str(r.get('l10n_cl_dte_acceptation_status')):16} count={r['__count']:7}")

    print("\n=== in_invoice por l10n_cl_claim (reclamo) ===")
    for r in grp(odoo, 'account.move', IN, 'l10n_cl_claim'):
        print(f"  {str(r.get('l10n_cl_claim')):14} count={r['__count']:7}")

    print("\n=== XML del DTE presente? ===")
    con_xml = odoo.search_count('account.move', IN + [('l10n_cl_dte_file', '!=', False)])
    sin_xml = odoo.search_count('account.move', IN + [('l10n_cl_dte_file', '=', False)])
    print(f"  con l10n_cl_dte_file: {con_xml:7} | sin: {sin_xml:7}")

    print("\n=== Tipos de documento (in_invoice) ===")
    for r in grp(odoo, 'account.move', IN, 'l10n_latam_document_type_id'):
        print(f"  {str(r.get('l10n_latam_document_type_id')):40} count={r['__count']:7}")

    print("\n=== Hueco SKU: lineas de producto sin product_id ===")
    LBASE = [('move_id.move_type', '=', 'in_invoice'), ('display_type', '=', 'product')]
    tot_lin = odoo.search_count('account.move.line', LBASE)
    sin_pid = odoo.search_count('account.move.line', LBASE + [('product_id', '=', False)])
    print(f"  lineas producto: {tot_lin:8} | sin product_id: {sin_pid:8} ({(sin_pid/tot_lin*100 if tot_lin else 0):.1f}%)")

    print("\n=== Foco 2026: in_invoice con invoice_date >= 2026-01-01 ===")
    IN26 = IN + [('invoice_date', '>=', '2026-01-01')]
    print(f"  total 2026: {odoo.search_count('account.move', IN26)}")
    for r in grp(odoo, 'account.move', IN26, 'state'):
        print(f"    {str(r.get('state')):10} count={r['__count']:7} monto={r.get('amount_total', 0):,.0f}")


if __name__ == '__main__':
    main()
