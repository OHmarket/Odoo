"""
Detector v3 — consolidado con 15 reglas aprendidas.

Casos diferenciados:
  1. SUBIDA pura sin promo propia        → canibal amplificado por ABC ponderado
  2. SUBIDA + promo propia                → jugada "subo lista + tiro volumen", confiar en lift real
  3. PROMO sola (sin cambio precio)       → modular por weeks_active (1 sem disparo, 2-3 saturacion)
  4. BAJADA pura                          → ganador si hay subidas opuestas
  5. BAJADA >30%                          → discontinuacion, no amplificar
  6. Sin cambio relevante                 → NO alertar
"""
import pandas as pd
import numpy as np
import re

PATH_PRICE = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PATH_PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
PATH_BT    = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
OUT_XLSX   = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_detector_v3_output.xlsx"

# Pesos ABC para canibalizacion
PESO_ABC = {'A': 1.0, 'B': 0.2, 'C': 0.03}

# ----------------------------------------------------------------------
# CARGA
# ----------------------------------------------------------------------
print("=" * 110)
print("DETECTOR v3 - 15 reglas consolidadas")
print("=" * 110)

dfp = pd.read_excel(PATH_PRICE, engine="openpyxl")
dfm = pd.read_excel(PATH_PROMO, engine="openpyxl")
dfb = pd.read_excel(PATH_BT, engine="openpyxl")
dfp["Fecha"] = pd.to_datetime(dfp["Fecha"], errors="coerce")
dfm["period_start"] = pd.to_datetime(dfm["period_start"], errors="coerce")
dfb["target_week_start"] = pd.to_datetime(dfb["target_week_start"], errors="coerce")

direccion_col = "Direcci\xf3n"
if direccion_col not in dfp.columns:
    for c in dfp.columns:
        if "irecci" in c.lower():
            direccion_col = c
            break

weeks_bt = sorted(dfb["target_week_start"].dropna().unique())[-3:]
dfb = dfb[(dfb["method"] == "hm_si") & (dfb["target_week_start"].isin(weeks_bt))].copy()
for c in ["real_qty", "forecast_qty", "abs_error_qty"]:
    dfb[c] = pd.to_numeric(dfb[c], errors="coerce").fillna(0.0)


def get_sub_cat(cat_str):
    parts = str(cat_str).split(' / ')
    return parts[2] if len(parts) >= 3 else parts[-1]


def get_abc_letter(abcxyz):
    s = str(abcxyz)
    return s[0] if len(s) >= 1 else ''


def extract_mecanica(program_name):
    s = str(program_name).upper()
    m = re.search(r'(\d+)X', s)
    return f"{m.group(1)}X" if m else "OTRO"


# Maps
sku_to_subcat = {}
sku_to_abc = {}
for _, row in dfb.iterrows():
    sku = row["product_id"]
    if sku not in sku_to_subcat:
        sku_to_subcat[sku] = get_sub_cat(row["categ_id"])
        sku_to_abc[sku] = get_abc_letter(row.get("abcxyz", ""))

sku_count_by_subcat = pd.Series(list(sku_to_subcat.values())).value_counts().to_dict()
print(f"  SKUs en backtest: {len(sku_to_abc):,}  (A: {sum(1 for v in sku_to_abc.values() if v=='A'):,}, B: {sum(1 for v in sku_to_abc.values() if v=='B'):,}, C: {sum(1 for v in sku_to_abc.values() if v=='C'):,})")

# Enriquecer promos
dfm["mecanica"] = dfm["program_name"].apply(extract_mecanica)
dfm["abc"] = dfm["product_variant_id"].map(sku_to_abc)
dfm["sub_cat"] = dfm["categ_id"].apply(get_sub_cat)
dfp["abc"] = dfp["Producto"].map(sku_to_abc)
dfp["sub_cat"] = dfp["Categoria"].apply(get_sub_cat)


