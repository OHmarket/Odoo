#!/usr/bin/env python3
"""Debug: revisar si product_id=17604 está en los candidatos de bias-outlier"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

CIGARRO_ID = 17604

print("=" * 80)
print("BUSQUEDA 1: ¿Está el cigarrillo en x_hm_si_forecast semana 2026-05-25?")
print("=" * 80)

forecast_cigarro = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', '2026-05-25'),
        ('x_studio_product_id', '=', CIGARRO_ID),
    ],
    fields=['id', 'x_studio_product_id', 'x_studio_team_id', 'x_studio_mu_week'],
    limit=20)

print(f"Encontrados: {len(forecast_cigarro)} registros")
for r in forecast_cigarro:
    print(f"  ID={r['id']} mu={r.get('x_studio_mu_week')}")

# Ahora buscar qué product_ids están en outliers
print("\n" + "=" * 80)
print("BUSQUEDA 2: ¿Está el cigarrillo (17604) en los OUTLIERS?")
print("=" * 80)

outliers_cigarro = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', '2026-05-25'),
        ('x_studio_bias_outlier', '=', True),
        ('x_studio_product_id', '=', CIGARRO_ID),
    ],
    fields=['id', 'x_studio_bias_outlier_factor'],
    limit=20)

print(f"Encontrados: {len(outliers_cigarro)} outliers")
for r in outliers_cigarro:
    print(f"  ID={r['id']} factor={r.get('x_studio_bias_outlier_factor')}")

# El problema: la búsqueda de outliers cigarrillo encontró product_id distinto.
# Vimos que el product_id_raw en outliers es [17604, '[10138154] CIGARRILLO ...']
# Pero aquí buscamos 17604 directamente. Quizás el problema es que la búsqueda
# interpreta el product_id de forma distinta.

print("\n" + "=" * 80)
print("BUSQUEDA 3: Revisando el mismatch de product_id")
print("=" * 80)

# Búsqueda SIN filtro de product_id, solo los outliers cigarrillo
all_outliers = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', '2026-05-25'),
        ('x_studio_bias_outlier', '=', True),
    ],
    fields=['id', 'x_studio_product_id', 'x_studio_bias_outlier_delta'],
    limit=500)

cigarro_outliers_found = []
for r in all_outliers:
    prod = r.get('x_studio_product_id')
    if isinstance(prod, (list, tuple)):
        prod_id = prod[0]
        prod_name = prod[1]
    else:
        prod_id = prod
        prod_name = str(prod)

    if 'cigarrillo' in str(prod_name).lower():
        cigarro_outliers_found.append({
            'id': r['id'],
            'product_id': prod_id,
            'product_name': prod_name,
            'delta': r.get('x_studio_bias_outlier_delta'),
        })

print(f"Cigarrillos encontrados en outliers (sin filtro): {len(cigarro_outliers_found)}")
for c in cigarro_outliers_found[:2]:
    print(f"  product_id={c['product_id']} name={c['product_name'][:50]}")

print("\n" + "=" * 80)
print("RESUMEN")
print("=" * 80)
print(f"¿Cigarrillo en forecast (direct search): {len(forecast_cigarro)} registros")
print(f"¿Cigarrillo en outliers (direct search): {len(outliers_cigarro)} registros")
print(f"¿Cigarrillo en outliers (scan all): {len(cigarro_outliers_found)} registros")

if len(forecast_cigarro) > 0 and len(outliers_cigarro) == 0 and len(cigarro_outliers_found) > 0:
    print("\nPROBLEMA: El cigarrillo se marca como outlier (found en scan all)")
    print("          Pero NO lo encuentra el filtro directo (product_id=17604)")
    print("          Esto sugiere que product_id se está guardando como algo diferente")
