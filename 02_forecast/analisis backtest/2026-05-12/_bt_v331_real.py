"""Comparar (12) v3.30 baseline vs (2) v3.31 con redondeo aplicado."""
import pandas as pd
import numpy as np

PATH_12 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (12).xlsx"
PATH_2  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (2).csv"


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
d2 = _prep(PATH_2, is_csv=True)
print(f"  (12) v3.30: {len(d12):,} filas")
print(f"  (2)  v3.31: {len(d2):,} filas")


def _wb(df):
    f, r, e = df["forecast_qty"].sum(), df["real_qty"].sum(), df["abs_err"].sum()
    return f, r, e, (f-r)/r*100 if r > 0 else 0, e/r*100 if r > 0 else 0


# ============ Verificacion redondeo ============
print("\n" + "=" * 90)
print("VERIFICACION REDONDEO")
print("=" * 90)
print(f"{'version':<15} {'enteros':>10} {'fraccional':>12} {'%entero':>8} {'min':>6} {'max':>8}")
print("-" * 70)
for k, df in [("(12) v3.30", d12), ("(2) v3.31", d2)]:
    enteros = (df["forecast_qty"] == df["forecast_qty"].astype(int)).sum()
    fraccional = len(df) - enteros
    pct_enteros = enteros / len(df) * 100
    print(f"{k:<15} {enteros:>10,} {fraccional:>12,} {pct_enteros:>7.1f}% {df['forecast_qty'].min():>6.2f} {df['forecast_qty'].max():>8.2f}")

# ============ GLOBAL ============
print("\n" + "=" * 90)
print("GLOBAL hm_si W17-W19")
print("=" * 90)
print(f"{'version':<15} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 70)
for k, df in [("(12) v3.30", d12), ("(2) v3.31", d2)]:
    f, r, e, b, w = _wb(df)
    print(f"{k:<15} {len(df):>8,} {f:>10,.0f} {r:>10,.0f} {b:>+8.2f} {w:>8.2f}")

# ============ FORECAST=0 con VENTAS ============
print("\n" + "=" * 90)
print("FILAS CON forecast=0 PERO real>0")
print("=" * 90)
print(f"{'version':<15} {'n_zero+real':>13} {'real_lost':>10} {'%real':>8}")
print("-" * 60)
for k, df in [("(12) v3.30", d12), ("(2) v3.31", d2)]:
    sub = df[(df["forecast_qty"] <= 0.001) & (df["real_qty"] > 0)]
    real_total = df["real_qty"].sum()
    print(f"{k:<15} {len(sub):>13,} {sub['real_qty'].sum():>10,.0f} {sub['real_qty'].sum()/real_total*100:>7.2f}%")

# ============ Distribucion del cambio ============
print("\n" + "=" * 90)
print("DISTRIBUCION DEL CAMBIO POR FILA")
print("=" * 90)
key_cols = ["product_id", "team_id", "target_week_start"]
m = d12[key_cols + ["forecast_qty", "real_qty", "abs_err"]].merge(
    d2[key_cols + ["forecast_qty", "abs_err"]],
    on=key_cols, suffixes=("_12", "_2"), how="inner",
)
m["delta_fcast"] = m["forecast_qty_2"] - m["forecast_qty_12"]
m["delta_abs_err"] = m["abs_err_2"] - m["abs_err_12"]

print(f"  Filas con cambio fcast != 0:       {(m['delta_fcast'].abs() > 0.01).sum():>7,}")
print(f"  Filas que SUBIO (redondeo arriba): {(m['delta_fcast'] > 0).sum():>7,}")
print(f"  Filas que BAJO (redondeo abajo):   {(m['delta_fcast'] < 0).sum():>7,}")
print(f"  Filas sin cambio (ya era entero):  {(m['delta_fcast'].abs() < 0.01).sum():>7,}")
print(f"  Filas con MEJORA en abs_err:       {(m['delta_abs_err'] < -0.01).sum():>7,}")
print(f"  Filas con EMPEORE en abs_err:      {(m['delta_abs_err'] > 0.01).sum():>7,}")

# ============ POR ABCXYZ ============
print("\n" + "=" * 95)
print("DELTAS POR ABCXYZ: (2) v3.31 vs (12) v3.30")
print("=" * 95)
print(f"{'abcxyz':<6} {'n':>7} {'WAPE12':>8} {'WAPE2':>8} {'dWAPE':>8} {'BIAS12':>8} {'BIAS2':>8} {'fcast=0_12':>11} {'fcast=0_2':>11}")
print("-" * 95)
for abc in sorted(d2["abcxyz"].dropna().unique()):
    s12 = d12[d12["abcxyz"] == abc]
    s2 = d2[d2["abcxyz"] == abc]
    if len(s2) == 0:
        continue
    _, _, _, b12, w12 = _wb(s12)
    _, _, _, b2, w2 = _wb(s2)
    z12 = ((s12["forecast_qty"] <= 0.001) & (s12["real_qty"] > 0)).sum()
    z2 = ((s2["forecast_qty"] <= 0.001) & (s2["real_qty"] > 0)).sum()
    print(f"{str(abc):<6} {len(s2):>7,} {w12:>8.1f} {w2:>8.1f} {w2-w12:>+8.2f} {b12:>+8.1f} {b2:>+8.1f} {z12:>11,} {z2:>11,}")
