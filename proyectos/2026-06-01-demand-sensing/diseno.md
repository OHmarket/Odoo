# Demand sensing — medir el efecto del evento de precio, no estimarlo

## Problema (heredado del 2026-05-31)

Los outliers que matan la credibilidad son SKU con evento de precio. El **onset
es impredecible**: 4 métodos (factor elasticidad, share, damped, ancla mediana)
fallan porque intentan **adivinar** la magnitud antes de que exista dato
post-evento. El ancla mediana-4 además **lag-ea** (+0.71pp peor en ciclo completo)
porque en la semana del evento ancla al nivel pre-evento.

Ver [[ancla_mediana_descartada]] y `proyectos/2026-05-31-top-errores/registro.md` §6.

## Solución: demand sensing (canon SAP IBP / o9 / Blue Yonder)

No predecir el efecto — **medirlo** con señal de alta frecuencia (venta diaria) y
**resetear el nivel** cuando el nuevo nivel está confirmado. Por debajo es
change-point: detectar el salto rápido, no anticiparlo.

```
detector de precio (x_price_coreccion)  →  DISPARA la ventana de medición
venta diaria POS (pos.order.line)        →  SEÑAL (run-rate post-evento real)
x_stock_balance_daily (stockout)         →  CONTROL (medir solo días con stock)
regla de confirmación (N días sostenidos)→  declara "nuevo nivel"
                                         →  resetea nivel del forecast
mientras mide                            →  flag de baja confianza
```

**Clave:** se mide la magnitud (mata el subestimar 6-45× del factor), no se estima.
El día 1 sigue siendo impredecible (flag), pero el error pasa de semanas a días.

## Roles (no se reemplaza nada, se completa)

- **Detector de precio** = trigger (causa: precio cambió). Sigue igual.
- **Demand sensing** = magnitud (efecto medido). Reemplaza el factor multiplicativo
  ([HM SI Forecast.py:2762](../../02_forecast/HM SI Forecast.py#L2762)) que explotaba.
- **x_stock_balance_daily** = control de quiebre (no confundir colapso-precio con quiebre).

## Fase 0 — lo que falta cerrar (este proyecto)

1. **Fuente diaria:** snapshot `pos.order.line` por día × team × producto (cervezas, ~3m).
   Mismo pull que `pos_weekly`, bucket diario. Solo lectura.
2. **Regla de confirmación:** ¿cuántos días sostenidos para declarar "nuevo nivel"?
   Backtest sobre datos diarios — esta vez **ciclo completo**, no la ventana cómoda.
3. **Recién después:** ~3 campos en `x_price_coreccion` (no modelo nuevo) + reset en motor.

## RESULTADO Fase 0 (2026-06-01) — VALIDÓ ✅

Backtest amplio: TODAS las cervezas con evento (72 SKU), 10 semanas (onset+tail),
motor del harness, MM7 diario (regla: ds=MM7(cutoff)×7 si ≥7 días post-evento;
si no, FLAG). Cruzado con quiebre (`x_stock_balance_daily`, 1.743 quiebres):

| | motor | ds (limpio, sin quiebre) |
|---|---|---|
| solo-evento (ciclo completo) | 40.8 | **35.5** (−5.2pp) |
| ds-activo (post-confirmación) | 39.2 | **24.2** (−15.0pp) |

- **Genuino, no quiebre:** solo 3% de filas con quiebre; el win se sostiene al limpiar.
- **No es la ventana cómoda:** ciclo completo, incluido el onset (que va a FLAG, no
  empeora — a diferencia del ancla que metía +21pp ahí).
- **Contraste:** ancla mediana-4 semanal = +0.71pp PEOR; demand sensing = −5/−15pp MEJOR.
  Diferencia: granularidad diaria + flag en onset + medir (no estimar).

**Por qué funciona:** el ds es persistencia reciente (MM7≈semana previa). Gana en
SALTOS de nivel (eventos de precio); lag-ea en tendencias sostenidas. Para el caso
(saltos por precio) es apropiado.

## Pendiente antes de tocar producción

1. **Verificar vs motor de PRODUCCIÓN** (con `bias_outlier`) — el harness no lo tiene.
   Usar server W20-22 como baseline real.
2. **Diseño de implementación (Fase 1):** trigger (detector), regla de confirmación,
   reset de nivel en motor, ~3 campos en `x_price_coreccion`, gating de apagado.
3. Solo cervezas por ahora.

## Regla de oro (aprendida caro el 2026-05-31)

Medir primero, estructurar después. NO agregar campos ni tocar producción hasta
que el backtest valide la regla sobre el ciclo completo. **Cumplido: validó antes
de proponer cualquier cambio de modelo.**
