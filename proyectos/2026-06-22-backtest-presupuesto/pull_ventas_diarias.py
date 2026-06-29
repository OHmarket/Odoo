# -*- coding: utf-8 -*-
"""
Pull venta diaria por local (crm.team), read-only via XML-RPC.

Replica la fuente del presupuesto: sale_order + pos_order, sumados por
dia-local y por team. Usa read_group (agregado server-side), NO search_read
masivo (regla: no matar la cache del POS).

Guarda un parquet con columnas: day (date), team_id (int), amt (float).
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

import pandas as pd

# Mismos teams que el presupuesto productivo
FILTERED_TEAM_IDS = [18, 16, 12, 10, 9, 8, 7, 6, 5, 17, 13, 11]

# Ventana: necesitamos >=2 anos para backtest YoY. Desde 2024-01-01.
DATE_FROM = "2024-01-01 00:00:00"
DATE_TO = "2026-06-22 00:00:00"

o = OdooReader()

# ---- 1) sale_order agregado por dia + team ----
print("read_group sale_order...", flush=True)
so_groups = o.execute(
    "sale.order", "read_group",
    [
        ("state", "in", ["sale", "done"]),
        ("team_id", "in", FILTERED_TEAM_IDS),
        ("date_order", ">=", DATE_FROM),
        ("date_order", "<", DATE_TO),
    ],
    fields=["amount_total:sum"],
    groupby=["date_order:day", "team_id"],
    lazy=False,
)
print("  grupos:", len(so_groups), flush=True)

# ---- 2) pos_order agregado por dia + config_id (team via pos.config) ----
print("read pos.config map...", flush=True)
configs = o.search_read("pos.config", domain=[], fields=["crm_team_id"])
cfg_team = {}
for c in configs:
    t = c.get("crm_team_id")
    cfg_team[c["id"]] = (t[0] if t else None)

print("read_group pos_order...", flush=True)
po_groups = o.execute(
    "pos.order", "read_group",
    [
        ("state", "in", ["paid", "invoiced", "done"]),
        ("date_order", ">=", DATE_FROM),
        ("date_order", "<", DATE_TO),
    ],
    fields=["amount_total:sum"],
    groupby=["date_order:day", "config_id"],
    lazy=False,
)
print("  grupos:", len(po_groups), flush=True)

# ---- 3) consolidar ----
def parse_day(g, key):
    # read_group day granularity devuelve algo tipo "22 Jun 2026" o ISO segun locale.
    # Pedimos el __range cuando exista; fallback al label.
    rng = g.get("__range", {}) or {}
    sub = rng.get(key) or rng.get(key.split(":")[0])
    if sub and sub.get("from"):
        return sub["from"][:10]
    return None

daily = defaultdict(float)

for g in so_groups:
    day = parse_day(g, "date_order:day")
    t = g.get("team_id")
    tid = t[0] if isinstance(t, (list, tuple)) else t
    amt = g.get("amount_total") or 0.0
    if day and tid in FILTERED_TEAM_IDS:
        daily[(day, tid)] += amt

for g in po_groups:
    day = parse_day(g, "date_order:day")
    cfg = g.get("config_id")
    cid = cfg[0] if isinstance(cfg, (list, tuple)) else cfg
    tid = cfg_team.get(cid)
    amt = g.get("amount_total") or 0.0
    if day and tid in FILTERED_TEAM_IDS:
        daily[(day, tid)] += amt

rows = [{"day": d, "team_id": t, "amt": v} for (d, t), v in daily.items()]
df = pd.DataFrame(rows)
df["day"] = pd.to_datetime(df["day"])
df = df.sort_values(["team_id", "day"]).reset_index(drop=True)

out = Path(__file__).resolve().parent / "resultados" / "ventas_diarias.parquet"
df.to_parquet(out)
print("guardado:", out, "filas:", len(df), flush=True)

# ---- 4) validacion: totales por ano y por team ----
df["year"] = df["day"].dt.year
print("\n=== Total por ano (MM CLP) ===")
print((df.groupby("year")["amt"].sum() / 1e6).round(0))
print("\n=== Total 2025 por team (MM CLP) ===")
print((df[df.year == 2025].groupby("team_id")["amt"].sum() / 1e6).round(0).sort_values(ascending=False))
print("\n=== Rango fechas por team ===")
print(df.groupby("team_id")["day"].agg(["min", "max", "count"]))
