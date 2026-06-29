# -*- coding: utf-8 -*-
"""
Impacto en SKU de bajo volumen del modelo DSD sin CD grande.

Pregunta (Marco, 2026-06-23): con el snapshot de x_analisis_de_stock, ver el
impacto en SKU de bajo volumen donde "la vuelta no da 30 dias": una caja minima
(MOQ) dura mas de 30 dias en sala porque venden poco. En el modelo DSD sin CD
estos obligan a 790 (mini-CD) o inmovilizan caja en sala.

Metrica: cobertura_caja_weeks = MOQ / mu_week (run-rate semanal).
  - "no da 30 dias" si cobertura_caja_weeks > 30/7 = 4.286 sem.
Read-only XML-RPC.
"""
from shared.odoo_xmlrpc import OdooReader
import pandas as pd

THRESH_30D_WEEKS = 30.0 / 7.0   # 4.286 sem
DEMAND_FLOOR = 1.0 / 4.345      # ~0.23 u/sem
CD_TEAM, WEB_TEAM = 26, 2

M = 'x_analisis_de_stock'
FIELDS = [
    'x_studio_team_id', 'x_studio_product_id', 'x_studio_categ_id',
    'x_studio_abcxyz', 'x_studio_mu_week', 'x_studio_demanda_semanal',
    'x_studio_moq', 'x_studio_cover_weeks', 'x_studio_buy_action',
    'x_studio_supply_source', 'x_studio_purchase_price_cash_unit',
    'x_studio_qty_a_pedir', 'x_studio_valor_orden_compra',
    'x_studio_decision_reason',
]

o = OdooReader()
rows = o.search_read(M, [], fields=FIELDS, order='id')
df = pd.DataFrame(rows)

def m2o(v):
    return v[0] if isinstance(v, list) and v else (v if v else None)

df['team_id'] = df['x_studio_team_id'].map(m2o)
df['product_id'] = df['x_studio_product_id'].map(m2o)
for c in ['x_studio_mu_week', 'x_studio_demanda_semanal', 'x_studio_moq',
          'x_studio_cover_weeks', 'x_studio_purchase_price_cash_unit',
          'x_studio_qty_a_pedir', 'x_studio_valor_orden_compra']:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

# Marcar hijos phantom (visibles pero NO compran: el padre compra por el pool).
# Excluirlos evita inflar el universo y doble-contar demanda.
dr = df['x_studio_decision_reason'].fillna('')
df['phantom_child'] = dr.str.contains('phantom_child|blocked_child', case=False)

# Separar salas vs CD/web
salas_all = df[~df['team_id'].isin([CD_TEAM, WEB_TEAM])].copy()
salas = salas_all[~salas_all['phantom_child']].copy()
cd = df[df['team_id'] == CD_TEAM].copy()

print('RECONCILIACION UNIVERSO')
print('  product_id distinct en snapshot       :', df['product_id'].nunique())
print('  lineas salas (todas)                  :', len(salas_all))
print('  lineas hijo-phantom en salas (no compran):', int(salas_all['phantom_child'].sum()))
print('  lineas salas REALES (compran/deciden) :', len(salas))
print('  product_id distinct salas reales      :', salas['product_id'].nunique())
print()

# Run-rate semanal: mu_week; fallback demanda_semanal
salas['runrate'] = salas['x_studio_mu_week'].where(
    salas['x_studio_mu_week'] > 0, salas['x_studio_demanda_semanal'])
salas['runrate_eff'] = salas['runrate'].clip(lower=DEMAND_FLOOR)
salas['moq'] = salas['x_studio_moq'].clip(lower=1.0)
salas['cob_caja_w'] = salas['moq'] / salas['runrate_eff']
salas['caja_cash'] = salas['moq'] * salas['x_studio_purchase_price_cash_unit']

# Solo lineas con demanda real (vendibles) — bajo volumen real, no SKU muertos
con_demanda = salas[salas['runrate'] > 0].copy()

