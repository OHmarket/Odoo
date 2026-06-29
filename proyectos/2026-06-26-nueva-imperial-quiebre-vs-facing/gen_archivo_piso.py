"""
Genera el archivo de piso de exhibicion por SKU x sala (toda la cadena).
Columnas pedidas: SKU, Demanda Semanal, Seguridad, Stock Piso, Costo Piso.
+ contexto para filtrar en Excel (Sala, Codigo, Categoria, Formato, Target, Costo Unit).

Piso (modelo en evaluacion): stock_piso = max(DIAS/7*demanda, PISO_FORMATO[formato]).
Read-only. Salida Excel-CL (sep ';', decimal ',', utf-8-sig).
"""
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader
import pandas as pd
import re
import math

# ─── PARAMS ───────────────────────────────────────────────────────────────────
# Modelo SAP minimum-target-stock con UMBRAL de demanda:
#   si demanda_semanal > DEMANDA_UMBRAL_SEM:  stock_minimo = ceil( (DIAS/7) * demanda_semanal )
#   si no:                                    stock_minimo = 0
# DIAS = rango minimo de cobertura. DEMANDA_UMBRAL_SEM = solo rotadores reciben piso.
DIAS = 3
DEMANDA_UMBRAL_SEM = 3.0
EXCLUDE_CIGARROS = [1628]
SKIP_GLOBALLY_DEAD = True
# ──────────────────────────────────────────────────────────────────────────────

SALAS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]
SALA_NAME = {5: 'Pangui790', 6: 'Los Lagos', 7: 'Futrono', 8: 'Pangui645',
             9: 'Pangui763', 10: 'Lautaro', 11: 'San Jose', 12: 'Paillaco',
             13: 'Mehuin', 16: 'Conaripe', 17: 'Nueva Imperial', 18: 'Malalhue'}

odoo = OdooReader()
cigarros_ids = set(odoo.execute('product.category', 'search',
                                [('id', 'child_of', EXCLUDE_CIGARROS)]))

rows = odoo.search_read(
    'x_analisis_de_stock', [('x_studio_team_id', 'in', SALAS)],
    ['x_studio_team_id', 'x_studio_product_id', 'x_studio_demanda_semanal',
     'x_studio_safety_stock_units', 'x_studio_target_units', 'x_studio_abcxyz',
     'x_studio_categ_id'])
print(f"filas leidas: {len(rows)}")

global_mu = defaultdict(float)
for r in rows:
    if r['x_studio_product_id']:
        global_mu[r['x_studio_product_id'][0]] += (r.get('x_studio_demanda_semanal') or 0.0)

tids = list({r['x_studio_product_id'][0] for r in rows if r['x_studio_product_id']})
tinfo = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template', [('id', 'in', tids[i:i+500])],
                              ['default_code', 'name', 'categ_id', 'x_studio_formato',
                               'standard_price', 'active', 'available_in_pos']):
        tinfo[t['id']] = t
catids = list({(t.get('categ_id') or [0])[0] for t in tinfo.values()})
catname = {c['id']: c['name'] for c in
           odoo.search_read('product.category', [('id', 'in', catids)], ['name'])}


def es_pack(name):
    return bool(re.search(r'\b\d+\s*X\s*\d', (name or '').upper()))


