"""
Detector de anomalias predictivas por semana.

Cruza:
  - x_price_change_event (cambios de precio recientes)
  - x_loyalty_promo_event (promos activas)
  - backtest file 10 (real medido para validacion retro)

Output:
  1. Por cada SKU activo en cada semana W17/W18/W19, detectar:
     - CAIDA_AMPLIFICADA: subida >=15% + CPI alto
     - CAIDA_SIMPLE: subida <15% sin contexto
     - DISPARO_PROMO: promo activa con lift relevante
     - NEUTRO
  2. Aplicar factor de correccion al forecast original
  3. Comparar forecast_v3_24 vs forecast_corregido vs real
"""
import pandas as pd
import numpy as np

PATH_PRICE  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PATH_PROMO  = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
PATH_BT     = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
OUT_XLSX    = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_detector_anomalias_output.xlsx"

# ----------------------------------------------------------------------
# CARGA
# ----------------------------------------------------------------------
print("=" * 100)
print("DETECTOR DE ANOMALIAS — cargando inputs")
print("=" * 100)
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

print(f"  Cambios precio: {len(dfp):,} filas")
print(f"  Promos:          {len(dfm):,} filas")
print(f"  Backtest:        {len(dfb):,} filas")

# Filtrar backtest a hm_si y 3 semanas
weeks_bt = sorted(dfb["target_week_start"].dropna().unique())[-3:]
print(f"\n  Semanas backtest: {[str(w)[:10] for w in weeks_bt]}")
dfb = dfb[(dfb["method"] == "hm_si") & (dfb["target_week_start"].isin(weeks_bt))].copy()
for c in ["real_qty", "forecast_qty", "abs_error_qty", "error_qty"]:
    dfb[c] = pd.to_numeric(dfb[c], errors="coerce").fillna(0.0)

# Construir mapeo SKU -> sub-categoria L3 desde backtest
sku_to_subcat = {}
for _, row in dfb.iterrows():
    sku = row["product_id"]
    cat = str(row["categ_id"])
    if sku not in sku_to_subcat and pd.notna(cat):
        parts = cat.split(' / ')
        sub_cat = parts[2] if len(parts) >= 3 else parts[-1]
        sku_to_subcat[sku] = sub_cat
print(f"  SKUs unicos en backtest con sub-cat: {len(sku_to_subcat):,}")


# ----------------------------------------------------------------------
# 1. CPI POR SUB-CATEGORIA POR SEMANA
# ----------------------------------------------------------------------
def calcular_cpi(target_week, lookback_weeks=4):
    """Calcula CPI por sub-categoria.

    CPI = (n_bajadas_ultimas_4sem + n_promos_activas) / n_skus_total_sub_cat
    """
    week_start_lookback = target_week - pd.Timedelta(weeks=lookback_weeks)
    # Bajadas recientes
    bajadas_recientes = dfp[
        (dfp["Fecha"] >= week_start_lookback) &
        (dfp["Fecha"] <= target_week) &
        (dfp[direccion_col] == "Baja")
    ].copy()
    bajadas_recientes["sub_cat"] = bajadas_recientes["Categoria"].astype(str).apply(
        lambda x: x.split(' / ')[2] if len(x.split(' / ')) >= 3 else x.split(' / ')[-1]
    )
    # Promos activas (period_start dentro de la semana o ya estaba activa)
    promos_activas = dfm[
        (dfm["period_start"] >= week_start_lookback) &
        (dfm["period_start"] <= target_week)
    ].copy()
    promos_activas["sub_cat"] = promos_activas["categ_id"].astype(str).apply(
        lambda x: x.split(' / ')[2] if len(x.split(' / ')) >= 3 else x.split(' / ')[-1]
    )
    # Total SKUs por sub-cat (desde backtest)
    sku_count_by_subcat = pd.Series(list(sku_to_subcat.values())).value_counts()

    cpi = {}
    all_sub_cats = set(bajadas_recientes["sub_cat"]) | set(promos_activas["sub_cat"]) | set(sku_count_by_subcat.index)
    for sub_cat in all_sub_cats:
        n_bajadas = (bajadas_recientes["sub_cat"] == sub_cat).sum()
        n_promos = (promos_activas["sub_cat"] == sub_cat).sum()
        n_total = max(1, sku_count_by_subcat.get(sub_cat, 0))
        cpi[sub_cat] = (n_bajadas + n_promos) / n_total
    return cpi


