# -*- coding: utf-8 -*-
"""
explore_iva2.py - Diagnostico READ-ONLY parte 2.

Resuelve:
  1. Tabla MENSUAL: debito IVA venta, credito recup (id2+22), no-recup (id17), neto.
  2. En que CUENTAS cae el IVA recuperable (id2/22) vs el No-Recup (id17)
     -> revela si el No-Recup es proporcionalidad de uso comun o gasto rechazado.
  3. Confirma que las ventas exentas (sin impuesto) son cigarrillos.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.odoo_xmlrpc import OdooReader

IVA_VENTA = 1
IVA_RECUP = [2, 22]          # IVA 19% Compra (2024) + (FC)
IVA_NO_RECUP = 17            # IVA Compra 19% No Recup.

MONTHS = [('2026-03-01', '2026-04-01'),
          ('2026-04-01', '2026-05-01'),
          ('2026-05-01', '2026-06-01')]


def sum_tax_line(odoo, move_types, tax_ids, start, end, journal_type=None):
    dom = [('parent_state', '=', 'posted'),
           ('move_id.move_type', 'in', move_types),
           ('date', '>=', start), ('date', '<', end),
           ('tax_line_id', 'in', tax_ids if isinstance(tax_ids, list) else [tax_ids])]
    if journal_type:
        dom.append(('journal_id.type', '=', journal_type))
    g = odoo.execute('account.move.line', 'read_group', dom,
                     ['balance:sum'], [], lazy=False)
    if g and g[0].get('balance') is not None:
        return g[0]['balance']
    return 0.0


def main():
    odoo = OdooReader()
    print(odoo)

    # ------------------------------------------------------------------
    # 1. TABLA MENSUAL
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("1. IVA MENSUAL (signo: debito venta es negativo; credito compra positivo)")
    print("=" * 78)
    print(f"{'Mes':<10} {'Debito':>14} {'CredRecup':>14} {'NoRecup':>13} "
          f"{'IVA a pagar':>13} {'cred/deb':>9}")
    for start, end in MONTHS:
        deb = sum_tax_line(odoo, ['out_invoice', 'out_receipt', 'out_refund'],
                           [IVA_VENTA], start, end)
        cred = sum_tax_line(odoo, ['in_invoice', 'in_refund'], IVA_RECUP, start, end)
        norec = sum_tax_line(odoo, ['in_invoice', 'in_refund'], [IVA_NO_RECUP],
                             start, end)
        debito = abs(deb)
        credito = abs(cred)
        a_pagar = debito - credito
        ratio = (credito / debito) if debito else 0
        print(f"{start[:7]:<10} {debito:>14,.0f} {credito:>14,.0f} {norec:>13,.0f} "
              f"{a_pagar:>13,.0f} {ratio:>8.1%}")

    # ------------------------------------------------------------------
    # 2. EN QUE CUENTAS CAE CADA IVA (base de las lineas con cada tax)
    #    Ventana completa mar-may.
    # ------------------------------------------------------------------
    full_start, full_end = '2026-03-01', '2026-06-01'

    def base_by_account(tax_ids, label):
        print(f"\n--- Base de compra con tax {label} por cuenta (top 20) ---")
        dom = [('parent_state', '=', 'posted'),
               ('move_id.move_type', 'in', ['in_invoice', 'in_refund']),
               ('date', '>=', full_start), ('date', '<', full_end),
               ('tax_line_id', '=', False),
               ('display_type', '=', 'product'),
               ('tax_ids', 'in', tax_ids if isinstance(tax_ids, list) else [tax_ids])]
        g = odoo.execute('account.move.line', 'read_group', dom,
                         ['balance:sum'], ['account_id'], lazy=False)
        g = sorted(g, key=lambda r: abs(r.get('balance') or 0), reverse=True)[:20]
        tot = 0.0
        for row in g:
            bal = row.get('balance') or 0
            tot += bal
            print(f"  {str(row.get('account_id')):<48} base={bal:>14,.0f} "
                  f"iva19%={abs(bal)*0.19:>12,.0f}")
        print(f"  TOTAL mostrado base={tot:,.0f}  iva19%={abs(tot)*0.19:,.0f}")

    print("\n" + "=" * 78)
    print("2. DESTINO CONTABLE DEL IVA DE COMPRA")
    print("=" * 78)
    base_by_account(IVA_RECUP, 'RECUPERABLE (id2/22)')
    base_by_account([IVA_NO_RECUP], 'NO-RECUP (id17)')

    # ------------------------------------------------------------------
    # 3. CONFIRMAR QUE EXENTO = CIGARRILLOS
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("3. VENTAS EXENTAS (tax_ids=False) - top productos")
    print("=" * 78)
    try:
        g = odoo.execute(
            'account.move.line', 'read_group',
            [('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ['out_invoice', 'out_receipt', 'out_refund']),
             ('date', '>=', full_start), ('date', '<', full_end),
             ('tax_line_id', '=', False),
             ('display_type', '=', 'product'),
             ('tax_ids', '=', False)],
            ['balance:sum'], ['product_id'], lazy=False,
        )
        g = sorted(g, key=lambda r: abs(r.get('balance') or 0), reverse=True)[:15]
        for row in g:
            print(f"  {str(row.get('product_id')):<55} base={row.get('balance'):>13,.0f}")
    except Exception as e:
        print(f"  ERROR: {e}")


if __name__ == '__main__':
    main()
