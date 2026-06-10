"""
Diagnostico de respuesta estacional REAL a nivel categoria (global, todos los
locales). Regresion armonica (Fourier K=3) + dummies de feriado por categoria.

Agrega en el servidor con read_group (categ x week_start) -> liviano.
Read-only. Salida: ranking de categorias por fuerza estacional + CSV.
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

K = 3
# iso_week aprox de feriados clave Chile
HOL = {38: "18-sep", 51: "navidad"}

# ----------------------------------------------------------------------
# 1. PULL agregado categoria x semana (global)
# ----------------------------------------------------------------------
o = OdooReader()
g = o.execute(
    'x_pos_week_sku_sale', 'read_group',
    [('x_studio_week_start', '>=', '2025-01-01')],
    ['x_studio_qty_sold:sum'],
    ['x_studio_categ_id', 'x_studio_week_start:week'],
    lazy=False,
)
rows = []
for r in g:
    cat = r.get('x_studio_categ_id')
    if not cat:
        continue
    ws = r['__range']['x_studio_week_start:week']['from']   # fecha limpia del lunes
    qty = r.get('x_studio_qty_sold') or 0.0
    rows.append((cat[1], ws, qty))
df = pd.DataFrame(rows, columns=["categoria", "week_start", "qty"])
df["week_start"] = pd.to_datetime(df["week_start"], format="%Y-%m-%d")
df = df.sort_values(["categoria", "week_start"])
df["iso_week"] = df["week_start"].dt.isocalendar().week.astype(int).clip(upper=52)
print(f"categorias: {df['categoria'].nunique()}  filas(cat-sem): {len(df):,}  "
      f"rango: {df['week_start'].min().date()} -> {df['week_start'].max().date()}")

# ----------------------------------------------------------------------
# 2. Regresion armonica por categoria
# ----------------------------------------------------------------------
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

SUMMER = list(range(49, 53)) + list(range(1, 10))    # dic-feb
WINTER = list(range(23, 36))                          # jun-ago

out = []
curves = {}
for cat, gg in df.groupby("categoria"):
    gg = gg[gg["qty"] > 0]
    if len(gg) < 30:                  # muy poca data
        continue
    n = len(gg)
    y_log = np.log(gg["qty"].values)
    t = (gg["week_start"] - gg["week_start"].min()).dt.days.values / 365.0
    X, names = design(gg["iso_week"].values, t, holidays=HOL.keys())
    b, *_ = np.linalg.lstsq(X, y_log, rcond=None)
    resid = y_log - X @ b
    # curva estacional sobre iso 1..52
    isow = np.arange(1, 53)
    Xs, ns = design(isow, np.zeros(52), holidays=None, with_trend=False)
    fidx = [j for j, nm in enumerate(ns) if nm.startswith(("sin", "cos"))]
    cidx = [names.index(ns[j]) for j in fidx]
    s_log = Xs[:, fidx] @ b[cidx]; s_log -= s_log.mean()
    curve = np.exp(s_log)
    curves[cat] = curve
    # Fs de la categoria (fuerza estacional del agregado)
    s_own = X[:, [names.index(nm) for nm in names if nm.startswith(("sin","cos"))]] @ \
            b[[names.index(nm) for nm in names if nm.startswith(("sin","cos"))]]
    s_own -= s_own.mean()
    fs = max(0.0, 1 - np.var(resid)/np.var(resid + s_own)) if np.var(resid+s_own) > 0 else 0.0
    summer = curve[[w-1 for w in SUMMER]].mean()
    winter = curve[[w-1 for w in WINTER]].mean()
    trend_pct = np.exp(b[names.index("trend")]) - 1     # %/ano
    out.append(dict(
        categoria=cat, n_sem=n, qty_total=gg["qty"].sum(),
        verano=summer, invierno=winter, ratio_v_i=summer/winter,
        amplitud=curve.max()/curve.min(), fs=fs, trend_pct_ano=trend_pct,
        hol_18sep=np.exp(b[names.index("hol38")])-1,
        hol_navidad=np.exp(b[names.index("hol51")])-1,
    ))

res = pd.DataFrame(out).sort_values("ratio_v_i", ascending=False)

# ----------------------------------------------------------------------
# 3. REPORTE
# ----------------------------------------------------------------------
def short(c):       # ultimo segmento del arbol
    return c.split("/")[-1].strip()[:24]

pd.set_option("display.width", 200, "display.max_rows", 100)
show = res.copy()
show["categoria"] = show["categoria"].map(short)
for c in ["verano", "invierno", "ratio_v_i", "amplitud", "fs"]:
    show[c] = show[c].round(2)
show["trend_%ano"] = (show["trend_pct_ano"]*100).round(0)
show["18sep_%"] = (show["hol_18sep"]*100).round(0)
show["navid_%"] = (show["hol_navidad"]*100).round(0)
show["qty_total"] = show["qty_total"].round(0).astype(int)

print("\n" + "="*100)
print("RESPUESTA ESTACIONAL POR CATEGORIA (ordenado por verano/invierno)")
print("="*100)
cols = ["categoria","n_sem","qty_total","verano","invierno","ratio_v_i","amplitud","fs","trend_%ano","18sep_%","navid_%"]
print(show[cols].to_string(index=False))

print("\nLEYENDA: verano/invierno = factor medio (mean~1). ratio_v_i>1 => vende mas en verano.")
print("         fs = fuerza estacional 0..1.  trend_%ano = crecimiento anual.")
print("         18sep_% / navid_% = uplift del feriado esa semana.")

os.makedirs(os.path.join(os.path.dirname(__file__), "resultados"), exist_ok=True)
res.to_csv(os.path.join(os.path.dirname(__file__), "resultados", "real_categoria_diag.csv"),
           index=False, encoding="utf-8-sig")
print("\n-> resultados/real_categoria_diag.csv")
