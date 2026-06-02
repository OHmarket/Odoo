# FVA — HM-SI vs Excel SMA(4)

**Fecha:** 2026-06-01
**Estado:** Fase 1 (medición read-only)

## Qué medimos
Forecast Value Added: ¿el motor HM-SI le gana al método incumbente (Excel de
promedio móvil de 4 semanas) en exactitud de pronóstico?

## Qué decisión
- Si HM-SI **NO** le gana a SMA(4) → el motor no se justifica vs el Excel; el
  60% de WAPE es complejidad sin valor.
- Si le gana → el 60% es el precio de la granularidad (SKU×sala×semana) y el
  motor agrega valor medible.

## Si se equivoca
Un naive mal construido mata o salva el motor injustamente. Mitigación: el
SMA(4) usa el **mismo `real_qty`** del backtest, mismo universo, mismo redondeo.
Una sola vara.

## Cómo lo hacen los grandes
Forecast Value Added (Gilliland / SAS, "lean forecasting"): se compara el modelo
contra un naive. SMA(4) = naive estándar, y acá es literalmente el método que el
negocio usa hoy en Excel.

## Baseline elegido
SMA(4) crudo = promedio del `real_qty` de las 4 semanas previas (replica el Excel
exacto). Descartado: nonzero-average (sesga alto), seasonal-naive (no hay año
previo limpio).

## Datos
- Fuente: `OH Forecast Backtest (x_forecast_backtest) (3).csv` — 6 semanas
  consecutivas (04-20 → 05-25), trae `forecast_qty` (HM-SI) y `real_qty`.
- Universo: modelos core (hm_si_core, _a_low_mu, _az, fair_share_canon),
  sin Ventas San José, sin quiebre en la semana target (`x_stock_balance_daily`).
- Cruce de IDs: `x_name` = `hm_si | sem | T<crm.team> | P<product.product>` →
  join directo por id con stock balance.

## Cobertura
SMA(4) limpio solo en semanas con 4 previas dentro de la ventana:
**05-18 y 05-25** (2 semanas target). El resto carece de historia suficiente.

## Caso canónico
SMA(4) de un SKU conocido debe coincidir con el promedio de sus 4 celdas en el
Excel del negocio.

---

## Resultados (2026-06-01)

### FVA HM-SI vs SMA(4) — enero→mayo (CSV (4), 21 sem)
- `fva_hist.py` (sin quiebre, 17 sem eval): **FVA −3.9%** — el Excel SMA(4) le
  gana al motor. Motor WAPE 63.1% bias +17.4% vs SMA4 60.7% bias +13.8%.
- `fva_hist_quiebre.py` (con exclusión de quiebre, solo 6 sem cubiertas):
  **FVA −8.1%** — al limpiar quiebre el over-forecast del motor queda más expuesto
  (bias +15.1%). El motor solo gana en el bloque de caída brusca 23-feb→16-mar.

### Bake-off de modelos simples — campeón ahora = SMA(4) (`bakeoff_simple.py`)
Pregunta: ¿hay un modelo simple que le gane al SMA(4)? **Sí.** Robusto en ventana
≥4 (17 sem, feb→may) y ≥8 (13 sem, mar→may). FVA vs SMA(4), ventana full:

| Modelo | FVA vs SMA4 | nota |
|--------|-------------|------|
| SES(0.5) | +5.2% | mejor WAPE |
| WMA(4) [1,2,3,4]/10 | +4.4% | explicable al negocio |
| Mediana(4) | +3.2% | menor bias (+5.6%), menos sobre-stock |
| SMA(3) | +2.8% | |
| Naive | +0.2% | artefacto de caídas, descartado |
| Holt / Holt-damp / Drift | −3% / ~0 / −24% | tendencia explícita FRACASA |
| SMA(6) / SMA(8) | −14% / −34% | suavizar más empeora |

**Hallazgo:** la palanca es **reaccionar más rápido** (recency-weighting), no la
tendencia explícita. El SMA(4) sobre-suaviza (bias +13%). Cross-check OK: SMA(4)
WAPE 63.15% y Motor FVA −4.3% vs SMA4.

**Recomendación:** WMA(4) (o Mediana(4) si el dolor es sobre-stock).

### Pendiente
- Corte con quiebre sobre todo el período (regenerar `stockout` ene→may).
- Llevar el modelo elegido al pipeline productivo de Odoo.

### Nota técnica
Clave-combo del harness = `product_id` COMPLETO (default_code alfanumérico tipo
`[VN18087]`, a veces sin código) + `team_id`. NO extraer id numérico (falla en
26% de las filas → claves duplicadas → explosión de memoria en el merge).
