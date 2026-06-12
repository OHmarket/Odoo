"""
Validacion LIVIANA: solo search_count (COUNT server-side, no trae filas).
No martiriza el POS como el pull de 226k filas.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
M = 'x_stock_balance_daily'
def c(dom): return o.search_count(M, dom)

total = c([])
v3 = c([('x_studio_run_version','=','STOCKOUT_v3_0')])
v2 = c([('x_studio_run_version','=','STOCKOUT_v2_0')])
part = c([('x_studio_stockout_partial','=',True)])
full = c([('x_studio_stockout_partial','=',False)])
neg = c([('x_studio_qty_balance','<',-0.0001)])
full_venta = c([('x_studio_stockout_partial','=',False),('x_studio_qty_out','>',0.0001)])
part_venta = c([('x_studio_stockout_partial','=',True),('x_studio_qty_out','>',0.0001)])

print(f"total filas: {total}   [v2.0 backfill previo: 226332]")
print(f"  run_version v3_0: {v3}   v2_0: {v2}")
print(f"  full: {full} ({100*full/max(total,1):.1f}%)   partial: {part} ({100*part/max(total,1):.1f}%)")
print(f"  balance NEGATIVO: {neg} ({100*neg/max(total,1):.1f}%)   [v2.0: 59.5% -> v3 esperado 0%]")
print(f"  FULL con venta>0: {full_venta} ({100*full_venta/max(full,1):.1f}% de full)   [esperado ~0%]")
print(f"  PARTIAL con venta>0: {part_venta} ({100*part_venta/max(part,1):.1f}% de partial)   [esperado ~100%]")

print("\n  casos canonicos (dias-quiebre, v2.0 ~400):")
for pid,name in [(28905,'BON O BON'),(28827,'PAPAS LAYS AMER'),(10474,'AUSTRAL CALAFATE')]:
    print(f"    {name}: {c([('x_studio_product_id','=',pid)])}")
