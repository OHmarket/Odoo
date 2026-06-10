"""
Paso 2c.2 — Lift relativo por rank ABCXYZ en semanas-evento.

Tesis a comprobar: en los eventos, dentro de cada categoria, los ranks de alta
rotacion (AX, BX) suben MAS que la categoria, y las colas (CZ) suben MENOS.

Metodo (ratio-of-ratios, robusto a cierre de salas porque afecta a todos los
ranks por igual):

    uplift_celda(e)  = qty_celda(semana_evento) / baseline_celda
    lift_relativo(e) = uplift_celda(e) / uplift_categ(e)

baseline = mediana de semanas limpias (sin evento) en +/-6 semanas.
Semana-evento por arquetipo del diseno: feriado -> semana de la VISPERA;
comercial (Halloween, San Valentin) -> semana del DIA.

PROXY documentados:
- Clasificacion ABCXYZ ACTUAL aplicada retroactivamente (no hay historia).
- Quiebre: se marca la celda si algun SKU tuvo stockout en la semana-evento
  (x_stock_balance_daily, cobertura desde abr-2025; antes queda
  quiebre_desconocido). El quiebre censura la venta de los A en el peak ->
  sesgo CONSERVADOR contra la tesis (si confirma igual, confirma de sobra).

Requiere: resultados/rank_week_sku_cache.parquet (lo genera rank_sparsity.py).
Read-only. Salida: resultados/rank_lift_eventos*.csv + reporte.
"""
from __future__ import annotations
import sys
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

RANK_ORDER = ["AX","AY","AZ","BX","BY","BZ","CX","CY","CZ","SIN"]
BL_HALF_WINDOW = 6        # semanas a cada lado para baseline
BL_MIN_WEEKS = 4          # minimo de semanas limpias para baseline
BL_MIN_QTY = 10.0         # mediana baseline minima (unidades/sem) para ratio estable
SB_COVER_FROM = dt.date(2025, 4, 1)   # cobertura de x_stock_balance_daily
N_BOOT = 2000
RNG = np.random.default_rng(7)

OUT = Path(__file__).parent / "resultados"

# ----------------------------------------------------------------------
# 1. Eventos dentro de la ventana del fact. Arquetipo A=feriado (vispera),
#    B=comercial (el dia). 18+19 sep = UN bloque (Fiestas Patrias).
# ----------------------------------------------------------------------
EVENTS = [
    # (nombre, arquetipo, fecha)
    ("Ano Nuevo",        "A", dt.date(2025, 1, 1)),
    ("San Valentin",     "B", dt.date(2025, 2, 14)),
    ("Viernes Santo",    "A", dt.date(2025, 4, 18)),
    ("Dia del Trabajo",  "A", dt.date(2025, 5, 1)),
    ("Dia de la Madre",  "B", dt.date(2025, 5, 11)),
    ("Glorias Navales",  "A", dt.date(2025, 5, 21)),
    ("Dia del Padre",    "B", dt.date(2025, 6, 15)),
    ("Virgen del Carmen","A", dt.date(2025, 7, 16)),
    ("Asuncion",         "A", dt.date(2025, 8, 15)),
    ("Fiestas Patrias",  "A", dt.date(2025, 9, 18)),
    ("Halloween",        "B", dt.date(2025, 10, 31)),
    ("Todos los Santos", "A", dt.date(2025, 11, 1)),
    ("Inmaculada",       "A", dt.date(2025, 12, 8)),
    ("Navidad",          "A", dt.date(2025, 12, 25)),
    ("Ano Nuevo",        "A", dt.date(2026, 1, 1)),
    ("San Valentin",     "B", dt.date(2026, 2, 14)),
    ("Viernes Santo",    "A", dt.date(2026, 4, 3)),
    ("Dia del Trabajo",  "A", dt.date(2026, 5, 1)),
    ("Dia de la Madre",  "B", dt.date(2026, 5, 10)),
]

def wk_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())

def event_week(arq: str, fecha: dt.date) -> dt.date:
    target = fecha - dt.timedelta(days=1) if arq == "A" else fecha
    return wk_start(target)

# todas las semanas tocadas por algun evento (dia Y vispera) -> excluir de baseline
dirty_weeks = set()
for _, _, f in EVENTS:
    dirty_weeks.add(wk_start(f))
    dirty_weeks.add(wk_start(f - dt.timedelta(days=1)))

# ----------------------------------------------------------------------
# 2. Cache semanal SKU (pooled salas) + serie por celda categ x rank
# ----------------------------------------------------------------------
df = pd.read_parquet(OUT / "rank_week_sku_cache.parquet")
df["week"] = pd.to_datetime(df["week"]).dt.date
weeks_have = set(df["week"].unique())
print(f"cache: {len(df):,} filas | semanas {min(weeks_have)} -> {max(weeks_have)}")

