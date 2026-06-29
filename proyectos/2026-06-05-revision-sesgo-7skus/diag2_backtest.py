# -*- coding: utf-8 -*-
"""DIAG2 read-only: caracterizar el backtest de los 7 SKUs."""
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

PP = {10772:'0154 CocaCola3L', 11446:'1963 Monster', 11449:'1966 MonsterUltra',
      11967:'2233 Vital1.6', 11061:'6242 Cab2L', 11065:'6243 Merlot2L', 11063:'6244 Carmenere2L'}

odoo = OdooReader()
rows = odoo.search_read(
    'x_forecast_backtest',
    domain=[('x_studio_product_id', 'in', list(PP.keys()))],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_forecast_cutoff',
            'x_studio_target_week_start','x_studio_forecast_model_code',
            'x_studio_forecast_qty','x_studio_real_qty','x_studio_bias_pct',
            'x_studio_abcxyz','x_studio_series_type','x_studio_regimen',
            'x_studio_method','create_date'],
)
print(f"filas={len(rows)}")
print("\ncreate_date range:", min(r['create_date'] for r in rows), "->", max(r['create_date'] for r in rows))
print("\nmodel_codes:", Counter(r['x_studio_forecast_model_code'] for r in rows))
print("\nmethods:", Counter(r['x_studio_method'] for r in rows))
print("\ncutoffs:", sorted(set(r['x_studio_forecast_cutoff'] for r in rows)))
print("\ntarget_weeks:", sorted(set(r['x_studio_target_week_start'] for r in rows)))
print("\nteams (count):", Counter((r['x_studio_team_id'][1] if r['x_studio_team_id'] else None) for r in rows))
print("\nabcxyz por SKU:")
seen=set()
for r in rows:
    pid=r['x_studio_product_id'][0]
    if pid not in seen:
        seen.add(pid)
        print(f"  {PP[pid]:>20}  abcxyz={r['x_studio_abcxyz']}  series={r['x_studio_series_type']}  regimen={r['x_studio_regimen']}")
