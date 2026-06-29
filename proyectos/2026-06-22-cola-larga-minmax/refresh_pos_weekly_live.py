# -*- coding: utf-8 -*-
"""
FIX del descuadre de pos_weekly. Reemplaza el pipeline CSV+default_code
(lossy, manual, stale) por lectura DIRECTA del modelo vivo x_pos_week_sku_sale
por IDs reales. Re-ejecutable. Batched por semana + throttle (Odoo productivo).

Salida: cache/pos_weekly.parquet (mismo schema: team_id, product_id, week_start,
        week_end, iso_week, qty_sold) -> drop-in, no rompe scripts existentes.
"""
import time, datetime
import pandas as pd
from shared.odoo_xmlrpc import OdooReader

OUT = 'proyectos/2026-05-27-harness-local/cache/pos_weekly.parquet'
WEEKS_BACK = 80          # historia a traer (cubre 52s + margen)
THROTTLE = 0.3           # seg entre batches, no saturar POS
o = OdooReader()

today = datetime.date.today()
start = today - datetime.timedelta(weeks=WEEKS_BACK)
# semanas ISO (lunes) en el rango
mondays = pd.date_range(start - datetime.timedelta(days=start.weekday()),
                        today, freq='W-MON').date

print(f'Refresh pos_weekly desde modelo VIVO x_pos_week_sku_sale')
print(f'  rango: {mondays[0]} -> {mondays[-1]} ({len(mondays)} semanas), batch por semana')

frames = []
for i, wk in enumerate(mondays):
    rows = o.search_read('x_pos_week_sku_sale',
        [['x_studio_week_start', '=', wk.isoformat()]],
        ['x_studio_product_id', 'x_studio_team_id', 'x_studio_week_start',
         'x_studio_week_end', 'x_studio_iso_week', 'x_studio_qty_sold'])
    if rows:
        d = pd.DataFrame(rows)
        d['product_id'] = d['x_studio_product_id'].apply(lambda x: x[0] if x else None)
        d['team_id'] = d['x_studio_team_id'].apply(lambda x: x[0] if x else None)
        d = d.rename(columns={'x_studio_week_start': 'week_start',
                              'x_studio_week_end': 'week_end',
                              'x_studio_iso_week': 'iso_week',
                              'x_studio_qty_sold': 'qty_sold'})
        frames.append(d[['team_id', 'product_id', 'week_start', 'week_end', 'iso_week', 'qty_sold']])
    if i % 10 == 0:
        print(f'  {i+1}/{len(mondays)} semanas... ({sum(len(f) for f in frames):,} filas)')
    time.sleep(THROTTLE)

df = pd.concat(frames, ignore_index=True)
df = df.dropna(subset=['team_id', 'product_id'])
df['team_id'] = df['team_id'].astype('Int64')
df['product_id'] = df['product_id'].astype('Int64')
df['week_start'] = pd.to_datetime(df['week_start']).dt.date
df['week_end'] = pd.to_datetime(df['week_end']).dt.date

df.to_parquet(OUT, index=False)
print(f'\nOK -> {OUT}')
print(f'  filas: {len(df):,} | productos: {df.product_id.nunique():,} | teams: {df.team_id.nunique()}')
print(f'  rango: {df.week_start.min()} -> {df.week_start.max()}')
print(f'  (antes: 581.848 filas, hasta 2026-05-18)')
