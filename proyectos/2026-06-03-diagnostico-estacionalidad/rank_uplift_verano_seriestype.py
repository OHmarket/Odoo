"""
Paso 2c.6 — Amplitud estacional (verano) por TIPO DE SERIE dentro de la categoria.

Igual que rank_uplift_verano.py pero la celda es categ x series_type
(smooth/erratic/intermittent/lumpy, Syntetos-Boylan global de x_calculo_abc_xyz,
campo x_studio_series_type_active con fallback a x_studio_series_type).

    amp_rel = ratio_v_i_celda / ratio_v_i_categ   (>1 = mas estacional que su categ)

CAVEAT de circularidad (mas fuerte que con XYZ): el tipo de serie se define por
ADI/CV2 de la demanda; un SKU con verano marcado tiene CV2 alto y cae en
erratic/lumpy POR CONSTRUCCION. smooth deberia salir plano casi por definicion.

Requiere: resultados/rank_week_sku_cache.parquet. Read-only.
Salida: resultados/rank_lift_verano_seriestype*.csv + reporte.
"""
from __future__ import annotations
import sys
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

K = 3
MIN_WEEKS_CELL = 50
MIN_SKUS_CELL = 5
MIN_UNITS_WEEK = 30.0
SUMMER = list(range(49, 53)) + list(range(1, 10))
WINTER = list(range(23, 36))
SEASONAL_VERANO = 1.30
N_BOOT = 2000
RNG = np.random.default_rng(7)
TYPE_ORDER = ["smooth", "erratic", "intermittent", "lumpy", "no_signal", "SIN"]

OUT = Path(__file__).parent / "resultados"

EVENT_DATES = [
    dt.date(2025,1,1), dt.date(2025,2,14), dt.date(2025,4,18), dt.date(2025,5,1),
    dt.date(2025,5,11), dt.date(2025,5,21), dt.date(2025,6,15), dt.date(2025,7,16),
    dt.date(2025,8,15), dt.date(2025,9,18), dt.date(2025,10,31), dt.date(2025,11,1),
    dt.date(2025,12,8), dt.date(2025,12,25),
    dt.date(2026,1,1), dt.date(2026,2,14), dt.date(2026,4,3), dt.date(2026,5,1),
    dt.date(2026,5,10),
]
def wk_start(d): return d - dt.timedelta(days=d.weekday())
event_weeks = set()
for f in EVENT_DATES:
    event_weeks.add(wk_start(f)); event_weeks.add(wk_start(f - dt.timedelta(days=1)))

# ----------------------------------------------------------------------
# 1. Mapa SKU -> series_type (global, x_calculo_abc_xyz)
# ----------------------------------------------------------------------
o = OdooReader()
rows, offset = [], 0
while True:
    chunk = o.search_read(
        "x_calculo_abc_xyz", domain=[],
        fields=["x_studio_product_id", "x_studio_series_type_active",
                "x_studio_series_type"],
        limit=5000, offset=offset, order="id")
    rows.extend(chunk)
    if len(chunk) < 5000:
        break
    offset += 5000
st = pd.DataFrame([
    dict(product_id=r["x_studio_product_id"][0],
         stype=(r.get("x_studio_series_type_active")
                or r.get("x_studio_series_type") or "SIN"))
    for r in rows if r.get("x_studio_product_id")
]).drop_duplicates("product_id")
print(f"series_type: {st['stype'].value_counts().to_dict()}")

# ----------------------------------------------------------------------
# 2. Series por celda categ x stype (mismos umbrales del censo 2c.1)
# ----------------------------------------------------------------------
df = pd.read_parquet(OUT / "rank_week_sku_cache.parquet")
df["week"] = pd.to_datetime(df["week"]).dt.date
df = df.merge(st, on="product_id", how="left")
df["stype"] = df["stype"].fillna("SIN")
n_weeks = df["week"].nunique()

cens = (df.groupby(["categoria", "stype"])
          .agg(n_skus=("product_id", "nunique"), qty_total=("qty", "sum"))
          .reset_index())
cens["qty_sem"] = cens["qty_total"] / n_weeks
cens["ok"] = (cens["n_skus"] >= MIN_SKUS_CELL) & (cens["qty_sem"] >= MIN_UNITS_WEEK)
ok_cells = set(map(tuple, cens.loc[cens["ok"], ["categoria", "stype"]].values))
print(f"celdas categ x stype con venta: {len(cens)} | OK: {len(ok_cells)} | "
      f"volumen OK: {cens.loc[cens['ok'],'qty_total'].sum()/cens['qty_total'].sum():.1%}")

cell_w = df.groupby(["categoria", "stype", "week"], as_index=False)["qty"].sum()
cat_w = df.groupby(["categoria", "week"], as_index=False)["qty"].sum()

