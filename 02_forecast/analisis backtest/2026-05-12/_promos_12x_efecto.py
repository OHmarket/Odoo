"""
Medir el efecto real de las promos por TIPO de mecanica (12X, 6X, 2X).

Pregunta del usuario: las 12X DESCUENTO generan solo un 10% extra de demanda?
"""
import pandas as pd
import numpy as np
import re

PATH_PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
PATH_BT    = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"

dfm = pd.read_excel(PATH_PROMO, engine="openpyxl")
dfb = pd.read_excel(PATH_BT, engine="openpyxl")
dfm["period_start"] = pd.to_datetime(dfm["period_start"], errors="coerce")
dfb["target_week_start"] = pd.to_datetime(dfb["target_week_start"], errors="coerce")

weeks_bt = sorted(dfb["target_week_start"].dropna().unique())[-3:]
dfb = dfb[(dfb["method"] == "hm_si") & (dfb["target_week_start"].isin(weeks_bt))].copy()
sku_to_abc = {row["product_id"]: str(row.get("abcxyz", ""))[:1]
              for _, row in dfb.iterrows()}
dfm["abc"] = dfm["product_variant_id"].map(sku_to_abc)


def extract_mecanica(program_name):
    """Extrae 12X, 6X, 2X o '?' del nombre del programa."""
    s = str(program_name).upper()
    m = re.search(r'(\d+)X', s)
    if m:
        return f"{m.group(1)}X"
    if "DESCUENTO" in s or "%" in s:
        return "OTRO_DESC"
    return "OTRO"


dfm["mecanica"] = dfm["program_name"].apply(extract_mecanica)

print("=" * 100)
print("EFECTO REAL DE PROMOS POR TIPO DE MECANICA (12X, 6X, 2X, etc.)")
print("=" * 100)

# ----------------------------------------------------------------------
# 1. Distribucion global por mecanica
# ----------------------------------------------------------------------
print("\n1. DISTRIBUCION GLOBAL DE PROMOS POR MECANICA")
print(dfm["mecanica"].value_counts().to_string())

# ----------------------------------------------------------------------
# 2. Efecto por mecanica — lift_qty medio y volumen movido
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. LIFT MEDIDO POR MECANICA (todas las promos)")
print("=" * 100)
print(f"\n{'mecanica':<12} {'n':>6} {'lift_avg':>10} {'lift_med':>10} {'qty_total':>12} {'baseline_tot':>14} {'lift_NETO':>12}")
print("-" * 90)
mecanicas_clave = sorted(dfm["mecanica"].value_counts().head(8).index.tolist())
for mec in mecanicas_clave:
    sub = dfm[(dfm["mecanica"] == mec) & (dfm["lift_qty"].notna())]
    if len(sub) == 0:
        continue
    lift_avg = sub["lift_qty"].mean()
    lift_med = sub["lift_qty"].median()
    qty_total = sub["qty_actual"].sum()
    baseline = sub["qty_baseline_8w"].sum()
    lift_neto = qty_total / baseline if baseline > 0 else 0
    print(f"{mec:<12} {len(sub):>6,} {lift_avg:>10.3f} {lift_med:>10.3f} {qty_total:>12,.0f} {baseline:>14,.0f} {lift_neto:>12.3f}")

# ----------------------------------------------------------------------
# 3. 12X DESCUENTO — el caso especifico que motiva la pregunta
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. ZOOM en 12X DESCUENTO — lift por letra ABC")
print("=" * 100)
m12x = dfm[dfm["mecanica"] == "12X"].copy()
print(f"\nTotal promos 12X: {len(m12x):,}")
print(f"\n{'abc':<5} {'n':>6} {'lift_avg':>10} {'lift_med':>10} {'qty_total':>12} {'baseline_tot':>14} {'lift_NETO':>12}")
for letra in ['A', 'B', 'C']:
    sub = m12x[(m12x["abc"] == letra) & (m12x["lift_qty"].notna())]
    if len(sub) == 0:
        continue
    qty = sub["qty_actual"].sum()
    base = sub["qty_baseline_8w"].sum()
    print(f"{letra:<5} {len(sub):>6,} {sub['lift_qty'].mean():>10.3f} {sub['lift_qty'].median():>10.3f} "
          f"{qty:>12,.0f} {base:>14,.0f} {qty/base if base > 0 else 0:>12.3f}")

