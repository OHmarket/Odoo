# -*- coding: utf-8 -*-
"""
explore_iva3.py - READ-ONLY. Mide el restock% estructural en ventana larga.

Por mes (ene-2025 .. may-2026):
  - venta_afecta  = debito IVA / 0.19
  - compras_reventa_recup = base cuenta 210230 con IVA recuperable (id2/22)
  - credito_recup_total   = lineas de impuesto id2/22
  - overhead_credit = credito_recup_total - 0.19*compras_reventa_recup
  - restock% = compras_reventa_recup / venta_afecta

El promedio en ventana larga ~ restock estructural (COGS/venta) = 1 - margen afecto.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.odoo_xmlrpc import OdooReader

IVA_VENTA = 1
IVA_RECUP = [2, 22]
ACC_MERCH = 82  # 210230 Facturas por Recibir

# meses ene-2025 .. may-2026
MONTHS = []
for y in (2025, 2026):
    for m in range(1, 13):
        if y == 2026 and m > 5:
            break
        start = f"{y}-{m:02d}-01"
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = f"{ny}-{nm:02d}-01"
        MONTHS.append((start, end))


def tax_line_sum(odoo, move_types, tax_ids, start, end):
    g = odoo.execute('account.move.line', 'read_group',
                     [('parent_state', '=', 'posted'),
                      ('move_id.move_type', 'in', move_types),
                      ('date', '>=', start), ('date', '<', end),
                      ('tax_line_id', 'in', tax_ids)],
                     ['balance:sum'], [], lazy=False)
    return abs(g[0]['balance']) if g and g[0].get('balance') else 0.0


def merch_base(odoo, start, end):
    g = odoo.execute('account.move.line', 'read_group',
                     [('parent_state', '=', 'posted'),
                      ('move_id.move_type', 'in', ['in_invoice', 'in_refund']),
                      ('date', '>=', start), ('date', '<', end),
                      ('tax_line_id', '=', False),
                      ('display_type', '=', 'product'),
                      ('account_id', '=', ACC_MERCH),
                      ('tax_ids', 'in', IVA_RECUP)],
                     ['balance:sum'], [], lazy=False)
    return abs(g[0]['balance']) if g and g[0].get('balance') else 0.0


def main():
    odoo = OdooReader()
    print(odoo)
    print(f"\n{'Mes':<9}{'VentaAfec':>14}{'ComprReven':>14}{'restock%':>10}"
          f"{'CredTotal':>13}{'OverhCred':>12}{'IVApagar':>13}")

    sums = {'va': 0, 'cr': 0, 'ct': 0, 'oh': 0}
    for start, end in MONTHS:
        deb = tax_line_sum(odoo, ['out_invoice', 'out_receipt', 'out_refund'],
                           [IVA_VENTA], start, end)
        va = deb / 0.19 if deb else 0.0
        cr = merch_base(odoo, start, end)
        ct = tax_line_sum(odoo, ['in_invoice', 'in_refund'], IVA_RECUP, start, end)
        oh = ct - 0.19 * cr
        restock = (cr / va) if va else 0.0
        iva_pagar = deb - ct
        sums['va'] += va; sums['cr'] += cr; sums['ct'] += ct; sums['oh'] += oh
        print(f"{start[:7]:<9}{va:>14,.0f}{cr:>14,.0f}{restock:>9.1%}"
              f"{ct:>13,.0f}{oh:>12,.0f}{iva_pagar:>13,.0f}")

    print("-" * 85)
    avg_restock = sums['cr'] / sums['va'] if sums['va'] else 0
    avg_oh_pct = sums['oh'] / sums['va'] if sums['va'] else 0
    print(f"{'TOTAL':<9}{sums['va']:>14,.0f}{sums['cr']:>14,.0f}{avg_restock:>9.1%}"
          f"{sums['ct']:>13,.0f}{sums['oh']:>12,.0f}")
    print(f"\nrestock% estructural (compras reventa / venta afecta) = {avg_restock:.1%}")
    print(f"  -> margen bruto afecto implicito              = {1-avg_restock:.1%}")
    print(f"overhead credit como % de venta afecta          = {avg_oh_pct:.2%}")
    print(f"\nIVA teorico en regimen = 0.19*VA*(1-restock%) - overhead_credit")
    print(f"  = 0.19*VA*{1-avg_restock:.3f} - {avg_oh_pct:.4f}*VA = "
          f"{0.19*(1-avg_restock) - avg_oh_pct:.2%} de la venta afecta")


if __name__ == '__main__':
    main()
