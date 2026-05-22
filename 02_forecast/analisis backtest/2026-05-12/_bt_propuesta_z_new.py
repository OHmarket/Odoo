"""
Valida la propuesta de 6 zonas nuevas (Z1, Z2-New ... Z6-Low) midiendo
el % de volumen real de cada una sobre el file 10.

Mapeo propuesto:
  Z1:      smooth AX/AY/BX mature/ramp_up con mu>=1 (AX) o mu>=2 (otros)
  Z2-New:  REG-2 + REG-3 + REG-4 + REG-1 fuera de Z1
  Z3-New:  REG-8 (seasonal)
  Z4-New:  REG-7 (intermittent) + REG-6 (lumpy C)
  Z5-New:  REG-5 (lumpy A/B)
  Z6-Low:  REG-0 + resto
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

total_real = hm["real_qty"].sum()
total_n = len(hm)


def asignar_z_new(row):
    z_actual = row["forecast_zone"]
    reg = row["regimen"]
    if z_actual == "Z1":
        return "Z1"
    if reg == "REG-1":
        return "Z2-New"  # REG-1 fuera de Z1 (mu<2)
    if reg in ("REG-2", "REG-3", "REG-4"):
        return "Z2-New"
    if reg == "REG-8":
        return "Z3-New"
    if reg in ("REG-6", "REG-7"):
        return "Z4-New"
    if reg == "REG-5":
        return "Z5-New"
    return "Z6-Low"  # REG-0, NaN, SIN_ZONA, etc.


hm["z_new"] = hm.apply(asignar_z_new, axis=1)

print("=" * 110)
print(f"PROPUESTA Z-NEW  |  total n={total_n:,}  |  total real={total_real:,.0f}")
print("=" * 110)

rows = []
for zn in ["Z1", "Z2-New", "Z3-New", "Z4-New", "Z5-New", "Z6-Low"]:
    sub = hm[hm["z_new"] == zn]
    n = len(sub)
    real = sub["real_qty"].sum()
    fcst = sub["forecast_qty"].sum()
    ae = sub["abs_error_qty"].sum()
    e = sub["error_qty"].sum()
    rows.append({
        "z_new": zn,
        "n_filas": n,
        "share_n_%": n / total_n * 100,
        "real": real,
        "share_real_%": real / total_real * 100 if total_real > 0 else 0,
        "forecast": fcst,
        "WAPE_%": (ae / real * 100) if real > 0 else float('nan'),
        "BIAS_%": (e / real * 100) if real > 0 else float('nan'),
    })
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# Detalle Z2-New: que regimen aporta cuanto
print("\n" + "=" * 110)
print("DETALLE Z2-New (composicion interna)")
print("=" * 110)
sub_z2 = hm[hm["z_new"] == "Z2-New"]
for reg in sorted(sub_z2["regimen"].dropna().unique()):
    s = sub_z2[sub_z2["regimen"] == reg]
    print(f"  {reg}: n={len(s):>6,}  real={s['real_qty'].sum():>10,.0f}  share_real_z2={s['real_qty'].sum()/sub_z2['real_qty'].sum()*100:5.1f}%")

# Verificacion: suma debe dar 108,714
total_check = sum(r["real"] for r in rows)
print(f"\nVerificacion: suma de reales = {total_check:,.0f} (debe ser {total_real:,.0f})")

print("\nDONE.")
