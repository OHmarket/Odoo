"""
DIAG read-only: de donde deberia salir el piso por formato.
Mira el stock REAL que sostienen las salas (stock_real>0) por formato y por
grupo de categoria (frio vs licoreria), y reporta percentiles. El piso de
exhibicion deberia anclarse en esto (p25 sostenido ~ presencia minima real),
no en un "1 pack" asumido.
"""
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SALAS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]
odoo = OdooReader()
cig = set(odoo.execute('product.category', 'search', [('id', 'child_of', [1628])]))

rows = odoo.search_read(
    'x_analisis_de_stock', [('x_studio_team_id', 'in', SALAS)],
    ['x_studio_product_id', 'x_studio_stock_real', 'x_studio_demanda_semanal',
     'x_studio_categ_id'])
tids = list({r['x_studio_product_id'][0] for r in rows if r['x_studio_product_id']})
fmt = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template', [('id', 'in', tids[i:i+500])],
                              ['x_studio_formato', 'categ_id']):
        fmt[t['id']] = t
catname = {c['id']: c['name'] for c in odoo.search_read(
    'product.category', [('id', 'in', list({(t.get('categ_id') or [0])[0] for t in fmt.values()}))], ['name'])}

# grupo grueso: licoreria vs frio/otros por nombre de categoria
LIC = ('Whisky', 'Pisco', 'Vino', 'Licor', 'Gin', 'Ron', 'Tequila', 'Vodka',
       'Espumante', 'Sidra', 'Coctel', 'Coctel', 'Sangr', 'Aperitivo', 'Cremas')


def grupo(cn):
    return 'licoreria' if any(k.lower() in (cn or '').lower() for k in LIC) else 'frio/otros'


def pct(vals, q):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(int(q * len(v)), len(v) - 1)]


# acumular stock_real (>0) por (formato, grupo); solo SKU con demanda (vivos)
buckets = defaultdict(list)
for r in rows:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]
    t = fmt.get(tid, {})
    cat = (t.get('categ_id') or [0])[0]
    if cat in cig:
        continue
    sr = r.get('x_studio_stock_real') or 0.0
    mu = r.get('x_studio_demanda_semanal') or 0.0
    if sr <= 0 or mu <= 0:        # solo en-stock y con venta (presencia real sostenida)
        continue
    f = t.get('x_studio_formato') or 'sin_formato'
    g = grupo(catname.get(cat, ''))
    buckets[(f, g)].append(sr)

print("Stock REAL sostenido (unidades) por formato x grupo  [solo en-stock con venta]")
print(f"{'formato':10} {'grupo':12} {'n':>6} {'p10':>5} {'p25':>5} {'mediana':>7} {'p75':>6}")
for k in sorted(buckets, key=lambda x: (x[0], x[1])):
    v = buckets[k]
    print(f"{k[0]:10} {k[1]:12} {len(v):6d} {pct(v,.10):5.0f} {pct(v,.25):5.0f} "
          f"{pct(v,.50):7.0f} {pct(v,.75):6.0f}")
