"""
CALCULO read-only: costo del piso canonico (floor) con corte AX, bebidas frias.
  piso_u   = max(DIAS/7 * demanda_semanal, PISO_FMT[formato])
  target_op = reorder_target_weeks * demanda_semanal   (lo que el motor ya apunta)
  incremental_u = max(0, piso_u - target_op)            (lo que el FLOOR agrega)
Reporta capital incremental (lo accionable) y bruto (contraste), por sala + NI.
"""
import sys, csv
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
SALAS = [5,6,7,8,9,10,11,12,13,16,17,18]
SALA_NAME = {5:'Pangui790',6:'Los Lagos',7:'Futrono',8:'Pangui645',9:'Pangui763',
             10:'Lautaro',11:'San Jose',12:'Paillaco',13:'Mehuin',16:'Conaripe',
             17:'Nueva Imperial',18:'Malalhue'}
BEB_CATS = [1621, 1614]
PISO_FMT = {'lata':6, 'vidrio':4, 'pet':3, 'sin_formato':3}
DIAS = 3
MU_MIN = 3.0   # solo SKUs con demanda semanal > 3 uds reciben piso
beb_ids = set(odoo.execute('product.category','search',[('id','child_of',BEB_CATS)]))

ax = odoo.search_read('x_analisis_de_stock',
    [('x_studio_abcxyz','=','AX'), ('x_studio_team_id','in',SALAS)],
    ['x_studio_team_id','x_studio_product_id','x_studio_demanda_semanal',
     'x_studio_reorder_target_weeks'])

tids = list({r['x_studio_product_id'][0] for r in ax if r['x_studio_product_id']})
tinfo = {}
import re
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template',[('id','in',tids[i:i+500])],
                              ['categ_id','x_studio_formato','standard_price','name']):
        tinfo[t['id']] = t

def es_pack(t):
    nm = (t.get('name') or '').upper()
    return bool(re.search(r'\b\d+\s*X\s*\d', nm))

by_sala = defaultdict(lambda: {'sku':0,'muerde':0,'inc_u':0.0,'inc_$':0.0,'bruto_$':0.0})
tot = {'sku':0,'muerde':0,'inc_$':0.0,'bruto_$':0.0}
rows = []
for r in ax:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]; t = tinfo.get(tid, {})
    cat = (t.get('categ_id') or [0])[0]
    if cat not in beb_ids:
        continue
    if es_pack(t):                      # packs: piso aparte, fuera del corte unidad
        continue
    mu = r.get('x_studio_demanda_semanal') or 0.0
    if mu <= MU_MIN:                    # solo rotadores > 3/sem
        continue
    team = r['x_studio_team_id'][0]
    tw = r.get('x_studio_reorder_target_weeks') or 0.0
    cost = t.get('standard_price') or 0.0
    fmt = t.get('x_studio_formato') or 'sin_formato'
    piso = max(DIAS/7.0*mu, PISO_FMT.get(fmt,3))
    target_op = tw * mu
    inc = max(0.0, piso - target_op)
    sname = SALA_NAME.get(team, str(team))
    d = by_sala[sname]; d['sku']+=1; tot['sku']+=1
    d['bruto_$'] += piso*cost; tot['bruto_$'] += piso*cost
    if inc > 0:
        d['muerde']+=1; tot['muerde']+=1
        d['inc_u']+=inc; d['inc_$']+=inc*cost; tot['inc_$']+=inc*cost
        rows.append({'sala':sname,'code':'','producto':(t.get('name') or '')[:42],
                     'fmt':fmt,'demanda_sem':round(mu,1),'target_op':round(target_op,1),
                     'piso':round(piso,1),'inc_u':round(inc,1),'inc_$':round(inc*cost)})

print(f"AX bebidas UNIDAD (sin packs), DIAS={DIAS}, mu>{MU_MIN}/sem, piso formato {PISO_FMT}\n")
print(f"{'sala':16} {'#AX':>4} {'muerde':>7} {'inc_u':>6} {'incremental$':>13} {'bruto$':>12}")
for s in sorted(by_sala, key=lambda x:-by_sala[x]['inc_$']):
    d=by_sala[s]
    print(f"{s:16} {d['sku']:4d} {d['muerde']:7d} {d['inc_u']:6.0f} {d['inc_$']:13,.0f} {d['bruto_$']:12,.0f}")
print(f"{'TOTAL':16} {tot['sku']:4d} {tot['muerde']:7d} {'':6} {tot['inc_$']:13,.0f} {tot['bruto_$']:12,.0f}")

print(f"\nINCREMENTAL (lo que el floor agrega sobre el motor): ${tot['inc_$']:,.0f}")
print(f"BRUTO (todo el piso, contraste):                      ${tot['bruto_$']:,.0f}")
print(f"El floor muerde en {tot['muerde']}/{tot['sku']} = {100*tot['muerde']/tot['sku']:.0f}% de los AX bebidas")

print("\n== Nueva Imperial: AX donde el floor agrega (top $) ==")
ni = sorted([r for r in rows if r['sala']=='Nueva Imperial'], key=lambda x:-x['inc_$'])[:20]
for r in ni:
    print(f"  {r['producto']:42} {r['fmt']:6} dem={r['demanda_sem']:5} "
          f"target={r['target_op']:5} piso={r['piso']:4} +{r['inc_u']:3.0f}u ${r['inc_$']:,}")

out = Path(__file__).parent / 'resultados' / 'floor_ax_bebidas.csv'
with out.open('w', newline='', encoding='utf-8-sig') as f:
    w=csv.DictWriter(f, fieldnames=['sala','code','producto','fmt','demanda_sem','target_op','piso','inc_u','inc_$'])
    w.writeheader(); w.writerows(sorted(rows, key=lambda x:(x['sala'],-x['inc_$'])))
print(f"\nCSV -> {out}")
