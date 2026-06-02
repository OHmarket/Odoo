# CIERRE — Backtest 2026-06-01 — SMA(4) reemplaza HM-SI

**Cambio:** Motor HM-SI (v3.46, 2.900 líneas) → **SMA(4) puro** (promedio simple de 4 semanas)
**Período:** W21-W23/2026 (May 11/18/25), head-to-head controlado mismas semanas
**Fecha:** 2026-06-01
**Aprobado por:** Marco Sanhueza

---

## ORIGEN

Operaciones pronostica con **promedio simple de 4 periodos** en Excel. Se aplicó
FVA (Forecast Value Added, canon SAP/Gartner): medir el motor complejo contra ese
naive. Veredicto: **el motor NO le gana al promedio-4.** Se reemplaza por SMA(4).

## RESUMEN EJECUTIVO (head-to-head, core, mismas 3 sem, sin San José)

| Métrica | Motor HM-SI v3.49 | SMA(4) | Ganador |
|---------|---|---|---|
| **WAPE** | 57.8% | **54.3%** | SMA(4) (−3.5pp) |
| **BIAS** | +12.7% | **+5.9%** | SMA(4) (mitad de sesgo) |
| **REG-1** (68% vol) | 52.4% | **48.9%** | SMA(4) |
| **REG-8** | 77.7% | **72.9%** | SMA(4) |
| Forecast NaN | 0 | 0 | — |

Vs el motor complejo v3.46 (CIERRE 26-05): REG-1 era **53.5%** → SMA(4) lo deja en **48.9%** (−4.6pp).

**Veredicto:** ✅ SMA(4) PROMOVIDO

## POR QUÉ PIERDE EL MOTOR

El over-forecast del motor (+17% bias en FVA full) venía de capas que agregan
varianza sin precisión: roundtrip de **SI** per-celda (ruido), **de-censura** de
quiebre, **bias-outlier** [0.65,4.0] que amplifica, y la **base lenta**. Apagar
todo (v3.49) bajó el bias a +12.7%, pero aún +7pp sobre el SMA(4) puro por la
maquinaria residual (combos, fair-share, caps, bake-off). SMA(4) puro las elimina.

## DÓNDE PIERDE EL SMA(4) (aceptado)

REG-7 (intermitente, 3% vol): el SMA(4) sub-pronostica las series con muchos ceros
(el motor las manejaba con Croston). Trade-off aceptado: simplicidad + ganancia en
el 97% del volumen vale más que la cola intermitente.

## IMPLEMENTACIÓN

- **Nuevo:** `02_forecast/OH SMA4 Forecast.py` v1.0 (Server Action 1576).
  mu_week = promedio de las 4 semanas cerradas previas (venta cruda combo-expandida),
  sigma = std. Escribe a `x_hm_si_forecast.x_studio_mu_week` (mismo contrato).
  Opción `agg='median'` disponible (Mediana(4) dio marginalmente mejor; no se eligió
  por alineación con el método del negocio).
- **Motor HM-SI** (`HM SI Forecast.py`, SA 1553): quedó en v3.49 (neutralizado),
  archivado como rollback.
- **Backtest** (`OH Forecast Backtest.py`): apunta a SA 1576, de-censura off.

## VALIDACIÓN

- **Paridad:** `forecast_qty` del servidor == SMA(4) calculado local: diff máx
  0.0000, corr 1.000000, 0 discrepancias. El servidor calcula SMA(4) exacto, sin
  look-ahead (promedio de las 4 PREVIAS, `shift(1)`).

## PENDIENTE

- **Deploy:** repuntar el cron del forecast de SA 1553 → SA 1576 (decisión de Marco).
- Si el sub-forecast de REG-7/REG-8 duele, evaluar híbrido SMA(4)+Croston para
  series intermitentes.

---

**Detalle:** `proyectos/2026-06-01-fva-vs-sma4/` (FVA, bake-off, validación).
**Snapshot:** `02_forecast/analisis backtest/2026-06-01/SNAPSHOT.md`.
