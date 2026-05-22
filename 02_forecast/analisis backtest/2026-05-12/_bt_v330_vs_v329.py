"""Comparar (10) baseline / (11) v3.29 / (12) v3.30 con foco en forecast=0 con ventas."""
import pandas as pd
import numpy as np

PATHS = {
    "10 baseline":  r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx",
    "11 v3.29":     r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (11).xlsx",
    "12 v3.30":     r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (12).xlsx",
}


def _prep(path):
    df = pd.read_excel(path, engine="openpyxl")
    df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
    weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
    df = df[(df["method"] == "hm_si") & (df["target_week_start"].isin(weeks))].copy()
    df["forecast_qty"] = df["forecast_qty"].astype(float)
    df["real_qty"] = df["real_qty"].astype(float)
    df["abs_err"] = df["abs_error_qty"].astype(float)
    return df


print("Cargando...")
data = {k: _prep(p) for k, p in PATHS.items()}
for k, df in data.items():
    print(f"  {k}: {len(df):,} filas")


def _wb(df):
    f, r, e = df["forecast_qty"].sum(), df["real_qty"].sum(), df["abs_err"].sum()
    return f, r, e, (f-r)/r*100 if r > 0 else 0, e/r*100 if r > 0 else 0


print("\n" + "=" * 95)
print("GLOBAL hm_si W17-W19")
print("=" * 95)
print(f"{'version':<15} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 75)
for k, df in data.items():
    f, r, e, b, w = _wb(df)
    print(f"{k:<15} {len(df):>8,} {f:>10,.0f} {r:>10,.0f} {b:>+8.2f} {w:>8.2f}")

# ============ FORECAST=0 con VENTAS ============
print("\n" + "=" * 95)
print("FILAS CON forecast=0 PERO real>0")
print("=" * 95)
print(f"{'version':<15} {'n_zero+real':>13} {'real_lost':>10} {'%real':>8}")
print("-" * 60)
for k, df in data.items():
    sub = df[(df["forecast_qty"] <= 0.001) & (df["real_qty"] > 0)]
    real_total = df["real_qty"].sum()
    real_lost = sub["real_qty"].sum()
    print(f"{k:<15} {len(sub):>13,} {real_lost:>10,.0f} {real_lost/real_total*100:>7.2f}%")

# ============ POR ABCXYZ delta 11 vs 12 ============
print("\n" + "=" * 95)
print("DELTAS POR ABCXYZ: (12) v3.30 vs (11) v3.29")
print("=" * 95)
d11 = data["11 v3.29"]
d12 = data["12 v3.30"]
print(f"{'abcxyz':<6} {'n':>7} {'WAPE11':>8} {'WAPE12':>8} {'dWAPE':>8} {'BIAS11':>8} {'BIAS12':>8} {'fcast=0+real_11':>18} {'fcast=0+real_12':>18}")
print("-" * 110)
for abc in sorted(d12["abcxyz"].dropna().unique()):
    s11 = d11[d11["abcxyz"] == abc]
    s12 = d12[d12["abcxyz"] == abc]
    if len(s12) == 0:
        continue
    _, _, _, b11, w11 = _wb(s11)
    _, _, _, b12, w12 = _wb(s12)
    z11 = ((s11["forecast_qty"] <= 0.001) & (s11["real_qty"] > 0)).sum()
    z12 = ((s12["forecast_qty"] <= 0.001) & (s12["real_qty"] > 0)).sum()
    print(f"{str(abc):<6} {len(s12):>7,} {w11:>8.1f} {w12:>8.1f} {w12-w11:>+8.2f} {b11:>+8.1f} {b12:>+8.1f} {z11:>18,} {z12:>18,}")

# ============ por forecast_zone ============
print("\n" + "=" * 95)
print("CONTEO POR FORECAST_ZONE  (cambio en routing por AXY rescue)")
print("=" * 95)
print(f"{'zone':<10}", end='')
for k in PATHS: print(f"{k:>15}", end='')
print()
print("-" * 70)
zones = sorted(set(z for df in data.values() for z in df["forecast_zone"].dropna().unique()))
for z in zones:
    print(f"{z:<10}", end='')
    for k, df in data.items():
        n = (df["forecast_zone"] == z).sum()
        print(f"{n:>15,}", end='')
    print()

# ============ Conteo model_code (rescate AXY) ============
print("\n" + "=" * 95)
print("CONTEO forecast_model_code (especial: hm_si_core_a_low_mu del rescate AXY)")
print("=" * 95)
codes = sorted(set(c for df in data.values() for c in df["forecast_model_code"].dropna().unique()))
print(f"{'code':<40}", end='')
for k in PATHS: print(f"{k:>15}", end='')
print()
print("-" * 90)
for c in codes:
    print(f"{str(c)[:38]:<40}", end='')
    for k, df in data.items():
        n = (df["forecast_model_code"] == c).sum()
        print(f"{n:>15,}", end='')
    print()
