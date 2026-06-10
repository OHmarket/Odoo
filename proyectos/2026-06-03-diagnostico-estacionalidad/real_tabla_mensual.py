"""
Tabla mensual de estacionalidad por categoria (indice base 100 = promedio anual).
Deriva los 12 indices desde la curva semanal Fourier ajustada (suave, sin
tendencia ni feriados). Read-only.
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

K = 3
HOL = {38: "18-sep", 51: "navidad"}
MIN_QTY = 20000          # filtro volumen para tabla limpia
MESES = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

# iso_week -> mes (jueves de la semana ISO define el mes/ano)
W2M = {w: pd.Timestamp.fromisocalendar(2025, w, 4).month for w in range(1, 53)}

# ---- pull ----
o = OdooReader()
g = o.execute('x_pos_week_sku_sale', 'read_group',
              [('x_studio_week_start', '>=', '2025-01-01')],
              ['x_studio_qty_sold:sum'],
              ['x_studio_categ_id', 'x_studio_week_start:week'], lazy=False)
rows = []
for r in g:
    cat = r.get('x_studio_categ_id')
    if not cat:
        continue
    ws = r['__range']['x_studio_week_start:week']['from']
    rows.append((cat[1], ws, r.get('x_studio_qty_sold') or 0.0))
df = pd.DataFrame(rows, columns=["categoria", "week_start", "qty"])
df["week_start"] = pd.to_datetime(df["week_start"], format="%Y-%m-%d")
df = df.sort_values(["categoria", "week_start"])
df["iso_week"] = df["week_start"].dt.isocalendar().week.astype(int).clip(upper=52)

def design(iso_w, t, k=K, holidays=None, with_trend=True):
    cols = [np.ones_like(t, dtype=float)]; names = ["const"]
    if with_trend:
        cols.append(t); names.append("trend")
    for kk in range(1, k + 1):
        cols.append(np.sin(2*np.pi*kk*iso_w/52)); names.append(f"sin{kk}")
        cols.append(np.cos(2*np.pi*kk*iso_w/52)); names.append(f"cos{kk}")
    if holidays:
        for wk in holidays:
            cols.append((iso_w == wk).astype(float)); names.append(f"hol{wk}")
    return np.column_stack(cols), names

recs = []
for cat, gg in df.groupby("categoria"):
    gg = gg[gg["qty"] > 0]
    if len(gg) < 30 or gg["qty"].sum() < MIN_QTY:
        continue
    y_log = np.log(gg["qty"].values)
    t = (gg["week_start"] - gg["week_start"].min()).dt.days.values / 365.0
    X, names = design(gg["iso_week"].values, t, holidays=HOL.keys())
    b, *_ = np.linalg.lstsq(X, y_log, rcond=None)
    resid = y_log - X @ b
    isow = np.arange(1, 53)
    Xs, ns = design(isow, np.zeros(52), holidays=None, with_trend=False)
    fidx = [j for j, nm in enumerate(ns) if nm.startswith(("sin", "cos"))]
    cidx = [names.index(ns[j]) for j in fidx]
    s_log = Xs[:, fidx] @ b[cidx]; s_log -= s_log.mean()
    curve = np.exp(s_log)                                  # factor semanal mean~1
    # agregar a 12 meses
    month_factor = np.array([np.mean([curve[w-1] for w in range(1,53) if W2M[w]==m])
                             for m in range(1, 13)])
    month_factor = month_factor / month_factor.mean()      # renormaliza mean 1
    si = s_log[[w-1 for w in gg["iso_week"].values]]
    fs = max(0.0, 1 - np.var(resid)/np.var(resid + si)) if np.var(resid+si) > 0 else 0.0
    rec = {"categoria": cat.split("/")[-1].strip(), "qty": int(gg["qty"].sum()),
           "fs": round(fs, 2), "trend": round(np.exp(b[names.index("trend")])-1, 2)}
    for i, m in enumerate(MESES):
        rec[m] = int(round(month_factor[i]*100))
    recs.append(rec)

res = pd.DataFrame(recs)
# orden por fuerza de verano (Ene+Feb vs Jul)
res["_v"] = (res["Ene"]+res["Feb"]) / (2*res["Jul"])
res = res.sort_values("_v", ascending=False).drop(columns="_v")

pd.set_option("display.width", 220, "display.max_rows", 100)
print("="*120)
print("TABLA MENSUAL DE ESTACIONALIDAD POR CATEGORIA  (indice base 100 = promedio anual)")
print(f"filtro: qty_total >= {MIN_QTY:,}.  Ordenado por verano (Ene+Feb vs Jul).")
print("="*120)
cols = ["categoria","qty","fs"] + MESES + ["trend"]
print(res[cols].to_string(index=False))
print("\nLEYENDA: 100 = mes promedio. 150 = +50% sobre el promedio. 60 = -40%.")
print("         fs = fuerza estacional 0..1.  trend = crecimiento anual (frac).")
print("         OJO: Jun-Dic con 1 sola observacion (span 17 meses) -> menor confianza 2do semestre.")

os.makedirs(os.path.join(os.path.dirname(__file__), "resultados"), exist_ok=True)
res.to_csv(os.path.join(os.path.dirname(__file__), "resultados", "real_tabla_mensual.csv"),
           index=False, encoding="utf-8-sig")
print("\n-> resultados/real_tabla_mensual.csv")
