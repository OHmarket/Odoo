"""
CALCULO read-only (dry-run): impacto del piso de presentacion.
Diseno acordado:
  - Gate: abc in {A,B} (volumen, NO XYZ)
  - Piso por formato: lata 6 / vidrio 4 / pet 3 / sin_formato 3
  - Aplica solo a salas (excluye CD wh15) y solo a (SKU,sala) en SURTIDO
    (con venta en las ultimas 8 semanas en esa sala).
  - Deficit_a_piso = max(0, piso - stock_actual_en_sala)
Reporta por sala: #SKU bajo piso, unidades y $ para llenar a piso. Detalle Nueva Imperial.
NOTA: deficit BRUTO contra piso; parte lo repondria el motor por demanda. Es el techo del esfuerzo de presentacion.
"""
import sys, csv
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
CATS = [1621, 1614]
PISO = {'lata': 6, 'vidrio': 4, 'pet': 3, 'sin_formato': 3}
WEEK_FROM = '2026-05-01'  # ~8 semanas de surtido

# team -> warehouse_id (fallback del script productivo) -> code
TEAM_WH = {5:1, 6:4, 7:2, 8:3, 9:16, 10:8, 11:5, 12:9, 13:10, 16:12, 17:14, 18:13}
wh = odoo.search_read('stock.warehouse', [('id', 'in', list(TEAM_WH.values()))],
                      ['id', 'code', 'name'])
code_of_wh = {w['id']: w['code'] for w in wh}
name_of_wh = {w['id']: w['name'] for w in wh}
team_code = {t: code_of_wh[w] for t, w in TEAM_WH.items()}   # team -> 'IM495'
team_name = {t: name_of_wh[w] for t, w in TEAM_WH.items()}

# 1) SKUs A/B cerveza+bebida: pid, formato, costo
abc = odoo.search_read('x_calculo_abc_xyz',
    [('x_studio_abc', 'in', ['A', 'B']), ('x_studio_categ_id', 'child_of', CATS)],
    ['x_studio_product_id'])
pids = [r['x_studio_product_id'][0] for r in abc if r['x_studio_product_id']]
print(f"SKUs A/B cerveza+bebida (gate volumen): {len(pids)}")

pp = odoo.search_read('product.product', [('id', 'in', pids)],
                      ['product_tmpl_id', 'standard_price', 'default_code', 'name'])
tmpls = list({p['product_tmpl_id'][0] for p in pp if p['product_tmpl_id']})
tinfo = {t['id']: t for t in odoo.search_read('product.template',
         [('id', 'in', tmpls)], ['x_studio_formato', 'x_studio_pack_qty'])}
fmt_of = {}; cost_of = {}; name_of = {}; code_of = {}; is_pack = {}
import re
for p in pp:
    tid = p['product_tmpl_id'][0]
    fmt_of[p['id']] = tinfo.get(tid, {}).get('x_studio_formato') or 'sin_formato'
    cost_of[p['id']] = p.get('standard_price') or 0.0
    name_of[p['id']] = p['name']
    code_of[p['id']] = p.get('default_code') or ''
    pq = tinfo.get(tid, {}).get('x_studio_pack_qty') or 1
    # pack si pack_qty>1 o el nombre trae patron NxM (6X470, 12X350)
    nm = (p['name'] or '').upper()
    is_pack[p['id']] = bool((pq and pq > 1) or re.search(r'\b\d+\s*X\s*\d', nm))

# 2) surtido por sala: venta ult 8 sem (team, pid)
sg = odoo.execute('x_pos_week_sku_sale', 'read_group',
    [('x_studio_week_start', '>=', WEEK_FROM), ('x_studio_product_id', 'in', pids)],
    ['x_studio_qty_sold:sum'], ['x_studio_team_id', 'x_studio_product_id'], lazy=False)
surtido = defaultdict(set)   # team -> {pid}
for r in sg:
    if r['x_studio_team_id'] and r['x_studio_product_id'] and (r.get('x_studio_qty_sold') or 0) > 0:
        surtido[r['x_studio_team_id'][0]].add(r['x_studio_product_id'][0])

