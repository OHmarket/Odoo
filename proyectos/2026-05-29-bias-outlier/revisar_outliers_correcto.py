#!/usr/bin/env python3
"""Revisar outliers cigarrillos: qué product_id realmente están usando"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Buscar outliers de cigarrillos CON los product_ids reales
cigarro_outliers = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', '2026-05-25'),
        ('x_studio_bias_outlier', '=', True),
    ],
    fields=[
        'id',
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_bias_outlier_delta',
        'x_studio_bias_outlier_factor',
    ],
    limit=20)

# Filtrar solo cigarrillos (buscar en los nombres)
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
            'record_id': r['id'],
            'product_id': prod_id,
            'product_name': prod_name[:60],
            'delta': r.get('x_studio_bias_outlier_delta'),
            'factor': r.get('x_studio_bias_outlier_factor'),
        })

print(f"\nTotal cigarrillos en outliers: {len(cigarro_list)}")
print("\nDetalle (primeros 5):")
for i, c in enumerate(cigarro_list[:5], 1):
    print(f"\n{i}. Record ID: {c['record_id']}")
    print(f"   Product ID: {c['product_id']}")
    print(f"   Name: {c['product_name']}")
    print(f"   Delta: {c['delta']:+.1f}")
    print(f"   Factor: {c['factor']:.3f}")

# Ahora verificar el mapeo de uno de esos product_ids
if cigarro_list:
    test_pid = cigarro_list[0]['product_id']
    print(f"\n" + "=" * 80)
    print(f"VERIFICAR MAPEO: product_id={test_pid} (KENT NEO)")
    print("=" * 80)

    prod = odoo.search_read('product.product',
        domain=[('id', '=', test_pid)],
        fields=['id', 'product_tmpl_id', 'name'])

    if prod:
        p = prod[0]
        tmpl = p.get('product_tmpl_id')
        tmpl_id = tmpl[0] if isinstance(tmpl, (list, tuple)) else tmpl
        print(f"\n✓ Variant (product.product): ID={p['id']} Name={p['name'][:50]}")
        print(f"✓ Template (product.template): ID={tmpl_id}")
    else:
        print(f"\n✗ Product ID {test_pid} NO EXISTE en product.product")
