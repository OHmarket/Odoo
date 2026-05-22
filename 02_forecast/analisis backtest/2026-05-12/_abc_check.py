"""
Verificación post-corrida ABCXYZ v19.2 (NO_BANDAS).
Lee XLSX exportado de x_calculo_abc_xyz y revisa:
  - Que las 7 columnas nuevas estén pobladas
  - Distribuciones de series_type, regimen, gmroi_class
  - Rangos de adi, cv2, gmroi, inv_valor_avg
  - Coherencia: REG-1 ↔ AX × smooth × mature, etc.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Calculo ABC  XYZ (x_calculo_abc_xyz) (1).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")

print("=" * 80)
print("1. ESTRUCTURA")
print("=" * 80)
print(f"Filas: {len(df):,}")
print(f"Columnas ({len(df.columns)}):")
for c in df.columns:
    print(f"  {c}")

# Identificar nombres reales (la exportación a veces usa labels en español)
def find_col(*candidates):
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        cl = c.lower()
        for cand in candidates:
            if cand.lower() in cl:
                return c
    return None

col_abcxyz   = find_col("x_studio_abcxyz", "ABCXYZ", "abcxyz")
col_xyz      = find_col("x_studio_xyz", "XYZ")
col_abc      = find_col("x_studio_abc", "ABC")
col_adi      = find_col("x_studio_adi", "adi")
col_cv2      = find_col("x_studio_cv2", "cv2")
col_series   = find_col("x_studio_series_type", "series_type")
col_regimen  = find_col("x_studio_regimen", "regimen")
col_gmroi    = find_col("x_studio_gmroi", "gmroi")
col_gmroiclass = find_col("x_studio_gmroi_class", "gmroi_class")
col_invvalor = find_col("x_studio_inv_valor_avg", "inv_valor_avg")
col_ciclo    = find_col("x_studio_ciclo_de_vida", "Ciclo de Vida", "ciclo_de_vida")
col_imp      = find_col("x_studio_importancia", "Importancia", "importancia")
col_mu       = find_col("x_studio_mu_week", "Promedio Semanal", "mu_week")
col_cv       = find_col("x_studio_cv", "Estabilidad", " cv")
col_product  = find_col("x_studio_product_id", "Producto", "product_id")

print("\n" + "=" * 80)
print("2. MAPEO DE COLUMNAS DETECTADO")
print("=" * 80)
for label, c in [
    ("abcxyz",       col_abcxyz),
    ("abc",          col_abc),
    ("xyz",          col_xyz),
    ("adi",          col_adi),
    ("cv2",          col_cv2),
    ("series_type",  col_series),
    ("regimen",      col_regimen),
    ("gmroi",        col_gmroi),
    ("gmroi_class",  col_gmroiclass),
    ("inv_valor_avg",col_invvalor),
    ("ciclo_de_vida",col_ciclo),
    ("importancia",  col_imp),
    ("mu_week",      col_mu),
    ("cv",           col_cv),
    ("product_id",   col_product),
]:
    flag = "OK" if c else "MISSING"
    print(f"  {label:18s} -> {c}    [{flag}]")


# ----------------------------------------------------------------------
# 3. POBLAMIENTO de columnas nuevas
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("3. POBLAMIENTO DE COLUMNAS NUEVAS")
print("=" * 80)
for c in [col_adi, col_cv2, col_series, col_regimen, col_gmroi, col_gmroiclass, col_invvalor]:
    if c:
        n_null = df[c].isnull().sum()
        n_zero_or_empty = ((df[c] == 0) | (df[c] == "")).sum() if df[c].dtype in (object, float, int, "float64", "int64") else 0
        print(f"  {c:35s}  nulos: {n_null:>6,}   ceros/vacios: {n_zero_or_empty:>6,}")


# ----------------------------------------------------------------------
# 4. DISTRIBUCION series_type
# ----------------------------------------------------------------------
if col_series:
    print("\n" + "=" * 80)
    print("4. DISTRIBUCION series_type")
    print("=" * 80)
    print(df[col_series].value_counts(dropna=False).to_string())
    intermittent_n = (df[col_series] == "intermittent").sum()
    print(f"\n  intermittent (clase NUEVA Syntetos-Boylan): {intermittent_n:,}")


# ----------------------------------------------------------------------
# 5. DISTRIBUCION regimen
# ----------------------------------------------------------------------
if col_regimen:
    print("\n" + "=" * 80)
    print("5. DISTRIBUCION regimen")
    print("=" * 80)
    print(df[col_regimen].value_counts(dropna=False).to_string())


# ----------------------------------------------------------------------
# 6. DISTRIBUCION gmroi_class
# ----------------------------------------------------------------------
if col_gmroiclass:
    print("\n" + "=" * 80)
    print("6. DISTRIBUCION gmroi_class")
    print("=" * 80)
    print(df[col_gmroiclass].value_counts(dropna=False).to_string())


# ----------------------------------------------------------------------
# 7. RANGOS NUMERICOS
# ----------------------------------------------------------------------
print("\n" + "=" * 80)
print("7. RANGOS DE METRICAS NUMERICAS")
print("=" * 80)
for c, label in [
    (col_adi, "ADI"),
    (col_cv2, "CV2"),
    (col_gmroi, "GMROI"),
    (col_invvalor, "inv_valor_avg"),
    (col_mu, "mu_week"),
    (col_cv, "cv (clasico)"),
]:
    if c:
        s = pd.to_numeric(df[c], errors="coerce")
        print(f"\n  {label} ({c}):")
        print(s.describe(percentiles=[0.10, 0.25, 0.50, 0.75, 0.90, 0.95]).to_string())


# ----------------------------------------------------------------------
# 8. CROSS-CHECK matriz series_type x regimen
# ----------------------------------------------------------------------
if col_series and col_regimen:
    print("\n" + "=" * 80)
    print("8. CROSS series_type x regimen (conteo)")
    print("=" * 80)
    print(pd.crosstab(df[col_series], df[col_regimen], dropna=False).to_string())


# ----------------------------------------------------------------------
# 9. CROSS-CHECK abcxyz x series_type
# ----------------------------------------------------------------------
if col_abcxyz and col_series:
    print("\n" + "=" * 80)
    print("9. CROSS abcxyz x series_type (conteo)")
    print("=" * 80)
    print(pd.crosstab(df[col_abcxyz], df[col_series], dropna=False).to_string())


# ----------------------------------------------------------------------
# 10. EJEMPLOS de intermittent (los SKUs que la matriz Syntetos rescató)
# ----------------------------------------------------------------------
if col_series and col_product:
    print("\n" + "=" * 80)
    print("10. EJEMPLOS de SKUs clasificados como 'intermittent' (top 15 por mu_week)")
    print("=" * 80)
    interm = df[df[col_series] == "intermittent"].copy()
    if len(interm) and col_mu:
        cols_show = [c for c in [col_product, col_abcxyz, col_adi, col_cv2, col_mu, col_regimen] if c]
        print(interm.sort_values(col_mu, ascending=False).head(15)[cols_show].to_string(index=False))
    elif len(interm):
        print(interm.head(15)[[col_product, col_abcxyz]].to_string(index=False))
    else:
        print("  Ningún SKU clasificado como intermittent.")


# ----------------------------------------------------------------------
# 11. PRODUCTOS SIN GMROI (revelarian si _load_inv_valor leyó stock OK)
# ----------------------------------------------------------------------
if col_gmroi and col_invvalor:
    print("\n" + "=" * 80)
    print("11. COBERTURA DE STOCK (lectura desde x_analisis_de_stock)")
    print("=" * 80)
    gmroi_num = pd.to_numeric(df[col_gmroi], errors="coerce").fillna(0.0)
    inv_num = pd.to_numeric(df[col_invvalor], errors="coerce").fillna(0.0)
    con_inv = (inv_num > 0).sum()
    sin_inv = (inv_num == 0).sum()
    con_gmroi = (gmroi_num > 0).sum()
    print(f"  SKUs con inv_valor_avg > 0 : {con_inv:>6,}  ({con_inv/len(df)*100:.1f}%)")
    print(f"  SKUs con inv_valor_avg = 0 : {sin_inv:>6,}  ({sin_inv/len(df)*100:.1f}%)")
    print(f"  SKUs con gmroi > 0         : {con_gmroi:>6,}  ({con_gmroi/len(df)*100:.1f}%)")
    if con_inv == 0:
        print("\n  ⚠️ NINGUN SKU tiene inv_valor_avg > 0. Posibles causas:")
        print("     - x_analisis_de_stock todavía no se ha corrido tras v19.2")
        print("     - Los nombres de campos en STOCK_PRODUCT_FIELD/STOCK_QTY_FIELD/STOCK_COST_FIELD no calzan")
        print("     - x_analisis_de_stock está vacío o con x_active=False")


print("\nDONE.")
