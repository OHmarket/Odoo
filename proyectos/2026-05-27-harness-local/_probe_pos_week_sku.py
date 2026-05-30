"""Sondeo estado x_pos_week_sku_sale - max week, conteos por semana reciente."""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def main():
    odoo = OdooReader()

    # Max week_start (1 query)
    print("Max week_start...")
    most_recent = odoo.search_read(
        'x_pos_week_sku_sale', [],
        fields=['x_studio_week_start'],
        order='x_studio_week_start desc',
        limit=1,
    )
    print(f"  {most_recent[0]['x_studio_week_start']}")

    # Min week_start (1 query)
    print("Min week_start...")
    oldest = odoo.search_read(
        'x_pos_week_sku_sale', [],
        fields=['x_studio_week_start'],
        order='x_studio_week_start asc',
        limit=1,
    )
    print(f"  {oldest[0]['x_studio_week_start']}")

    # Conteo por las ultimas 10 semanas (10 search_count chicos)
    print("\nConteo por semana (ultimas 10):")
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    for i in range(10, -1, -1):
        wk = monday - timedelta(weeks=i)
        n = odoo.search_count(
            'x_pos_week_sku_sale',
            [('x_studio_week_start', '=', wk.strftime('%Y-%m-%d'))],
        )
        marker = '  <-- hoy' if wk == monday else ''
        print(f"  {wk}: {n:>6,} filas{marker}")

    # Conteo por VERSION_ID en la tabla (qué versiones del script han escrito)
    # No tiene campo VERSION_ID directo. Buscamos via display_name.
    # Hago search_read limit=1 por cada version_id sospechosa
    print("\nVersiones presentes (sample por display_name):")
    for v in ['v11_OH_CALENDAR_STANDARD', 'v12_COMBO_EXPLODE']:
        n = odoo.search_count(
            'x_pos_week_sku_sale',
            [('x_name', 'ilike', v)],
        )
        print(f"  {v}: {n:,} filas")


if __name__ == "__main__":
    main()
