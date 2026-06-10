"""
Paso 2c.8 — Detector de SKUs evento-only (canasta del evento).

Problema: pan de pascua, cola de mono (Navidad), pipeño, granadina (Fiestas
Patrias) tienen baseline ~0 fuera del evento -> el factor multiplicativo no
los levanta (0 x factor = 0). Necesitan marca + tratamiento ancla-LY.

Deteccion por CONCENTRACION (patron Oracle RDF short-lifecycle):

    share_evento = qty(ventana evento) / qty(año)

ventana = [semana_evento - PRE_WEEKS, semana_evento + POST_WEEKS].
Candidato si share >= SHARE_MIN y qty año >= QTY_MIN. La lista resultante la
cura Marco (el negocio conoce la canasta); esto solo propone.

Read-only. Lee cache 2c.1 + nombres via XML-RPC.
Salida: resultados/sku_evento_candidatos.csv
"""
from __future__ import annotations
import sys
import datetime as dt
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

OUT = Path(__file__).parent / "resultados"
YEAR_FROM, YEAR_TO = dt.date(2025, 1, 6), dt.date(2025, 12, 29)   # 52 sem 2025
PRE_WEEKS, POST_WEEKS = 3, 0
SHARE_MIN = 0.50      # ventana de 4 sem = 7.7% del año; 50% = 6.5x concentracion
QTY_MIN = 24          # minimo unidades/año para no marcar ruido

EVENTOS = {
    "Navidad":         dt.date(2025, 12, 25),
    "Fiestas Patrias": dt.date(2025, 9, 18),
    "Año Nuevo":       dt.date(2025, 12, 31),  # vispera como ancla de semana
    "Halloween":       dt.date(2025, 10, 31),
    "San Valentin":    dt.date(2025, 2, 14),
}

def wk_start(d): return d - dt.timedelta(days=d.weekday())

df = pd.read_parquet(OUT / "rank_week_sku_cache.parquet")
df["week"] = pd.to_datetime(df["week"]).dt.date
df = df[(df["week"] >= YEAR_FROM) & (df["week"] <= YEAR_TO)]
anual = df.groupby("product_id").agg(qty_ano=("qty", "sum"),
                                     categoria=("categoria", "first"))

cands = []
for ev, fecha in EVENTOS.items():
    ew = wk_start(fecha - dt.timedelta(days=1))
    lo = ew - dt.timedelta(weeks=PRE_WEEKS)
    hi = ew + dt.timedelta(weeks=POST_WEEKS)
    win = (df[(df["week"] >= lo) & (df["week"] <= hi)]
           .groupby("product_id")["qty"].sum().rename("qty_ventana"))
    m = anual.join(win, how="inner")
    m["share"] = m["qty_ventana"] / m["qty_ano"]
    m = m[(m["share"] >= SHARE_MIN) & (m["qty_ano"] >= QTY_MIN)]
    m["evento"] = ev
    m["ventana"] = f"{lo} a {hi + dt.timedelta(days=6)}"
    cands.append(m.reset_index())
C = pd.concat(cands, ignore_index=True)

# nombres de producto (solo candidatos)
o = OdooReader()
ids = sorted(set(C["product_id"].astype(int)))
names = {}
for i in range(0, len(ids), 500):
    for r in o.execute("product.product", "read", ids[i:i+500], ["name"]):
        names[r["id"]] = r["name"]
C["producto"] = C["product_id"].map(names)
C["categ"] = C["categoria"].str.split("/").str[-1].str.strip()
C = C.sort_values(["evento", "share"], ascending=[True, False])

pd.set_option("display.width", 180, "display.max_colwidth", 48)
print(f"candidatos evento-only (share >= {SHARE_MIN:.0%}, qty año >= {QTY_MIN}): "
      f"{len(C)} filas, {C['product_id'].nunique()} SKUs\n")
for ev, g in C.groupby("evento"):
    print("=" * 96)
    print(f"{ev}  (ventana {g['ventana'].iloc[0]})  — {len(g)} SKUs")
    print("=" * 96)
    show = g.head(20)[["producto", "categ", "qty_ano", "qty_ventana", "share"]]
    print(show.round(2).to_string(index=False))
    print()

# casos canonicos pedidos por Marco
print("=" * 96)
print("CHEQUEO CASOS CANONICOS (¿el detector los encuentra?)")
print("=" * 96)
full_names = pd.Series(names)
for patron in ["pascua", "cola de mono", "granadina", "pipe", "piña"]:
    hits = C[C["producto"].str.contains(patron, case=False, na=False)]
    if hits.empty:
        en_maestro = full_names[full_names.str.contains(patron, case=False)]
        print(f"  '{patron}': NO detectado "
              f"({'ni siquiera vendio en candidatos' if en_maestro.empty else 'revisar umbral'})")
    else:
        for _, h in hits.iterrows():
            print(f"  '{patron}': {h['producto'][:45]} -> {h['evento']} "
                  f"share {h['share']:.0%} ({h['qty_ventana']:.0f}/{h['qty_ano']:.0f} u)")

C[["evento", "producto", "categ", "qty_ano", "qty_ventana", "share",
   "ventana", "product_id"]].to_csv(
    OUT / "sku_evento_candidatos.csv", index=False,
    sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT / 'sku_evento_candidatos.csv'} (para curar a mano)")
