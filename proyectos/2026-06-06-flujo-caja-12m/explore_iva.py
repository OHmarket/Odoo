# -*- coding: utf-8 -*-
"""
explore_iva.py - Diagnostico READ-ONLY de la estructura tributaria para el
calculo de IVA del flujo de caja 12m.

Objetivo (Fase 1 - validar estado actual, NO escribe nada):
  1. Catalogo de impuestos (account.tax): que IVA 19%, exentos, ILA existen.
  2. Ventas ultimos 3 meses cerrados: afecto vs exento (la proporcion 80/20 real).
  3. Compras ultimos 3 meses: credito IVA 19% y como se reparte por cuenta
     (mercaderia reventa vs gasto/overhead = uso comun).

Corre desde la raiz del repo:  python proyectos/2026-06-06-flujo-caja-12m/explore_iva.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.odoo_xmlrpc import OdooReader


def months_window(n_full_months: int = 3):
    """Devuelve (start, end) de los n meses calendario cerrados anteriores a hoy."""
    today = date.today()
    first_this_month = today.replace(day=1)
    # end = ultimo dia del mes anterior
    end = first_this_month.replace(day=1)
    # retroceder n meses para el start
    y, m = first_this_month.year, first_this_month.month
    for _ in range(n_full_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    start = date(y, m, 1)
    # end exclusivo = primer dia del mes actual
    return start.isoformat(), end.isoformat()


def main():
    odoo = OdooReader()
    print(odoo)

    start, end = months_window(3)
    print(f"\n=== Ventana de analisis: {start} (incl) .. {end} (excl) ===")

    # ------------------------------------------------------------------
    # 1. CATALOGO DE IMPUESTOS
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("1. CATALOGO account.tax (amount_type=percent o group)")
    print("=" * 70)
    taxes = odoo.search_read(
        'account.tax',
        domain=[],
        fields=['name', 'amount', 'amount_type', 'type_tax_use',
                'price_include', 'active'],
        order='type_tax_use,amount desc',
    )
    for t in taxes:
        print(f"  [{t['id']:>4}] use={t['type_tax_use']:<8} "
              f"amt={t['amount']:>7} type={t['amount_type']:<8} "
              f"pinc={str(t['price_include']):<5} act={str(t['active']):<5} "
              f"| {t['name']}")

    # ------------------------------------------------------------------
    # 2. VENTAS: afecto vs exento (debito IVA por tax)
    #    Lineas de impuesto (tax_line_id != False) en movimientos de venta.
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("2a. DEBITO IVA ventas - lineas de impuesto por tax_line_id")
    print("=" * 70)
    try:
        g = odoo.execute(
            'account.move.line', 'read_group',
            [('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ['out_invoice', 'out_receipt', 'out_refund']),
             ('date', '>=', start), ('date', '<', end),
             ('tax_line_id', '!=', False)],
            ['balance:sum'], ['tax_line_id'],
            lazy=False,
        )
        for row in g:
            print(f"  {row.get('tax_line_id')}: balance_sum={row.get('balance'):,.0f} "
                  f"(n={row.get('__count')})")
    except Exception as e:
        print(f"  ERROR read_group debito: {e}")

    print("\n2b. VENTAS base por impuesto aplicado (tax_ids) - mide afecto vs exento")
    try:
        g = odoo.execute(
            'account.move.line', 'read_group',
            [('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ['out_invoice', 'out_receipt', 'out_refund']),
             ('date', '>=', start), ('date', '<', end),
             ('tax_line_id', '=', False),
             ('display_type', '=', 'product')],
            ['balance:sum'], ['tax_ids'],
            lazy=False,
        )
        for row in g:
            print(f"  tax_ids={row.get('tax_ids')}: base_sum={row.get('balance'):,.0f} "
                  f"(n={row.get('__count')})")
    except Exception as e:
        print(f"  ERROR read_group ventas base: {e}")

    # ------------------------------------------------------------------
    # 2c. VENTAS POS via asientos 'entry' en diario de venta
    # ------------------------------------------------------------------
    print("\n2c. VENTAS 'entry' (POS) en diarios tipo sale - debito por tax")
    try:
        g = odoo.execute(
            'account.move.line', 'read_group',
            [('parent_state', '=', 'posted'),
             ('move_id.move_type', '=', 'entry'),
             ('journal_id.type', '=', 'sale'),
             ('date', '>=', start), ('date', '<', end),
             ('tax_line_id', '!=', False)],
            ['balance:sum'], ['tax_line_id'],
            lazy=False,
        )
        for row in g:
            print(f"  {row.get('tax_line_id')}: balance_sum={row.get('balance'):,.0f} "
                  f"(n={row.get('__count')})")
    except Exception as e:
        print(f"  ERROR read_group POS entry: {e}")

    # ------------------------------------------------------------------
    # 3. COMPRAS: credito IVA por tax
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("3a. CREDITO compras - lineas de impuesto por tax_line_id")
    print("=" * 70)
    try:
        g = odoo.execute(
            'account.move.line', 'read_group',
            [('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ['in_invoice', 'in_refund']),
             ('date', '>=', start), ('date', '<', end),
             ('tax_line_id', '!=', False)],
            ['balance:sum'], ['tax_line_id'],
            lazy=False,
        )
        for row in g:
            print(f"  {row.get('tax_line_id')}: balance_sum={row.get('balance'):,.0f} "
                  f"(n={row.get('__count')})")
    except Exception as e:
        print(f"  ERROR read_group credito: {e}")

    # 3b. Compras base por cuenta contable (mercaderia vs gasto/uso comun)
    print("\n3b. COMPRAS base por account_id (reventa vs overhead) - top 25")
    try:
        g = odoo.execute(
            'account.move.line', 'read_group',
            [('parent_state', '=', 'posted'),
             ('move_id.move_type', 'in', ['in_invoice', 'in_refund']),
             ('date', '>=', start), ('date', '<', end),
             ('tax_line_id', '=', False),
             ('display_type', '=', 'product')],
            ['balance:sum'], ['account_id'],
            lazy=False,
        )
        g = sorted(g, key=lambda r: abs(r.get('balance') or 0), reverse=True)[:25]
        for row in g:
            print(f"  {row.get('account_id')}: base_sum={row.get('balance'):,.0f} "
                  f"(n={row.get('__count')})")
    except Exception as e:
        print(f"  ERROR read_group compras base: {e}")


if __name__ == '__main__':
    main()
