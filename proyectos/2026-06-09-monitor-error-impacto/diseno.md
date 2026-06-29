# Monitor de error de forecast por impacto-$ (Fase 1)

## Qué problema resuelve
El backtest mide WAPE/BIAS por fila, pero el WAPE plano trata igual un error de
1 unidad en un vino de $1.000 que en un destilado de $40.000. La decisión comercial
(¿dónde mirar / qué corregir?) necesita rankear el error por **plata en riesgo**, no
por porcentaje. Y necesita decir **por qué** falla cada fila para no perseguir ruido
irreducible.

## Qué decisión se toma con el resultado
1. Saber si existe un bucket de error **accionable** (no ruido, no quiebre, no surtido)
   que justifique construir la capa de corrección (Fase 2).
2. Priorizar el subconjunto de SKUs-sala donde una corrección rinde en $.
3. Confirmar/refutar con datos la conclusión de `2026-05-31-top-errores` (el error grande
   es por evento de precio/promo con onset impredecible, no corregible post-hoc).

## Qué pasa si el modelo se equivoca
Es read-only y diagnóstico: el riesgo es priorizar mal dónde mirar. Cero riesgo operativo
(no toca forecast ni compras). El gate FVA de Fase 2 atrapa cualquier corrección mala.

## Cómo lo resuelven los grandes (modelo canónico)
- **Forecast Value Added (FVA)** — Gilliland (SAS/IBF), SAP IBP exception management:
  no todo error se corrige; el override de juicio suele tener valor agregado negativo.
  Primero medir el impacto y la causa, recién después intervenir y solo si vence al naive.
- **Pinball / quantile loss asimétrica** — estándar para costo de error de inventario:
  el sub-forecast (quiebre, venta perdida) cuesta más que el sobre-forecast (capital
  inmovilizado). Se pondera por valor del ítem para llevar el error a $.

## Métrica de impacto (PROXY documentado)
```
pinball_unidades = K_UNDER * max(real - fcst, 0) + K_OVER * max(fcst - real, 0)
impacto_$        = pinball_unidades * list_price
```
- `K_UNDER = 2.0`, `K_OVER = 1.0` → **PROXY**: el ratio 2:1 es supuesto de negocio
  (quiebre cuesta ~2× el sobrestock), no calibrado con margen/costo de capital reales.
  Calibrar contra margen (`x_margen_por_producto_`) y costo de capital es deuda futura.
- `list_price` del maestro **incluye IVA** (memoria `ref_list_price_iva`); es proxy del
  valor del ítem, no del margen. Suficiente para rankear, no para reportar pérdida absoluta.

## Clasificación de causa (por fila de alto impacto)
Orden de prioridad (la primera que aplica gana):
1. **quiebre** — la semana tuvo stockout en `x_stock_balance_daily` para ese (producto,
   sala). El `real` está censurado → el "error" es artefacto. Se MARCA y se EXCLUYE del
   error accionable (evita doble conteo — memoria `feedback_doble_conteo_decensura`).
2. **fantasma** — `real=0` y `fcst>0`. Forecast sobre SKU que no vendió → problema de
   surtido/catálogo, no de precisión de forecast.
3. **evento** — la semana cruza con `x_price_change_event` (is_real_change) o
   `x_loyalty_promo_event` para ese producto. Demanda movida por precio/promo → candidato
   a Fase 2 (demand sensing). ÚNICO bucket con evidencia de mejora.
4. **cola/intermitente** — `series_type` ∈ {lumpy, intermittent, no_signal}. Ruido de
   proceso puntual; Croston/SBA ya probados y descartados. No accionable.
5. **smooth_real** — lo que queda: serie suave, vendió, sin evento ni quiebre. El residual
   "accionable" puro. La hipótesis (2026-05-31 + 2026-06-05) es que este bucket es CHICO y
   su error es varianza irreducible, no sesgo corregible.

## Filtros de medición limpia (memoria forecast_noise_feedback)
- Excluir filas con quiebre del cómputo de error accionable.
- Excluir sala **Ventas San José**.
- NO excluir categorías enteras.

## Casos canónicos de validación
- El ranking por impacto-$ debe sacar a flote SKUs de **evento** conocidos (cervezas:
  Budweiser, Royal Guard, Quilmes — los del `2026-05-31-top-errores`).
- El bucket **smooth_real** debe ser chico (consistente con "no hay top SKUs que arreglar").
- Si el grueso del impacto-$ cae en **evento**, Fase 2 se justifica solo para ese subconjunto.

## Enfoques considerados
- A) Rankear por WAPE/APE → descartado: ignora el valor del ítem, persigue baja rotación.
- B) Rankear por error absoluto en unidades → descartado: ignora precio y dirección.
- C) **Pinball asimétrica × list_price + clasificación de causa** → elegido: lleva el error
   a $, castiga el sub-forecast, y separa lo accionable del ruido. Canónico (FVA + pinball).

## Fuera de alcance (Fase 1)
- No corrige forecast (eso es Fase 2, condicional al resultado).
- No calibra K_UNDER con margen real (PROXY hoy).
- No toca el motor ni el pipeline productivo.
