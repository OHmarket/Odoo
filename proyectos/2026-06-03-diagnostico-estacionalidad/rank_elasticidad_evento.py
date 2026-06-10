"""
Paso 2c.5 — ¿Existe "elasticidad a eventos" por categoria?

Modelo multiplicativo (ANOVA log-lineal, estandar en promo modeling):

    log(uplift[e,c,y]) = alpha[evento,year] + beta[categoria] + residuo

- beta = sensibilidad de la categoria a eventos EN GENERAL (la "elasticidad").
- alpha = intensidad de cada ocurrencia de evento.
- Si R2 es alto, el factor se factoriza y beta sirve de fallback para pares
  sin muestra. Los residuos grandes marcan pares IDIOSINCRATICOS (ej:
  espumantes x Ano Nuevo) que necesitan factor directo, no formula.

Lee lo ya medido (rank_lift_eventos_detalle.csv). Read-only.
Salida: resultados/elasticidad_evento_categ.csv + reporte.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "resultados"

det = pd.read_csv(OUT / "rank_lift_eventos_detalle.csv", sep=";", decimal=",",
                  encoding="utf-8-sig")
obs = (det.drop_duplicates(["evento", "year", "categoria"])
          [["evento", "arquetipo", "year", "categoria", "uplift_categ"]]
          .reset_index(drop=True))
obs["occ"] = obs["evento"] + " " + obs["year"].astype(str)
obs["y"] = np.log(obs["uplift_categ"])
print(f"observaciones evento-ano x categoria: {len(obs)} | "
      f"ocurrencias: {obs['occ'].nunique()} | categorias: {obs['categoria'].nunique()}")

# ----------------------------------------------------------------------
# ANOVA log-lineal con dummies (sin intercepto: alpha absorbe el nivel)
# ----------------------------------------------------------------------
occ_d = pd.get_dummies(obs["occ"], dtype=float)
cat_d = pd.get_dummies(obs["categoria"], dtype=float)
cat_d = cat_d.drop(columns=[cat_d.sum().idxmax()])   # referencia: categ con mas obs
X = np.hstack([occ_d.values, cat_d.values])
names = list(occ_d.columns) + list(cat_d.columns)
b, *_ = np.linalg.lstsq(X, obs["y"].values, rcond=None)
pred = X @ b
ss_res = float(np.sum((obs["y"] - pred) ** 2))
ss_tot = float(np.sum((obs["y"] - obs["y"].mean()) ** 2))
r2 = 1 - ss_res / ss_tot
obs["pred_factor"] = np.exp(pred)
obs["residuo"] = obs["uplift_categ"] / obs["pred_factor"]
print(f"R2 del modelo intensidad x sensibilidad: {r2:.3f}")

n_occ = occ_d.shape[1]
alpha = pd.Series(np.exp(b[:n_occ]), index=occ_d.columns, name="intensidad")
beta = pd.Series(np.exp(b[n_occ:]), index=cat_d.columns, name="sensibilidad")

pd.set_option("display.width", 160)
print("\n" + "=" * 78)
print("INTENSIDAD por ocurrencia de evento (alpha; nivel de la categ referencia)")
print("=" * 78)
print(alpha.sort_values(ascending=False).round(2).to_string())

print("\n" + "=" * 78)
print("SENSIBILIDAD a eventos por categoria (beta; 1.0 = igual a la referencia)")
print("=" * 78)
bshow = beta.sort_values(ascending=False)
bshow.index = [c.split("/")[-1].strip() for c in bshow.index]
print(pd.concat([bshow.head(12), bshow.tail(8)]).round(2).to_string())

print("\n" + "=" * 78)
print("PARES IDIOSINCRATICOS (|residuo| mayor): factor directo, no formula")
print("=" * 78)
idio = obs.loc[(obs["residuo"] - 1).abs().sort_values(ascending=False).index]
ishow = idio.head(12)[["evento", "year", "categoria", "uplift_categ",
                       "pred_factor", "residuo"]].copy()
ishow["categoria"] = ishow["categoria"].str.split("/").str[-1].str.strip()
print(ishow.round(2).to_string(index=False))

out = obs[["evento", "arquetipo", "year", "categoria", "uplift_categ",
           "pred_factor", "residuo"]]
out.to_csv(OUT / "elasticidad_evento_categ.csv", index=False,
           sep=";", decimal=",", encoding="utf-8-sig")
alpha.to_frame().to_csv(OUT / "elasticidad_intensidad_eventos.csv",
                        sep=";", decimal=",", encoding="utf-8-sig")
beta.to_frame().to_csv(OUT / "elasticidad_sensibilidad_categ.csv",
                       sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT / 'elasticidad_evento_categ.csv'} (+ intensidad/sensibilidad)")
