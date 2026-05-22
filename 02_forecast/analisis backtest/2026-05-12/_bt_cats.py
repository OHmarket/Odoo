"""Enumera categorias del CSV para confirmar filtros de exclusion."""
import pandas as pd

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).csv"
df = pd.read_csv(PATH, encoding="utf-8", low_memory=False)
df["real_qty"] = pd.to_numeric(df["real_qty"], errors="coerce").fillna(0.0)

print("=" * 80)
print("CATEGORIAS UNICAS Y VOLUMEN REAL")
print("=" * 80)

cats = (
    df.groupby("categ_id", dropna=False)
    .agg(filas=("real_qty", "size"), real=("real_qty", "sum"))
    .reset_index()
    .sort_values("real", ascending=False)
)
cats["%_real"] = cats["real"] / cats["real"].sum() * 100
print(cats.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))

print("\n" + "=" * 80)
print("CATEGORIAS QUE EL FILTRO ACTUAL CAPTURA (Cerveza | Cigarrillo|Tabaco | Snack)")
print("=" * 80)
pat = r"Cerveza|Cigarrillo|Tabaco|Snack"
mask = df["categ_id"].fillna("").str.contains(pat, case=False, regex=True)
hit = (
    df[mask].groupby("categ_id")
    .agg(filas=("real_qty", "size"), real=("real_qty", "sum"))
    .reset_index().sort_values("real", ascending=False)
)
print(hit.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
print(f"\nTOTAL CAPTURADO: {hit['real'].sum():,.0f} unidades ({hit['real'].sum()/df['real_qty'].sum()*100:.1f}%)")

print("\n" + "=" * 80)
print("BUSQUEDA DE 'IMPULSIVOS' — donde viven chicles, chocolates, caramelos")
print("=" * 80)
impul_skus = df[df["product_id"].str.contains("CHICLE|CHOCOLATE|CARAMELO|BIGTIME|BON O BON", case=False, na=False, regex=True)]
print("Categorias asociadas a SKUs de impulsivos:")
print(impul_skus.groupby("categ_id").agg(filas=("real_qty", "size"), real=("real_qty", "sum")).sort_values("real", ascending=False).to_string(float_format=lambda x: f"{x:,.1f}"))

print("\n" + "=" * 80)
print("CATEGORIAS QUE NO MATCHEAN EL FILTRO PERO SUENAN A IMPULSIVO")
print("=" * 80)
no_match = df[~mask]
sospechosas = no_match[no_match["categ_id"].fillna("").str.contains("Chicle|Chocolate|Caramelo|Confite|Impuls|Galleta", case=False, regex=True)]
print(sospechosas.groupby("categ_id").agg(filas=("real_qty", "size"), real=("real_qty", "sum")).sort_values("real", ascending=False).to_string(float_format=lambda x: f"{x:,.1f}"))
