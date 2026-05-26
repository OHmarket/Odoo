# Detector v5.9 — Promos de pareo (min_qty≤2)

**Fecha:** 2026-05-25
**Versión motor afectada:** OH Price Correccion v5.8 → v5.9
**Alcance:** UN cambio — capturar promos `min_qty=2` con lift moderado (1.5x-2.5x) que hoy se descartan.
**Fuera de alcance:** ML, calibración por categoría, decay no-lineal, lift inferido sin loyalty.

---

## 1. Problema y decisión comercial

**Decisión:** que HM-SI reciba factor de corrección para SKUs en **promo 2x** (pareo) activa,
para que el motor no use la qty inflada por promo como baseline del SMA.

**Causa raíz medida (2026-05-25):**
- `x_loyalty_promo_event` tiene **588 eventos de cervezas/alcoholes en 6 meses**.
- El detector v5.8 emite solo **5 PROMOS totales** ([OH Price Correccion.py:611-625](02_forecast/OH Price Correccion.py#L611-L625)):
  - Rama `min_qty <= 2` (80% de eventos cerveza): solo emite si `lift >= 2.5`.
  - El 80% de promos cerveza tienen lift entre 1.0x y 2.5x → quedan sin emitir.
- Casos canónicos perdidos:
  - **CUSQUEÑA GOLDEN LAGER 6X** (SKU 10844): lift 2.44x, `2X DESCUENTO -9%`, activa desde 2025-12-01. **Queda 0.06 abajo del umbral**.
  - **MAD CHARLIES** (SKU 22281, 22287): lift 2.0-3.04x, `2X -22%`. Solo se emiten las que superan 2.5x.
  - **MICHELOB ULTRA** (SKU 28858): lift 3.17x con `12X -12%`. Se detecta (min_qty=12 ≥ 6).
  - **DOLBEK MAQUI** (SKU 28486): lift 33x-22x-8x-6x-5x. Debería detectar pero solo 5 PROMOS totales en sistema (hay otro filtro inhibiendo, a investigar en Task 1).

**Decisión comercial:** sub-corrección de promos de pareo causa que el SMA del HM-SI quede inflado.
Cuando termina la promo o sobreviene quiebre, el forecast queda alto. Esto produce sobre-stock
(menos doloroso que sub-forecast pero igual cuesta capital).

**Por qué importa ahora:** el backtest del proyecto de [normalización de demanda](../2026-05-25-normalizacion-demanda/diseno.md)
mostró sobre-forecast de cervezas con promo activa. La normalización hace lo correcto (corregir
censura por quiebre) pero el efecto promo se interpreta como demanda real → forecast inflado.

---

## 2. Cómo lo resuelve la industria

- **SAP IBP / Demand Planning**: Promotional Lift Profile separado del baseline. La qty de
  semanas en promo se ajusta a baseline antes de entrar al algoritmo (similar a outlier correction
  pero con razón promocional explícita).
- **Blue Yonder Luminate**: "Promo Decomposition" - serie de baseline + serie de promo lift.
  El forecast del baseline ignora la qty extra de promo.
- **Oracle RDF**: Promotional Effect Tracking con campos `promo_active` y `lift_factor` por semana.

**Patrón canónico común:** detectar qué semanas tienen promo activa, aislar el lift de promo
del baseline, aplicar factor de corrección al forecast post-promo.

En OH Market ya está parcialmente implementado:
- `x_loyalty_promo_event` registra eventos con `lift_qty` y `price_delta_pct` (datos crudos OK).
- `x_price_coreccion` consume y emite factor (lógica de gating muy restrictiva).
- HM-SI aplica el factor `_load_correccion_context` (consumo OK).

**El gap es solo el gating** — relajar el filtro de `lift >= 2.5` para promos de pareo.

---

## 3. Enfoques considerados

| Enfoque | Pro | Contra |
|---|---|---|
| **A. Bajar umbral lift** (2.5 → 1.5) en rama min_qty≤2 | Cambio de 1 línea. Captura el 80% perdido. | Riesgo falso positivo: lift=1.5 puede ser ruido natural en SKUs con baseline bajo. |
| B. Agregar señal `price_delta_pct`: si effective < normal × 0.92, es promo activa | Captura promos que el lift no detecta (efecto canalizado a otro SKU). | Requiere mayor refactor. |
| C. ML para promo lift inferido (sin loyalty event) | Captura promos góndola/cartelería sin loyalty. | Proyecto largo, fuera de scope. |

**Elegido: A**, con guard rail anti-ruido. Razón: cambio mínimo, alta cobertura, alineado
con principio CLAUDE.md "una versión, un cambio".

---

## 4. Diseño del cambio

### Cambio único en `OH Price Correccion.py` líneas 610-625

**Antes (v5.8):**
```python
# PROMO DE PAREO (min_qty <= 2): solo extremos
if min_qty <= 2:
    if lift >= 2.5:
        factor = min(2.0, lift * 0.7)
        # emit PROMO_PAREO_LIFT_EXTREMO
    # else: no alertar pareo neutro
    continue
```

**Después (v5.9):**
```python
# PROMO DE PAREO (min_qty <= 2):
#   - lift >= 2.5: PROMO_PAREO_LIFT_EXTREMO (existente, sin cambio)
#   - lift >= 1.5: PROMO_PAREO_MODERADO (NUEVO)
#   - lift entre 1.0 y 1.5: descartar (ruido)
if min_qty <= 2:
    if lift >= 2.5:
        factor = min(2.0, lift * 0.7)
        # emit PROMO_PAREO_LIFT_EXTREMO (sin cambio)
    elif lift >= 1.5:
        factor = min(1.7, 1.0 + (lift - 1.0) * 0.6)
        # emit PROMO_PAREO_MODERADO
        # ruido: SKUs con baseline < N unidades excluidos (Task 1.1 calibra N)
    continue
```

### Anti-ruido: filtro de baseline mínimo

Para evitar falsos positivos donde `lift=1.5` viene de un SKU con baseline=2 (volatilidad natural):

```python
baseline_min = 5  # calibrable. Excluye SKUs con baseline<5 del rule lift moderado.
if min_qty <= 2 and lift >= 1.5 and baseline >= baseline_min:
    # emit
```

### Nuevo tipo en `_tipo_studio` mapping

Si Studio tiene `PROMO_PAREO_MODERADO` ya en la selection → usarlo. Si no, mapear a
`PROMO_DISPARO` (más cercano semánticamente).

---

## 5. Casos canónicos de validación

| Caso | Esperado v5.9 |
|---|---|
| CUSQUEÑA 10844 (lift 2.44, baseline=9, -9%) | ✅ emitir PROMO_PAREO_MODERADO con factor ~1.42 |
| MAD CHARLIES 22281 (lift 2.0-3.04, baseline=10) | ✅ emitir (algunas en moderado, otras en extremo) |
| DOLBEK 28486 (lift 33x, baseline=1) | ❌ descartar por baseline<5 (ruido) — verificar si era falso positivo o no |
| MICHELOB ULTRA 28858 (min_qty=12) | ✅ DISPARO_STOCKUP_W1 (rama existente) |
| SKU genérico con lift=1.1, baseline=20 | ❌ no emitir (lift < 1.5 = ruido) |

---

## 6. Métricas de éxito

- **Cantidad de PROMOS emitidas** sube de ~5 a 100-200 en 6 meses (significativamente más cobertura).
- **Falsos positivos** se mantienen bajos: spot check 20 alertas nuevas, ≥85% son promos reales identificables.
- **WAPE post-detector v5.9 mejora** (o BIAS se acerca más a 0) en SKUs con promo activa,
  medido vs WAPE pre-v5.9 con backtest comparativo en mismas semanas.

---

## 7. Lo que NO incluye

- Promos sin loyalty (góndola, cartelería) — Proyecto separado (Detector v6.0 con señal de precio).
- Re-calibración de decay (12 sem para SUBIDA). Mantiene v5.8.
- Cambios en HM-SI o backtest.

---

## 8. Pendiente de validar antes de codear

- **DOLBEK con lift 33x no se detectó en v5.8 a pesar de cumplir umbral 2.5x.** ¿Hay otro filtro
  inhibiendo? Investigar en Task 1.1 (auditar el log del detector para identificar la razón).
  Posibles causas: `wa` (weeks_active) mal calculado, dedupe por SKU, filtro de category, etc.
- **`baseline_min=5` es heurístico**. Calibrar en Task 1.2 mirando distribución de baseline de
  los 588 eventos cerveza.
- **¿Studio tiene `PROMO_PAREO_MODERADO` en la selection de `x_studio_tipo_alerta`?** Si no,
  hay que agregarlo (decisión técnica de Studio antes del code).
