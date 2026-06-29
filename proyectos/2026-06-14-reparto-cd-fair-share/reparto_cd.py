# -*- coding: utf-8 -*-
"""
Reparto de oportunidad del CD por fair-share de cobertura (equalize days-of-supply).

Vacia el stock actual del CD hacia las salas, repartido para igualar dias de
cobertura, ponderado por mu_week. One-shot, READ-ONLY. Salida CSV (Excel-CL).

Ver diseno.md. No toca documentos ni el motor productivo.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd

# raiz del repo para importar shared/
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / "resultados"
OUT.mkdir(exist_ok=True)
(OUT / "por_sala").mkdir(exist_ok=True)

# warehouses que NO son destino de venta
EXCLUDE_WH = {15, 17}  # 15 = CD, 17 = Camioneta

# tope de cobertura: no empujar a ninguna sala mas alla de esto.
# Lo que exceda el tope queda retenido en CD.
MAX_COVER_WEEKS = 8.0

CSV_KW = dict(sep=";", decimal=",", encoding="utf-8-sig", index=False)


def _code_desc(label: str):
    """'[0255] BEBIDA COCA...' -> ('0255', 'BEBIDA COCA...')."""
    if not label:
        return "", ""
    m = re.match(r"\[([^\]]+)\]\s*(.*)", label)
    if m:
        return m.group(1), m.group(2)
    return "", label


def waterfill(salas, Q, cap=MAX_COVER_WEEKS):
    """
    salas: list de dict {team, wh, d, s}
    Q: stock CD entero a repartir.
    cap: tope de cobertura (semanas). Lo que exceda queda en CD.
    Retorna (alloc_dict {wh_key: qty_int}, Cstar, residual_int).
    residual_int = unidades que quedan en CD (por tope o redondeo).
    """
    Q = int(round(Q))
    elig = [x for x in salas if x["d"] > 0]
    if Q <= 0 or not elig:
        return {}, None, Q

    for x in elig:
        x["c"] = x["s"] / x["d"]

    def N(C):
        return sum(x["d"] * max(C - x["c"], 0.0) for x in elig)

    n_cap = N(cap)
    if n_cap <= Q:
        # el tope manda: llenar a todas hasta `cap`, el resto queda en CD
        Cstar = cap
        target = n_cap
    else:
        # biseccion N(C)=Q con Cstar <= cap
        lo, hi = min(x["c"] for x in elig), cap
        for _ in range(100):
            mid = (lo + hi) / 2.0
            if N(mid) < Q:
                lo = mid
            else:
                hi = mid
        Cstar = (lo + hi) / 2.0
        target = float(Q)

    raw = {x["wh"]: max(x["d"] * (Cstar - x["c"]), 0.0) for x in elig}
    target_int = int(round(target))

    floor_alloc = {k: int(v) for k, v in raw.items()}
    remainder = target_int - sum(floor_alloc.values())

    # largest-remainder: completa hasta target con mayor parte fraccionaria
    fracs = sorted(((raw[k] - floor_alloc[k], k) for k in raw), reverse=True)
    i = 0
    while remainder > 0 and fracs:
        _, k = fracs[i % len(fracs)]
        floor_alloc[k] += 1
        remainder -= 1
        i += 1

    alloc = {k: v for k, v in floor_alloc.items() if v > 0}
    residual = Q - sum(alloc.values())  # queda en CD (tope o redondeo)
    return alloc, Cstar, max(residual, 0)


def main():
    o = OdooReader()
    print("Conectado:", o)

    rows = o.search_read(
        "x_analisis_de_stock",
        domain=[("x_studio_stock_central", ">", 0)],
        fields=[
            "x_studio_product_id",
            "x_studio_warehouse_id",
            "x_studio_mu_week",
            "x_studio_demanda_semanal",
            "x_studio_stock_effective",
            "x_studio_stock_central",
        ],
    )
    print("filas con stock CD>0:", len(rows))

    # agrupar por tmpl
    tmpls = {}
    for r in rows:
        prod = r.get("x_studio_product_id")
        wh = r.get("x_studio_warehouse_id")
        if not prod or not wh:
            continue
        wh_id = wh[0]
        if wh_id in EXCLUDE_WH:
            continue
        tmpl_id = prod[0]
        code, desc = _code_desc(prod[1])
        d = float(r.get("x_studio_mu_week") or 0.0)
        if d <= 0:
            d = float(r.get("x_studio_demanda_semanal") or 0.0)
        s = float(r.get("x_studio_stock_effective") or 0.0)
        Q = float(r.get("x_studio_stock_central") or 0.0)
        t = tmpls.setdefault(
            tmpl_id, {"code": code, "desc": desc, "Q": Q, "salas": []}
        )
        t["Q"] = max(t["Q"], Q)  # stock CD por SKU (mismo en todas las filas)
        t["salas"].append({"wh": wh_id, "name": wh[1], "d": d, "s": s})

    print("SKUs distintos con stock CD:", len(tmpls))

    master_recs = []
    residual_recs = []
    for tmpl_id, t in tmpls.items():
        Q = t["Q"]
        alloc, Cstar, residual = waterfill(
            [dict(s) for s in t["salas"]], Q
        )
        if not alloc:
            # Cstar None  -> ninguna sala con demanda; si no -> todas sobre el tope
            if Cstar is None:
                motivo = "ninguna sala vende (mu_week=0)"
            else:
                motivo = ("todas las salas ya superan el tope %g sem"
                          % MAX_COVER_WEEKS)
            residual_recs.append(
                {
                    "codigo": t["code"],
                    "descripcion": t["desc"],
                    "stock_cd": int(round(Q)),
                    "retenido_cd": int(round(Q)),
                    "motivo": motivo,
                }
            )
            continue
        name_by_wh = {s["wh"]: s["name"] for s in t["salas"]}
        d_by_wh = {s["wh"]: s["d"] for s in t["salas"]}
        s_by_wh = {s["wh"]: s["s"] for s in t["salas"]}
        for wh, qty in alloc.items():
            d = d_by_wh[wh]
            s0 = s_by_wh[wh]
            master_recs.append(
                {
                    "codigo": t["code"],
                    "descripcion": t["desc"],
                    "sala": name_by_wh[wh],
                    "mu_week": round(d, 2),
                    "stock_actual": round(s0, 1),
                    "cover_actual_sem": round(s0 / d, 2) if d > 0 else None,
                    "qty_asignada": qty,
                    "cover_post_sem": round((s0 + qty) / d, 2) if d > 0 else None,
                    "pct_del_cd": round(100.0 * qty / Q, 1) if Q > 0 else 0.0,
                }
            )
        if residual > 0:
            residual_recs.append(
                {
                    "codigo": t["code"],
                    "descripcion": t["desc"],
                    "stock_cd": int(round(Q)),
                    "retenido_cd": residual,
                    "motivo": "retenido en CD (excede tope %g sem)" % MAX_COVER_WEEKS,
                }
            )

    master = pd.DataFrame(master_recs).sort_values(
        ["sala", "descripcion"]
    )
    master.to_csv(OUT / "master.csv", **CSV_KW)

    if residual_recs:
        pd.DataFrame(residual_recs).to_csv(OUT / "residual.csv", **CSV_KW)

    # por sala
    for sala, g in master.groupby("sala"):
        safe = re.sub(r"[^\w\-]+", "_", str(sala))
        g[["codigo", "descripcion", "qty_asignada", "cover_post_sem"]].to_csv(
            OUT / "por_sala" / ("%s.csv" % safe), **CSV_KW
        )

    # resumen
    total_cd = sum(int(round(t["Q"])) for t in tmpls.values())
    repartido = int(master["qty_asignada"].sum())
    resumen = (
        master.groupby("sala")
        .agg(skus=("codigo", "nunique"), unidades=("qty_asignada", "sum"))
        .reset_index()
        .sort_values("unidades", ascending=False)
    )
    resumen.to_csv(OUT / "resumen.csv", **CSV_KW)

    retenido = total_cd - repartido
    print("\n=== RESUMEN (tope %g sem) ===" % MAX_COVER_WEEKS)
    print("SKUs con stock CD:", len(tmpls))
    print("Unidades totales en CD:", total_cd)
    print("Unidades repartidas:", repartido,
          "(%.1f%%)" % (100.0 * repartido / total_cd if total_cd else 0))
    print("Unidades retenidas en CD:", retenido,
          "(%.1f%%)" % (100.0 * retenido / total_cd if total_cd else 0))
    print("SKUs sin sala que venda (quedan completos en CD):",
          sum(1 for r in residual_recs if "ninguna" in r["motivo"]))
    print("\nPor sala:")
    print(resumen.to_string(index=False))
    print("\nCSVs en:", OUT)


if __name__ == "__main__":
    main()
