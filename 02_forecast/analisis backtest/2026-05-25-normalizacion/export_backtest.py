"""
Exporta x_forecast_backtest a CSV via XML-RPC.

Uso:
    python "02_forecast/analisis backtest/2026-05-25-normalizacion/export_backtest.py" pre
    python "02_forecast/analisis backtest/2026-05-25-normalizacion/export_backtest.py" post

Genera: ./resultados/{tag}_{YYYY-MM-DD-HHMMSS}.csv
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.odoo_xmlrpc import OdooReader
import pandas as pd

MODEL = 'x_forecast_backtest'
THIS_DIR = Path(__file__).resolve().parent
OUT_DIR = THIS_DIR / 'resultados'
OUT_DIR.mkdir(exist_ok=True)


def main():
    if len(sys.argv) < 2:
        print("Uso: python export_backtest.py <tag>  (tag = pre o post)")
        sys.exit(1)
    tag = sys.argv[1]

    odoo = OdooReader()
    print(odoo)

    total = odoo.search_count(MODEL, [])
    print(f"\nTotal en {MODEL}: {total:,}")
    if total == 0:
        print(f"Modelo vacio. Corre OH Forecast Backtest antes (con o sin normalizacion).")
        sys.exit(1)

    # Lee todos los campos
    sample = odoo.search_read(MODEL, [], limit=1)
    fields = sorted([f for f in sample[0].keys() if not f.startswith('display_')])
    print(f"Campos: {len(fields)}")

    # Baja en chunks de 5K para no saturar el server con search_read masivo
    print(f"Bajando {total:,} filas en chunks de 5,000...")
    rows = []
    CHUNK = 5000
    offset = 0
    while offset < total:
        chunk = odoo.search_read(MODEL, [], fields=fields, limit=CHUNK, offset=offset)
        if not chunk:
            break
        rows.extend(chunk)
        print(f"  ... {len(rows):,} / {total:,}")
        offset += CHUNK
    df = pd.DataFrame(rows)

    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    fname = OUT_DIR / f"{tag}_{ts}.csv"
    df.to_csv(fname, index=False)
    print(f"\nOK: {fname}")
    print(f"   filas={len(df):,}")
    print(f"   columnas={len(df.columns)}")


if __name__ == '__main__':
    main()
