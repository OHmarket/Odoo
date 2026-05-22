"""
Detector v4 - refinado sobre v3 con 3 ajustes clave:

  1. NO alertar promos 2X salvo lift extremo (>=2.5 o <=0.3)
     Razon: 7,994 promos 2X con lift_neto 0.996 ~ neutro. Solo ruido.

  2. NO alertar SUBIDA + PROMO PROPIA (eliminar SUBIDA_CON_DEFENSA_*)
     Razon: el combo confunde al detector. Mejor dejar al motor que se ajuste.
     Excepcion: subida >=20% + promo W1 + lift >=1.5 (caso muy excepcional)

  3. Mantener intactas las reglas que SI funcionaron en v3:
     - SUBIDA_CON_PRESION (+520 mejora, n=59)
     - SUBIDA_CANIBAL_FUERTE (+259, n=24)
     - BAJADA_UNICA (+75, n=98)
     - BAJADA_DISCONTINUACION (+10, n=196)
     - PROMO_3X_W3, PROMO_4X_W2, PROMO_6X_W3 (marginales pero positivos)

Esperado: WAPE 72.43% -> ~70-71% (mejora 1.5-2.5pp)
"""
import pandas as pd
import numpy as np
import re

PATH_PRICE = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PATH_PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
PATH_BT    = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"
OUT_XLSX   = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\analisis backtest\2026-05-12\_detector_v4_output.xlsx"

PESO_ABC = {'A': 1.0, 'B': 0.2, 'C': 0.03}

# ----------------------------------------------------------------------
# CARGA (igual que v3)
# ----------------------------------------------------------------------
print("=" * 110)
print("DETECTOR v4 - 3 ajustes sobre v3 (eliminar ruido 2X y combos defensivos)")
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


def get_sub_cat(s):
    parts = str(s).split(' / ')
    return parts[2] if len(parts) >= 3 else parts[-1]


def get_abc(s):
    s = str(s)
    return s[0] if s else ''


def extract_mecanica(s):
    s = str(s).upper()
    m = re.search(r'(\d+)X', s)
    return f"{m.group(1)}X" if m else "OTRO"


sku_to_subcat = {}
sku_to_abc = {}
for _, row in dfb.iterrows():
    sku = row["product_id"]
    if sku not in sku_to_subcat:
        sku_to_subcat[sku] = get_sub_cat(row["categ_id"])
        sku_to_abc[sku] = get_abc(row.get("abcxyz", ""))

sku_count_by_subcat = pd.Series(list(sku_to_subcat.values())).value_counts().to_dict()
print(f"  SKUs: A={sum(1 for v in sku_to_abc.values() if v=='A')}, B={sum(1 for v in sku_to_abc.values() if v=='B')}, C={sum(1 for v in sku_to_abc.values() if v=='C')}")

dfm["mecanica"] = dfm["program_name"].apply(extract_mecanica)
dfm["abc"] = dfm["product_variant_id"].map(sku_to_abc)
dfm["sub_cat"] = dfm["categ_id"].apply(get_sub_cat)
dfp["abc"] = dfp["Producto"].map(sku_to_abc)
dfp["sub_cat"] = dfp["Categoria"].apply(get_sub_cat)


# ----------------------------------------------------------------------
# INDICE CANIBAL PONDERADO POR ABC
# ----------------------------------------------------------------------
def indice_canibal(target_week, sub_cat, direccion_propia, sku_propio=None, lookback=4):
    wk_lb = target_week - pd.Timedelta(weeks=lookback)
    if direccion_propia == 'Sube':
        cambios = dfp[(dfp["Fecha"] >= wk_lb) & (dfp["Fecha"] <= target_week) &
                       (dfp[direccion_col] == "Baja") & (dfp["sub_cat"] == sub_cat)]
        promos = dfm[(dfm["period_start"] >= wk_lb) & (dfm["period_start"] <= target_week) &
                      (dfm["sub_cat"] == sub_cat)]
        if sku_propio:
            cambios = cambios[cambios["Producto"] != sku_propio]
            promos = promos[promos["product_variant_id"] != sku_propio]
        score = (
            float(sum(PESO_ABC.get(x, 0.0) for x in cambios["abc"].fillna("").tolist())) +
            float(sum(PESO_ABC.get(x, 0.0) for x in promos["abc"].fillna("").tolist()))
        )
    elif direccion_propia == 'Baja':
        cambios = dfp[(dfp["Fecha"] >= wk_lb) & (dfp["Fecha"] <= target_week) &
                       (dfp[direccion_col] == "Sube") & (dfp["sub_cat"] == sub_cat)]
        if sku_propio:
            cambios = cambios[cambios["Producto"] != sku_propio]
        score = float(sum(PESO_ABC.get(x, 0.0) for x in cambios["abc"].fillna("").tolist()))
    else:
        return 0.0
    n_total = sku_count_by_subcat.get(sub_cat, 1)
    return score / max(1, n_total)