# ----------------------------------------------------------------------
# 3. Ajuste armonico (mismo de rank_uplift_verano.py)
# ----------------------------------------------------------------------
def design(iso_w, t, ev=None, k=K, with_trend=True):
    cols = [np.ones(len(iso_w))]; names = ["const"]
    if with_trend:
        cols.append(t); names.append("trend")
    for kk in range(1, k+1):
        cols.append(np.sin(2*np.pi*kk*iso_w/52)); names.append(f"sin{kk}")
        cols.append(np.cos(2*np.pi*kk*iso_w/52)); names.append(f"cos{kk}")
    if ev is not None:
        cols.append(ev.astype(float)); names.append("event")
    return np.column_stack(cols), names

def seasonal_fit(g: pd.DataFrame):
    g = g[g["qty"] > 0]
    if len(g) < MIN_WEEKS_CELL:
        return None
    wk = pd.to_datetime(g["week"])
    iso = wk.dt.isocalendar().week.astype(int).clip(upper=52).values
    t = (wk - wk.min()).dt.days.values / 365.0
    ev = g["week"].isin(event_weeks).values
    y = np.log(g["qty"].values)
    X, names = design(iso, t, ev=ev)
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    isow = np.arange(1, 53)
    Xs, ns = design(isow, np.zeros(52), ev=None, with_trend=False)
    fi = [j for j, nm in enumerate(ns) if nm.startswith(("sin", "cos"))]
    ci = [names.index(ns[j]) for j in fi]
    s = Xs[:, fi] @ b[ci]; s -= s.mean()
    curve = np.exp(s)
    return dict(ratio_v_i=curve[[w-1 for w in SUMMER]].mean() /
                          curve[[w-1 for w in WINTER]].mean(),
                n_sem=len(g))

cat_fit = {c: r for c, g in cat_w.groupby("categoria") if (r := seasonal_fit(g))}

recs = []
for (cat, stype), g in cell_w.groupby(["categoria", "stype"]):
    if (cat, stype) not in ok_cells or cat not in cat_fit:
        continue
    r = seasonal_fit(g)
    if not r:
        continue
    recs.append(dict(categoria=cat, stype=stype, n_sem=r["n_sem"],
                     ratio_v_i_celda=r["ratio_v_i"],
                     ratio_v_i_categ=cat_fit[cat]["ratio_v_i"],
                     amp_rel=r["ratio_v_i"] / cat_fit[cat]["ratio_v_i"]))
R = pd.DataFrame(recs)
R["categ_verano"] = R["ratio_v_i_categ"] >= SEASONAL_VERANO
print(f"celdas ajustadas: {len(R)} | categ verano: "
      f"{R.loc[R['categ_verano'], 'categoria'].nunique()}")

# ----------------------------------------------------------------------
# 4. Resumen
# ----------------------------------------------------------------------
def boot_ci(vals, n=N_BOOT):
    if len(vals) < 5:
        return (np.nan, np.nan)
    meds = np.median(RNG.choice(vals, size=(n, len(vals)), replace=True), axis=1)
    return (float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5)))

def resumen(sub):
    out = []
    for v, g in sub.groupby("stype"):
        lo, hi = boot_ci(g["amp_rel"].values)
        out.append(dict(stype=v, n_celdas=len(g),
                        amp_rel_mediana=float(np.median(g["amp_rel"])),
                        ci_lo=lo, ci_hi=hi))
    return (pd.DataFrame(out).set_index("stype")
            .reindex([t for t in TYPE_ORDER if t in sub["stype"].unique()]))

pd.set_option("display.width", 160)
ver = R[R["categ_verano"]]
print("\n" + "=" * 84)
print("AMPLITUD RELATIVA POR TIPO DE SERIE — categorias estacionales de VERANO")
print("  amp_rel > 1: el tipo es MAS estacional que su categoria | < 1: MENOS")
print("=" * 84)
print(resumen(ver).round(3).to_string())

plano = R[~R["categ_verano"]]
print("\nCONTROL (categorias no estacionales):")
print(resumen(plano).round(3).to_string())

print("\nCASO CANONICO — Cervezas:")
m = R[R["categoria"].str.contains("cervez", case=False)]
show = m[["categoria", "stype", "n_sem", "ratio_v_i_categ",
          "ratio_v_i_celda", "amp_rel"]].copy()
show["categoria"] = show["categoria"].str.split("/").str[-1].str.strip()
print(show.sort_values(["categoria", "stype"]).round(2).to_string(index=False))

R.to_csv(OUT / "rank_lift_verano_seriestype_detalle.csv", index=False,
         sep=";", decimal=",", encoding="utf-8-sig")
pd.concat([resumen(ver).assign(segmento="categ_verano"),
           resumen(plano).assign(segmento="categ_no_estacional")]
          ).to_csv(OUT / "rank_lift_verano_seriestype_resumen.csv",
                   sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT / 'rank_lift_verano_seriestype_detalle.csv'}")
print(f"-> {OUT / 'rank_lift_verano_seriestype_resumen.csv'}")
