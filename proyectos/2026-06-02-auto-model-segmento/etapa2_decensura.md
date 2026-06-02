# Etapa 2 — De-censura de entrada por quiebre (LOCF)

**Fecha diseño:** 2026-06-02
**Estado:** diseño (no implementado)
**Depende de:** etapa 1 (modelo base AUTO) promovida en `02_forecast/OH Forecast Base.py`.

## Problema (Fase 0)

El modelo base usa input CRUDO. Cuando un combo estuvo en quiebre, su venta histórica
quedó **censurada a la baja** (no había stock que vender). El SES/Mediana, alimentado
por esa venta suprimida, pronostica bajo → se compra de menos → el producto sigue
quebrado. Círculo vicioso (confirmado en cigarros: cayeron a 28% del pico vs 42% del
resto del negocio — los 14pp extra son supresión por quiebre, no demanda).

## Qué decisión

Limpiar el input de las semanas con quiebre para que el forecast estime **demanda no
restringida** (lo que se habría vendido con stock), y reabastecer lo que corresponde.

## Qué pasa si se equivoca

- Si de-censura de más → over-forecast → sobre-stock (costo de capital).
- Si no de-censura → perpetúa el sub-stock de los productos que más rotan.
- Criterio del negocio: **sub-forecast cuesta más que over-forecast** → de-censurar es
  el lado correcto del error.

## Cómo lo hacen los grandes

SAP IBP / Blue Yonder: **demand unconstraining** — separar demanda de venta restringida
por supply antes de pronosticar. Reemplazar la venta de periodos con quiebre por la
demanda estimada del periodo.

## Enfoque elegido: LOCF (valor pre-quiebre)

Medido en `medir_decensura_entrada.py` (target SIN quiebre, 36.174 obs):

| método | WAPE | BIAS |
|--------|------|------|
| A crudo (referencia) | 62.84% | −2.72% |
| **D LOCF (pre-quiebre)** | **64.23%** | −2.19% |
| C imputa mediana | 65.19% | +1.01% |
| B excluye semana | 62.27% | −4.60% |

**LOCF gana entre los de-censura:** degrada menos el WAPE (64.23 vs 65.19 de mediana) y
queda más cerca del crudo en bias. Cambio local pequeño (reemplaza con el valor
inmediatamente anterior) vs la mediana que mete un nivel global y desplaza más.

**El WAPE SUBE vs crudo (62.8→64.2) y eso es ESPERADO/ACEPTADO:** sube porque el `real`
del backtest está censurado (no había qué vender), no porque el modelo empeore. Es
demanda no satisfecha hecha visible. NO se juzga esta capa por WAPE.

## Implementación (pendiente)

1. El script `OH Forecast Base.py` lee `x_stock_balance_daily` (o la fuente del flag de
   quiebre) y arma un set de (combo, semana) en quiebre dentro de la ventana de input.
2. Al construir el vector semanal de cada combo, reemplaza la venta de las semanas de
   quiebre por **LOCF** = el último valor observado en semana CON stock antes de esa.
3. Solo semanas de quiebre real → la baja estacional queda intacta ("lo otro es propio
   del negocio").
4. Clasificación (ADI/CV2) y SES/Mediana se calculan sobre el vector ya de-censurado.

## Medición (etapa 2 también define cómo medir)

El backtest debe poder mostrar el error **con y sin** exclusión de quiebre en el target,
para todos los productos (no solo cigarros). El error global subirá; se reporta limpio
(excluyendo target en quiebre: bias +4.59%→+1.14% ya medido) Y crudo, para no confundir
la capa de de-censura con un empeoramiento del modelo.

## Fuera de alcance

- Corrección estacional / índice de categoría (descartado: la baja post-verano es real
  del negocio, no se corrige).
- De-censura por mediana o exclusión (LOCF gana en backtest).
