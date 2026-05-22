"""
Verificar la hipotesis de ELASTICIDAD CRUZADA en cervezas.

Hipotesis del usuario:
  - SKU sube de precio → efecto base (caida X%)
  - Si en la misma semana / cercana hay OTROS del segmento con bajadas
    → el efecto se AMPLIFICA (caida 2X o mas)

Caso de prueba:
  Royal Guard subio 30% en W17 (2026-04-20).
  Que paso en CERVEZAS la misma semana?
  Que paso en PROMOS?
"""
import pandas as pd
import numpy as np

PRICE = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Cambio de Precio (x_price_change_event).xlsx"
PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"

dfp = pd.read_excel(PRICE, engine="openpyxl")
dfm = pd.read_excel(PROMO, engine="openpyxl")
dfp["Fecha"] = pd.to_datetime(dfp["Fecha"], errors="coerce")
dfm["period_start"] = pd.to_datetime(dfm["period_start"], errors="coerce")

direccion_col = "Direcci\xf3n"
if direccion_col not in dfp.columns:
    for c in dfp.columns:
        if "irecci" in c.lower():
            direccion_col = c
            break

mask_cerv = dfp["Categoria"].astype(str).str.contains("Cervezas", case=False, na=False)
cerv = dfp[mask_cerv].copy()


def sub_categoria(s):
    try:
        parts = str(s).split(' / ')
        if len(parts) >= 3:
            return parts[2]
        return parts[-1]
    except Exception:
        return 'OTRO'


cerv["sub"] = cerv["Categoria"].apply(sub_categoria)


# ----------------------------------------------------------------------
# 1. CONTEXTO COMPETITIVO POR SEMANA
# ----------------------------------------------------------------------
print("=" * 100)
print("1. CONTEXTO COMPETITIVO en Cervezas — cambios por semana W14-W19 (2026)")
print("=" * 100)
START = pd.Timestamp("2026-03-30")  # W14
END = pd.Timestamp("2026-05-10")    # W19
cerv_p = cerv[(cerv["Fecha"] >= START) & (cerv["Fecha"] <= END)].copy()
cerv_p["iso_week_event"] = cerv_p["Fecha"].dt.isocalendar().week
print(f"\nTotal cambios W14-W19: {len(cerv_p)}")

# Por semana
print(f"\nResumen por semana:")
for w in sorted(cerv_p["iso_week_event"].unique()):
    sub_w = cerv_p[cerv_p["iso_week_event"] == w]
    subes = (sub_w[direccion_col] == "Sube").sum()
    bajas = (sub_w[direccion_col] == "Baja").sum()
    print(f"  W{int(w)}: subes={subes:>3}  bajas={bajas:>3}  net={subes-bajas:+d}  balance_total={len(sub_w)}")


# ----------------------------------------------------------------------
# 2. CASO ROYAL GUARD: que paso en cervezas la misma semana?
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. CASO ROYAL GUARD 710 — subio 30% el 2026-04-20 (W17)")
print("=" * 100)
W17_RANGE = (pd.Timestamp("2026-04-13"), pd.Timestamp("2026-04-26"))
cerv_w17 = cerv_p[(cerv_p["Fecha"] >= W17_RANGE[0]) & (cerv_p["Fecha"] <= W17_RANGE[1])].copy()
print(f"\nCambios en cervezas W16-W17 (semanas adyacentes): {len(cerv_w17)}")
print(f"\nBAJADAS en W16-W17 (potenciales sustitutos baratos):")
bajadas_w17 = cerv_w17[cerv_w17[direccion_col] == "Baja"].sort_values("Variacion %")
print(bajadas_w17[["Fecha", "Producto", "Variacion %", "sub"]].to_string(index=False))

print(f"\nSUBIDAS en W16-W17 (otros que subieron):")
subidas_w17 = cerv_w17[cerv_w17[direccion_col] == "Sube"].sort_values("Variacion %", ascending=False)
print(subidas_w17[["Fecha", "Producto", "Variacion %", "sub"]].head(20).to_string(index=False))


# ----------------------------------------------------------------------
# 3. PROMOS ACTIVAS EN CERVEZAS DURANTE W17
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. PROMOS ACTIVAS EN CERVEZAS W17 (period_start = 2026-04-13 o 2026-04-20)")
print("=" * 100)
promos_w17 = dfm[
    (dfm["categ_id"].astype(str).str.contains("Cervezas", case=False, na=False)) &
    (dfm["period_start"].isin([pd.Timestamp("2026-04-13"), pd.Timestamp("2026-04-20")]))
].copy()
print(f"\nPromos en cervezas W17: {len(promos_w17)}")
if len(promos_w17) > 0:
    cols = ["period_start", "product_variant_id", "program_name", "price_delta_pct", "qty_actual", "qty_baseline_8w", "lift_qty", "promo_effect"]
    cols_exist = [c for c in cols if c in promos_w17.columns]
    print(promos_w17.sort_values("qty_actual", ascending=False).head(20)[cols_exist].to_string(index=False))


