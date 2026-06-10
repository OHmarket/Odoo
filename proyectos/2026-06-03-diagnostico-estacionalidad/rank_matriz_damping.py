"""
Paso 2c.7 — Matriz de damping de verano por rank ABCXYZ.

Convierte lo medido en 2c.3 (amp_rel por rank) en una matriz aplicable:

    factor_sku = 1 + (factor_categ - 1) * d[rank]

Regla de promocion (anti-sobreajuste): d[rank] = amp_rel medido SOLO si el
CI 95% bootstrap excluye 1 y hay >= 5 celdas; si no, d = 1.0 (sigue a la
categoria). Eventos NO llevan damping (lift proporcional, paso 2c.2).

Lee resultados/rank_lift_verano_resumen.csv. Read-only.
Salida: resultados/matriz_damping_verano_rank.csv
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "resultados"
RANKS = ["AX", "AY", "AZ", "BX", "BY", "BZ", "CX", "CY", "CZ"]
MIN_CELDAS = 5

res = pd.read_csv(OUT / "rank_lift_verano_resumen.csv", sep=";", decimal=",",
                  encoding="utf-8-sig")
ver = res[res["segmento"] == "categ_verano"].set_index(res.columns[0])

rows = []
for r in RANKS:
    if r in ver.index:
        g = ver.loc[r]
        n = int(g["n_celdas"])
        med = float(g["amp_rel_mediana"])
        lo, hi = float(g["ci_lo"]), float(g["ci_hi"])
        significativo = (n >= MIN_CELDAS and not np.isnan(lo)
                         and (hi < 1.0 or lo > 1.0))
        d = round(med, 2) if significativo else 1.0
        rows.append(dict(rank=r, n_celdas=n, amp_rel_medido=round(med, 3),
                         ci_lo=lo, ci_hi=hi,
                         d_aplicar=d, evidencia="medido" if significativo
                         else "sin evidencia -> sigue a categ"))
    else:
        rows.append(dict(rank=r, n_celdas=0, amp_rel_medido=np.nan,
                         ci_lo=np.nan, ci_hi=np.nan, d_aplicar=1.0,
                         evidencia="sin celdas -> sigue a categ"))
M = pd.DataFrame(rows)

pd.set_option("display.width", 140)
print("MATRIZ DAMPING VERANO POR RANK  (factor_sku = 1 + (factor_categ-1)*d)")
print("eventos: d = 1.0 para todos (proporcional, paso 2c.2)\n")
print(M.round(3).to_string(index=False))

M.to_csv(OUT / "matriz_damping_verano_rank.csv", index=False,
         sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT / 'matriz_damping_verano_rank.csv'}")
