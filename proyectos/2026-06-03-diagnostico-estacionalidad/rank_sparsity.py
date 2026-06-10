"""
Paso 2c.1 — Censo de celdas categ x rank ABCXYZ (sparsity).

Pregunta: si los factores L1/L2 bajan de `categ` a `categ x rank` (o incluso
`team x categ x rank`), cuantas celdas tienen muestra suficiente para estimar
un uplift confiable? Define el nivel de pooling antes de medir lift.

PROXY documentado: la clasificacion ABCXYZ es la ACTUAL de x_calculo_abc_xyz
(no hay historia de clasificacion); se aplica retroactivamente a la venta
2025-2026. Deriva de clasificacion = sesgo conocido.

Read-only. Salida: resultados/rank_sparsity_*.csv + reporte en consola.
"""
from __future__ import annotations
import sys, os
import datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

WEEK_FROM = "2024-12-30"          # primer lunes con fact completo
MIN_SKUS_CELL = 5                 # umbral propuesto: SKUs por celda
MIN_UNITS_WEEK = 30               # umbral propuesto: unidades/semana por celda
RANK_ORDER = ["AX","AY","AZ","BX","BY","BZ","CX","CY","CZ","SIN"]

OUT = Path(__file__).parent / "resultados"
OUT.mkdir(exist_ok=True)

o = OdooReader()

# ----------------------------------------------------------------------
# 1. Mapa SKU -> rank ABCXYZ (clasificacion ACTUAL, ver PROXY del header)
# ----------------------------------------------------------------------
abc_rows = []
offset = 0
while True:
    chunk = o.search_read(
        "x_calculo_abc_xyz", domain=[],
        fields=["x_studio_product_id", "x_studio_abcxyz"],
        limit=5000, offset=offset, order="id",
    )
    abc_rows.extend(chunk)
    if len(chunk) < 5000:
        break
    offset += 5000
abc = pd.DataFrame([
    dict(product_id=r["x_studio_product_id"][0], rank=(r.get("x_studio_abcxyz") or "SIN"))
    for r in abc_rows if r.get("x_studio_product_id")
]).drop_duplicates("product_id")
print(f"ABCXYZ: {len(abc):,} SKUs clasificados | ranks: "
      f"{abc['rank'].value_counts().to_dict()}")

# ----------------------------------------------------------------------
# 2. Venta semanal SKU pooled entre salas (loop mensual para no reventar RPC)
# ----------------------------------------------------------------------
def month_windows(start: dt.date, end: dt.date):
    cur = start
    while cur < end:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        yield cur, min(nxt, end)
        cur = nxt

start = dt.date.fromisoformat(WEEK_FROM)
today = dt.date.today()
rows = []
for lo, hi in month_windows(start, today):
    g = o.execute(
        "x_pos_week_sku_sale", "read_group",
        [("x_studio_week_start", ">=", lo.isoformat()),
         ("x_studio_week_start", "<", hi.isoformat())],
        ["x_studio_qty_sold:sum", "x_studio_sales_gross:sum"],
        ["x_studio_product_id", "x_studio_categ_id", "x_studio_week_start:week"],
        lazy=False,
    )
    for r in g:
        p = r.get("x_studio_product_id")
        c = r.get("x_studio_categ_id")
        if not p or not c:
            continue
        rows.append((
            p[0], c[0], c[1],
            r["__range"]["x_studio_week_start:week"]["from"][:10],
            r.get("x_studio_qty_sold") or 0.0,
            r.get("x_studio_sales_gross") or 0.0,
        ))
    print(f"  {lo} -> {hi}: acumulado {len(rows):,} filas sku-semana")

df = pd.DataFrame(rows, columns=["product_id","categ_id","categoria","week","qty","gross"])
df["week"] = pd.to_datetime(df["week"], format="%Y-%m-%d")
df = df.merge(abc, on="product_id", how="left")
df["rank"] = df["rank"].fillna("SIN")
n_weeks = df["week"].nunique()
print(f"\nfact: {df['product_id'].nunique():,} SKUs | {df['categoria'].nunique()} categorias | "
      f"{n_weeks} semanas ({df['week'].min().date()} -> {df['week'].max().date()})")
print(f"SKUs del fact sin clasificacion ABCXYZ: "
      f"{(df.groupby('product_id')['rank'].first() == 'SIN').sum():,}")

# ----------------------------------------------------------------------
# 3. Censo categ x rank (pooled salas)
# ----------------------------------------------------------------------
cell = (df.groupby(["categoria","rank"])
          .agg(n_skus=("product_id","nunique"),
               qty_total=("qty","sum"),
               gross_total=("gross","sum"),
               n_sem=("week","nunique"))
          .reset_index())
