"""DIAG read-only parte 2: filas x_analisis_de_stock + stock fisico CD del VINO PIPEÑO."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

TMPL = 24185
VARIANT = 19988
odoo = OdooReader()

def show(t):
    print('\n' + '=' * 70); print(t); print('=' * 70)

# 1) Filas del analisis para este template
show('1) x_analisis_de_stock filas (tmpl 24185)')
rows = odoo.search_read(
    'x_analisis_de_stock',
    [('x_studio_product_id', '=', TMPL)],
    ['id', 'x_studio_team_id', 'x_studio_buy_action', 'x_studio_qty_transferir',
     'x_studio_stock_central', 'x_studio_stock_real', 'x_studio_stock_effective',
     'x_studio_stock_source_mode', 'x_studio_stock_root_location_id', 'write_date'],
    order='x_studio_team_id')
sum_tr = 0.0
for r in rows:
    team = r['x_studio_team_id'] or [0, '-']
    root = r['x_studio_stock_root_location_id'] or [0, '-']
    tr = r['x_studio_qty_transferir'] or 0.0
    sum_tr += tr
    print(f"  id={r['id']:>7} team={str(team[0]):>3} {str(team[1])[:18]:18s} "
          f"buy={str(r['x_studio_buy_action'])[:18]:18s} transf={tr:>6.1f} "
          f"cd={r['x_studio_stock_central'] or 0:>7.1f} real={r['x_studio_stock_real'] or 0:>6.1f} "
          f"mode={r['x_studio_stock_source_mode']} root={root[0]} wd={r['write_date']}")
print(f"\n  Sigma qty_transferir = {sum_tr}")

# 2) Stock fisico real de la variante por ubicacion (de donde sale el CD pool)
show('2) stock.quant variante 19988 por ubicacion interna')
quants = odoo.search_read(
    'stock.quant',
    [('product_id', '=', VARIANT), ('location_id.usage', '=', 'internal')],
    ['location_id', 'quantity', 'reserved_quantity'])
for q in quants:
    loc = q['location_id'] or [0, '-']
    print(f"  loc={loc[0]:>5} {str(loc[1])[:40]:40s} qty={q['quantity']:>7.1f} resv={q['reserved_quantity']:>6.1f}")

# 3) write_date del run mas reciente en TODO el modelo (para detectar filas stale)
show('3) write_date max del modelo vs filas del template')
recent = odoo.search_read('x_analisis_de_stock', [], ['write_date'],
                          limit=1, order='write_date desc')
print('  write_date max global:', recent[0]['write_date'] if recent else None)
