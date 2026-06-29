# -*- coding: utf-8 -*-
"""
Chequeo de reconciliación re-ejecutable. Corre los 4 detectores de error +
tie-outs y emite PASS/WARN/FAIL. Correr ANTES de cualquier informe.

    PYTHONPATH=. python proyectos/2026-06-22-reconciliacion-fuentes/reconciliacion.py
"""
import os, sys, datetime
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from definiciones import (Fuentes, CD_TEAMS, NO_SALA_TEAMS, CACHE_PARQUET,
                          CACHE_MAX_STALE_DAYS, MODELO_VENTA)

f = Fuentes()
o = f.o
res = []
def chk(nombre, estado, detalle):
    res.append((estado, nombre, detalle))

# ---- 1. CACHE: frescura + cobertura vs modelo vivo ----
cache = pd.read_parquet(CACHE_PARQUET, columns=['week_start', 'product_id'])
maxw = pd.to_datetime(cache['week_start']).max().date()
stale = (datetime.date.today() - maxw).days
filas_cache = len(pd.read_parquet(CACHE_PARQUET, columns=['qty_sold']))
filas_vivo = o.search_count(MODELO_VENTA, [])
cob = 100 * filas_cache / filas_vivo if filas_vivo else 0
estado = 'PASS' if (stale <= CACHE_MAX_STALE_DAYS and cob >= 98) else 'FAIL'
chk('1. Cache venta fresco y completo', estado,
    f'stale {stale}d (max {CACHE_MAX_STALE_DAYS}) | cobertura {cob:.1f}% ({filas_cache:,}/{filas_vivo:,} filas)')

# ---- 2. KIT phantom double-count en stock ----
raw = f.stock_raw()
kit_val = raw[raw.es_kit].stock_val.sum()
estado = 'PASS' if kit_val == 0 else 'WARN'
chk('2. Sin double-count de kits phantom', estado,
    f'${kit_val:,.0f} en {int(raw.es_kit.sum())} filas de kit con stock fantasma (se excluye en lectura)')

# ---- 3. CD tratado como sala ----
cd_val = raw[raw.es_cd].stock_val.sum()
# venta a público del CD en 13 sem (deberia ser ~0)
v = f.venta_semanal(weeks_back=13)
cd_venta = v[v.team_id.isin(CD_TEAMS)].qty_sold.sum()
estado = 'PASS' if cd_venta < 1 else 'WARN'
chk('3. CD/echelon separado de salas', estado,
    f'CD stock ${cd_val:,.0f} (pipeline, NO parado) | venta pública CD 13s = {cd_venta:.0f} u')

# ---- 4. TIE-OUT waterfall de stock ----
total = raw.stock_val.sum()
combo = raw[raw.es_combo & ~raw.es_kit].stock_val.sum()
real_salas = f.stock_salas().stock_val.sum()
cd_clean = f.stock_cd().stock_val.sum()
online = raw[(raw.team_id.isin(NO_SALA_TEAMS)) & ~raw.es_cd & ~raw.es_kit & ~raw.es_combo].stock_val.sum()
suma = real_salas + cd_clean + online + kit_val + combo
diff = total - suma
estado = 'PASS' if abs(diff) < 1 else 'FAIL'
chk('4. Tie-out stock (suma = total)', estado,
    f'total ${total:,.0f} = salas ${real_salas:,.0f} + CD ${cd_clean:,.0f} + web ${online:,.0f} '
    f'+ kits ${kit_val:,.0f} + combos ${combo:,.0f} | desc ${diff:,.0f}')

# ---- 5. HUERFANOS: stock de templates inactivos / no vendibles ----
attr = f.tmpl_attr()
salas = f.stock_salas()
salas = salas.assign(active=salas.tmpl.map(attr['active']), sale_ok=salas.tmpl.map(attr['sale_ok']))
huerf = salas[(salas.active == False) | (salas.sale_ok == False)]
estado = 'PASS' if len(huerf) == 0 else 'WARN'
chk('5. Sin stock en SKU inactivo/no-vendible', estado,
    f'{len(huerf)} filas | ${huerf.stock_val.sum():,.0f} en SKU active=False o sale_ok=False')

# ---- reporte ----
print('=' * 70)
print(f'RECONCILIACIÓN DE FUENTES — {datetime.date.today()}')
print('=' * 70)
ico = {'PASS': '[OK ]', 'WARN': '[!! ]', 'FAIL': '[XXX]'}
for estado, nombre, detalle in res:
    print(f'{ico[estado]} {nombre}')
    print(f'        {detalle}')
nfail = sum(1 for e, _, _ in res if e == 'FAIL')
nwarn = sum(1 for e, _, _ in res if e == 'WARN')
print('-' * 70)
print(f'Resultado: {nfail} FAIL, {nwarn} WARN, {len(res)-nfail-nwarn} PASS')
print()
print(f'STOCK PARADO REAL EN SALAS: ${real_salas:,.0f}')
print(f'  (excluye: kits ${kit_val:,.0f}, CD pipeline ${cd_clean:,.0f}, web ${online:,.0f}, combos ${combo:,.0f})')
sys.exit(1 if nfail else 0)
