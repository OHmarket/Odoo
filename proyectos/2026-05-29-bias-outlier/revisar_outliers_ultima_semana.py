#!/usr/bin/env python3
"""Revisar outliers en la ÚLTIMA semana disponible"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Buscar la ultima semana
last_week = odoo.search_read('x_hm_si_forecast',
    fields=['x_studio_week_start'],
    limit=1,
    order='x_studio_week_start desc')

if not last_week:
    print("No hay datos en x_hm_si_forecast")
    exit(1)

week_str = str(last_week[0]['x_studio_week_start'])
print(f"Analizando semana: {week_str}\n")

# Buscar outliers
cigarro_outliers = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', week_str),
        ('x_studio_bias_outlier', '=', True),
    ],
    fields=[
        'id',
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_bias_outlier_delta',
        'x_studio_bias_outlier_factor',
    ],
    limit=100)

# Filtrar cigarrillos
print("=" * 80)
print("OUTLIERS: CIGARRILLOS")
print("=" * 80)

cigarro_list = []
for r in cigarro_outliers:
    prod = r.get('x_studio_product_id')
    if isinstance(prod, (list, tuple)):
        prod_id = prod[0]
        prod_name = prod[1]
    else:
        prod_id = prod
        prod_name = str(prod)

    if 'cigarrillo' in prod_name.lower():
        cigarro_list.append({
            'product_id': prod_id,
            'product_name': prod_name[:70],
            'delta': r.get('x_studio_bias_outlier_delta'),
            'factor': r.get('x_studio_bias_outlier_factor'),
        })

print(f"\nTotal cigarrillos en outliers: {len(cigarro_list)} / {len(cigarro_outliers)} outliers")

if cigarro_list:
    print("\nDetalle (primeros 3):")
    for i, c in enumerate(cigarro_list[:3], 1):
        print(f"\n{i}. Product ID: {c['product_id']}")
        print(f"   Name: {c['product_name']}")
        print(f"   Delta: {c['delta']:+.1f}")
        print(f"   Factor: {c['factor']:.3f}")
else:
    print("\n✓ NO HAY CIGARRILLOS EN OUTLIERS (filtrados correctamente por quiebre)")
