#!/usr/bin/env python3
"""Debug: qué product_id se almacena en x_stock_balance_daily"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

VARIANT_ID = 17604
TEMPLATE_ID = 10138154

print("=" * 80)
print(f"BUSQUEDA 1: product_id={VARIANT_ID} (product.product variant)")
print("=" * 80)

sb1 = odoo.search_read('x_stock_balance_daily',
    domain=[('x_studio_product_id', '=', VARIANT_ID)],
    fields=['x_studio_product_id', 'x_studio_date'],
    limit=5)

print(f"Encontrados: {len(sb1)} registros")
if sb1:
    for r in sb1[:3]:
        print(f"  {r['x_studio_date']}")

print("\n" + "=" * 80)
print(f"BUSQUEDA 2: product_id={TEMPLATE_ID} (product.template)")
print("=" * 80)

sb2 = odoo.search_read('x_stock_balance_daily',
    domain=[('x_studio_product_id', '=', TEMPLATE_ID)],
    fields=['x_studio_product_id', 'x_studio_date'],
    limit=5)

print(f"Encontrados: {len(sb2)} registros")
if sb2:
    for r in sb2[:3]:
        print(f"  {r['x_studio_date']}")

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
if len(sb1) == 0 and len(sb2) > 0:
    print("PROBLEMA IDENTIFICADO:")
    print(f"  x_hm_si_forecast GUARDA: product_id={VARIANT_ID} (variant)")
    print(f"  x_stock_balance_daily TIENE: product_id={TEMPLATE_ID} (template)")
    print("  -> La query de quiebre NO ENCUENTRA NADA")
    print("  -> Los cigarrillos pasan sin filtro -> se marcan como outlier")
elif len(sb1) > 0 and len(sb2) == 0:
    print("OK: Ambas tablas usan el mismo format (variant ID)")
else:
    print(f"OK/MIXED: sb1={len(sb1)} sb2={len(sb2)}")
