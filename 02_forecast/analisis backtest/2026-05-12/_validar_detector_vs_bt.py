"""
Validacion del detector x_price_coreccion contra el backtest reciente.

Pregunta: los SKUs alertados por el detector son los que efectivamente
tienen errores grandes en el forecast actual?

Cruce:
  - Alertas en x_price_coreccion (target_week proxima = 2026-05-18)
  - Backtest W17/W18/W19 (target_week_start 2026-04-20, 04-27, 05-04)

Para cada SKU alertado:
  - Lifecycle, ABC, regimen
  - Forecast vs Actual en las 3 semanas medidas
  - BIAS y |error| promedio
  - Tipo de alerta y factor_corr propuesto

Salida: distribucion de error por tipo de alerta + top problematicos.
"""
import pandas as pd
import numpy as np
import os

PATH_CORR = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Corrección Precio (x_price_coreccion) (1).xlsx"
PATH_BT   = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"


def _to_pid(v):
    """Parsea product_id en formatos comunes:
      - int directo
      - '[6253] VINO ...'         (formato Odoo backtest)
      - '6253, VINO ...'          (formato Odoo correcciones)
      - 'VINO ...'                (solo nombre -> None)
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return int(v)
        except Exception:
            return None
    s = str(v).strip()
    # Formato [ID] nombre
    if s.startswith('['):
        try:
            return int(s.split(']')[0][1:].strip())
        except Exception:
            return None
    # Formato 'ID, nombre'
    if ',' in s:
        try:
            return int(s.split(',')[0].strip())
        except Exception:
            return None
    try:
        return int(s)
    except Exception:
        return None


print("Cargando archivos...")
dfc = pd.read_excel(PATH_CORR, engine="openpyxl")
dfb = pd.read_excel(PATH_BT, engine="openpyxl")
print(f"  Correcciones: {len(dfc):,} filas, cols={list(dfc.columns)[:10]}")
print(f"  Backtest:     {len(dfb):,} filas")

# Backtest: filtrar metodo hm_si y ultimas 3 semanas (W17-W19)
dfb["target_week_start"] = pd.to_datetime(dfb["target_week_start"], errors="coerce")
weeks_bt = sorted(dfb["target_week_start"].dropna().unique())[-3:]
print(f"\nSemanas backtest analizadas: {[str(w)[:10] for w in weeks_bt]}")
dfb = dfb[(dfb["method"] == "hm_si") & (dfb["target_week_start"].isin(weeks_bt))].copy()
# Extraer nombre limpio del producto. Backtest exporta '[default_code] NOMBRE',
# correcciones exporta solo 'NOMBRE'. Unimos por nombre normalizado.
def _clean_name(v):
    s = str(v or '').strip()
    if s.startswith('['):
        idx = s.find(']')
        if idx > 0:
            s = s[idx + 1:].strip()
    return s.upper()


dfb["sku_name"] = dfb["product_id"].apply(_clean_name)
dfb["err"] = dfb["forecast_qty"].astype(float) - dfb["real_qty"].astype(float)
dfb["abs_err"] = dfb["err"].abs()
print(f"Backtest filtrado (hm_si, W17-W19): {len(dfb):,} filas, {dfb['sku_name'].nunique():,} SKUs unicos")

# Correcciones: cruzamos por NOMBRE de producto. La columna 'product_id'
# en el Excel exportado de x_price_coreccion es el display_name del m2o.
prod_cols = [c for c in dfc.columns if c.lower() == 'product_id']
if not prod_cols:
    print("ERROR: no encuentro columna product_id en correcciones")
    raise SystemExit(1)
dfc["sku_name"] = dfc[prod_cols[0]].apply(_clean_name)
print(f"Correcciones con nombre normalizado: {len(dfc):,}  SKUs unicos: {dfc['sku_name'].nunique():,}")

# Detectar columnas de tipo y factor
tipo_cols   = [c for c in dfc.columns if 'tipo' in c.lower() and 'alerta' in c.lower()]
factor_cols = [c for c in dfc.columns if 'factor' in c.lower() and 'corr' in c.lower()]
varpct_cols = [c for c in dfc.columns if 'var' in c.lower() and 'pct' in c.lower()]
razon_cols  = [c for c in dfc.columns if 'razon' in c.lower() or 'raz' in c.lower()[:3]]

print(f"  tipo: {tipo_cols}, factor: {factor_cols}, var_pct: {varpct_cols}")
TIPO_COL   = tipo_cols[0] if tipo_cols else None
FACTOR_COL = factor_cols[0] if factor_cols else None

# ============ DISTRIBUCION DE ALERTAS ============
print("\n" + "=" * 90)
print("DISTRIBUCION DE ALERTAS GENERADAS")
print("=" * 90)
if TIPO_COL:
    print(f"\n{'tipo':<28} {'n':>8} {'factor_avg':>12}")
    print("-" * 60)
    for tipo, sub in dfc.groupby(TIPO_COL):
        fac = sub[FACTOR_COL].mean() if FACTOR_COL else float('nan')
        print(f"{str(tipo):<28} {len(sub):>8,} {fac:>12.3f}")

# ============ CRUCE: SKUs alertados que estan en backtest ============
skus_alertados = set(dfc["sku_name"].unique())
skus_backtest  = set(dfb["sku_name"].unique())
en_ambos = skus_alertados & skus_backtest
solo_alerta   = skus_alertados - skus_backtest
solo_backtest = skus_backtest - skus_alertados
pids_alertados = skus_alertados  # alias retro

print("\n" + "=" * 90)
print("INTERSECCION SKUs alertados vs SKUs en backtest")
print("=" * 90)
print(f"  Alertados:                {len(pids_alertados):>6,}")
print(f"  En backtest (W17-W19):    {len(skus_backtest):>6,}")
print(f"  En AMBOS:                 {len(en_ambos):>6,}  <- estos podemos medir")
print(f"  Solo alerta (no en bt):   {len(solo_alerta):>6,}")
print(f"  Solo backtest (sin alerta):{len(solo_backtest):>6,}")

# ============ ERROR de SKUs alertados vs no alertados ============
print("\n" + "=" * 90)
print("ERROR PROMEDIO: ALERTADOS vs NO-ALERTADOS")
print("=" * 90)
dfb["alertado"] = dfb["sku_name"].isin(pids_alertados)
ag = dfb.groupby("alertado").agg(
    n=("err", "size"),
    mu=("forecast_qty", "sum"),
    actual=("real_qty", "sum"),
    abs_err=("abs_err", "sum"),
)
ag["bias_pct"] = (ag["mu"] - ag["actual"]) / ag["actual"].replace(0, np.nan) * 100
ag["wape"]    = ag["abs_err"] / ag["actual"].replace(0, np.nan) * 100
print(ag[["n", "mu", "actual", "bias_pct", "wape"]].rename(columns={
    "n": "filas", "mu": "forecast_tot", "actual": "actual_tot",
}).to_string(float_format=lambda x: f"{x:,.1f}"))

# ============ ERROR por TIPO DE ALERTA ============
print("\n" + "=" * 90)
print("ERROR EN BACKTEST POR TIPO DE ALERTA")
print("=" * 90)
print(f"{'tipo':<28} {'n_filas':>8} {'forecast':>11} {'actual':>11} {'bias%':>8} {'WAPE%':>8}")
print("-" * 80)
# join: cada fila de backtest <- tipo_alerta del SKU
pid_to_tipo = dict(zip(dfc["sku_name"], dfc[TIPO_COL])) if TIPO_COL else {}
dfb["tipo_alerta"] = dfb["sku_name"].map(pid_to_tipo)
for tipo in sorted([t for t in dfb["tipo_alerta"].dropna().unique()]):
    sub = dfb[dfb["tipo_alerta"] == tipo]
    if len(sub) == 0:
        continue
    fcast = sub["forecast_qty"].sum()
    act   = sub["real_qty"].sum()
    abs_e = sub["abs_err"].sum()
    bias  = (fcast - act) / act * 100 if act > 0 else 0
    wape  = abs_e / act * 100 if act > 0 else 0
    print(f"{str(tipo):<28} {len(sub):>8,} {fcast:>11,.0f} {act:>11,.0f} {bias:>+8.1f} {wape:>8.1f}")

# Sin alerta (referencia)
sub = dfb[dfb["tipo_alerta"].isna()]
fcast = sub["forecast_qty"].sum()
act   = sub["real_qty"].sum()
abs_e = sub["abs_err"].sum()
bias  = (fcast - act) / act * 100 if act > 0 else 0
wape  = abs_e / act * 100 if act > 0 else 0
print(f"{'(sin alerta)':<28} {len(sub):>8,} {fcast:>11,.0f} {act:>11,.0f} {bias:>+8.1f} {wape:>8.1f}")

# ============ TOP 20 SKUs alertados con MAYOR error en backtest ============
print("\n" + "=" * 90)
print("TOP 20 SKUs ALERTADOS con MAYOR |error| en backtest (W17-W19)")
print("=" * 90)
agg_sku = dfb[dfb["alertado"]].groupby("product_id").agg(
    n=("err", "size"),
    fcast=("forecast_qty", "sum"),
    actual=("real_qty", "sum"),
    abs_err=("abs_err", "sum"),
).reset_index()
agg_sku["bias_pct"] = (agg_sku["fcast"] - agg_sku["actual"]) / agg_sku["actual"].replace(0, np.nan) * 100
agg_sku["tipo"] = agg_sku["product_id"].map(pid_to_tipo)
agg_sku = agg_sku.sort_values("abs_err", ascending=False).head(20)
print(agg_sku[["product_id", "tipo", "n", "fcast", "actual", "abs_err", "bias_pct"]].to_string(
    index=False, float_format=lambda x: f"{x:,.1f}"
))

# ============ VALOR del detector ============
print("\n" + "=" * 90)
print("VALOR DEL DETECTOR — cuanto error 'capturamos' si aplicaramos factor_corr?")
print("=" * 90)
pid_to_factor = dict(zip(dfc["sku_name"], dfc[FACTOR_COL])) if FACTOR_COL else {}
dfb["factor_corr"] = dfb["sku_name"].map(pid_to_factor).fillna(1.0)
dfb["mu_corregido"] = dfb["forecast_qty"] * dfb["factor_corr"]
dfb["abs_err_corr"] = (dfb["mu_corregido"] - dfb["real_qty"]).abs()

# Solo alertados
sub_a = dfb[dfb["alertado"]]
act_a = sub_a["real_qty"].sum()
abs_e_pre  = sub_a["abs_err"].sum()
abs_e_post = sub_a["abs_err_corr"].sum()
wape_pre  = abs_e_pre  / act_a * 100 if act_a > 0 else 0
wape_post = abs_e_post / act_a * 100 if act_a > 0 else 0
mejora    = wape_pre - wape_post

print(f"  SKUs alertados en backtest: {len(sub_a):,} filas, {sub_a['product_id'].nunique():,} SKUs")
print(f"  WAPE actual (sin factor):   {wape_pre:6.2f}%")
print(f"  WAPE con factor_corr:       {wape_post:6.2f}%")
print(f"  Mejora:                     {mejora:+6.2f}pp")

# Tambien WAPE global proyectado
act_g = dfb["real_qty"].sum()
abs_g_pre  = dfb["abs_err"].sum()
abs_g_post = dfb["abs_err_corr"].sum()
print(f"\n  WAPE global actual:         {abs_g_pre/act_g*100:6.2f}%")
print(f"  WAPE global con factor:     {abs_g_post/act_g*100:6.2f}%")
print(f"  Mejora global:              {(abs_g_pre-abs_g_post)/act_g*100:+6.2f}pp")

print("\nFin del analisis.")
