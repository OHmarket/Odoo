"""
Aproximacion: usar `importancia` (alto/medio/bajo/critico) como proxy de revenue.

Limitacion: importancia es categorica. No reemplaza precio unitario.
Util como vista preliminar mientras se obtiene el dato de precio.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
df = pd.read_excel(PATH, engine="openpyxl")
weeks = sorted(df["target_week_start"].dropna().unique())
if len(weeks) > 3:
    df = df[df["target_week_start"].isin(weeks[-3:])].copy()
for c in ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
hm = df[df["method"] == "hm_si"].copy()

total_real = hm["real_qty"].sum()
total_n = len(hm)

# ----------------------------------------------------------------------
# 1. POR IMPORTANCIA (proxy de revenue)
# ----------------------------------------------------------------------
print("=" * 100)
print("REVENUE PROXY via `importancia` (alto/medio/bajo/critico)")
print("=" * 100)
print(f"\nUniverso: {total_n:,} filas | real total: {total_real:,.0f} unidades")

if "importancia" in hm.columns:
    rows = []
    for imp in sorted(hm["importancia"].dropna().unique()):
        sub = hm[hm["importancia"] == imp]
        n = len(sub)
        real = sub["real_qty"].sum()
        ae = sub["abs_error_qty"].sum()
        e = sub["error_qty"].sum()
        rows.append({
            "importancia": imp,
            "n_filas": n,
            "share_n_%": n/total_n*100,
            "real_unid": real,
            "share_real_%": real/total_real*100 if total_real > 0 else 0,
            "wape_%": (ae/real*100) if real > 0 else np.nan,
            "bias_%": (e/real*100) if real > 0 else np.nan,
        })
    print("\n1. PERFORMANCE POR IMPORTANCIA")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 2. CRUCE importancia x regimen
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. CRUCE IMPORTANCIA x REGIMEN (n filas)")
print("=" * 100)
if "importancia" in hm.columns:
    ct = pd.crosstab(hm["importancia"].fillna("(NaN)"), hm["regimen"].fillna("(NaN)"))
    print(ct.to_string())


# ----------------------------------------------------------------------
# 3. CRUCE importancia x zona
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. CRUCE IMPORTANCIA x FORECAST_ZONE (n filas)")
print("=" * 100)
if "importancia" in hm.columns and "forecast_zone" in hm.columns:
    ct = pd.crosstab(hm["importancia"].fillna("(NaN)"), hm["forecast_zone"].fillna("(NaN)"))
    print(ct.to_string())


# ----------------------------------------------------------------------
# 4. CONCENTRACION DE UNIDADES POR IMPORTANCIA (proxy del revenue)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. SHARE DE REAL UNIDADES POR IMPORTANCIA")
print("=" * 100)
if "importancia" in hm.columns:
    by_imp = hm.groupby("importancia", as_index=False).agg(
        n=("real_qty", "size"),
        real=("real_qty", "sum"),
        forecast=("forecast_qty", "sum"),
        ae=("abs_error_qty", "sum"),
    )
    by_imp["share_real_%"] = by_imp["real"] / total_real * 100
    by_imp["wape_%"] = by_imp["ae"] / by_imp["real"] * 100
    print(by_imp.sort_values("real", ascending=False).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 5. TOP SKUs por categoria L2 segun importancia
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. CATEGORIAS L2 — cuales agrupan los SKUs criticos vs bajo?")
print("=" * 100)
if "importancia" in hm.columns and "categ_id" in hm.columns:
    # Agrupar por categoria, contar SKUs unicos por importancia
    sku_per_cat = hm.groupby(["categ_id", "importancia"], as_index=False).agg(
        n_filas=("real_qty", "size"),
        real=("real_qty", "sum"),
    )
    # Pivotear por categoria con columnas importancia
    pivot_n = sku_per_cat.pivot(index="categ_id", columns="importancia", values="n_filas").fillna(0).astype(int)
    pivot_r = sku_per_cat.pivot(index="categ_id", columns="importancia", values="real").fillna(0)
    # Ordenar por total real desc, top 15
    pivot_n["total_n"] = pivot_n.sum(axis=1)
    pivot_r["total_real"] = pivot_r.sum(axis=1)
    pivot_top = pivot_r.sort_values("total_real", ascending=False).head(15)
    print("\nTop 15 categorias por volumen real, share por importancia:")
    print(pivot_top.to_string(float_format=lambda x: f"{x:,.0f}"))


# ----------------------------------------------------------------------
# 6. Top 100 SKUs unicos: que mix de importancia tienen?
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. Composicion del TOP 100 SKUs por volumen real (proxy concentracion)")
print("=" * 100)
sku_agg = hm.groupby("product_id", as_index=False).agg(
    real=("real_qty", "sum"),
    importancia=("importancia", "first"),
    regimen=("regimen", "first"),
    categ_id=("categ_id", "first"),
)
top100 = sku_agg.sort_values("real", ascending=False).head(100)
print(f"\nDistribucion importancia del Top 100:")
print(top100["importancia"].value_counts())
print(f"\nReal total del Top 100: {top100['real'].sum():,.0f} ({top100['real'].sum()/total_real*100:.1f}% del volumen)")

print("\nDONE.")