out = []
for r in rows:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]
    t = tinfo.get(tid, {})
    # solo productos activos y disponibles en POS (venta POS activa)
    if not (t.get('active') and t.get('available_in_pos')):
        continue
    cat = (t.get('categ_id') or [0])[0]
    if cat in cigarros_ids:
        continue
    mu = r.get('x_studio_demanda_semanal') or 0.0
    if SKIP_GLOBALLY_DEAD and mu <= 0.0 and global_mu.get(tid, 0.0) <= 0.0:
        continue

    cost = t.get('standard_price') or 0.0
    target_op = r.get('x_studio_target_units') or 0.0          # = demanda·H + seguridad
    seguridad = r.get('x_studio_safety_stock_units') or 0.0
    demanda_calc = max(0.0, target_op - seguridad)             # parte de demanda (demanda·H)
    # solo rotadores (demanda > umbral) reciben piso; lentos quedan en 0
    raw_piso = math.ceil(DIAS / 7.0 * mu) if mu > DEMANDA_UMBRAL_SEM else 0
    # redondeo a packs: multiplos de 6; lo menor a 6 (pero >0) queda en 3
    if raw_piso <= 0:
        stock_minimo = 0
    elif raw_piso < 6:
        stock_minimo = 3
    else:
        stock_minimo = int(round(raw_piso / 6.0) * 6)
    minimo_manual = 0.0                                        # reserva manual extra (Oracle presentation stock curado)
    # MODELO ADITIVO (presentation stock): el piso se SUMA, no es max.
    # target final = piso + demanda_calculada + seguridad + minimo_manual
    target_final = stock_minimo + demanda_calc + seguridad + minimo_manual

    out.append({
        'Sala': SALA_NAME.get(r['x_studio_team_id'][0], str(r['x_studio_team_id'][0])),
        'Codigo': t.get('default_code') or '',
        'SKU': (t.get('name') or ''),
        'Categoria': catname.get(cat, str(cat)),
        'ABCXYZ': (r.get('x_studio_abcxyz') or '').strip(),
        'Demanda Semanal': round(mu, 2),
        'Stock Minimo (3d)': round(stock_minimo, 2),
        'Demanda Calculada': round(demanda_calc, 2),
        'Seguridad': round(seguridad, 2),
        'Minimo Manual': '',                                   # Operaciones llena los ceros a exhibir
        'Target Final': round(target_final, 2),
        'Costo Unitario': round(cost, 0),
        'Costo Target Final': round(target_final * cost, 0),
    })

df = pd.DataFrame(out).sort_values(['Sala', 'Costo Target Final'], ascending=[True, False])
outdir = Path(__file__).parent / 'resultados'
outdir.mkdir(exist_ok=True)
fp = outdir / 'piso_exhibicion_cadena.csv'
df.to_csv(fp, sep=';', decimal=',', encoding='utf-8-sig', index=False)

manda_base = (df['Stock Minimo (3d)'] > (df['Demanda Calculada'] + df['Seguridad'])).sum()
print(f"\nfilas: {len(df):,}")
print(f"Stock Minimo (3d) total (u):     {df['Stock Minimo (3d)'].sum():,.0f}")
print(f"Demanda Calculada total (u):     {df['Demanda Calculada'].sum():,.0f}")
print(f"Seguridad total (u):             {df['Seguridad'].sum():,.0f}")
print(f"Target Final total (u):          {df['Target Final'].sum():,.0f}")
print(f"Costo Target Final total:        ${df['Costo Target Final'].sum():,.0f}")
print(f"\nCSV -> {fp}")

# costo estimado del PISO por clase ABCXYZ (lo que suma el modelo aditivo)
df['Costo Piso'] = df['Stock Minimo (3d)'] * df['Costo Unitario']
g = df.groupby('ABCXYZ').agg(
    sku=('SKU', 'size'),
    con_piso=('Stock Minimo (3d)', lambda s: (s > 0).sum()),
    piso_u=('Stock Minimo (3d)', 'sum'),
    costo_piso=('Costo Piso', 'sum')).sort_values('costo_piso', ascending=False)
print("\n== COSTO DEL PISO POR ABCXYZ ==")
print(f"  {'clase':6} {'#sku':>6} {'con_piso':>9} {'piso_u':>8} {'costo_piso':>15}")
for k, row in g.iterrows():
    print(f"  {str(k) or '(sin)':6} {int(row['sku']):6d} {int(row['con_piso']):9d} "
          f"{int(row['piso_u']):8d} {row['costo_piso']:15,.0f}")
print(f"  {'TOTAL':6} {len(df):6d} {int((df['Stock Minimo (3d)']>0).sum()):9d} "
      f"{int(df['Stock Minimo (3d)'].sum()):8d} {df['Costo Piso'].sum():15,.0f}")
