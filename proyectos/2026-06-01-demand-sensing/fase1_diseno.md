# Diseño Fase 1 — Demand Sensing (eventos de precio, solo cervezas)

> Diseño de implementación aprobado el 2026-06-01. Fase 0 (validación de la
> regla) cerrada en `diseno.md`. **No se toca producción hasta cerrar el GATE
> previo (abajo).**

## Context

Los outliers que matan la credibilidad del forecast son SKU con **evento de
precio**: el onset es impredecible y 4 métodos de *estimación* (elasticidad,
share, damped, ancla mediana) fallan porque adivinan la magnitud antes de tener
dato post-evento. Fase 0 (2026-06-01) validó la alternativa: en vez de estimar,
**medir** el nuevo nivel con venta diaria (MM7×7, excluyendo días con quiebre) y
resetear el nivel del forecast cuando está confirmado.

Resultado backtest (72 cervezas con evento, 10 sem, ciclo completo, limpio de
quiebre): solo-evento **40.8 → 35.5** (−5.2pp); post-confirmación **39.2 → 24.2**
(−15.0pp). Genuino (quiebre 3%), no cherry-pick. Contraste: el ancla mediana-4
era +0.71pp PEOR.

Fase 1 = diseño de implementación productiva de esa regla. Alcance: solo
cervezas. No se crea modelo nuevo; se extiende el detector y se agregan ~3
campos a `x_price_coreccion`.

## Decisiones cerradas (con el usuario)

| Decisión | Elección |
|---|---|
| Dónde se computa el sensing | **Extender el detector** `OH Price Correccion.py` v5.9 (mismo modelo, mismo LOCK, misma cadencia; el motor solo consume campos) |
| Cómo entra al motor | **Hard-set del nivel** (no blend) sobre el nivel des-estacionalizado |
| Gating de apagado | **Hasta que el motor (SMA-6) alcance el nivel** (gap < umbral); luego devuelve control |

## Arquitectura — 3 piezas, ninguna se reemplaza

```
OH Price Correccion.py (detector v5.9 -> v6.0)
   |- [hoy]  detecta evento de precio  -> factor_corr  (sigue igual)
   `- [NUEVO] mide nivel post-evento   -> nivel_medido + dias_medidos + sensing_estado
        |- pull pos.order.line diario (cervezas, ventana del evento)
        |- cruce x_stock_balance_daily (excluir dias stockout)
        `- MM7x7 + regla de confirmacion

x_price_coreccion (modelo destino, +3 campos Studio)

HM SI Forecast.py (motor, linea ~2762)
   `- si sensing_estado='confirmado' -> reset de nivel (reemplaza el factor mult.)