cell["qty_sem"] = cell["qty_total"] / n_weeks
cell["ok"] = (cell["n_skus"] >= MIN_SKUS_CELL) & (cell["qty_sem"] >= MIN_UNITS_WEEK)

categ_tot = df.groupby("categoria")["qty"].sum()
cell["share_categ"] = cell.apply(
    lambda r: r["qty_total"] / categ_tot[r["categoria"]], axis=1)

n_cells = len(cell)
n_ok = int(cell["ok"].sum())
vol_ok = cell.loc[cell["ok"], "qty_total"].sum() / cell["qty_total"].sum()
print("\n" + "="*88)
print(f"CENSO CATEG x RANK (pooled 12 salas, {n_weeks} semanas)")
print("="*88)
print(f"celdas con venta: {n_cells} | celdas OK (>= {MIN_SKUS_CELL} SKUs y >= "
      f"{MIN_UNITS_WEEK} u/sem): {n_ok} ({n_ok/n_cells:.0%})")
print(f"volumen (unidades) cubierto por celdas OK: {vol_ok:.1%}")

# distribucion de celdas OK por rank
piv = (cell.assign(rank=pd.Categorical(cell["rank"], RANK_ORDER, ordered=True))
           .pivot_table(index="rank", values="ok", aggfunc=["count","sum"], observed=True))
piv.columns = ["celdas","celdas_ok"]
piv["pct_ok"] = (piv["celdas_ok"]/piv["celdas"]*100).round(0)
print("\nPor rank:")
print(piv.to_string())

# ----------------------------------------------------------------------
# 4. Censo team x categ x rank (una llamada agregada por producto x team)
# ----------------------------------------------------------------------
rows_t = []
for lo, hi in month_windows(start, today):
    g = o.execute(
        "x_pos_week_sku_sale", "read_group",
        [("x_studio_week_start", ">=", lo.isoformat()),
         ("x_studio_week_start", "<", hi.isoformat())],
        ["x_studio_qty_sold:sum"],
        ["x_studio_team_id", "x_studio_product_id"],
        lazy=False,
    )
    for r in g:
        t = r.get("x_studio_team_id"); p = r.get("x_studio_product_id")
        if not t or not p:
            continue
        rows_t.append((t[0], p[0], r.get("x_studio_qty_sold") or 0.0))
dt_team = pd.DataFrame(rows_t, columns=["team_id","product_id","qty"])
dt_team = dt_team.groupby(["team_id","product_id"], as_index=False)["qty"].sum()
dt_team = dt_team.merge(abc, on="product_id", how="left")
dt_team["rank"] = dt_team["rank"].fillna("SIN")
categ_map = df.groupby("product_id")["categoria"].first()
dt_team["categoria"] = dt_team["product_id"].map(categ_map)

cell_t = (dt_team.dropna(subset=["categoria"])
                 .groupby(["team_id","categoria","rank"])
                 .agg(n_skus=("product_id","nunique"), qty_total=("qty","sum"))
                 .reset_index())
cell_t["qty_sem"] = cell_t["qty_total"] / n_weeks
cell_t["ok"] = (cell_t["n_skus"] >= MIN_SKUS_CELL) & (cell_t["qty_sem"] >= MIN_UNITS_WEEK)
nt, nt_ok = len(cell_t), int(cell_t["ok"].sum())
vol_t_ok = cell_t.loc[cell_t["ok"], "qty_total"].sum() / cell_t["qty_total"].sum()
print("\n" + "="*88)
print("CENSO TEAM x CATEG x RANK")
print("="*88)
print(f"celdas con venta: {nt:,} | OK: {nt_ok:,} ({nt_ok/nt:.0%}) | "
      f"volumen cubierto por OK: {vol_t_ok:.1%}")

print("\nLECTURA: si pocas celdas team-level pasan el umbral pero las pooled si,")
print("el efecto-rank se estima pooled entre salas y la sala vive a nivel categ (L1).")

# ----------------------------------------------------------------------
# 5. Persistir
# ----------------------------------------------------------------------
cell.sort_values(["categoria","rank"]).to_csv(
    OUT / "rank_sparsity_categ_rank.csv", index=False,
    sep=";", decimal=",", encoding="utf-8-sig")
cell_t.sort_values(["team_id","categoria","rank"]).to_csv(
    OUT / "rank_sparsity_team_categ_rank.csv", index=False,
    sep=";", decimal=",", encoding="utf-8-sig")
# cache tecnico para los pasos 2c.2/2c.3 (formato estandar, lo leen scripts)
df.to_parquet(OUT / "rank_week_sku_cache.parquet", index=False)
print(f"\n-> {OUT/'rank_sparsity_categ_rank.csv'}")
print(f"-> {OUT/'rank_sparsity_team_categ_rank.csv'}")
print(f"-> {OUT/'rank_week_sku_cache.parquet'} (cache para 2c.2/2c.3)")
