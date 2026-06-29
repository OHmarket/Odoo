"""
CALCULO read-only (Fase A): piso de exhibicion para TODOS los SKU (sin gate AX,
sin gate de categoria bebidas), excluyendo cigarros, CD y Web.

  piso        = max(DIAS/7 * demanda_semanal, FLOOR_BY_FORMATO[formato])   (pack -> PACK_FLOOR)
  target_op   = x_studio_target_units    (el target REAL que el motor ya apunta)
  incremental = max(0, piso - target_op)  (capital de target que el FLOOR agrega)

Reporta el incremental por formato, categoria, sala y clase ABCXYZ, mas
sensibilidad a excluir muertos (demanda 0 / sin clasificacion). PROXY: usa
standard_price como costo, sin MOQ/redondeos ni propagacion al CD.

Iterar los params de arriba y volver a correr. Read-only: no escribe en Odoo.
"""
import sys, csv, re
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

# ─── PARAMS (iterar aca) ──────────────────────────────────────────────────────
DIAS = 2
FLOOR_BY_FORMATO = {'lata': 6, 'vidrio': 4, 'pet': 3, 'tetra': 3, 'sin_formato': 0}
PACK_FLOOR = 1
EXCLUDE_CIGARROS = [1628]
# Regla Marco: floorear si demanda local>0 O demanda de red>0 (un 0 local con
# venta en la red = falta de surtido en esa sala = hay que enviar). Solo se
# excluye el SKU MUERTO en toda la red (demanda_red==0, no vende en ningun lado).
SKIP_GLOBALLY_DEAD = True
# ──────────────────────────────────────────────────────────────────────────────

SALAS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]   # excluye CD(26) y Web(2)
SALA_NAME = {5: 'Pangui790', 6: 'Los Lagos', 7: 'Futrono', 8: 'Pangui645',
             9: 'Pangui763', 10: 'Lautaro', 11: 'San Jose', 12: 'Paillaco',
             13: 'Mehuin', 16: 'Conaripe', 17: 'Nueva Imperial', 18: 'Malalhue'}

odoo = OdooReader()
cigarros_ids = set(odoo.execute('product.category', 'search',
                                [('id', 'child_of', EXCLUDE_CIGARROS)]))

# 1) filas de analisis en salas
rows = odoo.search_read(
    'x_analisis_de_stock', [('x_studio_team_id', 'in', SALAS)],
    ['x_studio_team_id', 'x_studio_product_id', 'x_studio_demanda_semanal',
     'x_studio_target_units', 'x_studio_abcxyz', 'x_studio_categ_id',
     'x_studio_stock_proyectado'])
print(f"filas leidas: {len(rows)}")

# demanda de red por template = suma de demanda_semanal en todas las salas
global_mu = defaultdict(float)
for r in rows:
    if r['x_studio_product_id']:
        global_mu[r['x_studio_product_id'][0]] += (r.get('x_studio_demanda_semanal') or 0.0)

# 2) meta de templates (formato, name, costo, categoria)
tids = list({r['x_studio_product_id'][0] for r in rows if r['x_studio_product_id']})
tinfo = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template', [('id', 'in', tids[i:i+500])],
                              ['categ_id', 'x_studio_formato', 'standard_price', 'name']):
        tinfo[t['id']] = t

# 3) nombres de categoria para el desglose
catids = list({(t.get('categ_id') or [0])[0] for t in tinfo.values()})
catname = {c['id']: c['name'] for c in
           odoo.search_read('product.category', [('id', 'in', catids)], ['name'])}


def es_pack(name):
    return bool(re.search(r'\b\d+\s*X\s*\d', (name or '').upper()))


by_fmt = defaultdict(lambda: {'sku': 0, 'muerde': 0, 'inc_$': 0.0})
by_cat = defaultdict(lambda: {'sku': 0, 'muerde': 0, 'inc_$': 0.0})
by_sala = defaultdict(lambda: {'sku': 0, 'muerde': 0, 'inc_$': 0.0})
by_class = defaultdict(lambda: {'sku': 0, 'muerde': 0, 'inc_$': 0.0})
by_dem = defaultdict(lambda: {'muerde': 0, 'inc_$': 0.0})   # dem=0 vs dem>0
tot = {'sku': 0, 'muerde': 0, 'inc_$': 0.0, 'inc_$_dem0': 0.0, 'excl_cig': 0, 'excl_dead': 0}
out_rows = []

