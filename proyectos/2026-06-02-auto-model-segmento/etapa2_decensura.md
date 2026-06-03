# Etapa 2 — De-censura de entrada por quiebre

**Fecha diseño:** 2026-06-02
**Estado:** IMPLEMENTADO en `02_forecast/OH Forecast Base.py` v1.1 (pendiente validar en Odoo).
**Depende de:** etapa 1 (modelo base AUTO).

## RESOLUCIÓN FINAL — CLEANSING POR SEMANA (v1.2, validado en producción)

**Enfoque: demand unconstraining canónico (SAP IBP) — cleansing por SEMANA del input,
NO override por combo.** El override por combo (SMA12) solo tocaba combos con mucho
quiebre (21 cigarros), pero la contaminación es pervasiva (96% del volumen de cigarros
en combos con quiebre, mayoría smooth con quiebre de 1-6 días que el SMA12 no agarraba).

```
ANTES de clasificar/estimar, para cada combo y cada SEMANA:
  semana con quiebre (>= cleanse_min_days=1 día sin stock) →
       venta = max(promedio cleanse_base_weeks=6 sem in-stock previas, venta observada)
       (SOLO LEVANTA: venta <= demanda, nunca recorta -> respeta quiebre parcial que vendió bien)
luego modelo base sobre la serie LIMPIA:
  smooth → SES | erratic → SES(0.7) | intermittent/lumpy → SMA(6) | no_signal → Mediana(4)
```

- **Fuente quiebre:** `x_stock_balance_daily` (stockout OR stockout_partial OR
  qty_balance<=0). Query por (combo, semana) con `COUNT(DISTINCT date)`, escanea solo
  las últimas `cleanse_lookback_weeks=16` sem (acota el peso; el SMA6/SES no usan más atrás).
- **Data-driven, sin factor a dedo:** el cleansing recupera la supresión desde el dato
  de stock. El stock va hasta abr-2025 → recupera meses de supresión solo.
- **El WAPE sube vs crudo y es ESPERADO** (real censurado, no defecto del modelo).
  No se juzga esta capa por WAPE — es para reabastecer la demanda real.

## VALIDACIÓN EN PRODUCCIÓN (cigarros)

- Compra de cigarros: **9M → 14M** (cae en el rango realista 2025-limpio × 0.75 ≈ 14-16M).
- mu_total: 2.706 → 3.198 u/sem. El lift vino de los **smooth de alta rotación**
  (ses_a0.50: 1.551 → 2.713, +75%) — los que tenían quiebre pervasivo y el SES seguía
  hacia abajo. En valor pesan más (premium) → por eso saltó 9M→14M.
- Diagnóstico previo: 2026 cigarros al 36% del nivel limpio 2025 (may), por debajo del
  piso de invierno — supresión de meses (espiral de sub-compra), no estacionalidad.
  Confirmado: 78% combos / 96% volumen con quiebre reciente.

## Descartado en el camino

- **Factor YoY a dedo (2025 × 0.75):** Marco lo descartó ("poner a dedo") → mejor que
  fluya con el cleansing data-driven.
- **Override por combo (SMA12, ≥7 días):** muy grueso, no agarraba la contaminación pervasiva.
- **Mediana(4) en la cola:** daba ceros estructurales (≥3 de 4 sem en cero) → sub-stock.
  Reemplazada por SMA(6) en intermittent/lumpy; no_signal queda en Mediana (~0 correcto,
  no inflar casi-muertos). Artefactos: `cola_sma_largo.py`, `estimador_intermitente.py`,
  `cleansing_estimadores.py`, `nivel_forecast_cigarros.py`.

---

## (Histórico — diseños LOCF y SMA12-por-combo, reemplazados por el cleansing por semana)

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
