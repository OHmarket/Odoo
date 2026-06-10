"""
Paso 2c.3 — Amplitud estacional (verano) por rank ABCXYZ dentro de la categoria.

Tesis a comprobar: en categorias estacionales de verano, los ranks de alta
rotacion (AX, BX) tienen MAS amplitud estacional que su categoria; las colas
(CZ) menos.

Metodo: misma regresion armonica de real_categoria_diag.py (Fourier K=3 sobre
log qty, destendenciada, dummies de semana-evento que absorben los spikes),
ajustada POR CELDA categ x rank. Metrica:

    ratio_v_i_celda  = factor medio verano / factor medio invierno (celda)
    amp_rel          = ratio_v_i_celda / ratio_v_i_categ

amp_rel > 1: el rank es MAS estacional que su categoria.

PROXY documentados:
- Clasificacion ABCXYZ ACTUAL aplicada retroactivamente (sin historia).
- Ventana de 73 semanas (~1.4 anos): UN solo verano completo en el fact ->
  estimacion de 1 ciclo, se reporta como tal hasta el backfill a 2023.

Requiere: resultados/rank_week_sku_cache.parquet (lo genera rank_sparsity.py).
Read-only. Salida: resultados/rank_lift_verano*.csv + reporte.
"""
from __future__ import annotations
import sys
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RANK_ORDER = ["AX","AY","AZ","BX","BY","BZ","CX","CY","CZ","SIN"]
K = 3
MIN_WEEKS_CELL = 50           # semanas con venta para ajustar Fourier K3 (9 params)
SUMMER = list(range(49, 53)) + list(range(1, 10))    # dic-feb
WINTER = list(range(23, 36))                          # jun-ago
SEASONAL_VERANO = 1.30        # categ con ratio_v_i >= esto = estacional de verano
N_BOOT = 2000
RNG = np.random.default_rng(7)

OUT = Path(__file__).parent / "resultados"

# semanas-evento (mismos eventos de rank_uplift_eventos) para dummy
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
# 1. Series semanales por celda y por categoria
# ----------------------------------------------------------------------
df = pd.read_parquet(OUT / "rank_week_sku_cache.parquet")
df["week"] = pd.to_datetime(df["week"]).dt.date

census = pd.read_csv(OUT / "rank_sparsity_categ_rank.csv", sep=";", decimal=",",
                     encoding="utf-8-sig")
ok_cells = set(map(tuple, census.loc[census["ok"], ["categoria","rank"]].values))

cell_w = df.groupby(["categoria","rank","week"], as_index=False)["qty"].sum()
cat_w = df.groupby(["categoria","week"], as_index=False)["qty"].sum()

# ----------------------------------------------------------------------
# 2. Regresion armonica (reusa el diseno de real_categoria_diag.py)
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
    """ratio verano/invierno de la curva estacional limpia. None si poca data."""
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
    fi = [j for j, nm in enumerate(ns) if nm.startswith(("sin","cos"))]
    ci = [names.index(ns[j]) for j in fi]
    s = Xs[:, fi] @ b[ci]; s -= s.mean()
    curve = np.exp(s)
    summer = curve[[w-1 for w in SUMMER]].mean()
    winter = curve[[w-1 for w in WINTER]].mean()
    return dict(ratio_v_i=summer/winter, amplitud=curve.max()/curve.min(),
                n_sem=len(g))

cat_fit = {}
for cat, g in cat_w.groupby("categoria"):
    r = seasonal_fit(g)
    if r:
        cat_fit[cat] = r

recs = []
for (cat, rank), g in cell_w.groupby(["categoria","rank"]):
    if (cat, rank) not in ok_cells or cat not in cat_fit:
        continue
    r = seasonal_fit(g)
    if not r:
        continue
    rc = cat_fit[cat]
    recs.append(dict(
        categoria=cat, rank=rank, n_sem=r["n_sem"],
        ratio_v_i_celda=r["ratio_v_i"], ratio_v_i_categ=rc["ratio_v_i"],
        amp_rel=r["ratio_v_i"]/rc["ratio_v_i"],
        amplitud_celda=r["amplitud"],
    ))