# ----------------------------------------------------------------------
# REGLAS v4
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


def detectar_alerta_v4(target_week, sku):
    sub_cat = sku_to_subcat.get(sku, "OTROS")
    abc = sku_to_abc.get(sku, "")
    wk_lb = target_week - pd.Timedelta(weeks=4)

    cambios = dfp[(dfp["Producto"] == sku) & (dfp["Fecha"] >= wk_lb) & (dfp["Fecha"] <= target_week)]
    cambio = cambios.sort_values("Fecha", ascending=False).head(1)
    has_cambio = len(cambio) > 0

    promos = dfm[(dfm["product_variant_id"] == sku) & (dfm["period_start"] >= wk_lb) & (dfm["period_start"] <= target_week)]
    promo = promos.sort_values("period_start", ascending=False).head(1)
    has_promo = len(promo) > 0

    if not has_cambio and not has_promo:
        return None

    # =========================================================
    # AJUSTE #2: SUBIDA + PROMO PROPIA -> NO ALERTAR (regla v4)
    # Excepcion: subida >=20% + promo W1 + lift >=1.5
    # =========================================================
    if has_cambio and has_promo:
        c = cambio.iloc[0]
        p = promo.iloc[0]
        if c.get(direccion_col, "") == "Sube":
            var_pct = c.get("Variacion %", 0.0)
            lift = p.get("lift_qty", 1.0)
            weeks_active = max(1, int((target_week - p["period_start"]).days // 7) + 1)
            # Excepcion estrecha
            if var_pct >= 0.20 and weeks_active == 1 and lift >= 1.5:
                factor = min(1.8, 1.0 + (lift - 1.0) * 0.6)
                return {
                    "tipo": "SUBIDA_FUERTE_CON_PROMO_W1_EXCEPCIONAL",
                    "factor_corr": round(factor, 3),
                    "razon": f"Sube {var_pct*100:+.0f}% + promo {p.get('mecanica','OTRO')} W1 lift {lift:.2f}",
                    "fuente": "MIXTO", "indice_canibal": 0.0,
                }
            else:
                return None  # NO alertar combos defensivos

    # Bajada >30% -> liquidacion
    if has_cambio:
        c = cambio.iloc[0]
        if c.get(direccion_col, "") == "Baja" and c.get("Variacion %", 0.0) <= -0.30:
            return {
                "tipo": "BAJADA_DISCONTINUACION", "factor_corr": 1.0,
                "razon": f"Baja {c['Variacion %']*100:+.0f}% (liquidacion)",
                "fuente": "PRICE_CHANGE", "indice_canibal": 0.0,
            }

    # =========================================================
    # CASO: SOLO PROMO (sin cambio precio)
    # AJUSTE #1: NO alertar 2X salvo lift extremo
    # =========================================================
    if has_promo and not has_cambio:
        p = promo.iloc[0]
        lift = p.get("lift_qty", 1.0)
        weeks_active = max(1, int((target_week - p["period_start"]).days // 7) + 1)
        mecanica = p.get("mecanica", "OTRO")

        if pd.isna(lift) or lift <= 0:
            return None

        # AJUSTE #1: 2X solo si extremo
        if mecanica == "2X":
            if lift >= 2.5:
                factor = min(2.0, lift * 0.7)
                return {
                    "tipo": "PROMO_2X_LIFT_EXTREMO",
                    "factor_corr": round(factor, 3),
                    "razon": f"2X lift extremo {lift:.2f}",
                    "fuente": "PROMO_PURA", "indice_canibal": 0.0,
                }
            elif lift <= 0.3:
                factor = max(0.5, lift)
                return {
                    "tipo": "PROMO_2X_DESPLOME",
                    "factor_corr": round(factor, 3),
                    "razon": f"2X desplome {lift:.2f}",
                    "fuente": "PROMO_PURA", "indice_canibal": 0.0,
                }
            else:
                return None  # ruido neutro

        # Para 12X/6X/4X/3X: alertar segun weeks_active y lift
        # SOLO si la mecanica genera efectos materiales (segun datos):
        if mecanica in ("12X", "6X", "4X", "3X"):
            if weeks_active <= 1 and lift >= 1.5:
                factor = min(2.0, 1.0 + (lift - 1.0) * 0.7)
                tipo = f"DISPARO_{mecanica}_W1"
            elif 2 <= weeks_active <= 4 and lift <= 0.5:
                factor = max(0.3, lift)
                tipo = f"SATURACION_{mecanica}_W{weeks_active}"
            elif weeks_active >= 3 and 0.5 < lift < 0.8:
                # Saturacion media en semana tardia
                factor = max(0.6, lift)
                tipo = f"SATURACION_{mecanica}_W{weeks_active}"
            else:
                return None  # no claro
            return {
                "tipo": tipo, "factor_corr": round(factor, 3),
                "razon": f"{mecanica} W{weeks_active} lift {lift:.2f}",
                "fuente": "PROMO_PURA", "indice_canibal": 0.0,
            }
        return None

    # =========================================================
    # CASO: SOLO CAMBIO PRECIO (sin promo)
    # =========================================================
    if has_cambio and not has_promo:
        c = cambio.iloc[0]
        var_pct = c.get("Variacion %", 0.0)
        direccion = c.get(direccion_col, "")
        weeks_since = max(0, (target_week - c["Fecha"]).days // 7)
        decay = max(0.0, 1.0 - weeks_since / 8.0)

        if abs(var_pct) < 0.05:
            return None

        if direccion == "Sube":
            factor_b = factor_base_subida(var_pct)
            idx = indice_canibal(target_week, sub_cat, "Sube", sku)
            # Magnitud modula el piso
            if var_pct >= 0.20:
                piso = 0.40
            elif var_pct >= 0.10:
                piso = 0.55
            else:
                piso = 0.75
            if idx >= 0.50:
                tipo = "SUBIDA_CANIBAL_FUERTE"
                factor = factor_b * max(piso, 1.0 - idx * 0.6)
            elif idx >= 0.25:
                tipo = "SUBIDA_CANIBAL_MODERADO"
                factor = factor_b * max(piso + 0.10, 1.0 - idx * 0.4)
            elif idx >= 0.10:
                tipo = "SUBIDA_CON_PRESION"
                factor = factor_b * (1.0 - idx * 0.2)
            else:
                tipo = "SUBIDA_UNICA"
                factor = factor_b
            factor = 1.0 - (1.0 - factor) * decay
            return {
                "tipo": tipo, "factor_corr": round(factor, 3),
                "razon": f"Sube {var_pct*100:+.0f}% + canibal {idx:.2f}",
                "fuente": "PRICE_CHANGE", "indice_canibal": round(idx, 3),
            }

        if direccion == "Baja":
            factor_b = factor_base_bajada(var_pct)
            idx = indice_canibal(target_week, sub_cat, "Baja", sku)
            if idx >= 0.50:
                tipo = "BAJADA_GANADORA_FUERTE"
                factor = factor_b * (1.0 + idx * 0.6)
            elif idx >= 0.25:
                tipo = "BAJADA_GANADORA_MODERADA"
                factor = factor_b * (1.0 + idx * 0.4)
            elif idx >= 0.10:
                tipo = "BAJADA_CON_PRESION"
                factor = factor_b * (1.0 + idx * 0.2)
            else:
                tipo = "BAJADA_UNICA"
                factor = factor_b
            factor = 1.0 + (factor - 1.0) * decay
            return {
                "tipo": tipo, "factor_corr": round(factor, 3),
                "razon": f"Baja {var_pct*100:+.0f}% + canibal {idx:.2f}",
                "fuente": "PRICE_CHANGE", "indice_canibal": round(idx, 3),
            }

    return None


# ----------------------------------------------------------------------
# APLICAR Y VALIDAR
# ----------------------------------------------------------------------
all_alertas = []
for week_target in weeks_bt:
    print("\n" + "=" * 110)
    print(f"SEMANA: {str(week_target)[:10]}")
    print("=" * 110)
    wk_lb = week_target - pd.Timedelta(weeks=4)
    skus = set()
    skus.update(dfp[(dfp["Fecha"] >= wk_lb) & (dfp["Fecha"] <= week_target)]["Producto"].tolist())
    skus.update(dfm[(dfm["period_start"] >= wk_lb) & (dfm["period_start"] <= week_target)]["product_variant_id"].tolist())

    alertas = []
    for sku in skus:
        r = detectar_alerta_v4(week_target, sku)
        if r:
            r["product_id"] = sku
            r["sub_cat"] = sku_to_subcat.get(sku, "OTROS")
            r["abc"] = sku_to_abc.get(sku, "")
            r["target_week"] = week_target
            alertas.append(r)
    df_a = pd.DataFrame(alertas)
    print(f"  Alertas v4 (selectivas): {len(df_a):,}")
    if len(df_a) == 0:
        continue
    print(df_a["tipo"].value_counts().to_string())

    bt_w = dfb[dfb["target_week_start"] == week_target]
    bt_a = bt_w.groupby("product_id", as_index=False).agg(
        real=("real_qty", "sum"), forecast_v3_24=("forecast_qty", "sum")
    )
    m = df_a.merge(bt_a, on="product_id", how="left").dropna(subset=["real", "forecast_v3_24"])
    m["forecast_corregido"] = (m["forecast_v3_24"] * m["factor_corr"]).round(0)
    m["ae_orig"] = (m["forecast_v3_24"] - m["real"]).abs()
    m["ae_corr"] = (m["forecast_corregido"] - m["real"]).abs()
    m["mejora"] = m["ae_orig"] - m["ae_corr"]
    real_s = m["real"].sum()
    if real_s > 0:
        wo = m["ae_orig"].sum() / real_s * 100
        wc = m["ae_corr"].sum() / real_s * 100
        bo = (m["forecast_v3_24"] - m["real"]).sum() / real_s * 100
        bc = (m["forecast_corregido"] - m["real"]).sum() / real_s * 100
        print(f"\n  Sobre {len(m):,} SKUs alertados:")
        print(f"    Real: {real_s:>9,.0f}  fcst_orig: {m['forecast_v3_24'].sum():>9,.0f} (WAPE {wo:.2f}% BIAS {bo:+.2f}%)")
        print(f"                                    fcst_corr: {m['forecast_corregido'].sum():>9,.0f} (WAPE {wc:.2f}% BIAS {bc:+.2f}%)")
        print(f"    Mejora: {m['mejora'].sum():+,.0f} ({m['mejora'].sum()/m['ae_orig'].sum()*100:+.1f}%)")
    all_alertas.append(m)


# ----------------------------------------------------------------------
# RESUMEN CONSOLIDADO
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("RESUMEN POR TIPO (3 semanas consolidado)")
print("=" * 110)
da = pd.concat(all_alertas, ignore_index=True)
rows = []
for tipo in da["tipo"].unique():
    sub = da[da["tipo"] == tipo]
    real = sub["real"].sum()
    ao = sub["ae_orig"].sum()
    ac = sub["ae_corr"].sum()
    mej = ao - ac
    rows.append({
        "tipo": tipo, "n": len(sub), "real": real,
        "ae_orig": ao, "ae_corr": ac, "mejora": mej,
        "pct_mejora": mej/ao*100 if ao > 0 else 0,
    })
df_r = pd.DataFrame(rows).sort_values("mejora", ascending=False)
print(df_r.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))


# ----------------------------------------------------------------------
# IMPACTO GLOBAL
# ----------------------------------------------------------------------
print("\n" + "=" * 110)
print("IMPACTO GLOBAL HM-SI")
print("=" * 110)
real_tot = da["real"].sum()
ao_tot = da["ae_orig"].sum()
ac_tot = da["ae_corr"].sum()
mej_tot = ao_tot - ac_tot
print(f"\n  SKUs alertados: {len(da):,}")
print(f"  Real alertados: {real_tot:,.0f}")
print(f"  abs_err orig:   {ao_tot:,.0f}  WAPE alertados {ao_tot/real_tot*100:.2f}%")
print(f"  abs_err corr:   {ac_tot:,.0f}  WAPE alertados {ac_tot/real_tot*100:.2f}%")
print(f"  Mejora total:   {mej_tot:+,.0f} unidades ({mej_tot/ao_tot*100:+.1f}%)")

# Aplicar selectivo (solo tipos con mejora>0)
tipos_buenos = df_r[df_r["mejora"] > 0]["tipo"].tolist()
da["aplicar"] = da["tipo"].isin(tipos_buenos)
da["fcst_final"] = np.where(da["aplicar"], da["forecast_corregido"], da["forecast_v3_24"])
da["ae_final"] = (da["fcst_final"] - da["real"]).abs()
mej_neto_sel = (da["ae_orig"] - da["ae_final"]).sum()
print(f"\n  CON FILTRO SELECTIVO (solo tipos con mejora positiva):")
print(f"  Tipos: {tipos_buenos}")
print(f"  Mejora neta selectiva: {mej_neto_sel:+,.0f} unidades")

# Estimar WAPE global
TOTAL_REAL_HM = 108714
WAPE_BASE = 72.43
ae_base = TOTAL_REAL_HM * WAPE_BASE / 100
ae_nuevo_tot = ae_base - mej_tot
ae_nuevo_sel = ae_base - mej_neto_sel
print(f"\n  WAPE base hm_si:          {WAPE_BASE:.2f}%")
print(f"  WAPE con v4 (todas):      {ae_nuevo_tot / TOTAL_REAL_HM * 100:.2f}%  (mejora {WAPE_BASE - ae_nuevo_tot/TOTAL_REAL_HM*100:+.2f}pp)")
print(f"  WAPE con v4 (selectivo):  {ae_nuevo_sel / TOTAL_REAL_HM * 100:.2f}%  (mejora {WAPE_BASE - ae_nuevo_sel/TOTAL_REAL_HM*100:+.2f}pp)")

da.to_excel(OUT_XLSX, index=False)
print(f"\n  Archivo: {OUT_XLSX}")
print("\nDONE.")
