"""
DIAG read-only: cuantos dias marcados stockout TUVIERON venta (qty_out>0)?
Un dia donde el producto SE VENDIO no puede ser quiebre total: hubo stock fisico.
Si esto es alto, la venta misma es prueba de disponibilidad y es mejor senal
que el balance reconstruido.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
rows = odoo.search_read(
    'x_stock_balance_daily',
    domain=[('x_studio_stockout', '=', True)],
    fields=['x_studio_qty_out', 'x_studio_qty_in', 'x_studio_qty_balance'],
)
n = len(rows)
con_venta = sum(1 for r in rows if (r['x_studio_qty_out'] or 0) > 1e-4)
con_in    = sum(1 for r in rows if (r['x_studio_qty_in'] or 0) > 1e-4)
neg       = sum(1 for r in rows if (r['x_studio_qty_balance'] or 0) < -1e-4)
print(f"dias marcados stockout: {n}")
print(f"  con qty_out>0 (VENDIO ese dia => habia stock): {con_venta} ({100*con_venta/n:.1f}%)")
print(f"  con qty_in>0  (entro mercaderia ese dia):       {con_in} ({100*con_in/n:.1f}%)")
print(f"  con balance < 0 (fisicamente imposible):        {neg} ({100*neg/n:.1f}%)")
