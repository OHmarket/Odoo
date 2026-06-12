"""
Valida la idea de Marco: un SKU inactivo/perpetuo en quiebre, ¿tiene stock real
AHORA? Si si, el chequeo de stock-al-correr lo rescata gratis (no es quiebre).

Toma pares (team, producto) con racha de quiebre >= 30 dias en la tabla actual
y consulta su stock.quant interno real hoy.
"""
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
TEAM_WH = {5:1, 6:4, 7:2, 8:3, 9:16, 10:8, 11:5, 12:9, 13:10, 16:12, 17:14, 18:13}

rows = o.search_read('x_stock_balance_daily', [('x_studio_stockout','=',True)],
    fields=['x_studio_team_id','x_studio_product_id'])
runlen = defaultdict(int)
for r in rows:
    t=r['x_studio_team_id']; p=r['x_studio_product_id']
    tid=t[0] if isinstance(t,(list,tuple)) else t
    pid=p[0] if isinstance(p,(list,tuple)) else p
    runlen[(tid,pid)] += 1

largos = [(t,p) for (t,p),n in runlen.items() if n>=30]
print(f"pares con >=30 dias en quiebre: {len(largos)}")

# quant real por (warehouse, product) para los productos involucrados
pids = list({p for (_,p) in largos})
# traer en lotes
quant = defaultdict(float)  # (wh,pid)->qty
for i in range(0, len(pids), 500):
    chunk = pids[i:i+500]
    q = o.search_read('stock.quant',
        [('product_id','in',chunk), ('location_id.usage','=','internal')],
        fields=['product_id','warehouse_id','quantity'])
    for r in q:
        p=r['product_id']; w=r.get('warehouse_id')
        pid=p[0] if isinstance(p,(list,tuple)) else p
        wid=w[0] if isinstance(w,(list,tuple)) else w
        if wid: quant[(wid,int(pid))] += r['quantity'] or 0

con_stock = 0
sin_stock = 0
for (tid,pid) in largos:
    wh = TEAM_WH.get(tid)
    q = quant.get((wh,pid), 0.0)
    if q > 1e-4: con_stock += 1
    else: sin_stock += 1

n=len(largos)
print(f"  con stock real >0 HOY (rescatables gratis): {con_stock} ({100*con_stock/n:.1f}%)")
print(f"  sin stock real HOY (ambiguo: deslistado/quiebre real): {sin_stock} ({100*sin_stock/n:.1f}%)")
