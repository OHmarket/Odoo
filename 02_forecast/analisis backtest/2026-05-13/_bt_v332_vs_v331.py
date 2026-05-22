"""Comparar (2) v3.31 baseline vs (13) v3.32 con series_type_active de ABCXYZ v19.4."""
import pandas as pd
import numpy as np

PATH_2  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (2).csv"
PATH_13 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (13).xlsx"


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
d2 = _prep(PATH_2, is_csv=True)
d13 = _prep(PATH_13)
print(f"  (2)  v3.31:        {len(d2):,} filas")
print(f"  (13) v3.32 short:  {len(d13):,} filas")


def _wb(df):
    f, r, e = df["forecast_qty"].sum(), df["real_qty"].sum(), df["abs_err"].sum()
    return f, r, e, (f-r)/r*100 if r > 0 else 0, e/r*100 if r > 0 else 0


# GLOBAL
print("\n" + "=" * 85)
print("GLOBAL hm_si W17-W19")
print("=" * 85)
print(f"{'version':<20} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 75)
for k, df in [("(2) v3.31", d2), ("(13) v3.32", d13)]:
    f, r, e, b, w = _wb(df)
    print(f"{k:<20} {len(df):>8,} {f:>10,.0f} {r:>10,.0f} {b:>+8.2f} {w:>8.2f}")

# Forecast=0 con ventas
print("\n" + "=" * 85)
print("FILAS CON forecast=0 PERO real>0")
print("=" * 85)
print(f"{'version':<20} {'n_zero+real':>13} {'real_lost':>10} {'%real':>8}")
print("-" * 60)
for k, df in [("(2) v3.31", d2), ("(13) v3.32", d13)]:
    sub = df[(df["forecast_qty"] <= 0.001) & (df["real_qty"] > 0)]
    real_total = df["real_qty"].sum()
    print(f"{k:<20} {len(sub):>13,} {sub['real_qty'].sum():>10,.0f} {sub['real_qty'].sum()/real_total*100:>7.2f}%")

# Por forecast_zone
print("\n" + "=" * 85)
print("CONTEO POR FORECAST_ZONE")
print("=" * 85)
print(f"{'zone':<10} {'(2) v3.31':>12} {'(13) v3.32':>12} {'delta':>8}")
zones = sorted(set(d2["forecast_zone"].dropna().unique()) | set(d13["forecast_zone"].dropna().unique()))
for z in zones:
    n2 = (d2["forecast_zone"] == z).sum()
    n13 = (d13["forecast_zone"] == z).sum()
    print(f"{str(z):<10} {n2:>12,} {n13:>12,} {n13-n2:>+8,}")

# Por series_type
print("\n" + "=" * 85)
print("CONTEO POR series_type")
print("=" * 85)
print(f"{'series_type':<20} {'(2) v3.31':>12} {'(13) v3.32':>12} {'delta':>8}")
sts = sorted(set(d2["series_type"].dropna().unique()) | set(d13["series_type"].dropna().unique()))
for s in sts:
    n2 = (d2["series_type"] == s).sum()
    n13 = (d13["series_type"] == s).sum()
    print(f"{str(s):<20} {n2:>12,} {n13:>12,} {n13-n2:>+8,}")

# Por ABCXYZ
print("\n" + "=" * 95)
print("DELTAS POR ABCXYZ: (13) v3.32 vs (2) v3.31")
print("=" * 95)
print(f"{'abcxyz':<8} {'n':>7} {'WAPE2':>8} {'WAPE13':>8} {'dWAPE':>8} {'BIAS2':>8} {'BIAS13':>8} {'f=0_2':>8} {'f=0_13':>8}")
print("-" * 90)
for abc in sorted(d13["abcxyz"].dropna().unique()):
    s2 = d2[d2["abcxyz"] == abc]
    s13 = d13[d13["abcxyz"] == abc]
    _, _, _, b2, w2 = _wb(s2)
    _, _, _, b13, w13 = _wb(s13)
    z2 = ((s2["forecast_qty"] <= 0.001) & (s2["real_qty"] > 0)).sum()
    z13 = ((s13["forecast_qty"] <= 0.001) & (s13["real_qty"] > 0)).sum()
    print(f"{str(abc):<8} {len(s13):>7,} {w2:>8.1f} {w13:>8.1f} {w13-w2:>+8.2f} {b2:>+8.1f} {b13:>+8.1f} {z2:>8,} {z13:>8,}")

# SKUs en ramp-up: aparecen ahora con forecast > 0?
print("\n" + "=" * 95)
print("OUTLIERS RAMP-UP — comparativo")
print("=" * 95)
tags = ['451523', '870689', '300066348', '447082', '300066167', '9518',
        'COORS', 'PEPSI ZERO', '102320050']
print(f"{'sku':<55} {'real':>6} {'f2':>6} {'f13':>6} {'zone2':<8} {'zone13':<8}")
print("-" * 95)
for tag in tags:
    s2 = d2[d2["product_id"].astype(str).str.contains(tag, na=False, regex=False)]
    s13 = d13[d13["product_id"].astype(str).str.contains(tag, na=False, regex=False)]
    if len(s13) == 0:
        continue
    name = str(s13["product_id"].iloc[0])[:53]
    r = s13["real_qty"].sum()
    f2 = s2["forecast_qty"].sum()
    f13 = s13["forecast_qty"].sum()
    z2 = s2["forecast_zone"].mode().iloc[0] if len(s2) > 0 else '-'
    z13 = s13["forecast_zone"].mode().iloc[0] if len(s13) > 0 else '-'
    print(f"{name:<55} {r:>6,.0f} {f2:>6,.0f} {f13:>6,.0f} {z2:<8} {z13:<8}")
