"""Comparar (12) v3.30 vs (1) CSV v3.31 con redondeo medio-arriba."""
import pandas as pd
import numpy as np

PATH_12 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (12).xlsx"
PATH_1 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (1).csv"


def _prep(path, is_csv=False):
    if is_csv:
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path, engine="openpyxl")
    df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
    weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
    if "method" in df.columns:
        df = df[(df["method"] == "hm_si") & (df["target_week_start"].isin(weeks))].copy()
    else:
        df = df[df["target_week_start"].isin(weeks)].copy()
    df["forecast_qty"] = df["forecast_qty"].astype(float)
    df["real_qty"] = df["real_qty"].astype(float)
    df["abs_err"] = df["abs_error_qty"].astype(float)
    return df


print("Cargando...")
d12 = _prep(PATH_12)
d1 = _prep(PATH_1, is_csv=True)
print(f"  (12) v3.30: {len(d12):,} filas")
print(f"  (1)  v3.31: {len(d1):,} filas")


def _wb(df):
    f, r, e = df["forecast_qty"].sum(), df["real_qty"].sum(), df["abs_err"].sum()
    return f, r, e, (f-r)/r*100 if r > 0 else 0, e/r*100 if r > 0 else 0


# ============ GLOBAL ============
print("\n" + "=" * 85)
print("GLOBAL hm_si W17-W19")
print("=" * 85)
print(f"{'version':<15} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 70)
for k, df in [("(12) v3.30", d12), ("(1) v3.31", d1)]:
    f, r, e, b, w = _wb(df)
    print(f"{k:<15} {len(df):>8,} {f:>10,.0f} {r:>10,.0f} {b:>+8.2f} {w:>8.2f}")

# ============ FORECAST=0 con VENTAS ============
print("\n" + "=" * 85)
print("FILAS CON forecast=0 PERO real>0")
print("=" * 85)
print(f"{'version':<15} {'n_zero+real':>13} {'real_lost':>10} {'%real':>8}")
print("-" * 60)
for k, df in [("(12) v3.30", d12), ("(1) v3.31", d1)]:
    sub = df[(df["forecast_qty"] <= 0.001) & (df["real_qty"] > 0)]
    real_total = df["real_qty"].sum()
    print(f"{k:<15} {len(sub):>13,} {sub['real_qty'].sum():>10,.0f} {sub['real_qty'].sum()/real_total*100:>7.2f}%")

# ============ Distribucion del forecast_qty entero ============
print("\n" + "=" * 85)
print("VERIFICACION REDONDEO: distribucion de forecast_qty fraccional")
print("=" * 85)
print(f"{'archivo':<15} {'enteros':>10} {'fraccional':>12} {'min':>6} {'max':>6}")
print("-" * 60)
for k, df in [("(12) v3.30", d12), ("(1) v3.31", d1)]:
    enteros = (df["forecast_qty"] == df["forecast_qty"].astype(int)).sum()
    fraccional = len(df) - enteros
    print(f"{k:<15} {enteros:>10,} {fraccional:>12,} {df['forecast_qty'].min():>6.2f} {df['forecast_qty'].max():>6.2f}")

# ============ POR ABCXYZ delta 12 vs 1 ============
print("\n" + "=" * 95)
print("DELTAS POR ABCXYZ: (1) v3.31 vs (12) v3.30")
print("=" * 95)
print(f"{'abcxyz':<6} {'n':>7} {'WAPE12':>8} {'WAPE1':>8} {'dWAPE':>8} {'BIAS12':>8} {'BIAS1':>8} {'fcast=0_12':>11} {'fcast=0_1':>11}")
print("-" * 95)
for abc in sorted(d1["abcxyz"].dropna().unique()):
    s12 = d12[d12["abcxyz"] == abc]
    s1 = d1[d1["abcxyz"] == abc]
    if len(s1) == 0:
        continue
    _, _, _, b12, w12 = _wb(s12)
    _, _, _, b1, w1 = _wb(s1)
    z12 = ((s12["forecast_qty"] <= 0.001) & (s12["real_qty"] > 0)).sum()
    z1 = ((s1["forecast_qty"] <= 0.001) & (s1["real_qty"] > 0)).sum()
    print(f"{str(abc):<6} {len(s1):>7,} {w12:>8.1f} {w1:>8.1f} {w1-w12:>+8.2f} {b12:>+8.1f} {b1:>+8.1f} {z12:>11,} {z1:>11,}")

# ============ Royal Guard / Cristal Ultra / Budweiser ============
print("\n" + "=" * 95)
print("OUTLIERS TIPICOS — comparativo")
print("=" * 95)
outliers = ['9413', '9407', '451548', '451500', '9430', '9958', '1726']
print(f"{'sku':<55} {'real':>6} {'f12':>6} {'f1':>6} {'BIAS12':>8} {'BIAS1':>8}")
print("-" * 95)
for tag in outliers:
    s12 = d12[d12["product_id"].astype(str).str.contains(tag, na=False)]
    s1 = d1[d1["product_id"].astype(str).str.contains(tag, na=False)]
    if len(s12) == 0 or len(s1) == 0:
        continue
    name = str(s1["product_id"].iloc[0])[:53]
    r = s12["real_qty"].sum()
    f12 = s12["forecast_qty"].sum()
    f1 = s1["forecast_qty"].sum()
    b12 = (f12 - r) / r * 100 if r > 0 else 0
    b1 = (f1 - r) / r * 100 if r > 0 else 0
    print(f"{name:<55} {r:>6,.0f} {f12:>6,.0f} {f1:>6,.0f} {b12:>+8.1f} {b1:>+8.1f}")
