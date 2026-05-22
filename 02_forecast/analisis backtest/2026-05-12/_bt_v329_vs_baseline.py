"""Comparar backtest (10) baseline vs (11) v3.29 con detector x_price_coreccion.

(10): motor v3.28 sin correccion del detector.
(11): motor v3.29 con factor_corr aplicado.

Mide:
  - WAPE/BIAS global hm_si
  - WAPE/BIAS por ABCXYZ
  - Mejora especifica en SKUs alertados (cruce con el detector)
"""
import pandas as pd
import numpy as np

PATH_10 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
PATH_11 = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (11).xlsx"
PATH_CORR = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Corrección Precio (x_price_coreccion) (1).xlsx"


def _clean(v):
    s = str(v or '').strip()
    if s.startswith('['):
        idx = s.find(']')
        if idx > 0:
            s = s[idx + 1:].strip()
    return s.upper()


def _prep_bt(path):
    df = pd.read_excel(path, engine="openpyxl")
    df["target_week_start"] = pd.to_datetime(df["target_week_start"], errors="coerce")
    weeks = sorted(df["target_week_start"].dropna().unique())[-3:]
    df = df[(df["method"] == "hm_si") & (df["target_week_start"].isin(weeks))].copy()
    df["sku"] = df["product_id"].apply(_clean)
    df["abs_err"] = df["abs_error_qty"].astype(float)
    return df


print("Cargando archivos...")
d10 = _prep_bt(PATH_10)
d11 = _prep_bt(PATH_11)
print(f"  Baseline (10): {len(d10):,} filas, {d10['sku'].nunique():,} SKUs")
print(f"  v3.29   (11): {len(d11):,} filas, {d11['sku'].nunique():,} SKUs")

# ============ Detectar SKUs que cambiaron entre 10 y 11 ============
# Forecast cambio = la corrección aplicó. Cruzamos forecast por (sku, team, semana)
import os
m_change = d10[["sku", "team_id", "target_week_start", "forecast_qty"]].merge(
    d11[["sku", "team_id", "target_week_start", "forecast_qty"]],
    on=["sku", "team_id", "target_week_start"],
    suffixes=("_10", "_11"), how="inner",
)
m_change["delta_fcast"] = m_change["forecast_qty_11"] - m_change["forecast_qty_10"]
skus_que_cambiaron = set(m_change.loc[m_change["delta_fcast"].abs() > 0.01, "sku"].unique())
print(f"  SKUs con forecast cambiado: {len(skus_que_cambiaron):,}")
skus_alertados = skus_que_cambiaron
sku_to_tipo = {}
sku_to_factor = {}
if os.path.exists(PATH_CORR):
    dfc = pd.read_excel(PATH_CORR, engine="openpyxl")
    dfc["sku"] = dfc["product_id"].apply(_clean)
    sku_to_tipo = dict(zip(dfc["sku"], dfc["tipo_alerta"]))
    sku_to_factor = dict(zip(dfc["sku"], dfc["factor_corr"]))
    print(f"  Detector: {len(dfc):,} alertas (merged con SKUs que cambiaron)")


def _wape_bias(df, label):
    fcast = df["forecast_qty"].sum()
    real = df["real_qty"].sum()
    abs_err = df["abs_err"].sum()
    wape = abs_err / real * 100 if real > 0 else 0
    bias = (fcast - real) / real * 100 if real > 0 else 0
    return {"label": label, "n": len(df), "fcast": fcast, "real": real, "abs_err": abs_err, "wape": wape, "bias": bias}


