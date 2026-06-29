# Plan — Demand sensing (Fase 0: validar la regla antes de tocar nada)

## ESTADO (2026-06-01): Fase 0 CERRADA ✅ — siguiente en NUEVO HILO

Tareas 1-5 hechas y validadas (ver `diseno.md` §RESULTADO). El demand sensing
gana −15pp post-confirmación (limpio de quiebre), robusto, ciclo completo.

**Para retomar en el nuevo hilo de diseño (Fase 1):**
1. **Verificar vs motor de PRODUCCIÓN** (con `bias_outlier`) — el harness no lo
   tiene. Baseline: server `OH Forecast Backtest 30-05.csv` (W20-22). Comparar
   ds vs `forecast_qty` real para cervezas con evento.
2. **Diseñar Fase 1** (sin codear hasta aprobar):
   - Trigger: detector `x_price_coreccion` (active + reciente).
   - Regla de confirmación: ~7 días (calibrado), MM7 diario. Gating de apagado
     (¿cuántas semanas dura el ds antes de devolver al motor?).
   - Reset de nivel en motor: reemplazar el factor mult. de [HM SI Forecast.py:2762].
   - ~3 campos en `x_price_coreccion` (NO modelo nuevo): nivel_medido, dias_medidos,
     sensing_confirmado.
   - Manejo del FLAG (onset): baja confianza para operación.
3. Solo cervezas por ahora.

Memoria: [[demand_sensing_validado]].

## Tareas

1. **Snapshot diario** `pos.order.line` (cervezas, ~3m, agregado salas).
   `snapshot_pos_daily.py` → `pos_daily_cerv.parquet`. Solo lectura. ✅ probe OK, full corriendo.

2. **Explorar la serie diaria de los testigos** (Royal Guard, Cristal, Budweiser,
   Quilmes) alrededor de su evento (fecha del `x_price_coreccion`). Ver el
   **escalón**: ¿cuándo cambió el nivel y en cuántos días se estabilizó?

3. **Diseñar la regla de confirmación:**
   - ¿Cuántos días sostenidos para declarar "nuevo nivel"? (3 ruidoso ↔ 7 tarde)
   - ¿Cómo confirmar? (ej. run-rate de N días vs nivel previo, gate de persistencia)
   - Cuidado día-de-semana: medir sobre ≥7 días o normalizar intra-semana.

4. **Backtest CICLO COMPLETO** (no la ventana cómoda — lección 2026-05-31):
   ¿el nivel medido en N días post-evento predice las semanas siguientes
   **mejor que el motor**, incluyendo el onset? Métrica: error vs venta real
   semanal posterior.

5. **Cruce con quiebre** `x_stock_balance_daily` (`stockout`): medir el run-rate
   solo en días con stock, para no confundir colapso-precio con quiebre.

6. **Si valida → Fase 1/2:** ~3 campos en `x_price_coreccion` + reset de nivel en
   el motor ([HM SI Forecast.py:2762](../../02_forecast/HM SI Forecast.py#L2762)),
   reemplazando el factor multiplicativo.

## Criterio de éxito (Fase 0)

- La regla baja el error vs motor en los testigos **a lo largo de todo el evento**
  (onset + tail), no solo el tail.
- El lag de confirmación es **días**, no semanas.
- No regresa en SKU sin evento (la regla no se dispara ahí).

## Lo que NO se hace todavía

Agregar campos al modelo / tocar producción. Solo cuando el backtest valide.