# Flag: una caja no rota en 30 dias
flag = con_demanda[con_demanda['cob_caja_w'] > THRESH_30D_WEEKS].copy()

def bucket_mos(w):
    if w <= 4.286:   return '<=1 mes (ok)'
    if w < 8.69:     return '1-2 meses'
    if w < 13.0:     return '2-3 meses'
    if w < 26.0:     return '3-6 meses'
    if w < 52.0:     return '6-12 meses'
    return '>1 anio'

flag['mos_bucket'] = flag['cob_caja_w'].map(bucket_mos)

print('=' * 70)
print('UNIVERSO SALAS (excl. CD team 26, Web team 2)')
print('=' * 70)
print('lineas SKU-sala totales        :', len(salas))
print('lineas con demanda > 0         :', len(con_demanda))
print('SKU distintos con demanda      :', con_demanda['product_id'].nunique())
print()
print('=' * 70)
print('"LA VUELTA NO DA 30 DIAS" (1 caja > 30 dias de cobertura)')
print('=' * 70)
print('lineas SKU-sala flagged        :', len(flag),
      '(%.0f%% de las con demanda)' % (100*len(flag)/max(len(con_demanda),1)))
print('SKU distintos flagged          :', flag['product_id'].nunique())
print('caja inmovilizada (1 caja/linea): $%s' % f"{flag['caja_cash'].sum():,.0f}")
print()
print('--- por bucket de meses de stock que deja UNA caja ---')
b = flag.groupby('mos_bucket').agg(
    lineas=('product_id', 'size'),
    skus=('product_id', 'nunique'),
    caja_cash=('caja_cash', 'sum'),
    cob_med_w=('cob_caja_w', 'median'),
).reindex(['1-2 meses','2-3 meses','3-6 meses','6-12 meses','>1 anio']).dropna(how='all')
pd.options.display.float_format = lambda v: f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}"
print(b.to_string())
print()
print('--- por ABCXYZ ---')
a = flag.groupby('x_studio_abcxyz').agg(
    lineas=('product_id', 'size'),
    skus=('product_id', 'nunique'),
    caja_cash=('caja_cash', 'sum'),
    cob_med_w=('cob_caja_w', 'median'),
).sort_values('caja_cash', ascending=False)
print(a.to_string())
print()
print('=' * 70)
print('RUTEO ACTUAL de estas lineas (que hace hoy el motor con el CD)')
print('=' * 70)
print(flag['x_studio_buy_action'].value_counts().to_string())
print()
print('supply_source:')
print(flag['x_studio_supply_source'].value_counts().to_string())

# Comparacion CD vs decentralizar: cash si cada sala tiene su caja vs 1 caja consolidada
print()
print('=' * 70)
print('IMPACTO CAJA: consolidar en 790 vs caja por sala')
print('=' * 70)
# por SKU: nro de salas que lo necesitan flagged, y cash si cada una tiene 1 caja
per_sku = flag.groupby('product_id').agg(
    n_salas=('team_id', 'nunique'),
    caja_unit=('caja_cash', 'mean'),
    caja_total_salas=('caja_cash', 'sum'),
)
cash_descentralizado = per_sku['caja_total_salas'].sum()
cash_consolidado_790 = (per_sku['caja_unit']).sum()  # 1 caja por SKU en 790
print('SKU flagged distintos          :', len(per_sku))
print('cash si CADA sala tiene 1 caja : $%s' % f"{cash_descentralizado:,.0f}")
print('cash si 1 caja consolidada/790 : $%s' % f"{cash_consolidado_790:,.0f}")
print('sobre-inmovilizacion por descentralizar: $%s' %
      f"{cash_descentralizado - cash_consolidado_790:,.0f}")

flag.to_csv(
    'proyectos/2026-06-23-reestructuracion-dsd/resultados/sku_no_da_30d.csv',
    index=False, sep=';', decimal=',', encoding='utf-8-sig')
print()
print('CSV: resultados/sku_no_da_30d.csv')
