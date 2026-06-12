"""
DIAG read-only: peso de quiebres PARCIALES (intradia: start>0, end<=0) vs
TOTALES, para decidir si vale invertir en precision intradia (timestamps POS).

Ojo: bal_start aqui viene del roll-backward drifteado, asi que es proxy sucio.
Reportamos varias particiones para acotar.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
rows = odoo.search_read(
    'x_stock_balance_daily',
    domain=[('x_studio_stockout', '=', True)],
    fields=['x_studio_qty_start', 'x_studio_qty_balance', 'x_studio_qty_out',
            'x_studio_stockout_partial'],
)
n = len(rows)

def pos(x): return (x or 0) > 1e-4
def zeroneg(x): return (x or 0) <= 1e-4

# Particion segun flag persistido
flag_partial = sum(1 for r in rows if r['x_studio_stockout_partial'])
# Particion "limpia": start claramente >0, end<=0 (definicion canonica intradia)
clean_partial = sum(1 for r in rows if pos(r['x_studio_qty_start']) and zeroneg(r['x_studio_qty_balance']))
# Partial REAL robusto: start>0 AND end<=0 AND vendio ese dia (prueba de actividad)
real_partial = sum(1 for r in rows
                   if pos(r['x_studio_qty_start']) and zeroneg(r['x_studio_qty_balance'])
                   and pos(r['x_studio_qty_out']))
# Total "duro": start<=0 y end<=0 (nunca tuvo)
hard_full = sum(1 for r in rows if zeroneg(r['x_studio_qty_start']) and zeroneg(r['x_studio_qty_balance']))

print(f"dias marcados stockout: {n}\n")
print(f"flag x_studio_stockout_partial = True : {flag_partial:>7} ({100*flag_partial/n:.1f}%)")
print(f"start>0 & end<=0 (parcial canonico)   : {clean_partial:>7} ({100*clean_partial/n:.1f}%)")
print(f"  ...y ademas vendio (parcial real)   : {real_partial:>7} ({100*real_partial/n:.1f}%)")
print(f"start<=0 & end<=0 (total, nunca tuvo) : {hard_full:>7} ({100*hard_full/n:.1f}%)")
