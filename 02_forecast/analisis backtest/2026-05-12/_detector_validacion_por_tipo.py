"""
Validar efecto del detector POR TIPO de alerta.
Identifica que tipos son confiables (mejoran) y cuales son ruido (empeoran).
"""
import pandas as pd
import numpy as np

PATH_OUT = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_detector_anomalias_output.xlsx"
df = pd.read_excel(PATH_OUT, engine="openpyxl")

print("=" * 110)
print("VALIDACION POR TIPO DE ALERTA")
print("=" * 110)
print(f"Total alertas (3 semanas): {len(df):,}")

# Por tipo: calcular efecto neto
print(f"\n{'tipo_alerta':<25} {'n':>5} {'real':>8} {'fcst_orig':>10} {'fcst_corr':>10} {'ae_orig':>8} {'ae_corr':>8} {'mejora':>10} {'pct_mejora':>12} {'bias_orig':>10} {'bias_corr':>10}")
print("-" * 130)
rows = []
for tipo in df["tipo_alerta"].unique():
    sub = df[df["tipo_alerta"] == tipo]
    if len(sub) == 0:
        continue
    real = sub["real"].sum()
    fcst_orig = sub["forecast_v3_24"].sum()
    fcst_corr = sub["forecast_corregido"].sum()
    ae_orig = sub["abs_err_original"].sum()
    ae_corr = sub["abs_err_corregido"].sum()
    mejora = ae_orig - ae_corr
    pct_mejora = mejora / ae_orig * 100 if ae_orig > 0 else 0
    bias_orig = (fcst_orig - real) / real * 100 if real > 0 else float('nan')
    bias_corr = (fcst_corr - real) / real * 100 if real > 0 else float('nan')
    rows.append({
        "tipo": tipo, "n": len(sub), "real": real,
        "fcst_orig": fcst_orig, "fcst_corr": fcst_corr,
        "ae_orig": ae_orig, "ae_corr": ae_corr,
        "mejora": mejora, "pct_mejora": pct_mejora,
        "bias_orig": bias_orig, "bias_corr": bias_corr,
    })
    print(f"{tipo:<25} {len(sub):>5,} {real:>8,.0f} {fcst_orig:>10,.0f} {fcst_corr:>10,.0f} {ae_orig:>8,.0f} {ae_corr:>8,.0f} {mejora:>+10,.0f} {pct_mejora:>+11.1f}% {bias_orig:>+9.1f}% {bias_corr:>+9.1f}%")

print("\n" + "=" * 110)
print("CLASIFICACION DE TIPOS — CUALES VALEN LA PENA APLICAR?")
print("=" * 110)

df_resumen = pd.DataFrame(rows).sort_values("mejora", ascending=False)
print("\n  TIPOS RECOMENDADOS (mejora real >0 y pct_mejora >0):")
buenos = df_resumen[df_resumen["mejora"] > 0]
print(buenos[["tipo", "n", "real", "ae_orig", "ae_corr", "mejora", "pct_mejora"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n  TIPOS A DESCARTAR (empeoran o son neutros):")
malos = df_resumen[df_resumen["mejora"] <= 0]
print(malos[["tipo", "n", "real", "ae_orig", "ae_corr", "mejora", "pct_mejora"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# Recalcular si solo aplicamos los tipos buenos
print("\n" + "=" * 110)
print("RECALCULO CONSERVADOR — Aplicar SOLO tipos con mejora positiva")
print("=" * 110)
tipos_buenos = buenos["tipo"].tolist()
df["aplicar"] = df["tipo_alerta"].isin(tipos_buenos)
df["fcst_final"] = np.where(df["aplicar"], df["forecast_corregido"], df["forecast_v3_24"])
df["ae_final"] = (df["fcst_final"] - df["real"]).abs()

real_total = df["real"].sum()
ae_orig_total = df["abs_err_original"].sum()
ae_final_total = df["ae_final"].sum()
mejora_neta = ae_orig_total - ae_final_total

print(f"\n  Tipos aplicados: {tipos_buenos}")
print(f"  SKUs con correccion aplicada: {df['aplicar'].sum():,} de {len(df):,}")
print(f"\n  Real total alertados: {real_total:,.0f}")
print(f"  abs_err original:     {ae_orig_total:,.0f}  WAPE {ae_orig_total/real_total*100:.2f}%")
print(f"  abs_err con tipos buenos: {ae_final_total:,.0f}  WAPE {ae_final_total/real_total*100:.2f}%")
print(f"  Mejora neta: {mejora_neta:+,.0f} unidades ({mejora_neta/ae_orig_total*100:+.1f}%)")

# Aplicar al full backtest hm_si (W17-W19) para ver impacto en WAPE global
print("\n" + "=" * 110)
print("IMPACTO EN WAPE GLOBAL HM-SI (estimacion)")
print("=" * 110)
TOTAL_HM_SI = 108714  # real total file 10
WAPE_ORIG_HM = 72.43
ae_total_hm = TOTAL_HM_SI * WAPE_ORIG_HM / 100  # ~78,750
# Si aplicamos correcciones de tipos buenos, restamos la mejora
ae_total_hm_nuevo = ae_total_hm - mejora_neta
wape_nuevo = ae_total_hm_nuevo / TOTAL_HM_SI * 100
print(f"\n  WAPE hm_si actual:          {WAPE_ORIG_HM:.2f}%")
print(f"  WAPE estimado con detector: {wape_nuevo:.2f}% (mejora ~{WAPE_ORIG_HM - wape_nuevo:.2f}pp)")

print("\nDONE.")
