# CIERRE Fase 1 — Monitor de error por impacto-$

Corrida: 4 semanas (2026-05-11 a 2026-06-01), 72.614 filas backtest, sala San José excluida.
Métrica: pinball asimétrica (K_UNDER=2, K_OVER=1) × list_price c/IVA. PROXY de impacto-$.

## Resultado: impacto-$ por causa

| Causa | Impacto-% | ¿Corregible por forecast? |
|---|---|---|
| cola_intermitente | 33.1% | No. Ruido de proceso puntual; Croston/SBA ya descartados (sobre-pronostican). |
| smooth_real | 25.2% | No. **BIAS −2.2% ≈ 0 → varianza irreducible**, no sesgo (confirma 2026-06-05). |
| quiebre | 19.6% | No aplica. `real` censurado por stockout → artefacto, se excluye. |
| evento | 13.3% | **Sí (único bucket).** Demanda movida por precio/promo. Candidato a demand sensing. |
| fantasma | 8.8% | No es forecast. Surtido / stock muerto en SKU que no vendió. |

Impacto-$ total (proxy): ~369M (con IVA, no es pérdida real; es ranking de plata en riesgo).

## Hallazgos

1. **El error NO se concentra en "top SKUs corregibles".** smooth_real top10 SKU = 18%,
   top50 = 46% de 644 SKU, y con sesgo ~0. No hay un puñado de SKUs con error sistemático
   que un agente pueda arreglar. Confirma con datos la conclusión de `2026-05-31-top-errores`.

2. **Solo ~13% del impacto-$ está en el bucket corregible (evento).** El resto es ruido
   irreducible (cola 33% + varianza smooth 25% = 58%), dato censurado (quiebre 20%) o surtido
   (fantasma 9%). Ningún "agente que corrige top SKUs" mueve eso — coincide con la disciplina
   FVA (overrides de juicio = valor agregado negativo sobre ruido).

3. **El lever más grande NO es forecast.** fantasma (9%) + el neto de sobre-forecast de la
   cola alimentan compra de stock que no rota → conecta con el sangrado de inventario
   (`project_flujo_caja_12m`). Es un proyecto de **surtido / des-listado**, no de precisión.

4. **La validación canónica pasa:** el ranking por impacto-$ saca a flote las cervezas y
   destilados de evento conocidos (Stella 660, JW Red Label → etiquetados `evento`).

## Veredicto sobre Fase 2 (demand sensing FVA-gated)
- Techo realista: actúa sobre el 13% (evento). Evidencia previa recupera −5/−15pp WAPE
  en ese subconjunto → ~3-5% del impacto-$ total como prize neto tras gate FVA.
- Es positivo pero **acotado**. No mueve el WAPE de catálogo de forma visible; mueve el $
  de un subconjunto chico de SKUs de evento (alto valor unitario).
- Decisión abierta para el usuario: construir Fase 2 (prize acotado, ya con receta validada)
  vs. pivotar al lever de surtido (fantasma + cola over-forecast → stock muerto), que es
  mayor en $ pero es otro proyecto.

## Entregables (resultados/)
- `resumen_por_causa.csv` — impacto-$ y % por bucket.
- `ranking_impacto_fila.csv` — top filas (SKU·sala·semana) por impacto-$.
- `ranking_impacto_sku.csv` — top SKU agregados por impacto-$ con causa dominante.

## Recurrencia
`python monitor_error.py --weeks N` corre read-only sobre las últimas N semanas del backtest.
Sirve como monitor de excepción periódico (FVA exception report).
