"""
Cuantas Cervezas subieron vs bajaron de precio en 2026, y cuanto.
Para entender si el problema es asimetrico (puro suben vs equilibrado).
"""
import pandas as pd
import numpy as np

PRICE = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
dfp = pd.read_excel(PRICE, engine="openpyxl")
dfp["Fecha"] = pd.to_datetime(dfp["Fecha"], errors="coerce")

# Filtrar categoria Cervezas
mask_cerv = dfp["Categoria"].astype(str).str.contains("Cervezas", case=False, na=False)
cerv = dfp[mask_cerv].copy()
print(f"Total cambios en categoria Cervezas: {len(cerv):,}")

# ----------------------------------------------------------------------
# 1. Distribucion por año y direccion
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("1. CERVEZAS - cambios por año y direccion")
print("=" * 100)
cerv["year"] = cerv["Fecha"].dt.year
direccion_col = "Direcci\xf3n"  # con ñ encoding
if direccion_col not in cerv.columns:
    for c in cerv.columns:
        if "irecci" in c.lower():
            direccion_col = c
            break
print(f"\nColumna direccion: '{direccion_col}'")
print(pd.crosstab(cerv["year"], cerv[direccion_col], margins=True).to_string())

# ----------------------------------------------------------------------
# 2. Foco en 2026 + sub-categoria Cervezas
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. CERVEZAS 2026 - cambios por sub-categoria y direccion")
print("=" * 100)
cerv_2026 = cerv[cerv["year"] == 2026].copy()
print(f"\nTotal Cervezas 2026: {len(cerv_2026):,}")

# Crear sub-categoria desde "Bebidas Alcoholicas / Cervezas / XXX"
def sub_categoria(s):
    try:
        parts = str(s).split(' / ')
        if len(parts) >= 3:
            return parts[2]
        return parts[-1]
    except Exception:
        return 'OTRO'

cerv_2026["sub"] = cerv_2026["Categoria"].apply(sub_categoria)
print(pd.crosstab(cerv_2026["sub"], cerv_2026[direccion_col], margins=True).to_string())

# ----------------------------------------------------------------------
# 3. Foco en periodo W15-W19 (2026-04-06 a 2026-05-10)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. CERVEZAS en W15-W19 (2026-04-06 a 2026-05-10) - todos los cambios")
print("=" * 100)
W15_START = pd.Timestamp("2026-04-06")
W19_END = pd.Timestamp("2026-05-10")
cerv_bt = cerv_2026[(cerv_2026["Fecha"] >= W15_START) & (cerv_2026["Fecha"] <= W19_END)].copy()
print(f"\nCambios en periodo W15-W19: {len(cerv_bt):,}")

if len(cerv_bt) > 0:
    print(f"\nDistribucion direccion x sub-categoria:")
    print(pd.crosstab(cerv_bt["sub"], cerv_bt[direccion_col], margins=True).to_string())

    print(f"\nDistribucion magnitud:")
    cerv_bt["var_abs"] = cerv_bt["Variacion %"].abs()
    print(f"  Promedio variacion absoluta: {cerv_bt['var_abs'].mean()*100:.1f}%")
    print(f"  Mediana variacion absoluta: {cerv_bt['var_abs'].median()*100:.1f}%")

    # Buckets de variacion
    print(f"\nBuckets de variacion (todos los cambios W15-W19):")
    buckets = [
        (-1, -0.15, "BAJADA_FUERTE (<-15%)"),
        (-0.15, -0.05, "BAJADA_LEVE (-15 a -5%)"),
        (-0.05, 0.05, "ESTABLE (±5%)"),
        (0.05, 0.15, "SUBIDA_LEVE (5 a 15%)"),
        (0.15, 10, "SUBIDA_FUERTE (>15%)"),
    ]
    for low, high, label in buckets:
        mask = (cerv_bt["Variacion %"] >= low) & (cerv_bt["Variacion %"] < high)
        n = mask.sum()
        if n > 0:
            print(f"  {label:<28} {n:>4} cambios ({n/len(cerv_bt)*100:5.1f}%)")

    # ----------------------------------------------------------------------
    # 4. Listar las BAJADAS especificamente
    # ----------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("4. BAJADAS DE PRECIO en Cervezas durante W15-W19 (lista completa)")
    print("=" * 100)
    bajadas = cerv_bt[cerv_bt[direccion_col].astype(str).str.contains("aja", na=False)].copy()
    print(f"\nTotal bajadas: {len(bajadas):,}")
    if len(bajadas) > 0:
        cols = ["Fecha", "Producto", "Precio Anterior", "Precio", "Variacion %", "sub"]
        cols = [c for c in cols if c in bajadas.columns]
        print(bajadas.sort_values("Variacion %")[cols].to_string(index=False))


# ----------------------------------------------------------------------
# 5. Listar las SUBIDAS especificamente
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. SUBIDAS DE PRECIO en Cervezas durante W15-W19 (top 20 por magnitud)")
print("=" * 100)
subidas = cerv_bt[cerv_bt[direccion_col].astype(str).str.contains("ube", na=False)].copy()
print(f"\nTotal subidas: {len(subidas):,}")
if len(subidas) > 0:
    cols = ["Fecha", "Producto", "Precio Anterior", "Precio", "Variacion %", "sub"]
    cols = [c for c in cols if c in subidas.columns]
    print(subidas.sort_values("Variacion %", ascending=False).head(20)[cols].to_string(index=False))


# ----------------------------------------------------------------------
# 6. Net effect: SKUs unicos
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. NET: cuantos SKUs unicos de Cervezas tuvieron cambio en el periodo")
print("=" * 100)
n_subidas_unique = subidas["Producto"].nunique() if len(subidas) > 0 else 0
n_bajadas_unique = bajadas["Producto"].nunique() if len(bajadas) > 0 else 0
print(f"  SKUs unicos con subida: {n_subidas_unique:,}")
print(f"  SKUs unicos con bajada: {n_bajadas_unique:,}")
print(f"  Ratio subida:bajada = {n_subidas_unique}/{n_bajadas_unique}")

print("\nDONE.")