cell_w = (df.groupby(["categoria","rank","week"], as_index=False)["qty"].sum())
cat_w = (df.groupby(["categoria","week"], as_index=False)["qty"].sum())

# censo de celdas OK (umbral del paso 2c.1)
census = pd.read_csv(OUT / "rank_sparsity_categ_rank.csv", sep=";", decimal=",",
                     encoding="utf-8-sig")
ok_cells = set(map(tuple, census.loc[census["ok"], ["categoria","rank"]].values))
print(f"celdas categ x rank que pasan umbral de muestra: {len(ok_cells)}")

# ----------------------------------------------------------------------
# 3. Quiebre en semana-evento por SKU (pooled: algun stockout en alguna sala)
# ----------------------------------------------------------------------
o = OdooReader()
quiebre_sku_week: dict[dt.date, set] = {}
for ew in sorted({event_week(a, f) for _, a, f in EVENTS}):
    if ew < SB_COVER_FROM or ew not in weeks_have:
        continue
    g = o.execute(
        "x_stock_balance_daily", "read_group",
        ["&", "&",
         ("x_studio_date", ">=", ew.isoformat()),
         ("x_studio_date", "<", (ew + dt.timedelta(days=7)).isoformat()),
         "|", "|",
         ("x_studio_stockout", "=", True),
         ("x_studio_stockout_partial", "=", True),
         ("x_studio_qty_balance", "<=", 0.0)],
        ["id:count"], ["x_studio_product_id"], lazy=False,
    )
    quiebre_sku_week[ew] = {r["x_studio_product_id"][0] for r in g
                            if r.get("x_studio_product_id")}
print(f"semanas-evento con data de quiebre: {len(quiebre_sku_week)}")

# qty por celda y semana-evento separada en SKUs con/sin quiebre
sku_cell = df.groupby(["product_id"]).agg(categoria=("categoria","first"),
                                          rank=("rank","first"))

# ----------------------------------------------------------------------
# 4. Uplift por celda y lift relativo
# ----------------------------------------------------------------------
def baseline_median(series: pd.Series, ew: dt.date) -> tuple[float, int]:
    """Mediana de semanas limpias en +/-BL_HALF_WINDOW alrededor de ew."""
    lo = ew - dt.timedelta(weeks=BL_HALF_WINDOW)
    hi = ew + dt.timedelta(weeks=BL_HALF_WINDOW)
    vals = [v for w, v in series.items()
            if lo <= w <= hi and w != ew and w not in dirty_weeks]
    return (float(np.median(vals)), len(vals)) if len(vals) >= BL_MIN_WEEKS else (np.nan, len(vals))

cell_series = {k: g.set_index("week")["qty"] for k, g in cell_w.groupby(["categoria","rank"])}
cat_series = {k: g.set_index("week")["qty"] for k, g in cat_w.groupby("categoria")}

recs = []
for name, arq, fecha in EVENTS:
    ew = event_week(arq, fecha)
    if ew not in weeks_have:
        continue
    for cat, s_cat in cat_series.items():
        bl_cat, _ = baseline_median(s_cat, ew)
        q_cat = float(s_cat.get(ew, 0.0))
        if not (bl_cat and bl_cat > 0 and q_cat > 0):
            continue
        up_cat = q_cat / bl_cat
        qset = quiebre_sku_week.get(ew)
        for rank in RANK_ORDER:
            key = (cat, rank)
            if key not in cell_series or key not in ok_cells:
                continue
            s = cell_series[key]
            bl, nbl = baseline_median(s, ew)
            q = float(s.get(ew, 0.0))
            if not (bl and bl >= BL_MIN_QTY and q > 0):
                continue
            # contaminacion por quiebre: % de SKUs de la celda con stockout esa semana
            if qset is None:
                pct_q = np.nan
            else:
                skus = sku_cell[(sku_cell["categoria"] == cat) & (sku_cell["rank"] == rank)].index
                pct_q = len(set(skus) & qset) / max(len(skus), 1)
            recs.append(dict(
                evento=name, arquetipo=arq, year=fecha.year, semana=ew, categoria=cat,
                rank=rank, uplift_celda=q/bl, uplift_categ=up_cat,
                lift_rel=(q/bl)/up_cat, bl_semanas=nbl, bl_qty=bl,
                pct_skus_quiebre=pct_q,
            ))