R = pd.DataFrame(recs)
R["abc"] = R["rank"].str[0].where(R["rank"] != "SIN", "SIN")
R["xyz"] = R["rank"].str[1].where(R["rank"] != "SIN", "SIN")
R["categ_verano"] = R["ratio_v_i_categ"] >= SEASONAL_VERANO
print(f"celdas ajustadas: {len(R)} | categorias: {R['categoria'].nunique()} | "
      f"categ estacionales de verano (ratio>= {SEASONAL_VERANO}): "
      f"{R.loc[R['categ_verano'],'categoria'].nunique()}")

# ----------------------------------------------------------------------
# 3. Resumen por rank con CI bootstrap
# ----------------------------------------------------------------------
def boot_ci(vals, n=N_BOOT):
    if len(vals) < 5:
        return (np.nan, np.nan)
    meds = np.median(RNG.choice(vals, size=(n, len(vals)), replace=True), axis=1)
    return (float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5)))

def resumen(sub, dim):
    out = []
    for v, g in sub.groupby(dim):
        vals = g["amp_rel"].values
        lo, hi = boot_ci(vals)
        out.append(dict(grupo=v, n_celdas=len(g),
                        amp_rel_mediana=float(np.median(vals)), ci_lo=lo, ci_hi=hi))
    return pd.DataFrame(out).set_index("grupo")

pd.set_option("display.width", 160)
ver = R[R["categ_verano"]]
print("\n" + "="*88)
print("AMPLITUD RELATIVA POR RANK — solo categorias estacionales de VERANO")
print("  amp_rel > 1: el rank es MAS estacional que su categoria | < 1: MENOS")
print("="*88)
print(resumen(ver, "rank").reindex(
    [r for r in RANK_ORDER if r in ver["rank"].unique()]).round(3).to_string())
print("\nPor letra ABC:")
print(resumen(ver, "abc").round(3).to_string())
print("\nPor letra XYZ:")
print(resumen(ver, "xyz").round(3).to_string())

plano = R[~R["categ_verano"]]
print("\n" + "="*88)
print("CONTROL: categorias NO estacionales — amp_rel deberia ~1 y sin gradiente")
print("="*88)
print(resumen(plano, "abc").round(3).to_string())

# ----------------------------------------------------------------------
# 4. Casos canonicos
# ----------------------------------------------------------------------
print("\n" + "="*88)
print("CASOS CANONICOS (ratio_v_i por celda vs categ)")
print("="*88)
def caso(patron):
    m = R[R["categoria"].str.contains(patron, case=False)]
    if m.empty:
        print(f"  {patron}: sin celdas")
        return
    show = m[["categoria","rank","n_sem","ratio_v_i_categ","ratio_v_i_celda","amp_rel"]].copy()
    show["categoria"] = show["categoria"].str.split("/").str[-1].str.strip()
    print(show.sort_values(["categoria","rank"]).round(2).to_string(index=False))

print("\n-- Cervezas --");  caso("cervez")
print("\n-- Aguas --");     caso("agua")
print("\n-- Hielo --");     caso("hielo")
print("\n-- Chocolates (estacional de invierno, espejo) --"); caso("chocolat")

# ----------------------------------------------------------------------
# 5. Persistir (formato Chile: lo mira Marco)
# ----------------------------------------------------------------------
R.to_csv(OUT / "rank_lift_verano_detalle.csv", index=False,
         sep=";", decimal=",", encoding="utf-8-sig")
pd.concat([resumen(ver, "rank").assign(segmento="categ_verano"),
           resumen(plano, "rank").assign(segmento="categ_no_estacional")]
          ).to_csv(OUT / "rank_lift_verano_resumen.csv",
                   sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT/'rank_lift_verano_detalle.csv'}")
print(f"-> {OUT/'rank_lift_verano_resumen.csv'}")
