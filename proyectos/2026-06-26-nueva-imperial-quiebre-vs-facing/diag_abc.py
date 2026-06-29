"""
DIAG read-only: estructura de x_calculo_abc_xyz para construir el set A/B-X.
Determina si el rank es global o por sala (team).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
fg = odoo.fields_get('x_calculo_abc_xyz')
keys = [k for k in fg if any(t in k.lower() for t in
        ('abc', 'xyz', 'rank', 'product', 'team', 'categ', 'mu', 'demand'))]
print("== campos x_calculo_abc_xyz relevantes ==")
for k in sorted(keys):
    print(f"  {k:32} {str(fg[k].get('ttype')):10} -> {fg[k].get('string')}"
          + (f"  rel={fg[k].get('relation')}" if fg[k].get('relation') else ''))

# muestra 3 filas
sample = odoo.search_read('x_calculo_abc_xyz', [], keys, limit=3)
print("\n== muestra ==")
for s in sample:
    print(s)

print("\ntotal filas:", odoo.search_count('x_calculo_abc_xyz', []))