# ----------------------------------------------------------------------
# INDICE CANIBAL PONDERADO POR ABC
# ----------------------------------------------------------------------
def indice_canibal_ponderado(target_week, sub_cat, direccion_propia, sku_propio=None, lookback=4):
    """Calcula score de competidores opuestos en sub-cat L3 ponderado por ABC."""
    week_lookback = target_week - pd.Timedelta(weeks=lookback)

    if direccion_propia == 'Sube':
        # Opuestos: bajadas + promos activas
        cambios_op = dfp[
            (dfp["Fecha"] >= week_lookback) &
            (dfp["Fecha"] <= target_week) &
            (dfp[direccion_col] == "Baja") &
            (dfp["sub_cat"] == sub_cat)
        ]
        promos_op = dfm[
            (dfm["period_start"] >= week_lookback) &
            (dfm["period_start"] <= target_week) &
            (dfm["sub_cat"] == sub_cat)
        ]
        # Excluir self
        if sku_propio:
            cambios_op = cambios_op[cambios_op["Producto"] != sku_propio]
            promos_op = promos_op[promos_op["product_variant_id"] != sku_propio]
        # Score ponderado (suma float, no concatenacion)
        def w(s):
            try:
                return float(sum(PESO_ABC.get(x, 0.0) for x in s.fillna("").tolist()))
            except Exception:
                return 0.0
        score = w(cambios_op["abc"]) + w(promos_op["abc"])
    elif direccion_propia == 'Baja':
        # Opuestos: subidas
        cambios_op = dfp[
            (dfp["Fecha"] >= week_lookback) &
            (dfp["Fecha"] <= target_week) &
            (dfp[direccion_col] == "Sube") &
            (dfp["sub_cat"] == sub_cat)
        ]
        if sku_propio:
            cambios_op = cambios_op[cambios_op["Producto"] != sku_propio]
        try:
            score = float(sum(PESO_ABC.get(x, 0.0) for x in cambios_op["abc"].fillna("").tolist()))
        except Exception:
            score = 0.0
    else:
        return 0.0
    n_total = sku_count_by_subcat.get(sub_cat, 1)
    return score / max(1, n_total)


# ----------------------------------------------------------------------
# REGLAS PRINCIPALES — RETORNAN (tipo, factor)
# ----------------------------------------------------------------------
def factor_base_subida(var_pct):
    if var_pct >= 0.15:
        return 0.76
    elif var_pct >= 0.05:
        return 0.85
    return 1.0


def factor_base_bajada(var_pct):
    if var_pct <= -0.15:
        return 1.20
    elif var_pct <= -0.05:
        return 1.10
    return 1.0


def factor_promo_temporal(lift_qty, weeks_active):
    """Modular factor por semana de la promo (regla 7).

    weeks_active=1 → cliente carga (lift puede ser alto)
    weeks_active=2-3 → cliente saturado (factor agresivo a la baja)
    weeks_active=4+ → regression to mean
    """
    if pd.isna(lift_qty) or lift_qty <= 0:
        return 1.0
    if weeks_active <= 1:
        if lift_qty >= 1.5:
            return min(2.0, 1.0 + (lift_qty - 1.0) * 0.7)
        elif lift_qty <= 0.5:
            return max(0.5, lift_qty)
        else:
            return 1.0
    elif weeks_active <= 3:
        # Cliente saturado: lift_qty es el observado pero comprimimos a 1 si era alto
        if lift_qty >= 1.5:
            return 0.50  # fuerte caida por saturacion
        elif lift_qty <= 0.5:
            return max(0.30, lift_qty)
        else:
            return max(0.60, lift_qty * 0.7)
    else:  # weeks_active >= 4
        if lift_qty <= 0.7:
            return max(0.70, lift_qty)
        elif lift_qty >= 1.3:
            return min(1.20, lift_qty * 0.8)
        return lift_qty


