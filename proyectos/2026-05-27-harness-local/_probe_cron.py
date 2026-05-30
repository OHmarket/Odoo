"""Busca el ir.cron del SA 'OH Analisis Ventas SKU'."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def main():
    odoo = OdooReader()

    # 1. Buscar SA por name
    sas = odoo.search_read(
        'ir.actions.server',
        domain=[('name', 'ilike', 'POS Semana SKU')],
        fields=['id', 'name', 'state', 'model_id'],
    )
    if not sas:
        sas = odoo.search_read(
            'ir.actions.server',
            domain=[('name', 'ilike', 'Analisis Ventas SKU')],
            fields=['id', 'name', 'state', 'model_id'],
        )
    print(f"Server Actions encontradas: {len(sas)}")
    for sa in sas:
        print(f"  id={sa['id']} name={sa['name']!r} state={sa.get('state')}")
    sa_ids = [sa['id'] for sa in sas]

    # 2. Buscar ir.cron asociado
    if sa_ids:
        crons = odoo.search_read(
            'ir.cron',
            domain=[('ir_actions_server_id', 'in', sa_ids)],
            fields=['id', 'name', 'ir_actions_server_id', 'active',
                    'interval_number', 'interval_type',
                    'nextcall', 'lastcall', 'numbercall'],
        )
    else:
        crons = []
    print(f"\nCrons asociados: {len(crons)}")
    for c in crons:
        print(f"  id={c['id']} name={c['name']!r}")
        print(f"    active={c['active']} interval={c['interval_number']} {c['interval_type']}")
        print(f"    nextcall={c.get('nextcall')} lastcall={c.get('lastcall')}")
        print(f"    numbercall={c.get('numbercall')}  (-1 = ilimitado)")

    # 3. Context del cron (campo code/eval_context si existe)
    if crons:
        # ir.cron en Odoo 17 a veces tiene campo 'code' o 'env.context'
        cron_full = odoo.search_read(
            'ir.cron',
            domain=[('id', 'in', [c['id'] for c in crons])],
            fields=[],  # todos los campos
        )
        for c in cron_full:
            print(f"\n  Cron {c['id']} full fields:")
            for k, v in c.items():
                if v not in (False, '', 0, None):
                    print(f"    {k}: {str(v)[:200]}")


if __name__ == "__main__":
    main()