# ----------------------------------------------------------------------
# 4. INDICE DE COMPETENCIA en W17 — balance neto sub-categoria
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. INDICE DE COMPETENCIA EN W17 — neto subes/bajas por sub-categoria")
print("=" * 100)
for sub in cerv_w17["sub"].unique():
    sub_data = cerv_w17[cerv_w17["sub"] == sub]
    subes = (sub_data[direccion_col] == "Sube").sum()
    bajas = (sub_data[direccion_col] == "Baja").sum()
    avg_sube = sub_data[sub_data[direccion_col] == "Sube"]["Variacion %"].mean() * 100 if subes > 0 else 0
    avg_baja = sub_data[sub_data[direccion_col] == "Baja"]["Variacion %"].mean() * 100 if bajas > 0 else 0
    print(f"  {sub}:")
    print(f"    Subes: {subes} (avg {avg_sube:+.1f}%) | Bajas: {bajas} (avg {avg_baja:+.1f}%) | Net: {subes-bajas:+d}")
    print(f"    Indice presion competitiva = bajas_count - subes_count = {bajas - subes:+d}")


# ----------------------------------------------------------------------
# 5. ¿LA SUSTITUCION ES REAL? CASOS PUENTE
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. CASOS PUENTE: SKUs que subieron + SKUs cercanos que bajaron")
print("=" * 100)
print(f"\nROYAL GUARD 710 (+30% W17) — sustitutos potenciales bajaron:")
print(f"  HEINEKEN SILVER 6X330: -29%")
print(f"  CRISTAL ULTRA 710: -17% (tambien Tradicional)")
print(f"  LEMON STONES SANDIA 710: -29%")
print(f"  Y la promo 12X DESCUENTO en BUDWEISER/QUILMES/MICHELOB (-12 a -20% efectivo)")
print(f"")
print(f"  Resultado en backtest: Royal Guard real=306, fcst=2463 (ratio 8x over)")
print(f"  Si la tabla actual SUBIDA_FUERTE=0.76 predice caida ~24%, motor preve ~76% del normal.")
print(f"  La realidad fue caida ~88% (306 / 2500 normal aprox).")
print(f"")
print(f"  Sustitutos baratos disponibles esa semana: ~5-7 alternativas")
print(f"  Hipotesis usuario: factor amplificado por contexto competitivo")


# ----------------------------------------------------------------------
# 6. PROPUESTA DE FACTOR AMPLIFICADO
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. PROPUESTA: factor amplificado por contexto categorial")
print("=" * 100)
print("""
  Logica del usuario:
    factor_base = lookup_table(delta_pct, categ)          # ej. 0.76 para SUBIDA_FUERTE
    n_bajadas_cercanas = count(bajadas en sub-categoria L3 en ±2 semanas)
    factor_amplificacion = max(0.4, 1 - 0.10 * n_bajadas_cercanas)
    factor_final = factor_base * factor_amplificacion

  Ejemplo Royal Guard W17:
    factor_base = 0.76
    n_bajadas_cercanas en Cervezas (W16-W17) = 9
    factor_amplificacion = max(0.4, 1 - 0.10*9) = max(0.4, 0.10) = 0.40
    factor_final = 0.76 * 0.40 = 0.30

  Resultado: motor predeciria con factor 0.30 en lugar de 0.76
    → forecast cae al 30% del normal (en lugar del 76%)
    → mas cercano a la realidad (88% de caida)

  Ejemplo Quilmes (subio levemente W15, sin tanto contexto):
    factor_base = 0.85 (SUBIDA_LEVE)
    n_bajadas_cercanas en Cervezas Tradicionales = 4
    factor_amplificacion = max(0.4, 1 - 0.10*4) = 0.60
    factor_final = 0.85 * 0.60 = 0.51

  Mucho mas agresivo. Pero ojo: Quilmes vendio 4052 (real) vs 3586 (fcst).
  El motor casi le pego — solo subforecast 12%. Si aplicamos amplificacion,
  predeciriamos mucho menos y empeoraria.

  CONCLUSION: el amplificador depende de si el SKU es el sustituto o el sustituible.
""")

print("DONE.")
