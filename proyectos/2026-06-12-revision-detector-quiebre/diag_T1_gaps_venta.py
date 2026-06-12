"""
T1 (read-only): distribucion de gaps entre ventas por (sala, SKU) para calibrar
la ventana N de "surtido activo".

Fuente: report.pos.order (date, product_id, product_qty, config_id), agregado
server-side por (product, semana) via read_group. Une cajas de una misma sala.

Pregunta: si un SKU CARGADO (vende antes y despues de un gap) normalmente pasa
hasta cuantos dias sin vender? N debe cubrir el gap normal de los SKU de baja
rotacion (Z) para no marcarlos "deslistados" entre ventas.

Metrica clave: % de gaps inter-venta que superan N (=falso inactivo) por clase.
"""
import sys, datetime
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
DESDE = '2025-04-01'

# Salas representativas -> configs (cajas) que la componen
SALAS = {
    'Panguipulli790 (alto)': [420, 421, 422],
    'Paillaco (medio)':      [414, 415],
    'Mehuin Express (bajo)': [445, 446],
}

# ABCXYZ por producto (segunda letra X/Y/Z = regularidad)
abc_rows = o.search_read('x_calculo_abc_xyz', [],
                         fields=['x_studio_product_id', 'x_studio_abcxyz'], limit=100000)
prod_abc = {}
for r in abc_rows:
    p = r['x_studio_product_id']
    pid = p[0] if isinstance(p, (list, tuple)) else p
    v = (r['x_studio_abcxyz'] or '').strip()
    if pid and v:
        prod_abc[int(pid)] = v

def parse_week(label):
    # read_group date:week -> 'W14 2025' o similar; parseamos via __domain mejor.
    return label

# Acumular gaps por clase (segunda letra) y global
gaps_by_x = defaultdict(list)   # 'X'/'Y'/'Z'/'?' -> [gap_dias,...]
pairs_total = 0
pairs_con_gap = 0

for sala, configs in SALAS.items():
    # read_group por (product_id, semana). Usamos date:week.
    g = o.execute('report.pos.order', 'read_group',
        [('date', '>=', DESDE), ('config_id', 'in', configs), ('product_qty', '>', 0)],
        ['product_qty:sum'], ['product_id', 'date:week'], lazy=False)
    # construir set de semanas-con-venta por producto
    weeks_by_prod = defaultdict(set)
    for row in g:
        p = row.get('product_id')
        pid = p[0] if isinstance(p, (list, tuple)) else p
        wk = row.get('date:week')   # ej '2025-04-07' o 'W15 2025'
        if not pid or not wk:
            continue
        # date:week en Odoo devuelve string tipo 'W15 2025'
        weeks_by_prod[int(pid)].add(wk)
    # convertir labels de semana a fecha (lunes) para medir gaps
    def wk_to_date(lbl):
        # formatos posibles: 'W15 2025'
        try:
            parts = lbl.replace('W', '').split()
            wnum = int(parts[0]); year = int(parts[1])
            return datetime.date.fromisocalendar(year, wnum, 1)
        except Exception:
            return None
    for pid, wks in weeks_by_prod.items():
        dates = sorted(d for d in (wk_to_date(w) for w in wks) if d)
        pairs_total += 1
        if len(dates) < 2:
            continue
        pairs_con_gap += 1
        x = (prod_abc.get(pid) or '??')
        xl = x[1] if len(x) >= 2 else '?'
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i-1]).days
            gaps_by_x[xl].append(gap)

def pct(arr, q):
    if not arr: return 0
    arr = sorted(arr); k = int(len(arr)*q)
    return arr[min(k, len(arr)-1)]

print(f"pares (sala,SKU) con venta: {pairs_total}, con >=2 semanas (medibles): {pairs_con_gap}\n")
print(f"{'clase':<8}{'n_gaps':>8}{'p50':>6}{'p75':>6}{'p90':>6}{'p95':>7}"
      f"{'>30d':>8}{'>45d':>8}{'>60d':>8}")
allg = []
for xl in ['X', 'Y', 'Z', '?']:
    arr = gaps_by_x.get(xl, [])
    allg += arr
    if not arr: continue
    n = len(arr)
    g30 = 100*sum(1 for x in arr if x > 30)/n
    g45 = 100*sum(1 for x in arr if x > 45)/n
    g60 = 100*sum(1 for x in arr if x > 60)/n
    print(f"{xl:<8}{n:>8}{pct(arr,.5):>6}{pct(arr,.75):>6}{pct(arr,.9):>6}{pct(arr,.95):>7}"
          f"{g30:>7.1f}%{g45:>7.1f}%{g60:>7.1f}%")
n = len(allg)
g30 = 100*sum(1 for x in allg if x > 30)/n; g45 = 100*sum(1 for x in allg if x > 45)/n; g60 = 100*sum(1 for x in allg if x > 60)/n
print(f"{'TODOS':<8}{n:>8}{pct(allg,.5):>6}{pct(allg,.75):>6}{pct(allg,.9):>6}{pct(allg,.95):>7}"
      f"{g30:>7.1f}%{g45:>7.1f}%{g60:>7.1f}%")
print("\nLectura: '>Nd' = % de gaps inter-venta que superan N dias = riesgo de marcar")
print("falso-inactivo a un SKU cargado durante ese gap. N debe dejar esto bajo en X/Y.")
