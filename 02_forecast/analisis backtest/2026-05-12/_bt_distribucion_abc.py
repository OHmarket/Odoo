"""
Distribucion de A/B/C: cuantos SKUs caen en cada letra, cuanto volumen mueven.

Limitacion: el backtest NO tiene total_margin_abc. Para ver el margen exacto
seria necesario el export de x_calculo_abc_xyz.
Como aproximacion, cruzamos con `importancia` (que SI se calcula sobre margen).
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

# Extraer letra ABC (primer caracter de abcxyz)
hm["abc_letter"] = hm["abcxyz"].fillna("").str[:1].str.upper()
hm["xyz_letter"] = hm["abcxyz"].fillna("").str[-1:].str.upper()

# Por SKU para ver n unicos
sku_agg = hm.groupby("product_id", as_index=False).agg(
    abc_letter=("abc_letter", "first"),
    xyz_letter=("xyz_letter", "first"),
    abcxyz=("abcxyz", "first"),
    importancia=("importancia", "first"),
    real_total=("real_qty", "sum"),
    forecast_total=("forecast_qty", "sum"),
)
total_real = sku_agg["real_total"].sum()
total_skus = len(sku_agg)

# ----------------------------------------------------------------------
# 1. CUANTOS SKUs UNICOS EN A/B/C (la pregunta principal)
# ----------------------------------------------------------------------
print("=" * 100)
print(f"DISTRIBUCION ABC SOBRE {total_skus:,} SKUs UNICOS")
print("=" * 100)
print(f"\nABC se construye sobre MARGEN ACUMULADO en runner ABCXYZ:")
print(f"  A: cum_margin <= 80% (por construccion)")
print(f"  B: cum_margin 80-95% (15%)")
print(f"  C: cum_margin > 95% (5%)")
print(f"\nPregunta: cuantos SKUs caen en cada cubeta?")

rows = []
for letra in ['A', 'B', 'C', '']:
    sub = sku_agg[sku_agg["abc_letter"] == letra]
    n = len(sub)
    real = sub["real_total"].sum()
    rows.append({
        "letra": letra if letra else "(vacio)",
        "n_skus": n,
        "share_skus_%": n / total_skus * 100,
        "real_unid": real,
        "share_volumen_%": real / total_real * 100 if total_real > 0 else 0,
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ----------------------------------------------------------------------
# 2. SKUs por LETRA A/B/C cruzado con IMPORTANCIA (proxy del ranking en margen)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. CRUCE LETRA ABC x IMPORTANCIA (importancia = top X% del ranking por margen)")
print("=" * 100)
ct = pd.crosstab(sku_agg["abc_letter"], sku_agg["importancia"].fillna("(NaN)"), margins=True)
print(ct.to_string())

# ----------------------------------------------------------------------
# 3. CRUCE LETRA ABC x XYZ (la matriz tradicional)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. CRUCE LETRA ABC x XYZ (matriz tradicional 9 cubetas)")
print("=" * 100)
ct = pd.crosstab(sku_agg["abc_letter"], sku_agg["xyz_letter"], margins=True)
print(ct.to_string())

# ----------------------------------------------------------------------
# 4. VOLUMEN POR ABCXYZ TRADICIONAL (9 cubetas)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. VOLUMEN POR ABCXYZ (cuanto vende cada cubeta)")
print("=" * 100)
rows = []
for abc in sorted(sku_agg["abcxyz"].dropna().unique()):
    sub = sku_agg[sku_agg["abcxyz"] == abc]
    n = len(sub)
    real = sub["real_total"].sum()
    rows.append({
        "abcxyz": abc,
        "n_skus": n,
        "share_skus_%": n / total_skus * 100,
        "real_unid": real,
        "share_vol_%": real / total_real * 100 if total_real > 0 else 0,
    })
df_abcxyz = pd.DataFrame(rows).sort_values("real_unid", ascending=False)
print(df_abcxyz.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ----------------------------------------------------------------------
# 5. CONCENTRACION DEL VOLUMEN POR LETRA ABC
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. LO IMPORTANTE: si A se construye sobre MARGEN, captura X% del margen.")
print("   Pero capturan que % del VOLUMEN?  (proxy imperfecto)")
print("=" * 100)
for letra in ['A', 'B', 'C']:
    sub = sku_agg[sku_agg["abc_letter"] == letra]
    n = len(sub)
    real = sub["real_total"].sum()
    print(f"  {letra}: {n:>5,} SKUs ({n/total_skus*100:5.1f}% de los SKUs)")
    print(f"     -> {real:>8,.0f} unidades ({real/total_real*100:5.1f}% del volumen)")
    print(f"     -> esperado por construccion: ~80% / 15% / 5% del MARGEN respectivamente")
    print()

# ----------------------------------------------------------------------
# 6. PERCENTIL DE VENTAS POR LETRA ABC
# ----------------------------------------------------------------------
print("=" * 100)
print("6. DISTRIBUCION DE unidades vendidas POR LETRA ABC")
print("=" * 100)
for letra in ['A', 'B', 'C']:
    sub = sku_agg[sku_agg["abc_letter"] == letra]
    if len(sub) == 0:
        continue
    r = sub["real_total"]
    print(f"\n  Letra {letra} (n={len(sub):,} SKUs):")
    print(f"    real_total per SKU: p10={np.percentile(r, 10):.0f}  p50={np.percentile(r, 50):.0f}  p90={np.percentile(r, 90):.0f}  max={r.max():.0f}")
    print(f"    SKUs con real=0:    {(r == 0).sum():,} ({(r == 0).sum()/len(sub)*100:.1f}%)")

print("\nDONE.")
