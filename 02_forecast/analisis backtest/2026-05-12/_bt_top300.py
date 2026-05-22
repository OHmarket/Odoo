"""
Top 300 SKUs por volumen real — el dinero del negocio.
Muestra perfil completo y diagnostica calidad del forecast en este universo.
"""
import pandas as pd
import numpy as np

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest).csv"

df = pd.read_csv(PATH, encoding="utf-8", low_memory=False)
for c in ["abs_error_qty", "bias_pct", "cv2", "error_qty", "forecast_qty", "real_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df["categ_id"] = df["categ_id"].fillna("")

# Flag de bolsa de ruido (informativo, no excluye)
EXCLUDE_PAT = r"Cerveza|Cigarrillo|Tabaco|Snack|Impulso"
df["bolsa_ruido"] = df["categ_id"].str.contains(EXCLUDE_PAT, case=False, regex=True, na=False)
df["bolsa_team_nuevo"] = df["team_id"].fillna("").str.contains("Ventas San Jos", case=False)

# Agregar por SKU (sumar todos los teams y semanas)
prod = df.groupby("product_id", as_index=False).agg(
    n_filas=("real_qty", "size"),
    n_teams=("team_id", "nunique"),
    n_semanas=("target_week_start", "nunique"),
    real_total=("real_qty", "sum"),
    fcst_total=("forecast_qty", "sum"),
    abs_err_total=("abs_error_qty", "sum"),
    err_total=("error_qty", "sum"),
    n_sem_con_venta=("real_qty", lambda s: (s > 0).sum()),
    categ_id=("categ_id", "first"),
    abcxyz=("abcxyz", "first"),
    series_type=("series_type", "first"),
    forecast_zone=("forecast_zone", "first"),
    importancia=("importancia", "first"),
    ciclo_de_vida=("ciclo_de_vida", "first"),
    price_dynamics_segment=("price_dynamics_segment", "first"),
    es_ruido=("bolsa_ruido", "first"),
)
prod["wape_%"] = prod["abs_err_total"] / prod["real_total"].replace(0, np.nan) * 100
prod["bias_%"] = prod["err_total"] / prod["real_total"].replace(0, np.nan) * 100
prod["intensidad_venta"] = prod["n_sem_con_venta"] / prod["n_filas"]
prod["categ_l1"] = prod["categ_id"].str.split(" / ").str[0]
prod["categ_l2"] = prod["categ_id"].str.split(" / ").str[:2].str.join(" / ")

# Ranking por volumen real
prod = prod.sort_values("real_total", ascending=False).reset_index(drop=True)
prod["rank"] = prod.index + 1
prod["cum_real"] = prod["real_total"].cumsum()
prod["cum_real_pct"] = prod["cum_real"] / prod["real_total"].sum() * 100

TOP = 300
top = prod.head(TOP).copy()
total_skus = len(prod)
real_total_global = prod["real_total"].sum()

print("=" * 100)
print(f"TOP {TOP} SKUs POR VOLUMEN REAL (universo COMPLETO, sin filtrar bolsas)")
print("=" * 100)
print(f"Universo total SKUs           : {total_skus:,}")
print(f"Top {TOP} concentra            : {top['real_total'].sum():,.0f} u  ({top['real_total'].sum()/real_total_global*100:.1f}% del volumen)")
print(f"SKUs para 50% volumen         : {(prod['cum_real_pct'] <= 50).sum() + 1:,}")
print(f"SKUs para 80% volumen         : {(prod['cum_real_pct'] <= 80).sum() + 1:,}")
print(f"SKUs para 95% volumen         : {(prod['cum_real_pct'] <= 95).sum() + 1:,}")

# Metricas globales top
r = top["real_total"].sum()
f = top["fcst_total"].sum()
ae = top["abs_err_total"].sum()
e = top["err_total"].sum()
print(f"\nMetricas Top {TOP}:")
print(f"  Real total     : {r:,.0f}")
print(f"  Forecast total : {f:,.0f}")
print(f"  WAPE           : {ae/r*100:.2f}%")
print(f"  BIAS           : {e/r*100:+.2f}%")


# Cuantos del top estan en bolsas de ruido / core
print("\n" + "=" * 100)
print(f"COMPOSICION del Top {TOP} por exclusion")
print("=" * 100)
top_clean = top[~top["es_ruido"]].copy()
top_ruido = top[top["es_ruido"]].copy()
print(f"En core limpio       : {len(top_clean):>3,} SKUs  ({top_clean['real_total'].sum():,.0f} u, WAPE {top_clean['abs_err_total'].sum()/top_clean['real_total'].sum()*100:.2f}%, BIAS {top_clean['err_total'].sum()/top_clean['real_total'].sum()*100:+.2f}%)")
print(f"En bolsa de ruido    : {len(top_ruido):>3,} SKUs  ({top_ruido['real_total'].sum():,.0f} u, WAPE {top_ruido['abs_err_total'].sum()/top_ruido['real_total'].sum()*100:.2f}%, BIAS {top_ruido['err_total'].sum()/top_ruido['real_total'].sum()*100:+.2f}%)")


# Composicion por dimension del modelo
def dist(col, label):
    print("\n" + "=" * 100)
    print(f"{label} — Top {TOP}")
    print("=" * 100)
    g = top.groupby(col, dropna=False).agg(
        skus=("product_id", "size"),
        real=("real_total", "sum"),
        fcst=("fcst_total", "sum"),
        abs_err=("abs_err_total", "sum"),
        err=("err_total", "sum"),
    ).reset_index()
    g["wape_%"] = g["abs_err"] / g["real"].replace(0, np.nan) * 100
    g["bias_%"] = g["err"] / g["real"].replace(0, np.nan) * 100
    g["%_real_top"] = g["real"] / r * 100
    g = g.sort_values("real", ascending=False)
    print(g.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

dist("categ_l1", "Por categoria L1")
dist("abcxyz", "Por abcxyz")
dist("series_type", "Por series_type")
dist("forecast_zone", "Por forecast_zone")
dist("importancia", "Por importancia")
dist("ciclo_de_vida", "Por ciclo_de_vida")
dist("price_dynamics_segment", "Por price_dynamics_segment")


# Buckets de calidad del forecast
print("\n" + "=" * 100)
print(f"CALIDAD DEL FORECAST — distribucion de WAPE del Top {TOP}")
print("=" * 100)
top["wape_bucket"] = pd.cut(
    top["wape_%"],
    bins=[-np.inf, 20, 35, 50, 70, 100, np.inf],
    labels=["excelente (<20%)", "bueno (20-35%)", "aceptable (35-50%)",
            "malo (50-70%)", "muy malo (70-100%)", "fuera de control (>100%)"],
)
buckets = top.groupby("wape_bucket", observed=True).agg(
    skus=("product_id", "size"),
    real=("real_total", "sum"),
    fcst=("fcst_total", "sum"),
    err=("err_total", "sum"),
).reset_index()
buckets["%_skus"] = buckets["skus"] / TOP * 100
buckets["%_real"] = buckets["real"] / r * 100
buckets["bias_%"] = buckets["err"] / buckets["real"] * 100
print(buckets.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# Buckets BIAS
print("\n" + "=" * 100)
print(f"BIAS — distribucion del Top {TOP}")
print("=" * 100)
top["bias_bucket"] = pd.cut(
    top["bias_%"],
    bins=[-np.inf, -50, -20, -5, 5, 20, 50, np.inf],
    labels=["sobre fuerte (<-50%)", "sobre (-50..-20%)", "sobre leve (-20..-5%)",
            "calibrado (-5..+5%)", "sub leve (+5..+20%)",
            "sub (+20..+50%)", "sub fuerte (>+50%)"],
)
bb = top.groupby("bias_bucket", observed=True).agg(
    skus=("product_id", "size"),
    real=("real_total", "sum"),
).reset_index()
bb["%_skus"] = bb["skus"] / TOP * 100
bb["%_real"] = bb["real"] / r * 100
print(bb.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# Detalle del Top 300 — listado completo
print("\n" + "=" * 100)
print(f"LISTADO COMPLETO — Top {TOP} ordenado por volumen real")
print("=" * 100)
cols_show = ["rank", "product_id", "real_total", "fcst_total", "wape_%", "bias_%",
             "abcxyz", "series_type", "forecast_zone", "importancia", "ciclo_de_vida",
             "es_ruido", "categ_l2"]
print(top[cols_show].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# Top 30 con peor WAPE del top 300 — donde duele
print("\n" + "=" * 100)
print(f"TOP {TOP} — los 30 SKUs con PEOR WAPE (riesgo de error grande en volumen alto)")
print("=" * 100)
peor = top.sort_values("wape_%", ascending=False).head(30)
print(peor[cols_show + ["abs_err_total"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# Top 30 con peor BIAS positivo (sub-forecast) y negativo (sobre)
print("\n" + "=" * 100)
print(f"TOP {TOP} — los 30 mas SUB-FORECAST (ranking por err_total positivo)")
print("=" * 100)
sub = top[top["err_total"] > 0].sort_values("err_total", ascending=False).head(30)
print(sub[cols_show + ["err_total"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 100)
print(f"TOP {TOP} — los 30 mas SOBRE-FORECAST (ranking por err_total negativo)")
print("=" * 100)
sob = top[top["err_total"] < 0].sort_values("err_total", ascending=True).head(30)
print(sob[cols_show + ["err_total"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# Export csv del top 300 para inspeccion en planilla
out_path = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_bt_top300.csv"
top[cols_show + ["err_total", "abs_err_total", "n_filas", "n_teams", "intensidad_venta"]].to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"\nExportado CSV del Top 300: {out_path}")
print("\nDONE.")