for r in rows:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]
    t = tinfo.get(tid, {})
    cat = (t.get('categ_id') or [0])[0]
    if cat in cigarros_ids:
        tot['excl_cig'] += 1
        continue

    abcxyz = (r.get('x_studio_abcxyz') or '').strip()
    mu = r.get('x_studio_demanda_semanal') or 0.0
    g_mu = global_mu.get(tid, 0.0)
    # floorear si vende local O vende en la red; saltar solo si muerto en toda la red
    if SKIP_GLOBALLY_DEAD and mu <= 0.0 and g_mu <= 0.0:
        tot['excl_dead'] += 1
        continue

    team = r['x_studio_team_id'][0]
    target_op = r.get('x_studio_target_units') or 0.0
    cost = t.get('standard_price') or 0.0
    fmt = t.get('x_studio_formato') or 'sin_formato'
    pack = es_pack(t.get('name'))

    stock_proy = r.get('x_studio_stock_proyectado') or 0.0
    fmt_floor = PACK_FLOOR if pack else FLOOR_BY_FORMATO.get(fmt, 0)
    piso = max(DIAS / 7.0 * mu, fmt_floor)
    inc = max(0.0, piso - target_op)            # alza del TARGET (objetivo)
    inc_d = inc * cost
    # compra incremental REAL = lo extra a comprar tras netear stock ya existente
    buy_base = max(0.0, target_op - stock_proy)
    buy_floor = max(0.0, max(target_op, piso) - stock_proy)
    inc_buy_u = buy_floor - buy_base
    inc_buy_d = inc_buy_u * cost
    tot['inc_buy_$'] = tot.get('inc_buy_$', 0.0) + inc_buy_d
    tot['inc_buy_u'] = tot.get('inc_buy_u', 0.0) + inc_buy_u
    # quien gobierna el piso: dias*demanda vs piso fisico de formato
    dias_term = DIAS / 7.0 * mu
    if inc > 0:
        if dias_term >= fmt_floor:
            tot['gob_dias_$'] = tot.get('gob_dias_$', 0.0) + inc_d
            tot['gob_dias_n'] = tot.get('gob_dias_n', 0) + 1
        else:
            tot['gob_fmt_$'] = tot.get('gob_fmt_$', 0.0) + inc_d
            tot['gob_fmt_n'] = tot.get('gob_fmt_n', 0) + 1

    sname = SALA_NAME.get(team, str(team))
    cname = catname.get(cat, str(cat))
    fkey = 'pack' if pack else fmt
    for agg, key in ((by_fmt, fkey), (by_cat, cname), (by_sala, sname),
                     (by_class, abcxyz or '(sin)')):
        agg[key]['sku'] += 1
    tot['sku'] += 1
    if inc > 0:
        tot['muerde'] += 1
        tot['inc_$'] += inc_d
        for agg, key in ((by_fmt, fkey), (by_cat, cname), (by_sala, sname),
                         (by_class, abcxyz or '(sin)')):
            agg[key]['muerde'] += 1
            agg[key]['inc_$'] += inc_d
        dk = 'dem=0' if mu <= 0.0 else 'dem>0'
        by_dem[dk]['muerde'] += 1
        by_dem[dk]['inc_$'] += inc_d
        if mu <= 0.0:
            tot['inc_$_dem0'] += inc_d
        out_rows.append({'sala': sname, 'categoria': cname, 'producto': (t.get('name') or '')[:42],
                         'fmt': fkey, 'abcxyz': abcxyz, 'demanda_sem': round(mu, 1),
                         'target_op': round(target_op, 1), 'piso': round(piso, 1),
                         'inc_u': round(inc, 1), 'inc_$': round(inc_d)})


def dump(title, d, namew=18):
    print(f"\n== {title} ==")
    print(f"  {'':{namew}} {'#sku':>6} {'muerde':>7} {'incremental$':>14}")
    for k in sorted(d, key=lambda x: -d[x]['inc_$']):
        v = d[k]
        print(f"  {str(k):{namew}} {v['sku']:6d} {v['muerde']:7d} {v['inc_$']:14,.0f}")


print(f"\nPARAMS  DIAS={DIAS}  FLOOR={FLOOR_BY_FORMATO}  PACK={PACK_FLOOR}  SKIP_GLOBALLY_DEAD={SKIP_GLOBALLY_DEAD}")
print(f"excluidos cigarros={tot['excl_cig']}  muertos_en_toda_la_red={tot['excl_dead']}")
print(f"\nINCREMENTAL TARGET (alza del objetivo de inventario): ${tot['inc_$']:,.0f}")
print(f"  de eso, SKU con demanda 0: ${tot['inc_$_dem0']:,.0f}")
print(f"COMPRA INCREMENTAL REAL (neteando stock ya existente):  ${tot.get('inc_buy_$',0.0):,.0f}")
_u = tot.get('inc_buy_u', 0.0)
print(f"  = {_u:,.0f} botellas/unidades nuevas, costo promedio ${tot.get('inc_buy_$',0.0)/max(_u,1):,.0f} c/u")
print(f"\nQUIEN GOBIERNA EL PISO (sobre el alza de target):")
print(f"  piso FISICO de formato (4 botellas, NO demanda): ${tot.get('gob_fmt_$',0.0):,.0f}  ({tot.get('gob_fmt_n',0)} filas)")
print(f"  dias*demanda (2 dias de venta):                   ${tot.get('gob_dias_$',0.0):,.0f}  ({tot.get('gob_dias_n',0)} filas)")
print(f"El floor muerde en {tot['muerde']}/{tot['sku']} filas SKUxsala "
      f"({100*tot['muerde']/max(tot['sku'],1):.0f}%)")
dump('por FORMATO', by_fmt)
dump('por CLASE ABCXYZ', by_class)
dump('por SALA', by_sala)
dump('por CATEGORIA (top 20)', {k: by_cat[k] for k in
     sorted(by_cat, key=lambda x: -by_cat[x]['inc_$'])[:20]}, namew=28)
print("\n== demanda 0 vs >0 (donde muerde) ==")
for k in ('dem=0', 'dem>0'):
    v = by_dem[k]
    print(f"  {k:8} muerde={v['muerde']:6d}  inc=${v['inc_$']:,.0f}")

outdir = Path(__file__).parent / 'resultados'
outdir.mkdir(exist_ok=True)
out = outdir / 'floor_allsku.csv'
with out.open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['sala', 'categoria', 'producto', 'fmt', 'abcxyz',
                                      'demanda_sem', 'target_op', 'piso', 'inc_u', 'inc_$'])
    w.writeheader()
    w.writerows(sorted(out_rows, key=lambda x: -x['inc_$']))
print(f"\nCSV -> {out}  ({len(out_rows)} filas donde el floor muerde)")
