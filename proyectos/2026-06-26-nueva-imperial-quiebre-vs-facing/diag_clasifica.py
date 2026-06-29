"""
DIAG read-only: clasifica SKUs cerveza+bebida de Nueva Imperial en
QUIEBRE vs FACING-sospecha cruzando stock teorico (quant) con venta
semanal reciente (x_pos_week_sku_sale team 17, ultimas 6 sem).
"""
import sys, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
LOC = 115
CATS = [1621, 1614]
TEAM = 17
WEEK_FROM = '2026-05-15'   # ~6 semanas

# relacion de x_studio_product_id (template vs variant)
rel = odoo.fields_get('x_pos_week_sku_sale', ['relation'])
print("x_studio_product_id relation:", rel.get('x_studio_product_id', {}).get('relation'))

# 1) stock teorico por product.product
rg = odoo.execute(
    'stock.quant', 'read_group',
    [('location_id', 'child_of', LOC), ('product_id.categ_id', 'child_of', CATS)],
    ['quantity:sum', 'reserved_quantity:sum'], ['product_id'], lazy=False,
)
stock = {}
for r in rg:
    pid = r['product_id'][0]
    qty = (r.get('quantity') or 0) - (r.get('reserved_quantity') or 0)
    stock[pid] = {'name': r['product_id'][1], 'stock': qty}

# map product.product -> template id (para cruzar con venta si es por template)
pp = odoo.search_read('product.product', [('id', 'in', list(stock))],
                      ['product_tmpl_id', 'default_code'])
tmpl_of = {p['id']: (p['product_tmpl_id'][0] if p['product_tmpl_id'] else None) for p in pp}
code_of = {p['id']: p.get('default_code') for p in pp}

# 2) venta reciente team 17 por producto
sg = odoo.execute(
    'x_pos_week_sku_sale', 'read_group',
    [('x_studio_team_id', '=', TEAM),
     ('x_studio_week_start', '>=', WEEK_FROM),
     ('x_studio_product_id.categ_id', 'child_of', CATS)],
    ['x_studio_qty_sold:sum'], ['x_studio_product_id'], lazy=False,
)
sold = {}
for r in sg:
    if r['x_studio_product_id']:
        sold[r['x_studio_product_id'][0]] = r.get('x_studio_qty_sold') or 0

# decidir clave de cruce: ids de venta vs product.product vs template
sold_ids = set(sold)
inter_pp = len(sold_ids & set(stock))
inter_tm = len(sold_ids & set(tmpl_of.values()))
print(f"venta keys={len(sold_ids)} | match product.product={inter_pp} | match template={inter_tm}")
by_template = inter_tm >= inter_pp

rows = []
for pid, d in stock.items():
    key = tmpl_of[pid] if by_template else pid
    qsold = sold.get(key, 0)
    st = d['stock']
    if st <= 0:
        clase = 'QUIEBRE'
    elif qsold <= 0:
        clase = 'FACING-sospecha (stock>0 sin venta 6sem)'
    else:
        clase = 'OK (stock>0 y rota)'
    rows.append({'code': code_of.get(pid) or '', 'producto': d['name'],
                 'stock': round(st, 1), 'venta_6sem': round(qsold, 1), 'clase': clase})

rows.sort(key=lambda x: (x['clase'], -x['venta_6sem']))

out = Path(__file__).parent / 'resultados' / 'clasificacion.csv'
with out.open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['code', 'producto', 'stock', 'venta_6sem', 'clase'])
    w.writeheader(); w.writerows(rows)

from collections import Counter
c = Counter(r['clase'] for r in rows)
print("\n== RESUMEN (cerveza+bebida Nueva Imperial) ==")
for k, v in sorted(c.items()):
    print(f"  {v:3d}  {k}")

print("\n== QUIEBRE (stock<=0) ==")
for r in [x for x in rows if x['clase'] == 'QUIEBRE']:
    print(f"  {r['stock']:6.1f}  v6={r['venta_6sem']:5.1f}  {r['producto'][:55]}")

print("\n== FACING-sospecha (stock>0, sin venta 6 sem) ==")
for r in [x for x in rows if x['clase'].startswith('FACING')]:
    print(f"  {r['stock']:6.1f}  {r['producto'][:60]}")

print(f"\nCSV -> {out}")
