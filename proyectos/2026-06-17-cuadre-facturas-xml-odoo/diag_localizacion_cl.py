"""DIAG read-only: estructura de la localizacion chilena (l10n_cl) en Odoo 17.

Objetivo Fase 0: confirmar DONDE viven folio, RUT emisor, tipo de documento,
estado SII y el XML del DTE sobre account.move, para disenar el cuadre
XML <-> registro Odoo. No asume campos: los lee de ir.model.fields / fields_get.

Solo lectura. Barato: fields_get + search_count + search_read con limit chico.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402


def main() -> None:
    odoo = OdooReader()
    print(odoo, "\n")

    # 1) Modulos de localizacion chilena instalados
    mods = odoo.search_read(
        'ir.module.module',
        domain=[('name', 'like', 'l10n_cl'), ('state', '=', 'installed')],
        fields=['name', 'shortdesc'],
        order='name',
    )
    print("=== Modulos l10n_cl instalados ===")
    for m in mods:
        print(f"  {m['name']:35} {m['shortdesc']}")

    # 2) Campos de account.move relevantes (l10n / dte / sii / latam / folio)
    fg = odoo.fields_get('account.move')
    keys = ('l10n', 'dte', 'sii', 'latam', 'folio', 'edi')
    print("\n=== account.move: campos localizacion ===")
    for fname in sorted(fg):
        if any(k in fname.lower() for k in keys):
            f = fg[fname]
            rel = f.get('relation', '')
            print(f"  {fname:38} {f.get('type',''):10} {rel:25} | {f.get('string','')}")

    # 3) Conteo de facturas de compra y su estado
    print("\n=== account.move (in_invoice) ===")
    total_in = odoo.search_count('account.move', [('move_type', '=', 'in_invoice')])
    print(f"  total in_invoice: {total_in}")

    # 4) Muestra de 3 facturas de compra: ver valores reales de los campos clave
    sample_fields = [f for f in (
        'name', 'move_type', 'state', 'partner_id', 'amount_total', 'amount_untaxed',
        'amount_tax', 'l10n_latam_document_type_id', 'l10n_latam_document_number',
        'l10n_cl_sii_send_state', 'l10n_cl_dte_status', 'l10n_cl_dte_acceptation_status',
        'edi_state', 'invoice_date',
    ) if f in fg]
    sample = odoo.search_read(
        'account.move',
        domain=[('move_type', '=', 'in_invoice')],
        fields=sample_fields,
        limit=3,
        order='id desc',
    )
    print("\n=== Muestra 3 facturas de compra (campos que existen) ===")
    print("  campos pedidos presentes:", sample_fields)
    for r in sample:
        print("  ---")
        for k in sample_fields:
            print(f"    {k:34} = {r.get(k)}")

    # 5) ir.attachment DTE xml (donde vive el XML del DTE)
    print("\n=== ir.attachment XML/DTE ===")
    n_dte = odoo.search_count('ir.attachment', [('name', 'like', 'DTE')])
    n_xml = odoo.search_count('ir.attachment', [('name', 'like', '.xml')])
    print(f"  attachments name~DTE: {n_dte} | name~.xml: {n_xml}")

    # 6) Existe modelo de registro de compras / RCV?
    for model in ('l10n_cl.rcv', 'l10n_cl.daily.book', 'account.move'):
        try:
            cnt = odoo.search_count(model, [])
            print(f"  modelo {model:25} accesible, count={cnt}")
        except Exception as e:  # noqa: BLE001
            print(f"  modelo {model:25} NO accesible: {type(e).__name__}")


if __name__ == '__main__':
    main()
