# Implementación capa demand sensing (Fase 1 productiva)

Gate vs motor actual (Forecast Base v1.6): PASÓ. Solo-evento limpio −1.86pp,
ds-activo limpio −2.87pp WAPE sobre 72 cervezas de evento, ciclo completo, 3% quiebre.
Ver `gate_vs_base.py`. Alcance elegido: capa automatizada + señal diaria. Solo cervezas.

## Arquitectura (capa post-forecast, NO toca el motor)

```
[OH Forecast Base.py]  → x_hm_si_forecast.x_studio_mu_week   (por team×producto)
        │ (pipeline corre después)
        ▼
[OH Demand Sensing.py] (Server Action NUEVA)
   1. universo evento: x_price_coreccion (|var_pct|>0) cervezas → pid, fecha evento
      ⚠️ TRIGGER = x_price_coreccion, NO x_price_change_event. Con x_price_change_event
      el ds es net NEGATIVO (+1.9pp, validar_layer.py). El gate y validar_layer_pcorr.py
      validaron con x_price_coreccion (−1.4/−2.0pp).
   2. señal diaria = SUMA venta últimos 7 días (un read_group pos.order.line) = MM7×7
   3. ds-activo si días_post≥7 y sin quiebre material (x_stock_balance_daily ≥3 salas)
   4. factor_producto = (venta_7d) / motor_total_producto   (acotado [0.2, 5.0])
   5. escribe x_hm_si_forecast.x_studio_mu_week_adjusted = mu_week × factor
      SOLO en filas ds-activas; resto queda en False (passthrough)
        │
        ▼
[OH Analisis de Stock.py]  lee COALESCE(mu_week_adjusted, mu_week)
```

## Por qué NO un cron diario separado (decisión de ingeniería)

El usuario pidió "snapshot diario + cron". **Recomiendo computar la señal diaria
on-demand dentro de la Server Action**, en vez de un cron nocturno que persista un
modelo diario nuevo. Razones:
- El universo que necesita señal diaria son los **SKUs con evento activo** (decenas),
  no el catálogo. `read_group` de `pos.order.line` por día sobre esos pids es barato.
- Un cron nocturno es infra que **se atrasa en silencio** (precedente:
  `x_loyalty_promo_event` sin cron, memoria `ref_loyalty_promo_event_feed`). On-demand
  no puede quedar stale: usa la venta hasta el cutoff cada vez que corre.
- Misma automatización (cero paso manual), menos superficie de falla.

Si se quiere **traza de auditoría** del run-rate diario, se agrega después un modelo
`x_pos_daily_event` alimentado por la misma SA (escribe lo que ya calcula). Opcional,
no bloquea.

## Factor por producto aplicado por team (PROXY documentado)

El gate validó a nivel **producto-total** (suma de teams). El forecast productivo es
por (team, producto). La señal diaria por team es demasiado rala para MM7. Solución:
calcular el **shift de nivel a nivel producto** (factor = ds_total/motor_total) y
aplicarlo multiplicativo a cada team. Re-sumando da exactamente el ds_total del gate
→ el WAPE a nivel producto es idéntico al validado. Supuesto: el evento de precio
mueve a todas las salas proporcionalmente (razonable para cambio de precio de cadena).
**PROXY**: reparto proporcional, no medido por sala. Cota [0.2, 5.0] evita explosiones.

## Cambios concretos
1. **Studio**: campo nuevo `x_studio_mu_week_adjusted` (float) en `x_hm_si_forecast`.
2. **Server Action nueva** `OH Demand Sensing` (en pipeline, después de Forecast Base):
   `02_forecast/OH Demand Sensing.py`. LOCK_KEY nuevo (revisar `ref_lock_keys`).
3. **Patch** `03_stock/OH Analisis de Stock.py` ~L1457/1486:
   - añadir `x_studio_mu_week_adjusted` a `fwd_read_fields`.
   - `mu_week = _safe_float(r.get('x_studio_mu_week_adjusted') or r.get('x_studio_mu_week'), 0.0)`.
3b. **OH Forecast Backtest.py**: opcional, leer el adjusted para medir la capa en el backtest.

## Gating de apagado
- Constante `DS_ENABLED` en la SA. Si False, no escribe nada → Stock cae a mu_week base.
- `DS_CATEG_FILTER = 'Cerveza'` (solo cervezas; ampliar tras nuevo gate).
- Si la señal diaria falta para un pid (cutoff fuera de rango) → no escribe (passthrough).

## Validación antes de promover
- `validar_layer.py`: reproduce el factor y el mu_adjusted desde el backtest live +
  caches, y confirma que el WAPE del adjusted = el del gate (−1.86/−2.87pp). Apples-to-apples.
- Promoción (usuario corre, confirma, luego git): crear campo Studio → pegar SA y
  encadenar en el cron del pipeline → aplicar patch Stock → correr 1 semana y revisar.

## Dependencias / riesgo de doble corrección
- `x_price_coreccion` ya tiene `x_studio_factor_corr` (corrección de precio por
  elasticidad) y campos de sensing nacientes (`x_studio_nivel_medido`,
  `x_studio_sensing_estado`) poblados en solo 6 filas. **El motor actual (Forecast Base)
  NO consume factor_corr** (lo confirmó la exploración; el legacy HM-SI lo aplicaba en
  HM SI Forecast.py:2762). Por eso esta capa es el único corrector → no hay doble conteo.
- ⚠️ Si alguien re-activa el consumo de `factor_corr` en el motor, coordinar: esta capa
  y factor_corr corregirían lo mismo dos veces. Documentar antes de tocar.

## Lecciones respetadas
- Medir, no estimar (MM7 real). Flag en onset (días_post<7 → no toca, mantiene base).
- Gate FVA ciclo completo cumplido antes de codear (regla de oro 2026-05-31).
- Capa separada, motor intacto. Apagable. Solo cervezas hasta nuevo gate.
