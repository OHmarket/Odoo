# Plan de implementación — Detector v5.9 promos de pareo

> **Goal:** capturar promos `min_qty=2` con lift 1.5x-2.5x que hoy se descartan en el detector v5.8.
> **Architecture:** modificar `OH Price Correccion.py` (Server Action ID a confirmar), agregar
> una rama nueva en el bloque min_qty≤2.
> **Tech Stack:** Odoo 17 EE Server Action (safe_eval).

---

## Task 1: Diagnóstico y calibración (read-only)

**Antes de tocar el detector productivo, validar 2 hipótesis abiertas del diseño.**

### Task 1.1: ¿Por qué DOLBEK 28486 (lift 33x) no se emitió en v5.8?

**Acción:** Server Action diagnóstico que reproduce la rama `min_qty<=2 + lift>=2.5` solo para SKU 28486 y muestra:
- `min_qty`, `lift`, `wa` (weeks_active), `baseline`
- Si pasó el filtro, qué tipo se emitió
- Si no pasó, qué filtro lo bloqueó

**Expected:** identificar la causa. Hipótesis a probar:
- (a) filtro de categoría excluye cervezas artesanales del bloque promo
- (b) `wa` está limitado a último evento y los 6 eventos se solapan
- (c) dedupe por (product_id, period_start, mecanica)

**Criterio de aceptación:** documento de 1 párrafo explicando la causa de DOLBEK ausente.

### Task 1.2: Calibrar `baseline_min`

**Acción:** script local vía XML-RPC que liste los 588 eventos cervecera/alcoholes con:
- `baseline_8w`, `lift_qty`, `qty_actual`, `price_delta_pct`

Y reporte:
- Distribución de baseline (percentiles 10/25/50/75)
- Cuántos eventos cumplirían `lift >= 1.5 AND baseline >= N` para N ∈ {3, 5, 8, 10}
- Spot check de 20 SKUs aleatorios — ¿son promos reales según el nombre del programa?

**Criterio de aceptación:** elegir `baseline_min` que maximice cobertura sin falsos positivos
obvios (objetivo: >150 eventos detectados, <10% ruido).

**Files (read-only):** `proyectos/2026-05-25-detector-promos-pareo/diag_calibracion.py` (XML-RPC local).

---

## Task 2: Validar selection en Studio

**Acción:** agregar `PROMO_PAREO_MODERADO` a `x_price_coreccion.x_studio_tipo_alerta` (Studio UI).
Si no se puede o se prefiere reusar, mapear a `PROMO_DISPARO` en la función `_tipo_studio`.

**Decisión técnica del dueño:** ¿valor nuevo o reuso? El plan asume valor nuevo.

**Criterio de aceptación:** la selection del campo tiene `PROMO_PAREO_MODERADO` listo.

---

## Task 3: Patch al detector

**Files:**
- Modify: `02_forecast/OH Price Correccion.py` — bloque min_qty<=2 (líneas ~610-625)
- Modify: `_tipo_studio` (líneas ~98-106) si se agregó PROMO_PAREO_MODERADO al mapping

### Step 1: Cambio en bloque min_qty≤2

```python
# PROMO DE PAREO (min_qty <= 2):
#   - lift >= 2.5: extremo (v5.8 existente)
#   - lift >= 1.5 y baseline >= BASELINE_MIN_PROMO_PAREO: moderado (NUEVO)
#   - resto: descartar (ruido)
if min_qty <= 2:
    baseline = promo.get('baseline_8w', 0) or 0
    if lift >= 2.5:
        factor = min(2.0, lift * 0.7)
        alertas.append({
            ...
            'tipo': 'PROMO_PAREO_LIFT_EXTREMO',
            ...
        })
    elif lift >= 1.5 and baseline >= BASELINE_MIN_PROMO_PAREO_DEFAULT:
        factor = min(1.7, 1.0 + (lift - 1.0) * 0.6)
        alertas.append({
            ...
            'tipo': 'PROMO_PAREO_MODERADO',
            'factor_corr': round(factor, 3),
            'razon': '%s (min_qty=%d) lift moderado %.2f (baseline=%d)' % (mec, min_qty, lift, baseline),
            ...
        })
    continue
```

### Step 2: Agregar constante calibrada en Task 1.2

```python
BASELINE_MIN_PROMO_PAREO_DEFAULT = 5  # calibrar segun Task 1.2
```

