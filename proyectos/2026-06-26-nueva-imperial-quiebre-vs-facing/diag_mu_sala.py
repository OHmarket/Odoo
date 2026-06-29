"""
DIAG read-only: de donde sacar demanda semanal POR SALA para el piso 30%.
Compara x_analisis_de_stock (motor, mu de-censurada por team) vs
x_pos_week_sku_sale (venta cruda). Inspecciona campos.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
fg = odoo.fields_get('x_analisis_de_stock')
keys = [k for k in fg if any(t in k.lower() for t in
        ('mu', 'demand', 'week', 'team', 'product', 'sala', 'abcxyz', 'forecast', 'qty'))]
print("== x_analisis_de_stock campos relevantes ==")
for k in sorted(keys):
    print(f"  {k:38} {str(fg[k].get('ttype')):9} -> {fg[k].get('string')}"
          + (f"  rel={fg[k].get('relation')}" if fg[k].get('relation') else ''))
print("\ntotal filas x_analisis_de_stock:", odoo.search_count('x_analisis_de_stock', []))
# muestra 1 fila AX si hay campo abcxyz
sample = odoo.search_read('x_analisis_de_stock', [], keys, limit=2)
for s in sample:
    print(s)