R = pd.DataFrame(recs)
R["abc"] = R["rank"].str[0].where(R["rank"] != "SIN", "SIN")
R["xyz"] = R["rank"].str[1].where(R["rank"] != "SIN", "SIN")
# categorias que SI responden al evento (donde la tesis aplica) vs planas
R["categ_responde"] = R["uplift_categ"] >= 1.2
print(f"\nobservaciones (evento x categ x rank): {len(R):,} | "
      f"eventos: {R['evento'].nunique()} | categs: {R['categoria'].nunique()}")

# ----------------------------------------------------------------------
# 5. Resumen por rank con CI bootstrap (mediana del lift relativo)
# ----------------------------------------------------------------------
def boot_ci(vals: np.ndarray, n=N_BOOT) -> tuple[float, float]:
    if len(vals) < 5:
        return (np.nan, np.nan)
    meds = np.median(RNG.choice(vals, size=(n, len(vals)), replace=True), axis=1)
    return (float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5)))

def resumen(sub: pd.DataFrame, dim: str) -> pd.DataFrame:
    out = []
    for v, g in sub.groupby(dim):
        vals = g["lift_rel"].values
        lo, hi = boot_ci(vals)
        out.append(dict(grupo=v, n_obs=len(g),
                        lift_rel_mediana=float(np.median(vals)),
                        ci_lo=lo, ci_hi=hi,
                        pct_quiebre_prom=float(g["pct_skus_quiebre"].mean(skipna=True))))
    return pd.DataFrame(out)

pd.set_option("display.width", 160)
print("\n" + "="*88)
print("LIFT RELATIVO POR RANK — solo categorias que RESPONDEN al evento (uplift>=1.2)")
print("  lift_rel > 1: el rank sube MAS que su categoria | < 1: sube MENOS")
print("="*88)
resp = R[R["categ_responde"]]
res_rank = resumen(resp, "rank").set_index("grupo").reindex(
    [r for r in RANK_ORDER if r in resp["rank"].unique()])
print(res_rank.round(3).to_string())

print("\nPor letra ABC (mismas obs):")
print(resumen(resp, "abc").set_index("grupo").round(3).to_string())
print("\nPor letra XYZ:")
print(resumen(resp, "xyz").set_index("grupo").round(3).to_string())

print("\n" + "="*88)
print("CONTROL: categorias PLANAS en el evento (uplift_categ < 1.2) — lift_rel deberia ~1")
print("="*88)
plano = R[~R["categ_responde"]]
print(resumen(plano, "rank").set_index("grupo").reindex(
    [r for r in RANK_ORDER if r in plano["rank"].unique()]).round(3).to_string())

# sensibilidad: excluyendo celdas con >30% de SKUs en quiebre
sens = resp[(resp["pct_skus_quiebre"].isna()) | (resp["pct_skus_quiebre"] <= 0.30)]
print("\nSensibilidad sin celdas con >30% SKUs en quiebre "
      f"({len(resp)-len(sens)} obs excluidas):")
print(resumen(sens, "abc").set_index("grupo").round(3).to_string())

# ----------------------------------------------------------------------
# 6. Casos canonicos
# ----------------------------------------------------------------------
print("\n" + "="*88)
print("CASOS CANONICOS")
print("="*88)
def caso(patron_cat: str, patron_ev: str):
    m = R[R["categoria"].str.contains(patron_cat, case=False) &
          R["evento"].str.contains(patron_ev, case=False)]
    if m.empty:
        print(f"  {patron_cat} x {patron_ev}: sin observaciones")
        return
    cols = ["evento","year","categoria","rank","uplift_categ","uplift_celda","lift_rel","pct_skus_quiebre"]
    show = m[cols].copy()
    show["categoria"] = show["categoria"].str.split("/").str[-1].str.strip()
    print(show.sort_values(["year","rank"]).round(2).to_string(index=False))

print("\n-- Cervezas en Fiestas Patrias --"); caso("cervez", "Fiestas")
print("\n-- Chocolates en Navidad --");       caso("chocolat", "Navidad")
print("\n-- Abarrotes (control) --");         caso("abarrote", ".")

# ----------------------------------------------------------------------
# 7. Persistir (formato Chile: lo mira Marco)
# ----------------------------------------------------------------------
R.to_csv(OUT / "rank_lift_eventos_detalle.csv", index=False,
         sep=";", decimal=",", encoding="utf-8-sig")
res_all = pd.concat([
    resumen(resp, "rank").assign(segmento="categ_responde"),
    resumen(plano, "rank").assign(segmento="categ_plana"),
])
res_all.to_csv(OUT / "rank_lift_eventos_resumen.csv", index=False,
               sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT/'rank_lift_eventos_detalle.csv'}")
print(f"-> {OUT/'rank_lift_eventos_resumen.csv'}")
