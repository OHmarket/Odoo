"""
Medir si la importancia ABC del SKU en promo cambia el efecto canibal.

Hipotesis del usuario:
  - Promo en A-class: gran canibalizador (sustituto real para SKUs caros)
  - Promo en B-class: canibalizador moderado
  - Promo en C-class: ruido, no es sustituto real

Test:
  1. Cruzar promos con backtest para obtener letra ABC del SKU en promo
  2. Comparar lift_qty promedio por letra ABC
  3. Ver si la distribucion de promos por ABC es asimetrica
"""
import pandas as pd
import numpy as np

PATH_PROMO = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Loyalty Event (x_loyalty_promo_event).xlsx"
PATH_BT    = r"c:\Users\sanhu\Mi unidad\Proyectos\Desarrollo\Odoo Produccion\OH Forecast Backtest (x_forecast_backtest) (10).xlsx"

dfm = pd.read_excel(PATH_PROMO, engine="openpyxl")
dfb = pd.read_excel(PATH_BT, engine="openpyxl")
dfm["period_start"] = pd.to_datetime(dfm["period_start"], errors="coerce")
dfb["target_week_start"] = pd.to_datetime(dfb["target_week_start"], errors="coerce")

# Cargar SKU -> ABC desde backtest (ultimas 3 semanas, hm_si)
weeks_bt = sorted(dfb["target_week_start"].dropna().unique())[-3:]
dfb = dfb[(dfb["method"] == "hm_si") & (dfb["target_week_start"].isin(weeks_bt))].copy()
sku_to_abc = {}
sku_to_abcxyz = {}
for _, row in dfb.iterrows():
    sku = row["product_id"]
    abc_full = str(row.get("abcxyz", ""))
    if sku not in sku_to_abc and len(abc_full) >= 1:
        sku_to_abc[sku] = abc_full[0]  # primera letra
        sku_to_abcxyz[sku] = abc_full

print("=" * 100)
print("ANALISIS PROMOS POR LETRA ABC")
print("=" * 100)
print(f"\nTotal promos en archivo: {len(dfm):,}")
print(f"SKUs en backtest con ABC: {len(sku_to_abc):,}")

# Cruzar promos con ABC
dfm["abc"] = dfm["product_variant_id"].map(sku_to_abc)
dfm["abcxyz"] = dfm["product_variant_id"].map(sku_to_abcxyz)
print(f"\nPromos con ABC matcheado: {dfm['abc'].notna().sum():,} ({dfm['abc'].notna().sum()/len(dfm)*100:.1f}%)")
print(f"Promos sin match ABC: {dfm['abc'].isna().sum():,}")


# ----------------------------------------------------------------------
# 1. Distribucion de promos por letra ABC
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("1. DISTRIBUCION DE PROMOS POR LETRA ABC")
print("=" * 100)
abc_dist = dfm[dfm["abc"].notna()]["abc"].value_counts()
print(f"\n{'abc':<5} {'n_promos':>10} {'%':>8}")
for letra in ['A', 'B', 'C']:
    n = abc_dist.get(letra, 0)
    print(f"{letra:<5} {n:>10,} {n/len(dfm[dfm['abc'].notna()])*100:>7.1f}%")


# ----------------------------------------------------------------------
# 2. LIFT_QTY promedio y distribucion por letra ABC
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("2. LIFT_QTY (efecto medido de la promo) POR LETRA ABC")
print("=" * 100)
print("lift_qty = qty_actual / qty_baseline_8w (en la semana de la promo)")
print(f"\n{'abc':<5} {'n':>8} {'mean':>8} {'median':>8} {'p25':>8} {'p75':>8} {'p90':>8} {'lift>=1.5':>11} {'lift<0.7':>10}")
for letra in ['A', 'B', 'C']:
    sub = dfm[(dfm["abc"] == letra) & (dfm["lift_qty"].notna())]
    if len(sub) == 0:
        continue
    lift = sub["lift_qty"]
    n_alto = (lift >= 1.5).sum()
    n_bajo = (lift < 0.7).sum()
    print(f"{letra:<5} {len(sub):>8,} {lift.mean():>8.2f} {lift.median():>8.2f} "
          f"{lift.quantile(0.25):>8.2f} {lift.quantile(0.75):>8.2f} {lift.quantile(0.90):>8.2f} "
          f"{n_alto:>11,} {n_bajo:>10,}")