# ============ GLOBAL ============
print("\n" + "=" * 90)
print("GLOBAL hm_si W17-W19")
print("=" * 90)
print(f"{'archivo':<20} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 70)
for r in (_wape_bias(d10, "(10) baseline"), _wape_bias(d11, "(11) v3.29")):
    print(f"{r['label']:<20} {r['n']:>8,} {r['fcast']:>10,.0f} {r['real']:>10,.0f} {r['bias']:>+8.2f} {r['wape']:>8.2f}")

r10 = _wape_bias(d10, "10")
r11 = _wape_bias(d11, "11")
print(f"\nDelta WAPE:  {r11['wape'] - r10['wape']:+.2f}pp")
print(f"Delta BIAS:  {r11['bias'] - r10['bias']:+.2f}pp")
print(f"Delta abs_err: {r11['abs_err'] - r10['abs_err']:+,.0f}")

# ============ SKUs ALERTADOS ============
print("\n" + "=" * 90)
print("SOLO SKUs ALERTADOS POR EL DETECTOR")
print("=" * 90)
d10a = d10[d10["sku"].isin(skus_alertados)]
d11a = d11[d11["sku"].isin(skus_alertados)]
print(f"{'archivo':<20} {'n':>8} {'fcast':>10} {'real':>10} {'BIAS%':>8} {'WAPE%':>8}")
print("-" * 70)
for r in (_wape_bias(d10a, "(10) baseline"), _wape_bias(d11a, "(11) v3.29")):
    print(f"{r['label']:<20} {r['n']:>8,} {r['fcast']:>10,.0f} {r['real']:>10,.0f} {r['bias']:>+8.2f} {r['wape']:>8.2f}")
ra10 = _wape_bias(d10a, "10")
ra11 = _wape_bias(d11a, "11")
print(f"\nDelta WAPE alertados:  {ra11['wape'] - ra10['wape']:+.2f}pp")
print(f"Delta BIAS alertados:  {ra11['bias'] - ra10['bias']:+.2f}pp")

# ============ POR TIPO DE ALERTA ============
print("\n" + "=" * 90)
print("MEJORA POR TIPO DE ALERTA (forecast (11) vs (10))")
print("=" * 90)
print(f"{'tipo_alerta':<28} {'n':>5} {'WAPE10':>8} {'WAPE11':>8} {'dWAPE':>8} {'BIAS10':>8} {'BIAS11':>8}")
print("-" * 80)
d10["tipo"] = d10["sku"].map(sku_to_tipo)
d11["tipo"] = d11["sku"].map(sku_to_tipo)
for tipo in sorted([t for t in d11["tipo"].dropna().unique()]):
    s10 = d10[d10["tipo"] == tipo]
    s11 = d11[d11["tipo"] == tipo]
    if len(s11) == 0:
        continue
    r10 = _wape_bias(s10, "")
    r11 = _wape_bias(s11, "")
    print(f"{str(tipo):<28} {len(s11):>5,} {r10['wape']:>8.1f} {r11['wape']:>8.1f} "
          f"{r11['wape']-r10['wape']:>+8.2f} {r10['bias']:>+8.1f} {r11['bias']:>+8.1f}")

# ============ POR ABCXYZ ============
print("\n" + "=" * 90)
print("DELTAS POR ABCXYZ")
print("=" * 90)
print(f"{'abcxyz':<8} {'n':>6} {'WAPE10':>8} {'WAPE11':>8} {'dWAPE':>8} {'BIAS10':>8} {'BIAS11':>8}")
print("-" * 70)
for abc in sorted(d11["abcxyz"].dropna().unique()):
    s10 = d10[d10["abcxyz"] == abc]
    s11 = d11[d11["abcxyz"] == abc]
    if len(s11) == 0:
        continue
    r10 = _wape_bias(s10, "")
    r11 = _wape_bias(s11, "")
    print(f"{str(abc):<8} {len(s11):>6,} {r10['wape']:>8.1f} {r11['wape']:>8.1f} "
          f"{r11['wape']-r10['wape']:>+8.2f} {r10['bias']:>+8.1f} {r11['bias']:>+8.1f}")

# ============ TOP cambios individuales ============
print("\n" + "=" * 90)
print("TOP 15 SKUs CON MAYOR MEJORA EN |error| (alertados)")
print("=" * 90)
# Join 10-11 sobre SKU+team+week
key_cols = ["sku", "team_id", "target_week_start"]
m = d10a[key_cols + ["abs_err", "real_qty", "forecast_qty"]].merge(
    d11a[key_cols + ["abs_err", "real_qty", "forecast_qty"]],
    on=key_cols, suffixes=("_10", "_11"), how="inner",
)
m["delta_abs_err"] = m["abs_err_11"] - m["abs_err_10"]
m["tipo"] = m["sku"].map(sku_to_tipo)
m["factor_corr"] = m["sku"].map(sku_to_factor)

# Agregar por SKU sumando semanas
sku_delta = m.groupby(["sku", "tipo", "factor_corr"]).agg(
    abs_err_10=("abs_err_10", "sum"),
    abs_err_11=("abs_err_11", "sum"),
    real=("real_qty_10", "sum"),
    fcast_10=("forecast_qty_10", "sum"),
    fcast_11=("forecast_qty_11", "sum"),
).reset_index()
sku_delta["delta_abs_err"] = sku_delta["abs_err_11"] - sku_delta["abs_err_10"]

print(f"\n{'sku':<40} {'tipo':<25} {'fact':>5} {'real':>6} {'f10':>6} {'f11':>6} {'dErr':>8}")
print("-" * 100)
for _, r in sku_delta.sort_values("delta_abs_err").head(15).iterrows():
    print(f"{r['sku'][:40]:<40} {str(r['tipo'])[:25]:<25} {r['factor_corr']:>5.2f} {r['real']:>6,.0f} {r['fcast_10']:>6,.0f} {r['fcast_11']:>6,.0f} {r['delta_abs_err']:>+8,.0f}")

print(f"\n{'sku':<40} {'tipo':<25} {'fact':>5} {'real':>6} {'f10':>6} {'f11':>6} {'dErr':>8}  [TOP 15 EMPEORAN]")
print("-" * 100)
for _, r in sku_delta.sort_values("delta_abs_err", ascending=False).head(15).iterrows():
    print(f"{r['sku'][:40]:<40} {str(r['tipo'])[:25]:<25} {r['factor_corr']:>5.2f} {r['real']:>6,.0f} {r['fcast_10']:>6,.0f} {r['fcast_11']:>6,.0f} {r['delta_abs_err']:>+8,.0f}")

print("\nFin del analisis.")
