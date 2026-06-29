# Harness local — re-apuntado a OH Forecast Base

## Problema

El harness local (`proyectos/2026-05-27-harness-local/`) probó su valor (iteración
30-60 min → 3 seg, cero riesgo al server) pero quedó **congelado y apuntando a un
motor muerto**: el mirror es `HM_SI_LOCAL_v3_46`. El motor productivo desde el
2026-06-03 es **`02_forecast/OH Forecast Base.py`** (v1.6) — otra cosa: SES/SMA
por forma de serie local, sin bake-off Croston/SBA, sin fair-share, sin router de
zonas. No existe mirror del motor actual → no se puede tunear/validar local.

## Decisión

Alcance MÍNIMO (elegido por Marco 2026-06-16): **crear `forecast_base_local.py`,
mirror del motor actual, y medir paridad**. No mover carpetas a infra estable,
no golden-set (eso queda para incrementos futuros).

## Qué replica el mirror (motor v1.6, core)

Por `(team=crm.team, product=product.product)` sobre ventana
`DEMAND_WINDOW_WEEKS=26`:

1. Serie semanal POS combo-expandida (cache `pos_weekly.parquet`).
2. Clasifica `series_type` LOCAL (Syntetos-Boylan ADI/CV2: 1.32 / 0.49).
3. Selección de modelo:
   - `smooth` + ABC=A  → SES(α=0.5)
   - `smooth` + ABC=B/C → SES(α=0.6)
   - `erratic`          → SES(α=0.7)
   - `intermittent/lumpy/no_signal` → SMA(6)
4. `mu_week` = nivel SES 1-paso (o SMA6); `sigma_week` = std poblacional de las
   últimas 4 semanas.

Funciones core (`_classify_series_type`, `_ses_level`, `_median`) son **COPIA
EXACTA** del motor productivo (líneas 215-265) → paridad numérica garantizada.

## De-censura (cleansing) — REPLICADA (2026-06-16)

El motor v1.5/v1.6 hace cleansing de entrada por quiebre (de-censura ponderada por
perfil día-de-semana). El mirror lo replica con `_cleanse_stockout` (COPIA EXACTA
del motor) + dos inputs nuevos al cache:
- `quiebres_daily.parquet` — días de quiebre por (product, team), pull vía
  `pull_quiebres.py` (search_read angosto chunked; read_group reventó por el
  `__domain` que infla a 97MB). 263.761 días / 10.677 combos en ventana 16 sem.
- `dow_profile.parquet` — 7 pesos día-semana. **PROXY**: usa `create_date` (UTC)
  como sustituto de `date_order` (el motor usa zona Santiago); desfase de horas en
  bordes de medianoche, irrelevante para la forma semanal. Sáb 22% / Dom 20% /
  Vie 17% / Lun-Jue ~10% (matchea el "sábado ~21%" del motor).

`run(decensor=True)` (default, = motor productivo) aplica el cleansing;
`decensor=False` corre crudo. Medido cutoff 2026-05-17: de-censura sube mu_sum
+31% (32.8k→43k) y toca 58% de los combos → posible **sobre-de-censura** vs
lost-sales real 3-5%; queda como hallazgo a validar.

## Validación

1. **Self-check:** correr cutoff 2026-05-17, revisar distribución de `model_code`
   (ses_a0.50/0.60/0.70 + sma6) y `mu_sum` creíbles.
2. **Paridad absoluta:** requiere export fresco de `x_hm_si_forecast` (output de
   Forecast Base) al MISMO cutoff con `decensor_stockout=False`. Comparar `mu_week`
   1-a-1. Criterio (mismo del harness viejo): diff<0.5 en ≥70% de SKUs = suficiente
   para A/B relativo. Pendiente del export.

## Cache

Reusa `proyectos/2026-05-27-harness-local/cache/` (no se duplica). `pos_weekly`
581K filas, todos los teams, semanal; `abcxyz` con abcxyz + ciclo_de_vida.
