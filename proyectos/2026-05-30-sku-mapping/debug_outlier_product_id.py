#!/usr/bin/env python3
"""Debug: qué se guarda realmente en x_studio_product_id para cigarrillos outlier"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Buscar TODOS los outliers de la semana
outliers_all = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', '2026-05-25'),
        ('x_studio_bias_outlier', '=', True),
    ],
    fields=[
        'id',
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_bias_outlier_factor',
    ],
    limit=500)

print(f"Total outliers: {len(outliers_all)}\n")

# Buscar cigarrillos entre los outliers
cigarro_outliers = []
for r in outliers_all:
    prod = r.get('x_studio_product_id')

    if isinstance(prod, (list, tuple)):
        prod_id = prod[0]
        prod_name = prod[1]
    else:
        prod_id = prod
        prod_name = str(prod)

    if 'cigarrillo' in str(prod_name).lower():
        cigarro_outliers.append({
            'id': r['id'],
            'product_id_raw': prod,
            'product_id': prod_id,
            'product_name': prod_name,
            'factor': r.get('x_studio_bias_outlier_factor'),
        })

print(f"Cigarrillos en outliers: {len(cigarro_outliers)}\n")

for i, c in enumerate(cigarro_outliers, 1):
    print(f"{i}. ID={c['id']}")
    print(f"   product_id_raw type: {type(c['product_id_raw'])}")
    print(f"   product_id_raw value: {c['product_id_raw']}")
    print(f"   product_id (parsed): {c['product_id']}")
    print(f"   product_name: {c['product_name']}")
    print(f"   factor: {c['factor']}\n")
