"""DIAG read-only parte 3: re-medir el universo separando direccion de transferencia.

Hipotesis de medicion: el sintoma (168 tmpl con Sigma transfer > stock_central)
mezcla retorno_a_cd (sala->CD) con transferir_desde_cd (CD->sala). Solo el segundo
puede prometer mas de lo que el CD tiene (bug real). Re-medimos por accion.
"""
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

odoo = OdooReader()

# Todas las filas con transferencia > 0 (universo acotado, no masivo)
rows = odoo.search_read(
    'x_analisis_de_stock',
    [('x_studio_qty_transferir', '>', 0)],
    ['x_studio_product_id', 'x_studio_buy_action',
     'x_studio_qty_transferir', 'x_studio_stock_central'])
print(f"filas con transfer>0: {len(rows)}")

# Conteo por accion
by_action = defaultdict(lambda: [0, 0.0])
for r in rows:
    a = r['x_studio_buy_action'] or '-'
    by_action[a][0] += 1
    by_action[a][1] += r['x_studio_qty_transferir'] or 0.0
print('\nfilas / unidades por buy_action:')
for a, (n, u) in sorted(by_action.items(), key=lambda x: -x[1][1]):
    print(f"  {a:24s} filas={n:>5} unidades={u:>10.1f}")

# Agregado por template SOLO direccion CD->sala (transferir_desde_cd)
CD_TO_SALA = 'transferir_desde_cd'
agg = defaultdict(float)
central = {}
for r in rows:
    if (r['x_studio_buy_action'] or '') != CD_TO_SALA:
        continue
    pid = r['x_studio_product_id']
    if not pid:
        continue
    tid = pid[0]
    agg[tid] += r['x_studio_qty_transferir'] or 0.0
    central[tid] = r['x_studio_stock_central'] or 0.0

print(f"\ntemplates con transferir_desde_cd: {len(agg)}")
over = [(tid, agg[tid], central[tid]) for tid in agg
        if agg[tid] > central[tid] + 0.5]
over.sort(key=lambda x: -(x[1] - x[2]))
print(f"templates con Sigma(CD->sala) > stock_central: {len(over)}")
for tid, s, c in over[:25]:
    pid_name = ''
    print(f"  tmpl={tid:>7} Sigma_transfer={s:>8.1f} stock_central={c:>8.1f} exceso={s-c:>8.1f}")
