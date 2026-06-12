"""
DIAG read-only: el ancla (stock.quant HOY) de los productos con balance negativo
es realmente negativo en Odoo, o el negativo es artefacto de la reconstruccion?

Chequea stock.quant directo para los productos ofensores en sus warehouses.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()

# Productos/warehouse de los ejemplos negativos
casos = [
    (10474, 'AUSTRAL CALAFATE', 13),
    (21867, 'LAYS STAX', 7),
    (21335, 'LAYS JAMON SERRANO', 16),
    (28905, 'BON O BON GALLETA', 9),
]
TEAM_WH = {13:10, 7:2, 16:12, 9:16, 18:13, 11:5, 5:1, 8:3, 10:8, 12:9, 17:14, 6:4}

# cuantos stock.quant negativos hay en total en locations internas
neg_quants = odoo.search_count('stock.quant', [('quantity', '<', 0), ('location_id.usage', '=', 'internal')])
tot_quants = odoo.search_count('stock.quant', [('location_id.usage', '=', 'internal')])
print(f"stock.quant internos con quantity<0: {neg_quants} de {tot_quants} "
      f"({100*neg_quants/max(tot_quants,1):.1f}%)\n")

for pid, name, tid in casos:
    wh = TEAM_WH[tid]
    q = odoo.search_read('stock.quant',
        [('product_id', '=', pid), ('location_id.usage', '=', 'internal'),
         ('warehouse_id', '=', wh)],
        fields=['location_id', 'quantity', 'warehouse_id'])
    total = sum(r['quantity'] for r in q)
    print(f"{name} (pid={pid}, wh={wh}): quant total internos = {total:.1f}")
    for r in q:
        loc = r['location_id'][1] if isinstance(r['location_id'], (list,tuple)) else r['location_id']
        print(f"    {loc}: {r['quantity']:.1f}")
