"""
Cruzar cambios de precio y promos con los Top 5 SKUs problematicos de
Cervezas en A (Royal Guard, Cusqueña, Budweiser, Stella, Quilmes,
Michelob, Cristal Ultra, Becker, Coors).

Foco: validar hipotesis del usuario.
"""
import pandas as pd
import numpy as np

PRICE = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"

dfp = pd.read_excel(PRICE, engine="openpyxl")
dfm = pd.read_excel(PROMO, engine="openpyxl")

# Normalizar fechas
dfp["Fecha"] = pd.to_datetime(dfp["Fecha"], errors="coerce")
dfm["period_start"] = pd.to_datetime(dfm["period_start"], errors="coerce")
dfm["date_from"] = pd.to_datetime(dfm["date_from"], errors="coerce")

# Rango de fechas en cada archivo
print("=" * 100)
print("0. RANGO TEMPORAL DE LOS ARCHIVOS")
print("=" * 100)
print(f"\nx_price_change_event:")
print(f"  Fecha min: {dfp['Fecha'].min()}")
print(f"  Fecha max: {dfp['Fecha'].max()}")
print(f"  Distribucion por año:")
print(dfp["Fecha"].dt.year.value_counts().sort_index())

print(f"\nx_loyalty_promo_event (period_start):")
print(f"  Fecha min: {dfm['period_start'].min()}")
print(f"  Fecha max: {dfm['period_start'].max()}")
print(f"  Distribucion por año:")
print(dfm["period_start"].dt.year.value_counts().sort_index())

# SKUs problematicos (del analisis previo de Top 30 en A)
SKUS_PROBLEMA = [
    "ROYAL GUARD",      # Over 8x - sospechoso de subida de precio
    "BUDWEISER",        # Under 0.51x - cannibal beneficiario?
    "STELLA ARTOIS",    # Under 0.47x
    "CUSQUE",           # Over 2.32x
    "QUILMES",          # Casi correcto
    "MICHELOB",         # Under 0.49x
    "CRISTAL ULTRA",    # Under 0.26x
    "BECKER",
    "COORS",
    "ESCUDO",
    "HEINEKEN",
]

# Buscar cada SKU en cambios de precio
print("\n" + "=" * 100)
print("1. CAMBIOS DE PRECIO EN SKUs PROBLEMATICOS (2026)")
print("=" * 100)
dfp_2026 = dfp[dfp["Fecha"].dt.year >= 2026].copy() if dfp["Fecha"].dt.year.max() >= 2026 else dfp[dfp["Fecha"].dt.year == dfp["Fecha"].dt.year.max()].copy()
print(f"\nTotal cambios en {dfp_2026['Fecha'].dt.year.max() if len(dfp_2026)>0 else 'N/A'}: {len(dfp_2026):,}")

for keyword in SKUS_PROBLEMA:
    mask = dfp["Producto"].astype(str).str.contains(keyword, case=False, na=False)
    sub = dfp[mask].sort_values("Fecha", ascending=False)
    if len(sub) == 0:
        continue
    # mostrar ultimos 5 cambios
    print(f"\n  >> {keyword}: {len(sub)} cambios totales registrados")
    cols = ["Fecha", "Producto", "Precio Anterior", "Precio", "Variacion %", "Direcci\xf3n", "is_real_change", "Semanas Activo"]
    cols_exist = [c for c in cols if c in sub.columns]
    print(sub[cols_exist].head(5).to_string(index=False))

# ----------------------------------------------------------------------
# 2. PROMOS ACTIVAS EN PERIODO BACKTEST (W17-W19 = 2026-04-20 a 2026-05-10)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. PROMOS ACTIVAS EN PERIODO BACKTEST (W17-W19: 2026-04-20 a 2026-05-10)")
print("=" * 100)
BT_START = pd.Timestamp("2026-04-20")
BT_END = pd.Timestamp("2026-05-10")
dfm_bt = dfm[(dfm["period_start"] >= BT_START - pd.Timedelta(days=14)) &
              (dfm["period_start"] <= BT_END)].copy()
print(f"\nPromos con period_start entre {BT_START.date()-pd.Timedelta(days=14)} y {BT_END.date()}: {len(dfm_bt):,}")

for keyword in SKUS_PROBLEMA:
    mask = dfm_bt["product_variant_id"].astype(str).str.contains(keyword, case=False, na=False)
    sub = dfm_bt[mask].sort_values("period_start", ascending=False)
    if len(sub) == 0:
        continue
    print(f"\n  >> {keyword}: {len(sub)} promos en periodo backtest")
    cols = ["period_start", "product_variant_id", "program_name", "qty_actual", "qty_baseline_8w", "lift_qty", "price_delta_pct", "weeks_active", "promo_effect"]
    cols_exist = [c for c in cols if c in sub.columns]
    print(sub[cols_exist].head(5).to_string(index=False))

# ----------------------------------------------------------------------
# 3. RESUMEN: que sabemos del periodo critico
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. RESUMEN POR CATEGORIA EN PERIODO BACKTEST")
print("=" * 100)

# Cambios recientes por categoria
print(f"\n3.1 Cambios de precio en periodo proximo al backtest:")
RECENT = pd.Timestamp("2026-03-01")  # ultimo 2-3 meses
dfp_recent = dfp[dfp["Fecha"] >= RECENT].copy()
print(f"  Cambios desde 2026-03-01: {len(dfp_recent):,}")
if "Categoria" in dfp_recent.columns:
    print(f"  Top categorias con mas cambios:")
    print(dfp_recent["Categoria"].value_counts().head(10).to_string())

# Promos activas en el periodo
print(f"\n3.2 Promos cuyo periodo cubre semanas del backtest (W17-W19):")
dfm_overlap = dfm[(dfm["period_start"] >= BT_START - pd.Timedelta(days=8*7)) &
                   (dfm["period_start"] <= BT_END)].copy()
print(f"  Promos overlap: {len(dfm_overlap):,}")
if "categ_id" in dfm_overlap.columns:
    print(f"  Top categorias con promo activa:")
    print(dfm_overlap["categ_id"].value_counts().head(10).to_string())

print("\nDONE.")