```

- **Detector** = trigger (causa: precio cambió) **y ahora** medidor (efecto).
- **`x_stock_balance_daily`** = control de quiebre: medir run-rate solo en días con stock, para no confundir colapso-precio con quiebre.
- **Motor** = solo consume campos precalculados (canon detector-precalcula / motor-consume, igual que `factor_corr` hoy).

## Campos nuevos en `x_price_coreccion` (Studio, NO modelo nuevo)

Recordar: Studio crea `x_name` NOT NULL — ya existe el registro, solo se agregan campos.

| Campo | Tipo | Contenido |
|---|---|---|
| `x_studio_nivel_medido` | Float | Run-rate semanal medido = MM7(diario en ventana) × 7, días con stock. **Raw** (el motor lo des-estacionaliza). |
| `x_studio_dias_medidos` | Integer | Nº de días con stock dentro de la ventana de medición (denominador efectivo). |
| `x_studio_sensing_estado` | Selection | `midiendo` (onset, < N días) / `confirmado` (≥ N días sostenidos) / `apagado` (motor ya alcanzó el nivel). |

`midiendo` = el FLAG del onset (baja confianza operativa, ver abajo).

## Cómputo en el detector (v6.0)

1. **Universo**: SKU cerveza con evento activo en `x_price_coreccion` (los que ya tienen `factor_corr`).
2. **Pull diario**: `pos.order.line` agregado por día × producto, ventana = desde la fecha del evento (`target_week_start`) hasta hoy. Reusar patrón de `snapshot_pos_daily.py` del proyecto. **OJO**: el groupby dotted `order_id.date_order:day` NO funciona — loop por día (validado en Fase 0).
3. **Cruce quiebre**: leer `x_stock_balance_daily` (`stockout`); excluir del MM7 los días sin stock. `dias_medidos` = días con stock en la ventana.
4. **Regla de confirmación**: `nivel_medido = MM7(últimos 7 días con stock) × 7`.
   - `dias_medidos >= 7` → `sensing_estado = 'confirmado'`.
   - `dias_medidos < 7`  → `sensing_estado = 'midiendo'` (FLAG, motor NO usa el nivel todavía).
   - Calibración N=7 viene de Fase 0 (3 ruidoso ↔ 7 tarde; 7 fue sweet spot). Re-validar en el gate de producción.
5. **Día de la semana**: medir sobre múltiplos de 7 días reales evita el sesgo intra-semana (por eso MM7, no MM3/MM5).

## Reset de nivel en el motor (línea ~2762)

Hoy: `mu_week = mu_week * correccion_factor`.

Nuevo (cuando `sensing_estado == 'confirmado'`), **reemplaza** esa multiplicación:

```
# mu_week en este punto ya = mu_base * si_next (linea 2578).
# Hard-set del NIVEL des-estacionalizado, re-aplicando si_next:
si_meas = SI promedio de las iso_weeks de la ventana de medicion
nivel_deseason = nivel_medido / si_meas        # si_meas>0; si no, fallback raw
mu_week  = nivel_deseason * si_next
sigma_week = sigma_week escalado por (mu_week / mu_week_pre_corr)   # mantener CV
```

- **Por qué des-estacionalizar**: `nivel_medido` es run-rate con la estacionalidad de la ventana de medición horneada; pisar `mu_week` con el valor plano perdería el `si_next` de la semana objetivo. Para cervezas el SI es casi plano (en Fase 0 daba ≈ igual), pero la versión des-estacionalizada es la correcta y general. **PROXY**: si `si_meas` no es confiable (ventana < 1 perfil), usar `nivel_medido` raw y marcarlo en `razon`.
- **Convive con las capas siguientes**: `categ_calib` (2790) y `trend_factor` (2822) aplican DESPUÉS, igual que hoy — el sensing entra al mismo punto donde entraba el factor, así que el orden no cambia.
- **`correccion_factor` queda inerte** cuando hay sensing confirmado (no se multiplica además; el sensing lo reemplaza). Mantener el factor solo para SKU sin sensing confirmado (estado `midiendo`/`apagado`).

## Gating de apagado (devolver control al motor)

El ds gana en saltos de nivel y **lag-ea en tendencias** (debilidad conocida).
Hay que devolver el control cuando el baseline SMA-6 ya absorbió el escalón:

- En el detector, comparar `nivel_medido` vs el baseline del motor del SKU
  (proxy disponible: `mu_week_pre_corr` ó SMA-6 reciente).
- Si `|nivel_medido − baseline_motor| / nivel_medido < UMBRAL` (ej. 15%) durante
  ≥ 2 semanas → `sensing_estado = 'apagado'`. El motor ya converge al nuevo nivel.
- A partir de `apagado` el motor ignora el sensing y vuelve a su pipeline normal
  (sin doble-conteo, captura tendencias post-evento que el ds lag-earía).
- SMA-6 tarda ~6 sem en absorber un escalón → vida típica del ds ≈ 4-6 semanas.

## Manejo del FLAG (onset, estado `midiendo`)

- Durante `midiendo` el motor **no** usa `nivel_medido` (sigue con baseline +
  `factor_corr` como hoy). El error del onset es inherente (impredecible) pero
  acotado a días, no semanas.
- El estado `midiendo` debe ser **visible para operación** como baja confianza.
  Decidir en implementación: ¿se propaga una marca a `x_analisis_de_stock`
  (para que el comprador sepa "nivel en medición, no sobre-comprar")? — alinear
  con el patrón de alarmas que ya vive en stock_analysis.

## Gate PREVIO a tocar producción (paso 0, read-only)

**No se modifica código productivo hasta cerrar esto.** Fase 0 corrió sobre el
motor del **harness**, que NO tiene la capa `bias_outlier` (ON en producción,
HM SI Forecast.py:1387).

1. Comparar `ds` vs `forecast_qty` del **motor de producción** (con `bias_outlier`)
   usando el backtest server `OH Forecast Backtest 30-05.csv` (W20-22), cervezas
   con evento. Confirmar que el −15pp se sostiene cuando `bias_outlier` ya está
   recortando outliers (puede solaparse con lo que el ds corrige).
2. Re-validar N=7 y el UMBRAL de apagado sobre ese set.
3. Verificar que la des-estacionalización no rompe en cervezas (SI ≈ plano → ≈ raw).

Si el win se sostiene → implementar. Si `bias_outlier` ya captura la mayoría →
re-evaluar alcance antes de codear.

### RESULTADO GATE (2026-06-01) — PASA ✅

`gate_produccion.py` vs CSV server 30-05 (W20-22, target 05-04/11/18,
`forecast_qty` con bias_outlier). Unión por `P<pid>` de la col Descripción.

| | motor_prod (bias_outlier) | ds | Δ |
|---|---|---|---|
| Solo-evento limpio | 38.7 | **28.2** | **−10.6pp** |
| DS-activo limpio (post-confirmación) | 35.4 | **22.3** | **−13.1pp** |

n ds-activo limpio = 82; quiebre 3%. **bias_outlier NO captura el salto de nivel
por evento de precio** — el ds aporta independiente. N=7 sostiene. Ventana corta
(3 sem vs 10 de Fase 0) pero consistente con Fase 0 (−13/−15pp). → IMPLEMENTAR.

## Criterios de éxito

- Sobre el backtest de producción, cervezas con evento: WAPE post-confirmación
  baja vs motor actual, ciclo completo (onset incluido, que va a FLAG, no empeora).
- El gating apaga el ds y devuelve el control sin doble-conteo ni regresión.
- **Cero regresión en SKU sin evento**: el sensing no se dispara (sin evento en
  `x_price_coreccion` → sin `nivel_medido` → motor intacto).
- El detector no se ralentiza materialmente con el pull diario (acotado a cervezas con evento).

## Archivos a tocar (en implementación, tras aprobar el gate)

- `02_forecast/OH Price Correccion.py` — v6.0: pull diario + cruce stockout + cómputo sensing + escritura de los 3 campos.
- `02_forecast/HM SI Forecast.py` — `_load_correccion_context` (~1018) lee los 3 campos nuevos; bloque de corrección (~2762) hard-set des-estacionalizado bajo `sensing_estado=='confirmado'`.
- `x_price_coreccion` (Studio) — 3 campos nuevos.
- (Posible) `x_analisis_de_stock` — marca de baja confianza para estado `midiendo`.

## Estado implementación

**Detector v6.0 — CODEADO (2026-06-01, pendiente correr en Odoo):**
`02_forecast/OH Price Correccion.py`. Ajustes vs diseño original, fieles a lo
que VALIDÓ Fase 0 (no a lo escrito de más):

- `nivel_medido` = **suma de venta de los últimos 7 días completos** (= MM7×7),
  1 read_group `pos.order.line`. Total producto (todas las salas).
- `dias_medidos` = **días calendario desde el evento** (no días-con-stock).
  `>=7` → `confirmado`, `<7` → `midiendo`. (El backtest usó días calendario.)
- **Filtro de quiebre NO entra al cómputo en v1** (en Fase 0 el cruce stockout
  fue solo validación). Marcado PROXY en el header; refinamiento futuro.
- El detector **solo mide**. `apagado` + reset + **reparto por team** los hace
  el MOTOR (nivel_medido es total-producto; el motor reparte por share de team).
- Defensivo: si faltan los 3 campos Studio o el pull POS falla → se omite.
- Flag de contexto `sensing_enabled` (default True) para rollback.

**Pendiente:**
1. **Marco crea los 3 campos Studio** en `x_price_coreccion` (sin ellos el
   detector omite el sensing en silencio).
2. Correr el detector y verificar `sensing=N` en la notificación + valores
   creados en `x_price_coreccion`.
3. **Motor (paso siguiente):** `_load_correccion_context` lee los 3 campos;
   bloque ~2762 reparte `nivel_medido` por team y hard-set des-estacionalizado
   bajo `sensing_estado=='confirmado'`; gating de apagado (gap vs baseline).

## Lo que NO se hace

- No se crea modelo nuevo (solo 3 campos en `x_price_coreccion`).
- No se toca producción antes del gate de verificación.
- No se extiende a no-cervezas en Fase 1.
- No blend medido+motor (reintroduce el subestimar del baseline).
