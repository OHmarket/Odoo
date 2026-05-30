"""Verifica si el cron ya escribio filas con v12_COMBO_EXPLODE."""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def main():
    odoo = OdooReader()
    VERSION = 'OH_POS_WEEK_SKU_SIMPLE_v12_COMBO_EXPLODE'

    # 1. Conteo total v12
    n_v12 = odoo.search_count(
        'x_pos_week_sku_sale',
        [('x_studio_source_version', '=', VERSION)],
    )
    print(f"Filas con source_version=v12: {n_v12:,}")

    if n_v12 == 0:
        print("  -> v12 NUNCA escribio. El cron no esta corriendo el script.")

        # Diagnostico extra: que tiene la SA 1550?
        sa = odoo.search_read(
            'ir.actions.server',
            domain=[('id', '=', 1550)],
            fields=['id', 'name', 'state', 'model_id', 'code'],
            limit=1,
        )
        if sa:
            print(f"\n  SA 1550: name={sa[0]['name']!r}")
            print(f"  state={sa[0].get('state')}")
            code = sa[0].get('code', '') or ''
            print(f"  code length: {len(code)} chars")
            if code:
                first_lines = code.split('\n')[:5]
                for ln in first_lines:
                    print(f"    {ln}")
        else:
            print(f"  SA 1550: NO ENCONTRADA")

    else:
        # 2. Max y min week_start con v12
        max_v12 = odoo.search_read(
            'x_pos_week_sku_sale',
            [('x_studio_source_version', '=', VERSION)],
            fields=['x_studio_week_start'],
            order='x_studio_week_start desc',
            limit=1,
        )
        min_v12 = odoo.search_read(
            'x_pos_week_sku_sale',
            [('x_studio_source_version', '=', VERSION)],
            fields=['x_studio_week_start'],
            order='x_studio_week_start asc',
            limit=1,
        )
        print(f"  Rango v12: {min_v12[0]['x_studio_week_start']} -> {max_v12[0]['x_studio_week_start']}")

        # 3. Progreso vs target (2023-05-29 -> 2026-05-24)
        target_start = date(2023, 5, 29)
        target_end = date(2026, 5, 24)
        last = date.fromisoformat(max_v12[0]['x_studio_week_start'])
        done_days = (last - target_start).days + 7
        total_days = (target_end - target_start).days + 7
        pct = done_days / total_days * 100
        print(f"  Progreso: {pct:.1f}%  ({done_days // 7}/{total_days // 7} semanas)")


if __name__ == "__main__":
    main()
