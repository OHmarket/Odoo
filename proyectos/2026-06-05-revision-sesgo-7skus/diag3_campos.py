# -*- coding: utf-8 -*-
"""DIAG3: campos de x_analisis_de_stock (safety) y x_stock_balance_daily (quiebre)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader
odoo = OdooReader()

for m in ['x_analisis_de_stock', 'x_stock_balance_daily']:
    fg = odoo.fields_get(m)
    print(f"=== {m} ===")
    for k in sorted(fg.keys()):
        if k.startswith('x_') or k in ('display_name','create_date'):
            print(f"  {k:<45} {fg[k].get('type'):<12} {fg[k].get('string')}")
    print()
