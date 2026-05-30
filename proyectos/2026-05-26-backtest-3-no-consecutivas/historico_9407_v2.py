"""
Pull historico SKU 9407 (Stella 660cc) usando x_forecast_weekly_data
(tabla agregada Studio: semana x team x producto). Mucho mas liviano que
levantar pos.order.line.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # 1. Descubrir modelo y campos
    try:
        f = odoo.fields_get('x_forecast_weekly_data')
        cand = [k for k in f.keys() if not k.startswith('_') and not k.startswith('create_') and not k.startswith('write_')]
        print(f"\nCampos x_forecast_weekly_data ({len(cand)}):")
        for k in sorted(cand):
            rel = f[k].get('relation') or ''
            print(f"  {k:40s} {f[k].get('type'):12s} {rel}")
    except Exception as e:
        print(f"ERROR fields_get: {e}")
        return


if __name__ == "__main__":
    main()
