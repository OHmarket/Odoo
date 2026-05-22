"""
Alarmas de quiebre — SKUs sin inventario cruzados con la clasificación.

Niveles de alarma:
  ROJA       : critico/alto con regimen activo (REG-1..6) sin stock
  NARANJA    : medio con regimen activo (REG-1..6) sin stock
  AMARILLA   : bajo con mu_week >= 1 sin stock
  INFO       : terminales (REG-0/REG-7/REG-8) o mu_week ~ 0 sin stock (esperable)
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Calculo ABC  XYZ (x_calculo_abc_xyz) (1).xlsx"

df = pd.read_excel(PATH, engine="openpyxl")
df = df.rename(columns={
    "Producto": "product",
    "Categoria": "categ",
    "ABCXYZ": "abcxyz",
    "Ciclo de Vida": "ciclo",
    "Promedio Semanal": "mu_week",
    "importancia": "importancia",
    "Eliminar (Si/No)": "eliminar",
})

# Tipos
for c in ["adi", "cv2", "gmroi", "inv_valor_avg", "mu_week"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

# Filtrar SKUs sin inventario
sin_stock = df[df["inv_valor_avg"] == 0].copy()
print("=" * 90)
print(f"SKUs SIN INVENTARIO: {len(sin_stock):,} ({len(sin_stock)/len(df)*100:.1f}% del catalogo)")
print("=" * 90)


# ----------------------------------------------------------------------
# 1. Composicion por dimension
# ----------------------------------------------------------------------
def crosstab(col):
    g = sin_stock.groupby(col, dropna=False).agg(
        n_sin_stock=("product", "size"),
        mu_sum=("mu_week", "sum"),
        mu_p50=("mu_week", "median"),
        mu_max=("mu_week", "max"),
    ).reset_index()
    g["%_de_sin_stock"] = g["n_sin_stock"] / len(sin_stock) * 100
    # Compara con cobertura total
    base = df.groupby(col, dropna=False)["product"].size().rename("n_total").reset_index()
    g = g.merge(base, on=col, how="left")
    g["%_sin_stock_del_grupo"] = g["n_sin_stock"] / g["n_total"] * 100
    return g.sort_values("n_sin_stock", ascending=False)


print("\n--- Por abcxyz ---")
print(crosstab("abcxyz").to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n--- Por importancia ---")
print(crosstab("importancia").to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n--- Por regimen ---")
print(crosstab("regimen").to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n--- Por ciclo de vida ---")
print(crosstab("ciclo").to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 2. Asignar nivel de alarma a cada SKU
# ----------------------------------------------------------------------
ACTIVE_REGS = {"REG-1", "REG-2", "REG-3", "REG-4", "REG-5", "REG-6"}
TERMINAL_REGS = {"REG-0", "REG-7", "REG-8"}

def nivel_alarma(row):
    imp = str(row["importancia"] or "").strip().lower()
    reg = (row["regimen"] or "").strip()
    mu = row["mu_week"] or 0
    if reg in TERMINAL_REGS:
        return "INFO"
    if mu < 0.5:
        return "INFO"
    if imp in ("critico", "alto") and reg in ACTIVE_REGS:
        return "ROJA"
    if imp == "medio" and reg in ACTIVE_REGS:
        return "NARANJA"
    if imp == "bajo" and mu >= 1.0:
        return "AMARILLA"
    return "INFO"

sin_stock["alarma"] = sin_stock.apply(nivel_alarma, axis=1)

# Resumen por alarma
print("\n" + "=" * 90)
print("RESUMEN POR NIVEL DE ALARMA")
print("=" * 90)
resumen = sin_stock.groupby("alarma").agg(
    skus=("product", "size"),
    mu_total=("mu_week", "sum"),
    mu_mediana=("mu_week", "median"),
).reset_index()
orden = {"ROJA": 0, "NARANJA": 1, "AMARILLA": 2, "INFO": 3}
resumen["orden"] = resumen["alarma"].map(orden)
resumen = resumen.sort_values("orden").drop(columns=["orden"])
print(resumen.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 3. Listado por alarma
# ----------------------------------------------------------------------
COLS_SHOW = ["product", "abcxyz", "regimen", "importancia", "ciclo", "mu_week", "adi", "cv2", "categ"]

for nivel in ["ROJA", "NARANJA", "AMARILLA"]:
    sub = sin_stock[sin_stock["alarma"] == nivel].sort_values("mu_week", ascending=False)
    print("\n" + "=" * 90)
    print(f"ALARMA {nivel} — {len(sub)} SKUs (ordenados por mu_week desc)")
    print("=" * 90)
    if len(sub) == 0:
        print("(sin entradas)")
    else:
        print(sub[COLS_SHOW].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# 4. INFO — primeros 20 solo para ver que efectivamente son terminales
# ----------------------------------------------------------------------
info = sin_stock[sin_stock["alarma"] == "INFO"]
print("\n" + "=" * 90)
print(f"INFO — {len(info)} SKUs (terminales o mu~0, no requieren accion)")
print("=" * 90)
print("Distribucion por regimen:")
print(info["regimen"].value_counts().to_string())
print("\nDistribucion por ciclo:")
print(info["ciclo"].value_counts().to_string())


# ----------------------------------------------------------------------
# 5. Exportar CSV operativo
# ----------------------------------------------------------------------
out_path = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_abc_alarmas.csv"
priorizado = sin_stock.copy()
priorizado["orden_alarma"] = priorizado["alarma"].map(orden)
priorizado = priorizado.sort_values(["orden_alarma", "mu_week"], ascending=[True, False])
priorizado[["alarma"] + COLS_SHOW + ["gmroi_class"]].to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nExportado: {out_path}")
print("\nDONE.")