(Cerca de otras constantes en el header del script.)

### Step 3: Mapping en `_tipo_studio`

Si Studio tiene `PROMO_PAREO_MODERADO`:

```python
if t == 'PROMO_PAREO_MODERADO':
    return 'PROMO_PAREO_MODERADO'  # o el valor exacto que tenga Studio
```

Si no, agregar al `if t in (..., 'PROMO_PAREO_MODERADO'):` que mapea a `PROMO_DISPARO`.

### Step 4: Bump VERSION_ID

```python
VERSION_ID = "PRICE_CORRECCION_v5_9"
```

**Criterio de aceptación:** el código pasa el syntax check (no errores safe_eval) y los casos
canónicos se emiten cuando se corre.

---

## Task 4: Correr y validar productivo

**Files:** (no modificación, solo ejecución)

### Step 1: Snapshot pre del modelo `x_price_coreccion`

```bash
python "proyectos/2026-05-25-detector-promos-pareo/export_x_price_coreccion.py" pre
```

Guarda CSV con todos los registros actuales del detector v5.8.

### Step 2: Pegar v5.9 en el SA y correr

- Settings → Technical → Server Actions → buscar el SA del detector → pegar v5.9.
- Action → Run.

### Step 3: Snapshot post + análisis

```bash
python "proyectos/2026-05-25-detector-promos-pareo/export_x_price_coreccion.py" post
python "proyectos/2026-05-25-detector-promos-pareo/comparar.py" pre.csv post.csv
```

**Esperado:**
- `n_PROMO_PAREO_MODERADO` ≥ 150 (los 80% perdidos de cerveza)
- CUSQUEÑA 10844, MAD CHARLIES 22281/22287 presentes en post (no en pre)
- Spot check 20 alertas nuevas → ≥85% promos reales

---

## Task 5: Backtest comparativo del HM-SI

**Files:**
- Reuso del proyecto [2026-05-25-normalizacion-demanda](../2026-05-25-normalizacion-demanda/) workflow.

### Step 1: Snapshot pre HM-SI

- Ejecutar `OH Forecast Backtest` con detector v5.9 activo.
- Exportar `x_forecast_backtest` a CSV (`detector_v59_pre.csv`).

### Step 2: Revertir detector a v5.8 temporalmente

- Pegar versión v5.8 en el SA.
- Correr backtest.
- Exportar (`detector_v58_baseline.csv`).

### Step 3: Comparar

```bash
python "proyectos/2026-05-25-detector-promos-pareo/comparar_backtest.py" \
    detector_v58_baseline.csv detector_v59_pre.csv
```

**Criterio de aceptación (decisión de mergear v5.9 a productivo):**
- WAPE no empeora >2 pp en SKUs sin promo (regresión core)
- WAPE mejora ≥1 pp en SKUs con promo identificada
- BIAS en cerveza/alcohol se acerca más a 0
- Spot check de los top 20 SKUs con cambio de forecast → tienen sentido (no son ruido)

---

## Task 6: Commit y memoria

### Step 1: Commit

```bash
git add proyectos/2026-05-25-detector-promos-pareo/ "02_forecast/OH Price Correccion.py"
git commit -m "forecast: detector v5.9 - promos de pareo (lift moderado)"
git push
```

### Step 2: Memoria

Guardar memoria nueva:
- `feedback_promo_pareo_lift_1.5.md` — la calibración del umbral de lift validada y por qué.
- (Si aplica) actualizar `ref_x_price_coreccion.md` con el nuevo tipo PROMO_PAREO_MODERADO.

---

## Fuera de este plan

- Detección de promo sin loyalty event (góndola/cartelería sin registro). Proyecto Detector v6.0.
- Re-calibración del decay (12 sem para SUBIDA). Mantiene v5.8.
- Cambios en HM-SI o en la corrección por canibalización.

---

## Self-review (cobertura vs spec)

- Bajar threshold lift 2.5→1.5 → Task 3 Step 1. ✓
- Guard rail anti-ruido `baseline_min` → Task 1.2 + Task 3 Step 2. ✓
- Casos canónicos: CUSQUEÑA, MAD CHARLIES → Task 4 Step 3 + Task 5. ✓
- Investigar por qué DOLBEK no se emitía en v5.8 → Task 1.1. ✓
- No tocar v5.8 hasta validar v5.9 en backtest → Task 5. ✓
- Backtest comparativo antes de productivo → Task 5. ✓
