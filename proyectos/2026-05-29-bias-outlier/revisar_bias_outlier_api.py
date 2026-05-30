#!/usr/bin/env python3
"""Revisar bias-outlier via API: validar 4 campos y detectar cigarrillos"""

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Semana mas reciente
last_week = odoo.search_read('x_hm_si_forecast',
    fields=['x_studio_week_start'],
    limit=1,
    order='x_studio_week_start desc')

if not last_week:
    print("No hay datos en x_hm_si_forecast")
    exit(1)

week_str = str(last_week[0]['x_studio_week_start'])
print(f"Semana: {week_str}\n")

# Leer TODOS los outliers de la semana
print("=" * 80)
print("VALIDACION BIAS-OUTLIER v3.48")
print("=" * 80)

outliers = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', week_str),
        ('x_studio_bias_outlier', '=', True),
    ],
    fields=[
        'id',
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_bias_outlier_factor',
        'x_studio_bias_outlier_delta',
        'x_studio_mu_week_pre_bias_outlier',
        'x_studio_mu_week',
    ],
    limit=500)

print(f"\nTotal outliers: {len(outliers)}")

# Analizar
cigarro_count = 0
factor_range = {'min': float('inf'), 'max': float('-inf')}
delta_stats = {'pos': 0, 'neg': 0, 'zero': 0}
pre_bias_zero = 0
pre_bias_populated = 0

cigarros_detail = []

for r in outliers:
    prod = r.get('x_studio_product_id')
    if isinstance(prod, (list, tuple)):
        prod_id = prod[0]
        prod_name = prod[1]
    else:
        prod_id = prod
        prod_name = str(prod)

    factor = r.get('x_studio_bias_outlier_factor')
    delta = r.get('x_studio_bias_outlier_delta')
    pre_bias = r.get('x_studio_mu_week_pre_bias_outlier')

    # Stats
    if factor is not None:
        f = float(factor)
        if f < factor_range['min']:
            factor_range['min'] = f
        if f > factor_range['max']:
            factor_range['max'] = f

    if delta is not None:
        d = float(delta)
        if d > 0:
            delta_stats['pos'] += 1
        elif d < 0:
            delta_stats['neg'] += 1
        else:
            delta_stats['zero'] += 1

    if pre_bias is not None:
        pb = float(pre_bias)
        if pb == 0.0:
            pre_bias_zero += 1
        else:
            pre_bias_populated += 1

    # Cigarrillos
    if 'cigarrillo' in prod_name.lower():
        cigarro_count += 1
        cigarros_detail.append({
            'id': r.get('id'),
            'product_id': prod_id,
            'product_name': prod_name[:60],
            'factor': factor,
            'delta': delta,
            'pre_bias': pre_bias,
            'mu_week': r.get('x_studio_mu_week'),
        })

print(f"\n[FACTORES]")
print(f"  Min: {factor_range['min']:.4f}")
print(f"  Max: {factor_range['max']:.4f}")

print(f"\n[DELTAS]")
print(f"  Positivos (sub-forecast): {delta_stats['pos']}")
print(f"  Negativos (over-forecast): {delta_stats['neg']} [SHOULD BE 0]")
print(f"  Cero: {delta_stats['zero']}")

print(f"\n[PRE_BIAS_OUTLIER]")
print(f"  Poblados: {pre_bias_populated}")
print(f"  Cero: {pre_bias_zero} [SHOULD BE 0]")

print(f"\n[CIGARRILLOS]")
if cigarro_count == 0:
    print(f"  OK CERO cigarrillos en outliers (filtrados correctamente por quiebre)")
else:
    print(f"  ERROR {cigarro_count} cigarrillos en outliers (deberian estar filtrados)")
    print(f"\n  Detalle:")
    for i, c in enumerate(cigarros_detail[:5], 1):
        print(f"  {i}. ID={c['id']} | {c['product_name']}")
        print(f"     factor={c['factor']:.3f} delta={c['delta']:+.1f} pre_bias={c['pre_bias']}")

print("\n" + "=" * 80)
print("RESUMEN")
print("=" * 80)
checks = []
checks.append(('Deltas negativos == 0', delta_stats['neg'] == 0))
checks.append(('Pre_bias ceros == 0', pre_bias_zero == 0))
checks.append(('Cigarrillos == 0', cigarro_count == 0))

all_pass = True
for check, result in checks:
    status = "OK" if result else "FAIL"
    print(f"{status} {check}: {result}")
    if not result:
        all_pass = False

if all_pass:
    print("\nOK OK OK TODAS LAS VALIDACIONES PASARON OK OK OK")
else:
    print("\nERROR ERROR ERROR REVISAR ARRIBA ERROR ERROR ERROR")
