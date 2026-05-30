#!/usr/bin/env python3
"""Debug: qué stock_balance existe para el cigarrillo en mayo 2026"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

CIGARRO_ID = 17604

print("=" * 80)
print(f"stock_balance para cigarrillo (product_id={CIGARRO_ID})")
print("=" * 80)

sb_may = odoo.search_read('x_stock_balance_daily',
    domain=[
        ('x_studio_product_id', '=', CIGARRO_ID),
        ('x_studio_date', '>=', '2026-05-01'),
        ('x_studio_date', '<=', '2026-05-31'),
    ],
    fields=[
        'x_studio_date',
        'x_studio_team_id',
        'x_studio_qty_balance',
        'x_studio_stockout',
    ],
    limit=50)

print(f"\nRegistros en mayo 2026: {len(sb_may)}")
if sb_may:
    for r in sb_may[:10]:
        team_val = r.get('x_studio_team_id')
        if isinstance(team_val, (list, tuple)):
            team_name = team_val[1]
        else:
            team_name = str(team_val)

        print(f"  {r['x_studio_date']} team={team_name} qty={r.get('x_studio_qty_balance')} so={r.get('x_studio_stockout')}")
else:
    print("  (ninguno)")

# Buscar en abril 2026
print("\n" + "=" * 80)
print("stock_balance para cigarrillo en ABRIL 2026")
print("=" * 80)

sb_apr = odoo.search_read('x_stock_balance_daily',
    domain=[
        ('x_studio_product_id', '=', CIGARRO_ID),
        ('x_studio_date', '>=', '2026-04-01'),
        ('x_studio_date', '<=', '2026-04-30'),
    ],
    fields=['x_studio_date', 'x_studio_team_id', 'x_studio_qty_balance'],
    limit=50)

print(f"Registros en abril 2026: {len(sb_apr)}")
if sb_apr:
    for r in sb_apr[:5]:
        team_val = r.get('x_studio_team_id')
        if isinstance(team_val, (list, tuple)):
            team_name = team_val[1]
        else:
            team_name = str(team_val)
        print(f"  {r['x_studio_date']} team={team_name} qty={r.get('x_studio_qty_balance')}")

print("\n" + "=" * 80)
print("DIAGNOSTICO")
print("=" * 80)
if len(sb_may) == 0:
    print("PROBLEMA: No hay stock_balance ACTUAL para este cigarrillo")
    print("  -> bias-outlier busca quiebre en mayo 2026, NO encuentra nada")
    print("  -> Asume que no hay quiebre -> cigarrillo pasa y se marca outlier")
    print("\nRAIZ: OH Quiebre de Stock NO esta escribiendo en stock_balance para mayo 2026")
