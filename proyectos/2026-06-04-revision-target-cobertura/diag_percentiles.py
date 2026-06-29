# DIAG read-only: percentiles del target de cobertura (reorder_target_weeks)
# por tipo de producto (categoria). Descompone cobertura(H) vs seguridad.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
FLOOR = 1.0 / 4.345  # DEMAND_FLOOR_WEEK

fields = ['x_studio_categ_id', 'x_studio_abcxyz', 'x_studio_mu_week',
          'x_studio_sigma_week', 'x_studio_safety_stock_units',
          'x_studio_reorder_target_weeks', 'x_studio_target_units']
dom = [('x_studio_mu_week', '>', FLOOR),
       ('x_studio_reorder_target_weeks', '>', 0.0)]

rows, off = [], 0
while True:
    batch = o.search_read('x_analisis_de_stock', dom, fields, limit=5000, offset=off)
    rows += batch
    if len(batch) < 5000:
        break
    off += 5000
print('filas activas (mu>floor, tgt>0):', len(rows))

df = pd.DataFrame(rows)
df['categ'] = df['x_studio_categ_id'].apply(lambda v: v[1] if isinstance(v, list) else 'sin_categ')
df['mu'] = df['x_studio_mu_week'].astype(float)
df['safe'] = df['x_studio_safety_stock_units'].astype(float)
df['tgt_w'] = df['x_studio_reorder_target_weeks'].astype(float)
df['seg_w'] = df['safe'] / df['mu']          # semanas de seguridad
df['cob_w'] = df['tgt_w'] - df['seg_w']      # cobertura base (H real)

def pct_table(g):
    s = g['tgt_w']
    return pd.Series({
        'n': len(s),
        'cob_med': g['cob_w'].median(),
        'seg_med': g['seg_w'].median(),
        'p10': s.quantile(.10), 'p25': s.quantile(.25),
        'p50': s.median(), 'p75': s.quantile(.75),
        'p90': s.quantile(.90), 'max': s.max(),
    })

print('\n=== TARGET DE COBERTURA (semanas) por TIPO DE PRODUCTO ===')
print('cob_med=cobertura base mediana | seg_med=seguridad mediana | pXX=percentiles tgt_w\n')
tbl = df.groupby('categ').apply(pct_table, include_groups=False)
tbl = tbl[tbl['n'] >= 20].sort_values('n', ascending=False)
pd.set_option('display.width', 160, 'display.max_rows', 60,
              'display.float_format', lambda x: f'{x:6.2f}')
print(tbl.to_string())

print('\n=== GLOBAL (todas las categorias) ===')
s = df['tgt_w']
print(f"n={len(s)}  cob_med={df['cob_w'].median():.2f}  seg_med={df['seg_w'].median():.2f}  "
      f"p10={s.quantile(.1):.2f} p25={s.quantile(.25):.2f} p50={s.median():.2f} "
      f"p75={s.quantile(.75):.2f} p90={s.quantile(.9):.2f} max={s.max():.2f}")

print('\n=== por ABCXYZ ===')
ab = df.groupby('x_studio_abcxyz').apply(pct_table, include_groups=False).sort_values('n', ascending=False)
print(ab.to_string())
