"""
Descubrimiento: confirmar nombres de campos en x_hm_si_forecast antes de pull masivo.
Hace 2 calls XML-RPC:
  1. fields_get filtrado a campos relevantes (1 call)
  2. search_count para Feb-16 y Mar-16 (2 calls)
"""
from __future__ import annotations
import sys
from pathlib import Path

# Path setup para importar shared/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
print(f"Conectado: {odoo}")
print()

fields = odoo.fields_get('x_hm_si_forecast', attributes=['type', 'string', 'relation'])
print(f"Total campos en x_hm_si_forecast: {len(fields)}")
print()

# Filtrar campos que nos interesan
keywords = ['si_', 'mu_week', 'week_start', 'product_id', 'team_id', 'categ', 'regimen', 'forecast_model', 'sigma']
print("Campos relevantes (nombre / tipo / label):")
for fname, info in sorted(fields.items()):
    fname_low = fname.lower()
    if any(k in fname_low for k in keywords):
        ftype = info.get('type', '?')
        label = info.get('string', '')
        relation = info.get('relation', '')
        rel_str = f" -> {relation}" if relation else ""
        print(f"  {fname:42s}  {ftype:12s}{rel_str}  '{label}'")

print()
# Conteo rapido por semana
for wk in ['2026-02-16', '2026-03-16']:
    # Probar dos nombres posibles del campo week
    for wk_field in ['x_studio_week_start', 'x_studio_target_week_start']:
        if wk_field in fields:
            cnt = odoo.search_count('x_hm_si_forecast', [(wk_field, '=', wk)])
            print(f"  {wk}  ({wk_field}): {cnt:,} filas")
            break
