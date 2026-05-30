#!/usr/bin/env python3
"""Debuggear: por qué cigarrillos no se filtran por quiebre"""

from datetime import datetime, timedelta
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Cigarrillo en cuestión
CIGARRO_PID = 10138154

# Buscar en forecast
print("=" * 80)
print("CIGARRILLO EN x_hm_si_forecast (semana 2026-05-25)")
print("=" * 80)

cigarro_forecast = odoo.search_read('x_hm_si_forecast',
    domain=[
        ('x_studio_week_start', '=', '2026-05-25'),
        ('x_studio_product_id', '=', CIGARRO_PID),
    ],
    fields=[
        'id',
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_mu_week',
        'x_studio_bias_outlier',
        'x_studio_bias_outlier_factor',
    ],
    limit=10)

print(f"\nEncontrados {len(cigarro_forecast)} registros:")
for r in cigarro_forecast:
    team_val = r.get('x_studio_team_id')
    if isinstance(team_val, (list, tuple)):
        team_id = team_val[0]
        team_name = team_val[1]
    else:
        team_id = team_val
        team_name = str(team_val)

    print(f"  ID={r['id']} team={team_name} (id={team_id}) mu={r.get('x_studio_mu_week'):.2f} outlier={r.get('x_studio_bias_outlier')} factor={r.get('x_studio_bias_outlier_factor')}")

# Buscar quiebre en stock_balance
print("\n" + "=" * 80)
print("QUIEBRE EN x_stock_balance_daily (ultimas 3 semanas)")
print("=" * 80)

date_to = datetime.strptime('2026-05-25', '%Y-%m-%d').date()
date_from = date_to - timedelta(weeks=3)

print(f"Rango: {date_from} a {date_to}\n")

quiebre = odoo.search_read('x_stock_balance_daily',
    domain=[
        ('x_studio_product_id', '=', CIGARRO_PID),
        ('x_studio_date', '>=', str(date_from)),
        ('x_studio_date', '<=', str(date_to)),
    ],
    fields=[
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_date',
        'x_studio_stockout',
        'x_studio_stockout_partial',
        'x_studio_qty_balance',
    ],
    limit=100)

if quiebre:
    print(f"Encontrados {len(quiebre)} registros:\n")
    for r in quiebre:
        team_val = r.get('x_studio_team_id')
        if isinstance(team_val, (list, tuple)):
            team_name = team_val[1]
        else:
            team_name = str(team_val)

        so = r.get('x_studio_stockout')
        sop = r.get('x_studio_stockout_partial')
        qb = r.get('x_studio_qty_balance')
        dt = r.get('x_studio_date')

        has_quiebre = bool(so) or bool(sop) or (qb is not None and float(qb) <= 0)
        quiebre_marker = "[QUIEBRE]" if has_quiebre else ""

        print(f"  {dt} team={team_name} so={so} sop={sop} qty={qb} {quiebre_marker}")
else:
    print("NO HAY REGISTROS DE x_stock_balance_daily PARA ESTE PRODUCTO")
    print("(El producto no tiene datos de stock, por eso no se detecta quiebre)")

print("\n" + "=" * 80)
print("DIAGNOSTICO")
print("=" * 80)
if not quiebre:
    print("PROBLEMA: No hay registros en x_stock_balance_daily para este cigarrillo")
    print("  -> bias-outlier NO puede detectar quiebre")
    print("  -> El cigarrillo pasa el gate y se marca como outlier")
