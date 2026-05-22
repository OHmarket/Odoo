"""
Detector v2 con LOGICA DE CANIBALIZACION explicita.

Distingue:
  - CAMBIO UNICO en categoria (factor base): sub-cat estable, sin movimientos opuestos
  - CAMBIO CON CANIBAL (amplificado en ambos sentidos):
      SKU sube + otros bajan/promo  → caida AMPLIFICADA
      SKU baja + otros suben         → subida AMPLIFICADA
      Promo activa + sustitutos caros → lift confirmado

Indice canibal = n_opuestos_subcat / n_total_subcat
"""
import pandas as pd
import numpy as np

PATH_PRICE  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PATH_PROMO  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
PATH_BT     = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
OUT_XLSX    = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_detector_anomalias_v2_output.xlsx"

# ----------------------------------------------------------------------
# CARGA
# ----------------------------------------------------------------------
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


# Mapeo SKU -> sub-cat desde backtest
sku_to_subcat = {}
for _, row in dfb.iterrows():
    sku = row["product_id"]
    if sku not in sku_to_subcat:
        sku_to_subcat[sku] = get_sub_cat(row["categ_id"])

# Conteo total SKUs por sub-cat
sku_count_by_subcat = pd.Series(list(sku_to_subcat.values())).value_counts().to_dict()


# ----------------------------------------------------------------------
# INDICES POR SUB-CAT
# ----------------------------------------------------------------------
def contar_movimientos_subcat(target_week, sub_cat, lookback_weeks=4):
    """Cuenta subidas, bajadas y promos en sub-cat L3 en ventana lookback."""
    week_lookback = target_week - pd.Timedelta(weeks=lookback_weeks)
    # Cambios precio
    cambios = dfp[
        (dfp["Fecha"] >= week_lookback) &
        (dfp["Fecha"] <= target_week)
    ].copy()
    cambios["sub"] = cambios["Categoria"].apply(get_sub_cat)
    cambios_sub = cambios[cambios["sub"] == sub_cat]
    n_subes = (cambios_sub[direccion_col] == "Sube").sum()
    n_bajas = (cambios_sub[direccion_col] == "Baja").sum()
    # Promos activas
    promos = dfm[
        (dfm["period_start"] >= week_lookback) &
        (dfm["period_start"] <= target_week)
    ].copy()
    promos["sub"] = promos["categ_id"].apply(get_sub_cat)
    n_promos = len(promos[promos["sub"] == sub_cat])
    n_total = sku_count_by_subcat.get(sub_cat, 1)
    return n_subes, n_bajas, n_promos, n_total