# ----------------------------------------------------------------------
# 2. DETECTAR ALERTAS POR SKU EN UNA SEMANA
# ----------------------------------------------------------------------
def detectar_alertas(target_week):
    """Genera alertas para SKUs activos en la semana objetivo."""
    cpi = calcular_cpi(target_week)
    week_start_lookback = target_week - pd.Timedelta(weeks=4)

    # Cambios de precio recientes por SKU (mas reciente)
    cambios_recientes = dfp[
        (dfp["Fecha"] >= week_start_lookback) &
        (dfp["Fecha"] <= target_week)
    ].copy()
    cambios_por_sku = cambios_recientes.sort_values("Fecha", ascending=False).groupby("Producto").first().reset_index()

    # Promos activas en target_week
    promos_activas = dfm[
        (dfm["period_start"] >= week_start_lookback) &
        (dfm["period_start"] <= target_week)
    ].copy()
    # Agrupar por SKU: tomar la mas reciente y el lift maximo
    promo_por_sku = promos_activas.groupby("product_variant_id").agg(
        lift_max=("lift_qty", "max"),
        period_start_max=("period_start", "max"),
        promo_effect_recent=("promo_effect", "first"),
        program_name_first=("program_name", "first"),
        price_delta_pct=("price_delta_pct", "mean"),
    ).reset_index()

    alertas = []
    skus_alertados = set()

    # Procesar cambios de precio
    for _, row in cambios_por_sku.iterrows():
        sku = row["Producto"]
        var_pct = row.get("Variacion %", 0.0)
        direccion = row.get(direccion_col, "")
        sub_cat = sku_to_subcat.get(sku, str(row.get("Categoria", "")).split(" / ")[-1])
        cpi_sub = cpi.get(sub_cat, 0.0)
        weeks_since = max(0, (target_week - row["Fecha"]).days // 7)

        # Decay del efecto del cambio: 0..4 semanas
        decay_factor = max(0.0, 1.0 - weeks_since / 16.0)

        if direccion == "Sube":
            if var_pct >= 0.15:
                if cpi_sub >= 0.30:
                    tipo = "CAIDA_AMPLIFICADA"
                    factor_sug = max(0.30, 0.76 * max(0.40, 1.0 - cpi_sub))
                else:
                    tipo = "CAIDA_FUERTE"
                    factor_sug = 0.65
            elif var_pct >= 0.05:
                if cpi_sub >= 0.30:
                    tipo = "CAIDA_MODERADA"
                    factor_sug = max(0.50, 0.85 * max(0.50, 1.0 - cpi_sub * 0.5))
                else:
                    tipo = "CAIDA_SIMPLE"
                    factor_sug = 0.85
            else:
                continue  # subida insignificante
            # aplicar decay (si el cambio es viejo, factor cerca de 1)
            factor_sug = 1.0 - (1.0 - factor_sug) * decay_factor
            razon = f"{direccion} {var_pct*100:+.0f}% hace {weeks_since}sem + CPI {cpi_sub:.2f}"
        elif direccion == "Baja":
            if var_pct <= -0.15:
                tipo = "CAIDA_DISCONTINUADO"  # bajadas fuertes suelen ser liquidacion
                factor_sug = 1.0  # no amplificar, dejar al motor
                razon = f"Baja {var_pct*100:+.0f}% hace {weeks_since}sem (liquidacion probable)"
            else:
                tipo = "ALZA_LEVE_PRECIO"  # bajada moderada → mas demanda esperada
                factor_sug = 1.0 - (1.0 - 1.20) * decay_factor
                razon = f"Baja {var_pct*100:+.0f}% hace {weeks_since}sem"
        else:
            continue

        alertas.append({
            "product_id": sku,
            "sub_cat": sub_cat,
            "cpi_sub": round(cpi_sub, 2),
            "tipo_alerta": tipo,
            "factor_correccion_sug": round(factor_sug, 3),
            "razon": razon,
            "fuente": "PRICE_CHANGE",
        })
        skus_alertados.add(sku)

    # Procesar promos activas
    for _, row in promo_por_sku.iterrows():
        sku = row["product_variant_id"]
        if sku in skus_alertados:
            continue  # ya alertado por precio
        lift = row.get("lift_max", 1.0)
        if pd.isna(lift):
            continue
        sub_cat = sku_to_subcat.get(sku, "OTROS")
        cpi_sub = cpi.get(sub_cat, 0.0)
        weeks_since = max(0, (target_week - row["period_start_max"]).days // 7)

        if lift >= 1.5:
            tipo = "DISPARO_PROMO"
            factor_sug = min(3.0, lift)
            razon = f"Promo activa lift {lift:.2f}x hace {weeks_since}sem ({row.get('program_name_first', '')[:40]})"
        elif lift >= 0.8 and lift < 1.5:
            tipo = "PROMO_NEUTRA"
            factor_sug = 1.0
            razon = f"Promo lift {lift:.2f}x sin efecto material"
        else:
            tipo = "PROMO_INEFECTIVA"
            factor_sug = max(0.6, lift)
            razon = f"Promo lift {lift:.2f}x baja"

        alertas.append({
            "product_id": sku,
            "sub_cat": sub_cat,
            "cpi_sub": round(cpi_sub, 2),
            "tipo_alerta": tipo,
            "factor_correccion_sug": round(factor_sug, 3),
            "razon": razon,
            "fuente": "PROMO",
        })
        skus_alertados.add(sku)

    return pd.DataFrame(alertas), cpi


# ----------------------------------------------------------------------
# 3. APLICAR Y VALIDAR POR SEMANA
# ----------------------------------------------------------------------
all_alertas = []
all_validacion = []
for week_target in weeks_bt:
    print("\n" + "=" * 100)
    print(f"SEMANA: {str(week_target)[:10]}")
    print("=" * 100)

    alertas_df, cpi = detectar_alertas(week_target)
    print(f"\n  SKUs alertados: {len(alertas_df):,}")
    if len(alertas_df) == 0:
        continue

    # Distribucion por tipo
    print(f"  Distribucion por tipo:")
    print(alertas_df["tipo_alerta"].value_counts().to_string())

    # Cruzar con backtest
    bt_week = dfb[dfb["target_week_start"] == week_target].copy()
    bt_agg = bt_week.groupby("product_id", as_index=False).agg(
        real=("real_qty", "sum"),
        forecast_v3_24=("forecast_qty", "sum"),
    )
    merged = alertas_df.merge(bt_agg, on="product_id", how="left")
    merged["forecast_corregido"] = (merged["forecast_v3_24"] * merged["factor_correccion_sug"]).round(0)
    merged["target_week"] = week_target

    # Metricas
    merged["abs_err_original"] = (merged["forecast_v3_24"] - merged["real"]).abs()
    merged["abs_err_corregido"] = (merged["forecast_corregido"] - merged["real"]).abs()
    merged["mejora_abs_err"] = merged["abs_err_original"] - merged["abs_err_corregido"]

    # Suma SKUs alertados
    real_sum = merged["real"].sum()
    if real_sum > 0:
        wape_orig = merged["abs_err_original"].sum() / real_sum * 100
        wape_corr = merged["abs_err_corregido"].sum() / real_sum * 100
        bias_orig = (merged["forecast_v3_24"] - merged["real"]).sum() / real_sum * 100
        bias_corr = (merged["forecast_corregido"] - merged["real"]).sum() / real_sum * 100
        print(f"\n  Sobre SKUs alertados (n={len(merged):,}):")
        print(f"    Real:               {real_sum:>9,.0f}")
        print(f"    Forecast original:  {merged['forecast_v3_24'].sum():>9,.0f}  WAPE {wape_orig:6.2f}%  BIAS {bias_orig:+7.2f}%")
        print(f"    Forecast corregido: {merged['forecast_corregido'].sum():>9,.0f}  WAPE {wape_corr:6.2f}%  BIAS {bias_corr:+7.2f}%")
        print(f"    Mejora abs_err:     {merged['mejora_abs_err'].sum():>9,.0f} unidades")

        all_validacion.append({
            "week": str(week_target)[:10],
            "n_skus_alertados": len(merged),
            "real_sum": real_sum,
            "fcst_orig": merged["forecast_v3_24"].sum(),
            "fcst_corr": merged["forecast_corregido"].sum(),
            "wape_orig_%": wape_orig,
            "wape_corr_%": wape_corr,
            "bias_orig_%": bias_orig,
            "bias_corr_%": bias_corr,
            "mejora_abs_err": merged["mejora_abs_err"].sum(),
        })

    # Top 15 mejoras
    print(f"\n  Top 15 SKUs alertados con mas mejora en abs_err:")
    cols_show = ["product_id", "tipo_alerta", "factor_correccion_sug", "forecast_v3_24", "forecast_corregido", "real", "abs_err_original", "abs_err_corregido", "mejora_abs_err"]
    cols_show = [c for c in cols_show if c in merged.columns]
    top_mejora = merged.sort_values("mejora_abs_err", ascending=False).head(15)
    print(top_mejora[cols_show].to_string(index=False))

    all_alertas.append(merged)


# ----------------------------------------------------------------------
# 4. RESUMEN GLOBAL
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("RESUMEN VALIDACION RETRO (W17-W19)")
print("=" * 100)
print(pd.DataFrame(all_validacion).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# Mejora consolidada
if all_alertas:
    all_alertas_df = pd.concat(all_alertas, ignore_index=True)
    real_total = all_alertas_df["real"].sum()
    mejora_total = all_alertas_df["mejora_abs_err"].sum()
    print(f"\n  Mejora total abs_err (W17-W19, solo SKUs alertados): {mejora_total:,.0f} unidades")
    print(f"  Real total alertados: {real_total:,.0f}")
    print(f"  Reduccion ae: {mejora_total/real_total*100:.1f}% sobre el real de SKUs alertados")

    # Exportar
    all_alertas_df.to_excel(OUT_XLSX, index=False, sheet_name="alertas")
    print(f"\n  Archivo exportado: {OUT_XLSX}")

print("\nDONE.")
