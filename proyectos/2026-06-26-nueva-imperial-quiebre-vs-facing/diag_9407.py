"""
DIAG read-only: caso 9407 (Stella 660) y los SKUs de ALTO volumen.
Pregunta: el piso constante por formato, sirve para los de alto volumen?
Mide mu, formato, abcxyz, stock por sala y compara contra el piso propuesto.
Ademas lista top-volumen cerveza/bebida y su abcxyz para ver cuantos
caerian FUERA del gate AX/BX.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
CATS = [1621, 1614]
PISO = {'lata': 6, 'vidrio': 4, 'pet': 3, 'sin_formato': 3}

# salas (excluir CD wh15 loc 138)
cd_locs = set(odoo.execute('stock.location', 'search', [('id', 'child_of', 138)]))

def stock_por_sala(pid):
    rg = odoo.execute('stock.quant', 'read_group',
        [('product_id', '=', pid), ('location_id.usage', '=', 'internal')],
        ['quantity:sum'], ['location_id'], lazy=False)
    out = {}
    for r in rg:
        loc = r['location_id'][0]
        if loc in cd_locs:
            continue
        out[r['location_id'][1]] = r['quantity']
    return out

# --- caso 9407 ---
pp = odoo.search_read('product.product', [('default_code', '=', '9407')],
                      ['id', 'name', 'product_tmpl_id'])
print("== 9407 ==")
for p in pp:
    pid = p['id']
    t = odoo.search_read('product.template', [('id', '=', p['product_tmpl_id'][0])],
                         ['x_studio_formato', 'x_studio_pack_qty'])[0]
    abc = odoo.search_read('x_calculo_abc_xyz', [('x_studio_product_id', '=', pid)],
                           ['x_studio_abcxyz', 'x_studio_mu_week'])
    fmt = t.get('x_studio_formato') or 'sin_formato'
    mu_w = abc[0]['x_studio_mu_week'] if abc else None
    abcxyz = abc[0]['x_studio_abcxyz'] if abc else None
    print(f"  {p['name']}")
    print(f"  formato={fmt} pack={t.get('x_studio_pack_qty')} abcxyz={abcxyz} "
          f"mu_week(global)={mu_w}")
    print(f"  piso constante propuesto para {fmt} = {PISO.get(fmt)} uds")
    if mu_w:
        print(f"  -> mu_dia global ~{mu_w/7:.0f}/dia; piso {PISO.get(fmt)} = "
              f"{PISO.get(fmt)/(mu_w/7)*24:.1f} horas de venta global")
    sp = stock_por_sala(pid)
    print("  stock por sala:", {k: round(v) for k, v in sorted(sp.items())})

# --- top volumen cerveza/bebida y su abcxyz (cuantos fuera de AX/BX) ---
print("\n== TOP 20 volumen (mu_week) cerveza+bebida y gate AX/BX ==")
top = odoo.search_read('x_calculo_abc_xyz',
    [('x_studio_categ_id', 'child_of', CATS)],
    ['x_studio_product_id', 'x_studio_abcxyz', 'x_studio_mu_week'],
    order='x_studio_mu_week desc', limit=20)
fuera = 0
for r in top:
    g = r['x_studio_abcxyz']
    en_gate = g in ('AX', 'BX')
    if not en_gate:
        fuera += 1
    print(f"  {str(g):4} mu={r['x_studio_mu_week']:8.0f}  "
          f"{'IN ' if en_gate else 'OUT'}  {r['x_studio_product_id'][1][:48]}")
print(f"\nDe los top-20 volumen, FUERA del gate AX/BX: {fuera}")
