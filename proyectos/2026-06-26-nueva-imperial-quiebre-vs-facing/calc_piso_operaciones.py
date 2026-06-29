"""
CALCULO read-only: costo de la capa de exhibicion propuesta por Operaciones.
Modelo: target = piso_exhib(p% * demanda_semanal) + demanda*H + safety  (ADITIVO)
  gate = AX (por sala, de x_analisis_de_stock)
  p = 30% y 40%
Capital adicional de la politica = SUM(p * demanda_semanal * costo) sobre AX en salas.
Reporta total, por sala, Nueva Imperial. Tambien cuantas unidades/SKU para sanity.
"""
import sys, csv
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
SALAS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]   # excluye CD(26)/web(2)
SALA_NAME = {5:'Pangui790',6:'Los Lagos',7:'Futrono',8:'Pangui645',9:'Pangui763',
             10:'Lautaro',11:'San Jose',12:'Paillaco',13:'Mehuin',16:'Conaripe',
             17:'Nueva Imperial',18:'Malalhue'}
BEB_CATS = [1621, 1614]

n = odoo.search_count('x_analisis_de_stock',
    [('x_studio_abcxyz', '=', 'AX'), ('x_studio_team_id', 'in', SALAS)])
print("filas AX en salas:", n)

ax = odoo.search_read('x_analisis_de_stock',
    [('x_studio_abcxyz', '=', 'AX'), ('x_studio_team_id', 'in', SALAS)],
    ['x_studio_team_id', 'x_studio_product_id', 'x_studio_demanda_semanal'])

# costo + categoria por template
tids = list({r['x_studio_product_id'][0] for r in ax if r['x_studio_product_id']})
tinfo = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template', [('id', 'in', tids[i:i+500])],
                              ['standard_price', 'categ_id', 'x_studio_formato']):
        tinfo[t['id']] = t

beb_ids = set(odoo.execute('product.category', 'search', [('id', 'child_of', BEB_CATS)]))

rows = []
by_sala = defaultdict(lambda: {'sku':0,'u30':0.0,'u40':0.0,'c30':0.0,'c40':0.0,
                               'b_c30':0.0})
tot = {'u30':0.0,'c30':0.0,'c40':0.0,'b_c30':0.0}
for r in ax:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]
    team = r['x_studio_team_id'][0]
    mu = r.get('x_studio_demanda_semanal') or 0.0
    cost = tinfo.get(tid, {}).get('standard_price') or 0.0
    catid = (tinfo.get(tid, {}).get('categ_id') or [0])[0]
    es_beb = catid in beb_ids
    u30, u40 = 0.30*mu, 0.40*mu
    c30, c40 = u30*cost, u40*cost
    d = by_sala[SALA_NAME.get(team, str(team))]
    d['sku']+=1; d['u30']+=u30; d['u40']+=u40; d['c30']+=c30; d['c40']+=c40
    if es_beb: d['b_c30']+=c30
    tot['u30']+=u30; tot['c30']+=c30; tot['c40']+=c40
    if es_beb: tot['b_c30']+=c30
    rows.append({'sala':SALA_NAME.get(team,str(team)),
                 'producto':(r['x_studio_product_id'][1] or '')[:45],
                 'demanda_sem':round(mu,1),'piso30_u':round(u30,1),
                 'costo30':round(c30),'es_bebida':es_beb})

print(f"\n== CAPA EXHIBICION ADITIVA (AX, % demanda semanal) ==")
print(f"{'sala':16} {'#AX':>5} {'u@30%':>8} {'$@30%':>12} {'$@40%':>12} {'$@30% beb':>11}")
for s in sorted(by_sala, key=lambda x:-by_sala[x]['c30']):
    d=by_sala[s]
    print(f"{s:16} {d['sku']:5d} {d['u30']:8.0f} {d['c30']:12,.0f} {d['c40']:12,.0f} {d['b_c30']:11,.0f}")
print(f"{'TOTAL':16} {'':5} {tot['u30']:8.0f} {tot['c30']:12,.0f} {tot['c40']:12,.0f} {tot['b_c30']:11,.0f}")

print(f"\nCapital inmovilizado por la capa: @30% = ${tot['c30']:,.0f} | @40% = ${tot['c40']:,.0f}")
print(f"  de eso, bebidas(cerveza+gaseosa): @30% = ${tot['b_c30']:,.0f}")

print("\n== Nueva Imperial: top AX por costo de piso 30% ==")
ni = sorted([r for r in rows if r['sala']=='Nueva Imperial'], key=lambda x:-x['costo30'])[:25]
for r in ni:
    print(f"  {r['producto']:45} dem={r['demanda_sem']:6} piso30={r['piso30_u']:5} ${r['costo30']:,}")

out = Path(__file__).parent / 'resultados' / 'capa_exhibicion_operaciones.csv'
with out.open('w', newline='', encoding='utf-8-sig') as f:
    w=csv.DictWriter(f, fieldnames=['sala','producto','demanda_sem','piso30_u','costo30','es_bebida'])
    w.writeheader(); w.writerows(sorted(rows, key=lambda x:(x['sala'],-x['costo30'])))
print(f"\nCSV -> {out}")
