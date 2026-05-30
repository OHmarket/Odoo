#!/usr/bin/env python3
"""Verificar mapeo: variant (product.product) -> template (product.template)"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Buscar KENT NEO variant
variants = odoo.search_read('product.product',
    domain=[('id', '=', 10107101)],
    fields=['id', 'product_tmpl_id', 'name'])

if variants:
    v = variants[0]
    tmpl = v.get('product_tmpl_id')
    if isinstance(tmpl, (list, tuple)):
        tmpl_id = tmpl[0]
        tmpl_name = tmpl[1]
    else:
        tmpl_id = tmpl
        tmpl_name = str(tmpl)

    print("=" * 80)
    print("MAPEO: VARIANT -> TEMPLATE")
    print("=" * 80)
    print(f"\nVariant (product.product):")
    print(f"  ID: {v['id']}")
    print(f"  Name: {v['name'][:70]}")

    print(f"\nTemplate (product.template):")
    print(f"  ID: {tmpl_id}")
    print(f"  Name: {tmpl_name}")

    print("\n" + "=" * 80)
    print("CONCLUSION:")
    print("=" * 80)
    if tmpl_id == 11205:
        print(f"✓ El template ID es 11205 (coincide con lo encontrado en x_stock_balance_daily)")
    else:
        print(f"✗ El template ID es {tmpl_id} (NO es 11205)")

    print(f"\nEl mismatch es:")
    print(f"  - x_hm_si_forecast usa: product.product ID = 10107101")
    print(f"  - x_stock_balance_daily usa: product.product ID = ?")
    print(f"  - Pero encontramos registros con template ID = 11205")
    print(f"\n-> El detector está escribiendo TEMPLATE IDs, no VARIANT IDs!")
else:
    print("Variant 10107101 no encontrado")