# 3) stock actual por (pid, warehouse code) excluyendo CD
cd_locs = set(odoo.execute('stock.location', 'search', [('id', 'child_of', 138)]))
rg = odoo.execute('stock.quant', 'read_group',
    [('product_id', 'in', pids), ('location_id.usage', '=', 'internal')],
    ['quantity:sum'], ['product_id', 'location_id'], lazy=False)
stock = defaultdict(float)   # (code, pid) -> qty
for r in rg:
    loc = r['location_id'][0]
    if loc in cd_locs:
        continue
    code = r['location_id'][1].split('/')[0]
    stock[(code, r['product_id'][0])] += r['quantity'] or 0

# piso para packs: 1 pack en cara (no 6). unidades sueltas usan PISO por formato.
PISO_PACK = 1

# 4) deficit a piso por (sala, pid en surtido), separando UNIDAD vs PACK
rows = []
by_sala = defaultdict(lambda: {'u_sku':0,'u_bajo':0,'u_def':0.0,'u_$':0.0,
                               'p_sku':0,'p_bajo':0,'p_def':0.0,'p_$':0.0})
for team, pset in surtido.items():
    if team not in team_code:   # excluye CD/web y teams no-sala
        continue
    code = team_code[team]; sname = team_name[team]
    for pid in pset:
        pack = is_pack.get(pid, False)
        fmt = fmt_of.get(pid, 'sin_formato')
        piso = PISO_PACK if pack else PISO.get(fmt, 3)
        st = stock.get((code, pid), 0.0)
        deficit = max(0.0, piso - st)
        d = by_sala[sname]
        if pack: d['p_sku'] += 1
        else:    d['u_sku'] += 1
        if deficit > 0:
            dd = deficit * cost_of.get(pid, 0.0)
            if pack: d['p_bajo']+=1; d['p_def']+=deficit; d['p_$']+=dd
            else:    d['u_bajo']+=1; d['u_def']+=deficit; d['u_$']+=dd
            rows.append({'sala': sname, 'tipo': 'PACK' if pack else 'unidad',
                         'code': code_of.get(pid), 'producto': name_of.get(pid, '')[:45],
                         'formato': fmt, 'piso': piso, 'stock': round(st, 1),
                         'deficit_u': round(deficit, 1),
                         'deficit_$': round(dd)})

print("\n== IMPACTO PISO POR SALA -- solo UNIDADES SUELTAS (lo creible) ==")
print(f"{'sala':22} {'surtidoU':>9} {'bajo':>6} {'unid':>6} {'$':>11}  | {'packs$':>10}")
tu = td = tpd = 0
for s in sorted(by_sala, key=lambda x: -by_sala[x]['u_$']):
    d = by_sala[s]
    tu += d['u_def']; td += d['u_$']; tpd += d['p_$']
    print(f"{s:22} {d['u_sku']:9d} {d['u_bajo']:6d} {d['u_def']:6.0f} {d['u_$']:11,.0f}  | {d['p_$']:10,.0f}")
print(f"{'TOTAL':22} {'':9} {'':6} {tu:6.0f} {td:11,.0f}  | {tpd:10,.0f}")
print(f"\nUNIDADES sueltas a piso: {td:,.0f}  |  PACKS a 1-pack: {tpd:,.0f}  |  combinado: {td+tpd:,.0f}")

print("\n== DETALLE Nueva Imperial -- UNIDADES SUELTAS bajo piso ==")
ni = sorted([r for r in rows if r['sala'] == 'Nueva Imperial' and r['tipo']=='unidad'],
            key=lambda x: -x['deficit_$'])
for r in ni:
    print(f"  [{r['code']:>13}] {r['producto']:45} {r['formato']:7} "
          f"piso={r['piso']} stock={r['stock']:5} def={r['deficit_u']:4.0f} ${r['deficit_$']:,}")

out = Path(__file__).parent / 'resultados' / 'impacto_piso.csv'
with out.open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['sala','tipo','code','producto','formato','piso','stock','deficit_u','deficit_$'])
    w.writeheader(); w.writerows(sorted(rows, key=lambda x: (x['sala'], -x['deficit_$'])))
print(f"\nCSV -> {out}")
print("NOTA: deficit BRUTO a piso. Parte ya la repondria el motor por demanda; el incremento NETO exige correr el motor con mu por sala.")
