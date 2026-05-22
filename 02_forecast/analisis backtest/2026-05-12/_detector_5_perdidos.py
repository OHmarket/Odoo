"""Identificar los 5 SKUs que v5.5 alertaba pero v5.6 ya no, comparando
los dos exports de x_price_coreccion contra el backtest."""
import pandas as pd

PATH_OLD = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Corrección Precio (x_price_coreccion) (1).xlsx"
PATH_BT  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"


def _clean(v):
    s = str(v or '').strip()
    if s.startswith('['):
        idx = s.find(']')
        if idx > 0:
            s = s[idx+1:].strip()
    return s.upper()


dfo = pd.read_excel(PATH_OLD, engine="openpyxl")
dfb = pd.read_excel(PATH_BT, engine="openpyxl")

dfo["sku"] = dfo["product_id"].apply(_clean)
dfb["sku"] = dfb["product_id"].apply(_clean)

old = set(dfo["sku"].unique())
bt  = set(dfb["sku"].unique())

solo_old = old - bt
print(f"\nSKUs alertados v5.5 ausentes del backtest: {len(solo_old)}")
for sku in sorted(solo_old):
    row = dfo[dfo["sku"] == sku].iloc[0]
    print(f"  - {sku[:50]:<50}  tipo={row['tipo_alerta']:<25}  factor={row['factor_corr']:.2f}  razon={row.get('razon', '')}")