# ----------------------------------------------------------------------
# DETECTAR ALERTAS CON LOGICA REFINADA
# ----------------------------------------------------------------------
def detectar_alertas_v2(target_week):
    alertas = []
    week_lookback = target_week - pd.Timedelta(weeks=4)

    # Cambios precio recientes por SKU (mas reciente)
    cambios_recientes = dfp[(dfp["Fecha"] >= week_lookback) & (dfp["Fecha"] <= target_week)].copy()
    cambios_por_sku = cambios_recientes.sort_values("Fecha", ascending=False).groupby("Producto").first().reset_index()

    skus_alertados = set()

    # ---- Procesar cambios de precio ----
    for _, row in cambios_por_sku.iterrows():
        sku = row["Producto"]
        var_pct = row.get("Variacion %", 0.0)
        direccion = row.get(direccion_col, "")
        sub_cat = sku_to_subcat.get(sku, get_sub_cat(row.get("Categoria", "")))
        weeks_since = max(0, (target_week - row["Fecha"]).days // 7)
        decay = max(0.0, 1.0 - weeks_since / 8.0)  # decay mas rapido (8 sem)

        # Magnitud del cambio
        if abs(var_pct) < 0.05:
            continue  # cambio insignificante

        # Contar movimientos en sub-categoria
        n_subes, n_bajas, n_promos, n_total = contar_movimientos_subcat(target_week, sub_cat)
        # Excluir self-count
        if direccion == "Sube":
            n_subes_otros = max(0, n_subes - 1)
            n_opuestos = n_bajas + n_promos
        else:
            n_bajas_otros = max(0, n_bajas - 1)
            n_opuestos = n_subes
        indice_canibal = n_opuestos / max(1, n_total)

        if direccion == "Sube":
            factor_base = 0.76 if var_pct >= 0.15 else 0.85
            if indice_canibal >= 0.30:
                tipo = "SUBIDA_CON_CANIBAL"
                # Amplificar caida: factor_base se hace mas pequeno
                factor_sug = max(0.20, factor_base * (1.0 - min(0.7, indice_canibal)))
                razon = f"SUBIDA {var_pct*100:+.0f}% + canibal={indice_canibal:.2f} ({n_bajas} bajas + {n_promos} promos en {sub_cat})"
            elif indice_canibal >= 0.15:
                tipo = "SUBIDA_CON_PRESION"
                factor_sug = max(0.40, factor_base * (1.0 - indice_canibal * 0.5))
                razon = f"SUBIDA {var_pct*100:+.0f}% + presion={indice_canibal:.2f} en {sub_cat}"
            else:
                tipo = "SUBIDA_UNICA"
                factor_sug = factor_base
                razon = f"SUBIDA {var_pct*100:+.0f}% aislada en {sub_cat} (canibal {indice_canibal:.2f})"
        elif direccion == "Baja":
            # Si la bajada es muy fuerte (>30%) sospecha de liquidacion
            if var_pct <= -0.30:
                tipo = "BAJADA_DISCONTINUACION"
                factor_sug = 1.0  # NO amplificar, posible liquidacion
                razon = f"BAJADA {var_pct*100:+.0f}% fuerte (liquidacion probable)"
            else:
                factor_base = 1.20 if var_pct <= -0.15 else 1.10
                if indice_canibal >= 0.30:
                    tipo = "BAJADA_CON_CANIBAL"
                    factor_sug = min(2.50, factor_base * (1.0 + indice_canibal))
                    razon = f"BAJADA {var_pct*100:+.0f}% + canibal={indice_canibal:.2f} ({n_subes} subidas en {sub_cat})"
                elif indice_canibal >= 0.15:
                    tipo = "BAJADA_CON_PRESION"
                    factor_sug = min(1.80, factor_base * (1.0 + indice_canibal * 0.5))
                    razon = f"BAJADA {var_pct*100:+.0f}% + presion={indice_canibal:.2f}"
                else:
                    tipo = "BAJADA_UNICA"
                    factor_sug = factor_base
                    razon = f"BAJADA {var_pct*100:+.0f}% aislada (canibal {indice_canibal:.2f})"

        # Aplicar decay temporal
        factor_sug = 1.0 - (1.0 - factor_sug) * decay

        alertas.append({
            "product_id": sku, "sub_cat": sub_cat,
            "n_subes_subcat": n_subes, "n_bajas_subcat": n_bajas, "n_promos_subcat": n_promos,
            "indice_canibal": round(indice_canibal, 3),
            "tipo_alerta": tipo, "factor_correccion_sug": round(factor_sug, 3),
            "razon": razon, "fuente": "PRICE_CHANGE",
        })
        skus_alertados.add(sku)

    # ---- Procesar promos activas (solo con lift comprobado) ----
    promos_activas = dfm[(dfm["period_start"] >= week_lookback) & (dfm["period_start"] <= target_week)].copy()
    if len(promos_activas) > 0:
        promo_por_sku = promos_activas.groupby("product_variant_id").agg(
            lift_max=("lift_qty", "max"),
            period_start_max=("period_start", "max"),
            promo_effect=("promo_effect", "first"),
            program_name=("program_name", "first"),
        ).reset_index()

        for _, row in promo_por_sku.iterrows():
            sku = row["product_variant_id"]
            if sku in skus_alertados:
                continue
            lift = row.get("lift_max", 1.0)
            if pd.isna(lift):
                continue
            sub_cat = sku_to_subcat.get(sku, "OTROS")
            weeks_since = max(0, (target_week - row["period_start_max"]).days // 7)
            decay = max(0.0, 1.0 - weeks_since / 4.0)

            # SOLO alertar si lift es claramente fuera de rango
            if lift >= 1.5:
                tipo = "DISPARO_PROMO_FUERTE"
                factor_sug = min(2.50, 1.0 + (lift - 1.0) * 0.8)  # mas conservador que lift puro
                # Aplicar decay
                factor_sug = 1.0 + (factor_sug - 1.0) * decay
                razon = f"Promo lift {lift:.2f}x ({row.get('program_name', '')[:35]})"
            elif lift >= 1.2:
                tipo = "DISPARO_PROMO_MODERADO"
                factor_sug = 1.0 + (lift - 1.0) * 0.7 * decay
                razon = f"Promo lift {lift:.2f}x moderado"
            else:
                continue  # NO alertar promos con lift bajo (eran las que generaban ruido)

            alertas.append({
                "product_id": sku, "sub_cat": sub_cat,
                "n_subes_subcat": 0, "n_bajas_subcat": 0, "n_promos_subcat": 0,
                "indice_canibal": 0.0,
                "tipo_alerta": tipo, "factor_correccion_sug": round(factor_sug, 3),
                "razon": razon, "fuente": "PROMO",
            })
            skus_alertados.add(sku)

    return pd.DataFrame(alertas)


# ----------------------------------------------------------------------
# APLICAR Y VALIDAR
# ----------------------------------------------------------------------
print("=" * 110)
print("DETECTOR v2 — con logica de canibalizacion en ambos sentidos")
print("=" * 110)

all_alertas = []
all_validacion = []
for week_target in weeks_bt:
    print("\n" + "=" * 110)
    print(f"SEMANA: {str(week_target)[:10]}")
    print("=" * 110)

    alertas_df = detectar_alertas_v2(week_target)
    print(f"\n  SKUs alertados: {len(alertas_df):,}")
    if len(alertas_df) == 0:
        continue

    print(f"\n  Distribucion por tipo:")
    print(alertas_df["tipo_alerta"].value_counts().to_string())

    # Cruzar con backtest
    bt_week = dfb[dfb["target_week_start"] == week_target]
    bt_agg = bt_week.groupby("product_id", as_index=False).agg(
        real=("real_qty", "sum"),
        forecast_v3_24=("forecast_qty", "sum"),
    )
    merged = alertas_df.merge(bt_agg, on="product_id", how="left")
    merged["forecast_corregido"] = (merged["forecast_v3_24"] * merged["factor_correccion_sug"]).round(0)
    merged["target_week"] = week_target
    merged["abs_err_orig"] = (merged["forecast_v3_24"] - merged["real"]).abs()
    merged["abs_err_corr"] = (merged["forecast_corregido"] - merged["real"]).abs()
    merged["mejora"] = merged["abs_err_orig"] - merged["abs_err_corr"]

    real_sum = merged["real"].sum()
    if real_sum > 0:
        wape_orig = merged["abs_err_orig"].sum() / real_sum * 100
        wape_corr = merged["abs_err_corr"].sum() / real_sum * 100
        bias_orig = (merged["forecast_v3_24"] - merged["real"]).sum() / real_sum * 100
        bias_corr = (merged["forecast_corregido"] - merged["real"]).sum() / real_sum * 100
        print(f"\n  Sobre SKUs alertados (n={len(merged):,}):")
        print(f"    Real:               {real_sum:>9,.0f}")
        print(f"    Forecast original:  {merged['forecast_v3_24'].sum():>9,.0f}  WAPE {wape_orig:6.2f}%  BIAS {bias_orig:+7.2f}%")
        print(f"    Forecast corregido: {merged['forecast_corregido'].sum():>9,.0f}  WAPE {wape_corr:6.2f}%  BIAS {bias_corr:+7.2f}%")
        print(f"    Mejora abs_err:     {merged['mejora'].sum():>+9,.0f} unidades ({merged['mejora'].sum()/merged['abs_err_orig'].sum()*100:+5.1f}% del ae_orig)")
        all_validacion.append({
            "week": str(week_target)[:10], "n": len(merged), "real": real_sum,
            "wape_orig_%": wape_orig, "wape_corr_%": wape_corr,
            "bias_orig_%": bias_orig, "bias_corr_%": bias_corr,
            "mejora": merged["mejora"].sum(),
        })

    all_alertas.append(merged)


# ----------------------------------------------------------------------
# RESUMEN GLOBAL POR TIPO
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("RESUMEN POR TIPO DE ALERTA (3 semanas consolidado)")
print("=" * 110)
df_all = pd.concat(all_alertas, ignore_index=True)
rows = []
for tipo in df_all["tipo_alerta"].unique():
    sub = df_all[df_all["tipo_alerta"] == tipo]
    real = sub["real"].sum()
    ae_orig = sub["abs_err_orig"].sum()
    ae_corr = sub["abs_err_corr"].sum()
    mejora = ae_orig - ae_corr
    rows.append({
        "tipo": tipo, "n": len(sub), "real": real,
        "ae_orig": ae_orig, "ae_corr": ae_corr,
        "mejora_ae": mejora,
        "pct_mejora": mejora/ae_orig*100 if ae_orig > 0 else 0,
    })
print(pd.DataFrame(rows).sort_values("mejora_ae", ascending=False).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


print("\n" + "=" * 110)
print("RESUMEN VALIDACION RETRO (W17-W19)")
print("=" * 110)
print(pd.DataFrame(all_validacion).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

df_all.to_excel(OUT_XLSX, index=False, sheet_name="alertas_v2")
print(f"\nArchivo exportado: {OUT_XLSX}")
print("\nDONE.")
