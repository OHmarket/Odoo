# -*- coding: utf-8 -*-
"""
explore_margin.py - READ-ONLY. Zanja el margen via stock.valuation.layer (COGS real).

Identidad: capa de valuacion negativa (salida) = COGS al costo.
  margen_blended = 1 - COGS_total / venta_neta_total
Compara contra el 25% que dice Marco y el 43,4% afecto que dio el restock%.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.odoo_xmlrpc import OdooReader

IVA_VENTA = 1
MONTHS = [('2026-03-01', '2026-04-01'),
          ('2026-04-01', '2026-05-01'),
          ('2026-05-01', '2026-06-01')]


def main():
    odoo = OdooReader()
    print(odoo)

    # 0. existe el modelo y tiene datos?
    try:
        n = odoo.search_count('stock.valuation.layer', [])
        print(f"\nstock.valuation.layer total registros: {n:,}")
    except Exception as e:
        print(f"NO existe stock.valuation.layer: {e}")
        return

    f = odoo.fields_get('stock.valuation.layer',
                        ['value', 'quantity', 'product_id', 'create_date',
                         'stock_move_id', 'description'])
    print("campos:", list(f.keys()))

    # fecha: usar create_date (no hay 'date' siempre)
    date_field = 'create_date'

    print("\n" + "=" * 70)
    print("COGS (capas negativas) vs VENTA NETA por mes")
    print("=" * 70)
    print(f"{'Mes':<9}{'COGS(salidas)':>16}{'Entradas':>16}{'VentaNeta':>16}{'MargenBlend':>12}")

    for start, end in MONTHS:
        # COGS: suma de value de capas con value<0 (salidas) en el mes
        g_out = odoo.execute('stock.valuation.layer', 'read_group',
                             [(date_field, '>=', start), (date_field, '<', end),
                              ('value', '<', 0)],
                             ['value:sum'], [], lazy=False)
        cogs = abs(g_out[0]['value']) if g_out and g_out[0].get('value') else 0.0

        g_in = odoo.execute('stock.valuation.layer', 'read_group',
                            [(date_field, '>=', start), (date_field, '<', end),
                             ('value', '>', 0)],
                            ['value:sum'], [], lazy=False)
        entradas = g_in[0]['value'] if g_in and g_in[0].get('value') else 0.0

        # venta neta total = afecta (debito/0.19) + exenta (sin tax)
        gd = odoo.execute('account.move.line', 'read_group',
                          [('parent_state', '=', 'posted'),
                           ('move_id.move_type', 'in', ['out_invoice', 'out_receipt', 'out_refund']),
                           ('date', '>=', start), ('date', '<', end),
                           ('tax_line_id', '=', IVA_VENTA)],
                          ['balance:sum'], [], lazy=False)
        deb = abs(gd[0]['balance']) if gd and gd[0].get('balance') else 0.0
        va = deb / 0.19

        ge = odoo.execute('account.move.line', 'read_group',
                          [('parent_state', '=', 'posted'),
                           ('move_id.move_type', 'in', ['out_invoice', 'out_receipt', 'out_refund']),
                           ('date', '>=', start), ('date', '<', end),
                           ('tax_line_id', '=', False),
                           ('display_type', '=', 'product'),
                           ('tax_ids', '=', False)],
                          ['balance:sum'], [], lazy=False)
        ve = abs(ge[0]['balance']) if ge and ge[0].get('balance') else 0.0
        venta_neta = va + ve

        margen = (1 - cogs / venta_neta) if venta_neta else 0
        print(f"{start[:7]:<9}{cogs:>16,.0f}{entradas:>16,.0f}{venta_neta:>16,.0f}{margen:>11.1%}")

    # inventario actual total
    g_all = odoo.execute('stock.valuation.layer', 'read_group', [],
                         ['value:sum'], [], lazy=False)
    inv_now = g_all[0]['value'] if g_all and g_all[0].get('value') else 0.0
    print(f"\nValor inventario actual (suma todas las capas): {inv_now:,.0f}")


if __name__ == '__main__':
    main()