# ----------------------------------------------------------------------
# 4. 12X por CATEGORIA L2 — ver si depende de tipo producto
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. 12X POR CATEGORIA L2")
print("=" * 100)
m12x["cat_l2"] = m12x["categ_id"].astype(str).apply(
    lambda x: x.split(' / ')[1] if len(x.split(' / ')) >= 2 else x.split(' / ')[-1]
)
print(f"\n{'cat_l2':<35} {'n':>6} {'lift_neto':>11}")
cat_stats = m12x.groupby("cat_l2").agg(
    n=("lift_qty", "size"),
    qty=("qty_actual", "sum"),
    base=("qty_baseline_8w", "sum"),
).reset_index()
cat_stats["lift_neto"] = cat_stats["qty"] / cat_stats["base"].replace(0, np.nan)
cat_stats = cat_stats.sort_values("qty", ascending=False).head(10)
print(cat_stats.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ----------------------------------------------------------------------
# 5. EN PERIODO BACKTEST W17-W19 — 12X especifico
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. 12X DESCUENTO EN W17-W19 (periodo del backtest)")
print("=" * 100)
W = (pd.Timestamp("2026-04-13"), pd.Timestamp("2026-05-10"))
m12x_bt = m12x[(m12x["period_start"] >= W[0]) & (m12x["period_start"] <= W[1])].copy()
print(f"\nPromos 12X en W17-W19: {len(m12x_bt):,}")
for letra in ['A', 'B', 'C']:
    sub = m12x_bt[m12x_bt["abc"] == letra]
    if len(sub) == 0:
        continue
    qty = sub["qty_actual"].sum()
    base = sub["qty_baseline_8w"].sum()
    print(f"  {letra}: n={len(sub):>3}  lift_avg={sub['lift_qty'].mean():.3f}  qty={qty:,.0f}  baseline={base:,.0f}  lift_NETO={qty/base if base>0 else 0:.3f}")

# Cervezas en 12X — el caso especifico de Budweiser/Quilmes/Stella/Michelob
print("\n" + "=" * 100)
print("6. 12X EN CERVEZAS EN W17-W19 (los SKUs problematicos)")
print("=" * 100)
cerv_12x = m12x_bt[m12x_bt["categ_id"].astype(str).str.contains("Cervezas", case=False, na=False)]
print(f"\nPromos 12X en cervezas W17-W19: {len(cerv_12x):,}")
if len(cerv_12x) > 0:
    sample = cerv_12x[["period_start", "product_variant_id", "qty_actual", "qty_baseline_8w", "lift_qty", "abc", "promo_effect"]].sort_values("qty_actual", ascending=False).head(20)
    print(sample.to_string(index=False))

# Agregado cervezas 12X
qty_cerv_12x = cerv_12x["qty_actual"].sum()
base_cerv_12x = cerv_12x["qty_baseline_8w"].sum()
print(f"\nTotal cervezas 12X W17-W19: qty_actual={qty_cerv_12x:,.0f}  baseline={base_cerv_12x:,.0f}")
print(f"Lift neto agregado cervezas 12X: {qty_cerv_12x/base_cerv_12x if base_cerv_12x > 0 else 0:.3f}")

# ----------------------------------------------------------------------
# 7. RESPUESTA A LA PREGUNTA
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("7. RESPUESTA — las 12X generan 10% o cuanto?")
print("=" * 100)
print(f"""
  Promos 12X globalmente:
    - n total: {len(m12x):,}
    - lift_neto agregado: {m12x['qty_actual'].sum()/m12x['qty_baseline_8w'].sum() if m12x['qty_baseline_8w'].sum() > 0 else 0:.3f}
""")
