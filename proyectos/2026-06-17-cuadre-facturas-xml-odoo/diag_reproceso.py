"""DIAG read-only: viabilidad del reproceso de vinculacion (línea -> product_id).

Pregunta: ¿se puede re-vincular product_id en líneas de facturas ya POSTED?
Señales read-only:
  - atributo readonly/states de product_id en account.move.line (fields_get)
  - universo del reproceso: líneas sin product_id en moves posted vs draft (junio)
La confirmacion DEFINITIVA es un test empírico de 1 registro (Server Action),
no se puede escribir desde el cliente read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402


def main() -> None:
    odoo = OdooReader()
    print(odoo, "\n")

    fg = odoo.fields_get('account.move.line', ['readonly', 'states', 'string', 'type'])
    pid = fg.get('product_id', {})
    print("=== account.move.line.product_id ===")
    print(f"  type     = {pid.get('type')}")
    print(f"  readonly = {pid.get('readonly')}")
    print(f"  states   = {pid.get('states')}")

    print("\n=== Universo reproceso: líneas producto sin product_id por state del move ===")
    base = [('display_type', '=', 'product'),
            ('product_id', '=', False),
            ('move_id.move_type', '=', 'in_invoice')]
    for st in ('posted', 'draft', 'cancel'):
        n = odoo.search_count('account.move.line', base + [('move_id.state', '=', st)])
        print(f"  {st:8}: {n}")

    print("\n=== Idem solo junio 2026 ===")
    jun = base + [('move_id.invoice_date', '>=', '2026-06-01'),
                  ('move_id.invoice_date', '<=', '2026-06-30')]
    for st in ('posted', 'draft'):
        n = odoo.search_count('account.move.line', jun + [('move_id.state', '=', st)])
        print(f"  {st:8}: {n}")


if __name__ == '__main__':
    main()
