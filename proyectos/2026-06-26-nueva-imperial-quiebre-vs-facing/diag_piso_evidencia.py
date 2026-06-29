"""
DIAG read-only: dimensiona el piso de presentacion por formato sobre EVIDENCIA.
Mide, para SKUs A/B-X de cerveza+bebida, cuantas unidades sostienen las salas
(stock.quant>0 por SKU x sala, excluyendo el CD) y reporta la distribucion por
formato (lata/pet/vidrio). Propuesta de piso = p25 redondeado (defensivo).
"""
import sys, statistics as st
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
CATS = [1621, 1614]

# 1) CD: ubicacion a excluir (wh15)
wh15 = odoo.search_read('stock.warehouse', [('id', '=', 15)], ['view_location_id'])
cd_loc = wh15[0]['view_location_id'][0]
print("CD view_location_id (excluir):", cd_loc)

# 2) set A/B-X cerveza+bebida -> product.product ids + formato
abc = odoo.search_read('x_calculo_abc_xyz',
    [('x_studio_abcxyz', 'in', ['AX', 'BX']), ('x_studio_categ_id', 'child_of', CATS)],
    ['x_studio_product_id', 'x_studio_abcxyz'])
pids = [r['x_studio_product_id'][0] for r in abc if r['x_studio_product_id']]
print(f"SKUs A/B-X cerveza+bebida: {len(pids)}")

# formato via template
pp = odoo.search_read('product.product', [('id', 'in', pids)], ['product_tmpl_id'])
tmpls = list({p['product_tmpl_id'][0] for p in pp if p['product_tmpl_id']})
tinfo = odoo.search_read('product.template', [('id', 'in', tmpls)],
                         ['x_studio_formato', 'x_studio_pack_qty'])
fmt_of_tmpl = {t['id']: (t.get('x_studio_formato') or 'sin_formato') for t in tinfo}
pack_of_tmpl = {t['id']: (t.get('x_studio_pack_qty') or 1) for t in tinfo}
fmt_of_pid = {p['id']: fmt_of_tmpl.get(p['product_tmpl_id'][0], 'sin_formato')
              for p in pp if p['product_tmpl_id']}
pack_of_pid = {p['id']: pack_of_tmpl.get(p['product_tmpl_id'][0], 1)
               for p in pp if p['product_tmpl_id']}

# 3) stock por SKU x sala (loc interna, NO CD, qty>0)
rg = odoo.execute(
    'stock.quant', 'read_group',
    [('product_id', 'in', pids), ('location_id.usage', '=', 'internal'),
     ('quantity', '>', 0)],
    ['quantity:sum'], ['product_id', 'location_id'], lazy=False,
)
# excluir filas del CD: necesitamos child_of cd_loc -> traer locs hijas del CD
cd_locs = set(odoo.execute('stock.location', 'search',
                           [('id', 'child_of', cd_loc)]))

by_fmt = defaultdict(list)
for r in rg:
    loc = r['location_id'][0]
    if loc in cd_locs:
        continue
    pid = r['product_id'][0]
    by_fmt[fmt_of_pid.get(pid, 'sin_formato')].append(r['quantity'])

print("\n== unidades sostenidas por SKU x sala, por formato ==")
print(f"{'formato':12} {'n':>5} {'p25':>6} {'mediana':>8} {'p75':>6} {'pack_tip':>9}")
prop = {}
for fmt in ['lata', 'vidrio', 'pet', 'sin_formato']:
    vals = sorted(by_fmt.get(fmt, []))
    if not vals:
        continue
    q = st.quantiles(vals, n=4) if len(vals) >= 4 else [vals[0], st.median(vals), vals[-1]]
    p25, med, p75 = q[0], st.median(vals), q[2]
    # pack tipico del formato
    packs = [pack_of_pid[p] for p in pids if fmt_of_pid.get(p) == fmt and pack_of_pid.get(p, 1) > 1]
    pack_tip = int(st.median(packs)) if packs else 1
    prop[fmt] = (round(p25), pack_tip)
    print(f"{fmt:12} {len(vals):5d} {p25:6.0f} {med:8.0f} {p75:6.0f} {pack_tip:9d}")

print("\n== PROPUESTA piso (p25 sostenido, ref pack) ==")
for fmt, (p25, pack) in prop.items():
    print(f"  {fmt:12} piso~{p25}  (pack tipico {pack})")
