"""
Tabla por zona Z1-Z4 con foco en volumen de ventas (real).
Datos: file 10 (v3.25). Solo hm_si.
"""
import pandas as pd

PATH = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
df = pd.read_excel(PATH, engine="openpyxl")
weeks = sorted(df["target_week_start"].dropna().unique())
if len(weeks) > 3:
    df = df[df["target_week_start"].isin(weeks[-3:])].copy()
for c in ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
hm = df[df["method"] == "hm_si"].copy()

total_n = len(hm)
total_real = hm["real_qty"].sum()
total_fcst = hm["forecast_qty"].sum()

print("=" * 100)
print(f"FILE 10 (v3.25)  |  total n={total_n:,}  |  total real={total_real:,.0f}  |  total fcst={total_fcst:,.0f}")
print("=" * 100)

rows = []
for z in ['Z1', 'Z2', 'Z3', 'Z4', 'SIN_ZONA']:
    sub = hm[hm["forecast_zone"] == z]
    n = len(sub)
    real = sub["real_qty"].sum()
    fcst = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    rows.append({
        "zone": z,
        "n_filas": n,
        "share_n_%": n / total_n * 100,
        "real": real,
        "share_real_%": real / total_real * 100 if total_real > 0 else 0,
        "forecast": fcst,
        "WAPE_%": (ae / real * 100) if real > 0 else float('nan'),
        "BIAS_%": (e / real * 100) if real > 0 else float('nan'),
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

print("\n" + "=" * 100)
print("Cuanto del real total esta en cada zona (donde esta el negocio):")
print("=" * 100)
for r in rows:
    print(f"  {r['zone']}: {r['share_real_%']:5.1f}% del real ({r['real']:,.0f} unid)  |  {r['share_n_%']:5.1f}% de las filas ({r['n_filas']:,})")