def detectar_alerta_sku(target_week, sku):
    """Aplica las 15 reglas a un SKU en una semana objetivo."""
    sub_cat = sku_to_subcat.get(sku, "OTROS")
    abc = sku_to_abc.get(sku, "")
    week_lookback = target_week - pd.Timedelta(weeks=4)

    # Cambio precio mas reciente
    cambios = dfp[
        (dfp["Producto"] == sku) &
        (dfp["Fecha"] >= week_lookback) &
        (dfp["Fecha"] <= target_week)
    ]
    cambio_reciente = cambios.sort_values("Fecha", ascending=False).head(1)
    has_cambio = len(cambio_reciente) > 0

    # Promo activa
    promos = dfm[
        (dfm["product_variant_id"] == sku) &
        (dfm["period_start"] >= week_lookback) &
        (dfm["period_start"] <= target_week)
    ]
    promo_reciente = promos.sort_values("period_start", ascending=False).head(1)
    has_promo = len(promo_reciente) > 0

    if not has_cambio and not has_promo:
        return None

    # ============ CASO 3: solo promo activa, sin cambio precio ============
    if has_promo and not has_cambio:
        p = promo_reciente.iloc[0]
        lift = p.get("lift_qty", 1.0)
        weeks_active = max(1, int((target_week - p["period_start"]).days // 7) + 1)
        mecanica = p.get("mecanica", "OTRO")
        # Regla 10: solo alertar si lift fuera de rango
        if 0.5 <= lift <= 1.5 and weeks_active <= 1:
            return None  # ambiguo, no alertar
        factor = factor_promo_temporal(lift, weeks_active)
        tipo = f"PROMO_{mecanica}_W{weeks_active}"
        razon = f"Promo {mecanica} (sem {weeks_active}, lift {lift:.2f})"
        return {
            "tipo": tipo, "factor_corr": factor, "razon": razon,
            "fuente": "PROMO_PURA", "indice_canibal": 0.0,
        }

    # Hay cambio de precio
    c = cambio_reciente.iloc[0]
    var_pct = c.get("Variacion %", 0.0)
    direccion = c.get(direccion_col, "")
    weeks_since_change = max(0, (target_week - c["Fecha"]).days // 7)
    decay = max(0.0, 1.0 - weeks_since_change / 8.0)

    # ============ CASO 5: bajada >30% = discontinuacion ============
    if direccion == "Baja" and var_pct <= -0.30:
        return {
            "tipo": "BAJADA_DISCONTINUACION", "factor_corr": 1.0,
            "razon": f"Baja {var_pct*100:+.0f}% (liquidacion)",
            "fuente": "PRICE_CHANGE", "indice_canibal": 0.0,
        }

    # ============ CASO 2: subida + promo propia (regla 6) ============
    if direccion == "Sube" and has_promo:
        p = promo_reciente.iloc[0]
        lift = p.get("lift_qty", 1.0)
        weeks_active = max(1, int((target_week - p["period_start"]).days // 7) + 1)
        mecanica = p.get("mecanica", "OTRO")
        factor = factor_promo_temporal(lift, weeks_active)
        return {
            "tipo": f"SUBIDA_CON_DEFENSA_{mecanica}",
            "factor_corr": factor,
            "razon": f"Subida {var_pct*100:+.0f}% defendida con {mecanica} sem {weeks_active} (lift {lift:.2f})",
            "fuente": "MIXTO", "indice_canibal": 0.0,
        }

    # ============ CASO 1: subida pura sin promo ============
    if direccion == "Sube":
        if abs(var_pct) < 0.05:
            return None
        factor_b = factor_base_subida(var_pct)
        indice = indice_canibal_ponderado(target_week, sub_cat, "Sube", sku)
        # Magnitud del cambio modula la amplificacion (regla 1)
        if var_pct >= 0.20:
            multi_max = 0.40
        elif var_pct >= 0.10:
            multi_max = 0.55
        else:
            multi_max = 0.75
        if indice >= 0.50:
            tipo = "SUBIDA_CANIBAL_FUERTE"
            factor = factor_b * max(multi_max, 1.0 - indice * 0.6)
        elif indice >= 0.25:
            tipo = "SUBIDA_CANIBAL_MODERADO"
            factor = factor_b * max(multi_max + 0.10, 1.0 - indice * 0.4)
        elif indice >= 0.10:
            tipo = "SUBIDA_CON_PRESION"
            factor = factor_b * (1.0 - indice * 0.2)
        else:
            tipo = "SUBIDA_UNICA"
            factor = factor_b
        # Aplicar decay
        factor = 1.0 - (1.0 - factor) * decay
        return {
            "tipo": tipo, "factor_corr": round(factor, 3),
            "razon": f"Sube {var_pct*100:+.0f}% sin promo + canibal {indice:.2f} en {sub_cat}",
            "fuente": "PRICE_CHANGE", "indice_canibal": round(indice, 3),
        }

    # ============ CASO 4: bajada pura ============
    if direccion == "Baja":
        if abs(var_pct) < 0.05:
            return None
        factor_b = factor_base_bajada(var_pct)
        indice = indice_canibal_ponderado(target_week, sub_cat, "Baja", sku)
        if indice >= 0.50:
            tipo = "BAJADA_GANADORA_FUERTE"
            factor = factor_b * (1.0 + indice * 0.6)
        elif indice >= 0.25:
            tipo = "BAJADA_GANADORA_MODERADA"
            factor = factor_b * (1.0 + indice * 0.4)
        elif indice >= 0.10:
            tipo = "BAJADA_CON_PRESION"
            factor = factor_b * (1.0 + indice * 0.2)
        else:
            tipo = "BAJADA_UNICA"
            factor = factor_b
        factor = 1.0 + (factor - 1.0) * decay
        return {
            "tipo": tipo, "factor_corr": round(factor, 3),
            "razon": f"Baja {var_pct*100:+.0f}% + canibal {indice:.2f} ({sub_cat})",
            "fuente": "PRICE_CHANGE", "indice_canibal": round(indice, 3),
        }

    return None


# ----------------------------------------------------------------------
# APLICAR Y VALIDAR POR SEMANA
# ----------------------------------------------------------------------
all_alertas = []
for week_target in weeks_bt:
    print("\n" + "=" * 110)
    print(f"SEMANA: {str(week_target)[:10]}")
    print("=" * 110)

    # SKUs con potencial alerta (cambio o promo en ventana)
    week_lookback = week_target - pd.Timedelta(weeks=4)
    skus_potenciales = set()
    skus_potenciales.update(dfp[(dfp["Fecha"] >= week_lookback) & (dfp["Fecha"] <= week_target)]["Producto"].tolist())
    skus_potenciales.update(dfm[(dfm["period_start"] >= week_lookback) & (dfm["period_start"] <= week_target)]["product_variant_id"].tolist())
    print(f"  SKUs potenciales (con cambio o promo): {len(skus_potenciales):,}")

    alertas = []
    for sku in skus_potenciales:
        res = detectar_alerta_sku(week_target, sku)
        if res:
            res["product_id"] = sku
            res["sub_cat"] = sku_to_subcat.get(sku, "OTROS")
            res["abc"] = sku_to_abc.get(sku, "")
            res["target_week"] = week_target
            alertas.append(res)

    alertas_df = pd.DataFrame(alertas)
    print(f"  Alertas generadas: {len(alertas_df):,}")
    if len(alertas_df) == 0:
        continue

    # Distribucion por tipo
    print(f"\n  Distribucion por tipo:")
    print(alertas_df["tipo"].value_counts().to_string())

    # Cruzar con backtest
    bt_week = dfb[dfb["target_week_start"] == week_target]
    bt_agg = bt_week.groupby("product_id", as_index=False).agg(
        real=("real_qty", "sum"),
        forecast_v3_24=("forecast_qty", "sum"),
    )
    merged = alertas_df.merge(bt_agg, on="product_id", how="left")
    merged = merged.dropna(subset=["real", "forecast_v3_24"])
    merged["forecast_corregido"] = (merged["forecast_v3_24"] * merged["factor_corr"]).round(0)
    merged["abs_err_orig"] = (merged["forecast_v3_24"] - merged["real"]).abs()
    merged["abs_err_corr"] = (merged["forecast_corregido"] - merged["real"]).abs()
    merged["mejora"] = merged["abs_err_orig"] - merged["abs_err_corr"]

    real_sum = merged["real"].sum()
    if real_sum > 0:
        wape_orig = merged["abs_err_orig"].sum() / real_sum * 100
        wape_corr = merged["abs_err_corr"].sum() / real_sum * 100
        bias_orig = (merged["forecast_v3_24"] - merged["real"]).sum() / real_sum * 100
        bias_corr = (merged["forecast_corregido"] - merged["real"]).sum() / real_sum * 100
        print(f"\n  Sobre {len(merged):,} SKUs alertados con backtest:")
        print(f"    Real:              {real_sum:>9,.0f}")
        print(f"    Forecast original: {merged['forecast_v3_24'].sum():>9,.0f}  WAPE {wape_orig:6.2f}%  BIAS {bias_orig:+7.2f}%")
        print(f"    Forecast corregido:{merged['forecast_corregido'].sum():>9,.0f}  WAPE {wape_corr:6.2f}%  BIAS {bias_corr:+7.2f}%")
        print(f"    Mejora abs_err:    {merged['mejora'].sum():>+9,.0f} ({merged['mejora'].sum()/merged['abs_err_orig'].sum()*100:+5.1f}% del ae_orig)")

    all_alertas.append(merged)


# ----------------------------------------------------------------------
# RESUMEN POR TIPO (3 semanas)
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("RESUMEN CONSOLIDADO POR TIPO DE ALERTA")
print("=" * 110)
df_all = pd.concat(all_alertas, ignore_index=True)
rows = []
for tipo in df_all["tipo"].unique():
    sub = df_all[df_all["tipo"] == tipo]
    real = sub["real"].sum()
    ae_orig = sub["abs_err_orig"].sum()
    ae_corr = sub["abs_err_corr"].sum()
    mejora = ae_orig - ae_corr
    rows.append({
        "tipo": tipo, "n": len(sub), "real": real,
        "ae_orig": ae_orig, "ae_corr": ae_corr,
        "mejora": mejora, "pct": mejora/ae_orig*100 if ae_orig > 0 else 0,
    })
df_resumen = pd.DataFrame(rows).sort_values("mejora", ascending=False)
print(df_resumen.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# Aplicar SOLO tipos con mejora positiva
print("\n" + "=" * 110)
print("APLICANDO SOLO TIPOS CON MEJORA POSITIVA (selectivo)")
print("=" * 110)
tipos_buenos = df_resumen[df_resumen["mejora"] > 0]["tipo"].tolist()
df_all["aplicar"] = df_all["tipo"].isin(tipos_buenos)
df_all["fcst_final"] = np.where(df_all["aplicar"], df_all["forecast_corregido"], df_all["forecast_v3_24"])
df_all["ae_final"] = (df_all["fcst_final"] - df_all["real"]).abs()

real_total = df_all["real"].sum()
ae_orig_total = df_all["abs_err_orig"].sum()
ae_final_total = df_all["ae_final"].sum()
mejora_neta = ae_orig_total - ae_final_total
print(f"\n  Tipos aplicados (mejora>0): {tipos_buenos}")
print(f"  SKUs con correccion aplicada: {df_all['aplicar'].sum():,} de {len(df_all):,}")
print(f"  abs_err original:  {ae_orig_total:>9,.0f}  WAPE {ae_orig_total/real_total*100:.2f}%")
print(f"  abs_err con tipos buenos: {ae_final_total:>9,.0f}  WAPE {ae_final_total/real_total*100:.2f}%")
print(f"  Mejora neta: {mejora_neta:+,.0f} unidades ({mejora_neta/ae_orig_total*100:+.1f}% del ae_orig)")

# Impacto en WAPE global hm_si estimado
TOTAL_REAL_HM = 108714
WAPE_BASE = 72.43
ae_base = TOTAL_REAL_HM * WAPE_BASE / 100
ae_nuevo = ae_base - mejora_neta
wape_nuevo = ae_nuevo / TOTAL_REAL_HM * 100
print(f"\n  WAPE hm_si actual:           {WAPE_BASE:.2f}%")
print(f"  WAPE estimado con detector:  {wape_nuevo:.2f}%  (mejora {WAPE_BASE - wape_nuevo:+.2f}pp)")

df_all.to_excel(OUT_XLSX, index=False)
print(f"\n  Archivo: {OUT_XLSX}")
print("\nDONE.")
