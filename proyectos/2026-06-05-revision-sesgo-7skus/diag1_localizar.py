# -*- coding: utf-8 -*-
"""
DIAG1 read-only: localizar los 7 SKUs y ver que backtest hay disponible.
Operaciones: corto en 0154,2233,1963,1966 / pasado en vinos 6243,6244,6242.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CODES = ['0154', '2233', '1963', '1966', '6243', '6244', '6242']

odoo = OdooReader()

# 1. Localizar product.product por default_code
prods = odoo.search_read(
    'product.product',
    domain=[('default_code', 'in', CODES)],
    fields=['id', 'default_code', 'name'],
)
print("=== PRODUCT.PRODUCT ===")
for p in prods:
    print(f"  id={p['id']:>6}  code={p['default_code']:>6}  {p['name']}")
found_codes = {p['default_code'] for p in prods}
missing = [c for c in CODES if c not in found_codes]
if missing:
    print(f"  !! NO encontrados por default_code: {missing}")

pp_ids = [p['id'] for p in prods]

# 2. Que trae el backtest: model codes y cutoffs disponibles (global, sample)
print("\n=== BACKTEST: campos disponibles ===")
fg = odoo.fields_get('x_forecast_backtest')
print("  campos:", sorted(fg.keys()))

# 3. Conteo de filas backtest para estos SKUs
cnt = odoo.search_count('x_forecast_backtest', [('x_studio_product_id', 'in', pp_ids)])
print(f"\n=== BACKTEST filas para los 7 SKUs: {cnt} ===")
