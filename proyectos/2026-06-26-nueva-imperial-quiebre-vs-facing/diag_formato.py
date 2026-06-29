"""
DIAG read-only: de donde sale el 'formato/envase' de un SKU para fijar el piso
de presentacion. Busca campos formato/envase/volumen en product.template y
muestra UoM + nombre de una muestra de cerveza/bebida.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

fg = odoo.fields_get('product.template')
hits = {k: v.get('string') for k, v in fg.items()
        if any(t in k.lower() for t in ('format', 'envase', 'volum', 'capac', 'litro', 'cc', 'pack', 'unidad'))}
print("== campos formato/envase/volumen en product.template ==")
for k, v in sorted(hits.items()):
    print(f"  {k} -> {v}")

# muestra cerveza+bebida con uom y categoria
sample = odoo.search_read(
    'product.template',
    [('categ_id', 'child_of', [1621, 1614]), ('active', '=', True)],
    ['name', 'default_code', 'categ_id', 'uom_id'],
    limit=25, order='name',
)
print("\n== muestra (nombre | uom | categ) ==")
for s in sample:
    print(f"  [{s.get('default_code') or ''}] {s['name'][:50]:50} | "
          f"{(s.get('uom_id') or [0,''])[1]:10} | {(s.get('categ_id') or [0,''])[1]}")
