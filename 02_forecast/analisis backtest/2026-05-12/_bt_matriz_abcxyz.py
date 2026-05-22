"""
Performance medida en la matriz 9-cubetas ABCXYZ.

Hipotesis: la letra XYZ (estabilidad de la demanda) determina que modelo
aplicar. La letra ABC (importancia) determina si forecasteamos.

  X (CV<=0.45)   = demanda estable    -> modelo simple basta
  Y (CV<=0.90)   = demanda variable   -> exponencial suavizado / Holt damped
  Z (CV>0.90)    = demanda esporadica -> Croston/SBA
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
hm["abc_letter"] = hm["abcxyz"].fillna("").str[:1].str.upper()
hm["xyz_letter"] = hm["abcxyz"].fillna("").str[-1:].str.upper()

total_real = hm["real_qty"].sum()
total_n = len(hm)

print("=" * 120)
print("MATRIZ 9-CUBETAS ABCXYZ — performance medida (file 10)")
print(f"Universo: {total_n:,} filas | real total: {total_real:,.0f}")
print("=" * 120)


# Calcular WAPE/BIAS por cubeta
rows = []
for abc in ['A', 'B', 'C']:
    for xyz in ['X', 'Y', 'Z']:
        sub = hm[(hm["abc_letter"] == abc) & (hm["xyz_letter"] == xyz)]
        n = len(sub)
        if n == 0:
            continue
        real = sub["real_qty"].sum()
        fcst = sub["forecast_qty"].sum()
        ae = sub["abs_error_qty"].sum()
        e = sub["error_qty"].sum()
        n_skus = sub["product_id"].nunique()
        rows.append({
            "cubeta": f"{abc}{xyz}",
            "n_skus": n_skus,
            "n_filas": n,
            "real": real,
            "share_vol_%": real / total_real * 100,
            "fcst": fcst,
            "wape_%": (ae / real * 100) if real > 0 else np.nan,
            "bias_%": (e / real * 100) if real > 0 else np.nan,
        })

df_matrix = pd.DataFrame(rows).sort_values("share_vol_%", ascending=False)
print("\n1. WAPE y BIAS por cada cubeta ABCXYZ (ordenado por % volumen)")
print("-" * 120)
print(df_matrix.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# Vista pivot WAPE
print("\n" + "=" * 120)
print("2. MATRIZ WAPE (%) — fila ABC × columna XYZ")
print("=" * 120)
wape_matrix = df_matrix.pivot(index="cubeta", columns=None, values="wape_%")
# Pivot mejor con dos dims
hm_grp = hm.groupby(["abc_letter", "xyz_letter"]).agg(
    real=("real_qty", "sum"),
    ae=("abs_error_qty", "sum"),
    e=("error_qty", "sum"),
    n_filas=("real_qty", "size"),
).reset_index()
hm_grp["wape"] = hm_grp["ae"] / hm_grp["real"] * 100
hm_grp["bias"] = hm_grp["e"] / hm_grp["real"] * 100

pivot_wape = hm_grp.pivot(index="abc_letter", columns="xyz_letter", values="wape").round(1)
pivot_bias = hm_grp.pivot(index="abc_letter", columns="xyz_letter", values="bias").round(1)
pivot_n = hm_grp.pivot(index="abc_letter", columns="xyz_letter", values="n_filas")
pivot_real = hm_grp.pivot(index="abc_letter", columns="xyz_letter", values="real").round(0)

print("\nWAPE %:")
print(pivot_wape.to_string())
print("\nBIAS %:")
print(pivot_bias.to_string())
print("\nVolumen real (unid 3sem):")
print(pivot_real.to_string(float_format=lambda x: f"{x:,.0f}"))
print("\nN filas backtest:")
print(pivot_n.to_string())


# Mapeo a modelo recomendado segun teoria
print("\n" + "=" * 120)
print("3. MODELO RECOMENDADO POR CUBETA — basado en teoria + datos medidos")
print("=" * 120)

modelos = {
    "AX": ("Holt linear simple (level + trend)", "v3.24 actual o Holt α=0.20", "Mejor cubeta del POS — no tocar"),
    "AY": ("Holt damped (Gardner-McKenzie 1985)", "α=0.25 β=0.10 φ=0.90", "El sub-forecast aqui es donde se pierde margen"),
    "AZ": ("Croston/SBA (Syntetos-Boylan 2005)", "SBA α=0.10", "Whisky/vino premium — alto margen baja rotacion"),
    "BX": ("Holt linear simple", "v3.24 actual", "Estable, menor importancia"),
    "BY": ("Holt damped", "α=0.30 β=0.10 φ=0.85", "Mas reactivo que AY por menor margen"),
    "BZ": ("SBA", "α=0.08", "Lumpy/intermittent de margen medio"),
    "CX": ("(N/A — solo 10 SKUs, 0.3% vol)", "forecast=0 o motor degradado", "Marginal"),
    "CY": ("(N/A — bajo margen)", "forecast=0 / min_stock", "Marginal economicamente"),
    "CZ": ("(N/A — la cola)", "forecast=0 / min_stock manual", "35% de SKUs, 1.4% volumen"),
}

print(f"\n{'Cubeta':<8} {'n SKUs':>8} {'%vol':>7} {'WAPE':>7} {'BIAS':>7}   {'Modelo recomendado':<40}  Comentario")
print("-" * 130)
for _, row in df_matrix.iterrows():
    c = row["cubeta"]
    mod, params, com = modelos.get(c, ("?", "?", "?"))
    print(f"{c:<8} {int(row['n_skus']):>8,} {row['share_vol_%']:>6.1f}% {row['wape_%']:>6.1f}% {row['bias_%']:>+6.1f}%   {mod:<40}  {com}")

print("\n" + "=" * 120)
print("4. SINTESIS — La decision matriz")
print("=" * 120)
print("""
Decision 1: SI forecastear (ABC)
  A → SI (82.6% del volumen, 80%+ del margen)
  B → SI (13.2% volumen, 15% margen)
  C → NO (4.2% volumen, 5% margen) — forecast=0 / min_stock manual

Decision 2: COMO forecastear (XYZ)
  X → Holt linear simple   (estable, motor v3.24 o Holt α=0.20)
  Y → Holt damped          (variable, α=0.25-0.30 con damping φ=0.85-0.90)
  Z → SBA                  (esporadico, α=0.08-0.10)

Las 6 cubetas activas:
  AX (52% vol) → motor v3.24 actual o Holt linear suave  [excelente hoy: WAPE 53%, BIAS -1%]
  AY (27% vol) → Holt damped                              [hoy WAPE 75%, BIAS +8% — espacio para mejorar]
  AZ ( 3% vol) → SBA                                       [hoy WAPE 87%, BIAS +48% — sub-forecast severo]
  BX ( 6% vol) → Holt linear simple                       [hoy estable]
  BY ( 7% vol) → Holt damped                              [hoy con dispersion]
  BZ ( 1% vol) → SBA                                       [hoy marginal]

C (CX/CY/CZ — 4.2% volumen, 899 SKUs) → forecast = 0 / stock manual
""")

print("DONE.")