# ----------------------------------------------------------------------
# 3. PROMO_EFFECT por letra ABC (clasificacion del modelo: MEJORA/NEUTRO/PEOR)
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("3. PROMO_EFFECT (modelo clasifica si la promo movio venta) POR LETRA ABC")
print("=" * 100)
if "promo_effect" in dfm.columns:
    ct = pd.crosstab(dfm["abc"].fillna("(NA)"), dfm["promo_effect"].fillna("(NA)"), margins=True)
    print(ct.to_string())


# ----------------------------------------------------------------------
# 4. VOLUMEN ABSOLUTO movido por promos por letra ABC
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("4. VOLUMEN movido por promos POR LETRA ABC (qty_actual sumada)")
print("=" * 100)
for letra in ['A', 'B', 'C']:
    sub = dfm[dfm["abc"] == letra]
    if len(sub) == 0:
        continue
    qty_total = sub["qty_actual"].sum()
    qty_baseline = sub["qty_baseline_8w"].sum()
    lift_neto = qty_total / qty_baseline if qty_baseline > 0 else 0
    print(f"  {letra}: qty_actual={qty_total:>10,.0f}  qty_baseline={qty_baseline:>10,.0f}  lift_neto={lift_neto:.2f}")


# ----------------------------------------------------------------------
# 5. Foco en periodo backtest W17-W19 — promos activas por letra ABC
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("5. PROMOS EN PERIODO BACKTEST W17-W19 (2026-04-13 a 2026-05-10) — efecto por ABC")
print("=" * 100)
W17_W19 = (pd.Timestamp("2026-04-13"), pd.Timestamp("2026-05-10"))
dfm_bt = dfm[(dfm["period_start"] >= W17_W19[0]) & (dfm["period_start"] <= W17_W19[1])].copy()
print(f"\nTotal promos W17-W19: {len(dfm_bt):,}")

print(f"\n{'abc':<5} {'n':>6} {'qty_act_total':>14} {'baseline_total':>15} {'lift_neto':>10} {'%_promos':>10}")
total_w17_w19 = len(dfm_bt)
for letra in ['A', 'B', 'C']:
    sub = dfm_bt[dfm_bt["abc"] == letra]
    if len(sub) == 0:
        continue
    qty_total = sub["qty_actual"].sum()
    qty_baseline = sub["qty_baseline_8w"].sum()
    lift_neto = qty_total / qty_baseline if qty_baseline > 0 else 0
    print(f"{letra:<5} {len(sub):>6,} {qty_total:>14,.0f} {qty_baseline:>15,.0f} {lift_neto:>10.2f} {len(sub)/total_w17_w19*100:>9.1f}%")


# ----------------------------------------------------------------------
# 6. CATEGORIA CERVEZAS — promos por ABC en W17-W19
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("6. CERVEZAS — promos por ABC en W17-W19 (la categoria critica)")
print("=" * 100)
mask_cerv = dfm_bt["categ_id"].astype(str).str.contains("Cervezas", case=False, na=False)
cerv_bt = dfm_bt[mask_cerv].copy()
print(f"\nTotal promos cervezas en W17-W19: {len(cerv_bt):,}")
for letra in ['A', 'B', 'C']:
    sub = cerv_bt[cerv_bt["abc"] == letra]
    if len(sub) == 0:
        continue
    lift_promedio = sub["lift_qty"].mean()
    lift_alto = (sub["lift_qty"] >= 1.5).sum()
    qty_actual = sub["qty_actual"].sum()
    baseline = sub["qty_baseline_8w"].sum()
    print(f"  {letra}: n={len(sub):>3}  lift_avg={lift_promedio:.2f}  n_lift>=1.5: {lift_alto}  qty={qty_actual:,.0f}  baseline={baseline:,.0f}  lift_neto={qty_actual/baseline:.2f}")


# ----------------------------------------------------------------------
# 7. CONCLUSION OPERATIVA
# ----------------------------------------------------------------------
print("\n" + "=" * 100)
print("7. CONCLUSION — ¿el peso ABC del SKU en promo cambia el efecto canibal?")
print("=" * 100)
print("""
  Si los datos muestran:
    - Promos A: lift alto Y volumen significativo → SI son canibalizadores reales
    - Promos B: lift moderado, volumen menor → canibalizadores parciales
    - Promos C: lift bajo o ruido, volumen marginal → NO canibalizan a nadie

  Implicacion para el detector:
    INDICE_CANIBAL deberia PONDERAR los SKUs en promo por su peso ABC:
    indice_canibal_v3 = (peso_A * n_promos_A + peso_B * n_promos_B + peso_C * n_promos_C) / total
    donde peso_A=1.0, peso_B=0.4, peso_C=0.1 (calibrado con datos)
""")
print("DONE.")
