"""
Descubrir que semanas estan actualmente en x_hm_si_forecast y planear desde ahi.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
print(f"Conectado: {odoo}\n")

# Conteo total y semanas presentes
total = odoo.search_count('x_hm_si_forecast', [])
print(f"Total filas en x_hm_si_forecast: {total:,}")

# Conteo por semana via read_group
rg = odoo.execute(
    'x_hm_si_forecast', 'read_group',
    [], ['x_studio_week_start'], ['x_studio_week_start'],
)
weeks = []
for g in rg:
    wk = g.get('x_studio_week_start')
    cnt = g.get('x_studio_week_start_count', g.get('__count', 0))
    if wk:
        weeks.append((wk, cnt))
print(f"\nSemanas distintas: {len(weeks)}")
print(f"Min: {min(weeks)[0]}  Max: {max(weeks)[0]}")
print(f"\nUltimas 10 semanas con conteo:")
for wk, cnt in sorted(weeks, key=lambda x: x[0])[-10:]:
    iso = date.fromisoformat(wk).isocalendar()[1]
    print(f"  {wk} (iso_week={iso})  {cnt:,} filas")

# Buscar iso_week 8 (Feb) y 12 (Mar) en cualquier ano disponible
print("\nBusqueda de iso_week 8 (Feb) e iso_week 12 (Mar):")
iso_8 = []
iso_12 = []
for wk, cnt in weeks:
    iso = date.fromisoformat(wk).isocalendar()[1]
    if iso == 8:
        iso_8.append((wk, cnt))
    elif iso == 12:
        iso_12.append((wk, cnt))
print(f"  iso_week 8: {iso_8}")
print(f"  iso_week 12: {iso_12}")
