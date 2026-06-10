"""Cobertura efectiva por rank: H + z*CV*sqrt(H) en dias, con CV reales."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import numpy as np
import pandas as pd
from shared.odoo_xmlrpc import OdooReader

Z = {"AX": 1.68, "BX": 1.68, "AY": 1.68, "BY": 1.28, "AZ": 1.04,
     "CX": 0.84, "BZ": 0.35, "CY": 0.35, "CZ": 0.0}
BIAS_MOTOR = 0.07          # sesgo medido del motor (~+7% smooth, proy 2026-06-05)
H_LIST = [1.0, 15/7, 30/7]  # periodos tipicos: 7, 15, 30 dias

o = OdooReader()
rows, off = [], 0
while True:
    ch = o.search_read("x_calculo_abc_xyz", domain=[],
                       fields=["x_studio_abcxyz", "x_studio_cv"],
                       limit=5000, offset=off, order="id")
    rows.extend(ch)
    if len(ch) < 5000:
        break
    off += 5000
df = pd.DataFrame([(r.get("x_studio_abcxyz"), r.get("x_studio_cv"))
                   for r in rows], columns=["rank", "cv"])
df = df[(df["rank"].notna()) & (df["cv"] > 0)]
cv_med = df.groupby("rank")["cv"].median()

out = []
for rank in ["AX", "AY", "AZ", "BX", "BY", "BZ", "CX", "CY", "CZ"]:
    cv = cv_med.get(rank, np.nan)
    z = Z[rank]
    row = {"rank": rank, "z": z, "cv_mediano": round(cv, 2)}
    for H in H_LIST:
        dias_nom = H * 7
        # cobertura = (mu*H + z*sigma*sqrt(H)) / mu = H + z*cv*sqrt(H) semanas
        cob_sem = H + z * cv * (H ** 0.5)
        cob_dias = cob_sem * 7
        cob_dias_bias = cob_dias * (1 + BIAS_MOTOR)
        row[f"P{int(dias_nom)}d_nominal"] = int(dias_nom)
        row[f"P{int(dias_nom)}d_efectivo"] = round(cob_dias, 1)
        row[f"P{int(dias_nom)}d_con_bias"] = round(cob_dias_bias, 1)
    out.append(row)
T = pd.DataFrame(out)
pd.set_option("display.width", 170)
print("COBERTURA EFECTIVA EN DIAS (target/mu), CV mediano real por rank")
print("  efectivo = periodo + z*CV*sqrt(H) | con_bias = x1.07 (sesgo motor)")
print(T.to_string(index=False))
print("\nNota: CZ usa regla especial min(2 sem, H) sin safety. +2 dias extra solo solo_bodega.")
