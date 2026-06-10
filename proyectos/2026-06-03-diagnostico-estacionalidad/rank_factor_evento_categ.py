"""
Paso 2c.4 — Tabla de factores evento x categoria (el proxy por SKU).

Conclusion del paso 2c: el evento sube la categoria de forma proporcional
entre ranks -> el proxy de crecimiento por SKU en evento es el factor de su
categoria aplicado al baseline del SKU:

    venta_sku(sem_evento) = baseline_sku x factor(evento, categ)

Este script solo agrega lo ya medido en rank_uplift_eventos.py: dedupe del
uplift_categ por evento x ano x categoria y mediana entre anos, con flag de
senal (consistencia y magnitud).

Read-only (lee resultados/). Salida: resultados/factor_evento_categ.csv
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "resultados"
MIN_UPLIFT = 1.20      # umbral de "senal real" (mismo del paso 2c.2)

det = pd.read_csv(OUT / "rank_lift_eventos_detalle.csv", sep=";", decimal=",",
                  encoding="utf-8-sig")
# una fila por evento x ano x categoria (uplift_categ viene repetido por rank)
cat = (det.drop_duplicates(["evento", "year", "categoria"])
          [["evento", "arquetipo", "year", "categoria", "uplift_categ"]])

tab = (cat.groupby(["evento", "arquetipo", "categoria"])
          .agg(n_anos=("year", "nunique"),
               factor=("uplift_categ", "median"),
               factor_min=("uplift_categ", "min"),
               factor_max=("uplift_categ", "max"))
          .reset_index())
# senal: factor >= umbral y, si hay 2 anos, ambos sobre 1 (consistencia)
tab["senal"] = (tab["factor"] >= MIN_UPLIFT) & (tab["factor_min"] > 1.0)
tab = tab.sort_values(["evento", "factor"], ascending=[True, False])

pd.set_option("display.width", 160)
print(f"pares evento x categoria: {len(tab)} | con senal real: {tab['senal'].sum()}")
print("\nTOP 5 categorias por evento (solo con senal):")
top = (tab[tab["senal"]]
       .assign(categ=lambda d: d["categoria"].str.split("/").str[-1].str.strip())
       .groupby("evento").head(5))
print(top[["evento", "arquetipo", "categ", "n_anos", "factor", "factor_min",
           "factor_max"]].round(2).to_string(index=False))

tab.to_csv(OUT / "factor_evento_categ.csv", index=False,
           sep=";", decimal=",", encoding="utf-8-sig")
print(f"\n-> {OUT / 'factor_evento_categ.csv'}")
