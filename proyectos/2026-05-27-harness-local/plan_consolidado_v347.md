# Plan consolidado v3.47 — calibración de factores HM-SI

**Estado:** Diseño consolidado tras trabajo 2026-05-27 / 2026-05-28.
**Filosofía aplicada:** una versión = un cambio + medir + decidir + promover (CLAUDE.md).
**Canon de referencia:** SAP IBP *Hierarchical Bias Correction*, Oracle Demantra *Multi-level Causal Forecasting*, Blue Yonder *Demand Sensing*.

---

## 0. Problema a resolver

El motor HM-SI v3.46 productivo tiene **sesgo sistemático sub-forecast +22.93%** sobre el universo limpio (sin cigarros/snack/impulso, sin quiebres en target_week). Cervezas tienen BIAS +18.46%. SKU 9407 Stella tiene +28.22% por lag de nivel del SMA.

Las 2 capas correctoras actuales del motor NO capturan ese sesgo:
- `correccion_factor` (precio) — solo dispara en eventos de cambio de precio del detector
- `trend_factor` (team v3.43) — promedia YoY del local, oculta variación intra-team por categoría (avg_spread 110pp al bajar a L2)

**Lo que NO funcionó:** tuning de 12 hyperparams (Test 1) empeoró BIAS +1.39pp con WAPE neutro. Descartado.

---

## 1. Inventario de hallazgos empíricos (28 may)

| # | Hallazgo | Fuente | Implicancia |
|---|---|---|---|
| H1 | BIAS sistémico +22.93% del motor v3.46 | `simulacion_final_v347.txt` | hay sesgo estructural por capturar |
| H2 | `(L2, abc)` discrimina BIAS más (std=52.15%) con 92% cobertura robusta | `analisis_nivel_bias.txt` | mejor granularidad de factor |
| H3 | `(L3, abc)` Test 2 actual cubre solo 63% robusto, dispersión 38.03% | mismo | sub-óptimo vs L2 |
| H4 | ABC discrimina más que XYZ (60.52 vs 43.22) pero XYZ tiene 43% poder igual | mismo | usar ABC primero; XYZ como capa adicional opcional |
| H5 | `team` solo es REDUNDANTE (std=10.71%, el más bajo) | mismo | trend_factor v3.43 ya captura ese efecto |
| H6 | Intra-team el spread por L2 es 110pp | mismo | el trend por team oculta diferencias categóricas dentro del local |
| H7 | REG-1 (76% volumen): calib reduce BIAS +12.9% → +0.5% ✅ | `analisis_calib_x_regimen.txt` | calib ideal acá |
| H8 | REG-2 / REG-4 / REG-8: calib mejora BIAS y/o WAPE | mismo | aplicar |
| H9 | REG-7 seasonal: calib mejora BIAS pero empeora WAPE +2.9pp | mismo | excluir |
| H10 | REG-5 lumpy raro: calib empeora WAPE +9.6pp (n=326 ruido) | mismo | excluir |
| H11 | REG-0/3/6 mu=0 forzado: factor neutro (no aplicable) | mismo | no afecta |
| H12 | Tracking Signal canon SAP IBP (Test 3) sobre-correge SKU 9407: +28% → +32% BIAS | `test_3_ts_detail.parquet` | descartado, queda como referencia |
| H13 | 50 factores categ_calib aplicados → BIAS global +22.93% → +10.66% | `simulacion_final_v347.txt` | corrección parcial, queda residual +10% |
| H14 | Tuning hyperparams Test 1 empeora BIAS +1.39pp | mismo | descartado |

---

## 2. Arquitectura propuesta — 3 capas multiplicativas nuevas

Siguiendo el canon **SAP IBP Hierarchical Bias Correction**, agregamos 3 capas en orden de aplicación al motor:

```
mu_week_pre_corr ← motor base (SMA + SI + bake-off + caps)
        ↓
correccion_factor (precio)       ← v3.29 existente
        ↓
[L1] categ_calib_factor          ← NUEVO v3.47 — hierarchical fallback por (L2, abc)
        ↓
trend_factor (team)              ← v3.43 existente
        ↓
[L2] residual_bias_correction    ← NUEVO v3.48 — cap global de sesgo residual
        ↓
mu_week final (persistido)
```

### Capa L1: `categ_calib_factor` — Hierarchical Bias Correction

**Inspiración canon:** SAP IBP — cuando el cluster fino no tiene sample suficiente, hace *roll-up* al nivel superior automáticamente.

**Algoritmo:**
```
Para cada (team, sku) en main loop:
    categ_L2 = product.category.parent (familia, ~14 buckets)
    abc = abcxyz_local[0]
    regimen = regimen_local
    
    if regimen NOT in {'REG-1', 'REG-2', 'REG-4', 'REG-8'}:
        factor = 1.0     # gate por régimen (H9, H10, H11)
    else:
        # Cascada de fallback (canon SAP IBP)
        factor = factor_dict[(categ_L2, abc)]      # nivel 1: familia × abc (top discriminante H2)
        if not factor:
            factor = factor_dict[abc]              # nivel 2: solo abc (siempre robusto H4)
        if not factor:
            factor = 1.0                           # nivel 3: identidad
    
    mu_week *= factor
    sigma_week *= factor
```

**Parámetros:**
- Clamp simétrico `[0.70, 1.30]`
- Threshold de aplicación: `|factor - 1.0| >= 0.05`
- `MIN_REAL_UNITS = 500` por cluster para calificar
- Régimen-gate: `{REG-1, REG-2, REG-4, REG-8}` (los que muestran mejora real)
- Refresh: mensual cron día 1

**Modelo Studio destino:** `x_categ_calib_factor` con campos para cada nivel (L2_id, abc_letter, factor_corr, raw_factor, n_real_units, target_week_start, calc_run_id, active).

### Capa L2: `residual_bias_correction` — cap global de sesgo

**Inspiración canon:** SAP IBP — después del *demand sensing* hay una capa final de *bias correction* que actúa sobre el residual no capturado por las capas anteriores.

**Por qué existe:** Tras aplicar L1, queda BIAS residual de +10.66% (H13). El motor aún sub-forecastea en agregado por razones que ni la categoría ni el régimen ni el local solo capturan (mix de SI sub-estimado, lag SMA, capping conservador).

**Algoritmo:**
```
1 vez por run (no por SKU):
    bias_residual = medir BIAS global del run anterior     ← desde x_hm_si_forecast log
    if |bias_residual| > BIAS_CAP_THRESHOLD (=5%):
        factor_global = clamp(1 + bias_residual / 100, 0.95, 1.05)
        aplica a TODOS los mu_week del run actual
```

**Parámetros:**
- Cap muy conservador `[0.95, 1.05]` (solo ajuste fino)
- Solo activa si BIAS residual > 5% en el último run cerrado
- Origen del BIAS residual: tabla `x_forecast_backtest` (último run cerrado)
- Override de seguridad: si BIAS_CAP > 8% NO aplica (señal de problema upstream)

### Capa L3: Tuning fino de hyperparams del motor (DESCARTADO)

**Razón:** Test 1 (12 hyperparams) probado empíricamente. Empeoró BIAS +1.39pp con WAPE neutro. NO promover.

**Archivado:** Test 1 hyperparams en `auto_tune.py` y `tune_phase_*.parquet` para futura referencia. Si en N meses se quiere reintentar, partir de ahí.

---

## 3. Plan de Tests local (validación antes de promover)

Cada capa se valida en orden, con criterio cuantitativo de promoción.

### Test L1A — Hierarchical fallback con régimen gate

**Script nuevo:** `proyectos/2026-05-27-harness-local/test_L1A_hierarchical_calib.py`

**Configs a comparar (sobre baseline v3.46, mismo universo 10 sem):**
- A: baseline v3.46 puro (referencia)
- B: factor solo `(L3, abc)` — el Test 2 actual (control, ya medido)
- C: factor solo `(L2, abc)` — nivel familia
- D: factor cascada `(L2, abc)` → `abc` → 1.0 con régimen gate
- E: factor cascada como D pero SIN régimen gate (para aislar el efecto)

**Criterio de promoción D → producción:**
- WAPE total no degrada > 0.5pp vs A
- BIAS magnitud baja al menos 8pp vs A
- En cervezas WAPE no degrada y BIAS magnitud baja al menos 10pp
- REG-7 y REG-5 NO sufren degradación de WAPE (validación del gate)

### Test L2A — Residual bias correction

**Script nuevo:** `proyectos/2026-05-27-harness-local/test_L2A_residual_bias.py`

**Premisa:** se ejecuta sobre el output de la mejor config L1 (D). Mide si el cap global cierra el BIAS residual.

**Configs:**
- F: config D (mejor L1) — referencia
- G: config D + L2 cap global aplicado

**Criterio de promoción G → producción:**
- BIAS magnitud baja al menos 2pp vs F
- WAPE total no degrada > 0.3pp
- Verificación: en el run siguiente el cap debe auto-deactivarse (BIAS residual < 5%) — testea convergencia

### Test L3A — Bake-off final

**Configs a comparar:**
- A: baseline v3.46 (control)
- D: L1 con cascada + gate (sin L2)
- G: D + L2 cap residual (full stack v3.48)
- D+G+excluir cig/snack/impulso: validación que el universo no cambió

**Criterio de promoción:** G domina A en BIAS y WAPE no degrada > 0.5pp.

---

## 4. Plan de implementación en Odoo (fases secuenciales)

### Fase A — Studio (manual, ~45 min)

1. Crear modelo `x_categ_calib_factor` (Studio) con campos:
   - `x_name` (Char, required), `x_studio_categ_id` (M2O product.category), `x_studio_categ_level` (Selection: L2/L3), `x_studio_abc_letter` (Selection A/B/C), `x_studio_factor_corr` (Float 4dec), `x_studio_raw_factor` (Float), `x_studio_n_real_units` (Float), `x_studio_n_sample_pairs` (Integer), `x_studio_bias_pct_pre` (Float), `x_studio_target_week_start` (Date), `x_studio_calc_run_id` (Char), `x_studio_active` (Boolean default True), `x_studio_regimenes_aplicables` (Char "REG-1,REG-2,REG-4,REG-8")
2. Agregar a `x_hm_si_forecast` 4 campos nuevos:
   - `x_studio_categ_calib_factor` (Float 4dec), `x_studio_categ_calib_level` (Char), `x_studio_categ_calib_meta` (Char), `x_studio_mu_week_pre_calib` (Float)
3. (Opcional v3.48) Crear modelo `x_global_bias_correction` con `x_studio_target_week`, `x_studio_bias_residual_pct`, `x_studio_factor_applied`, `x_studio_active`. Si decidimos no implementar L2, omitir.

### Fase B — SA Calc Categ Calib Factors (~2.5 hrs)

1. Script `04_analitica/OH Calib Factors.py` (renombrado por Marco hoy) ya existe.
2. **Actualizar** para implementar:
   - Cálculo en cascada (L2 y abc)
   - Persistir level junto al factor (`categ_calib_level = 'L2'` o `'abc'`)
   - Excluir clusters cuyo régimen mayoritario no esté en gate
3. Crear SA en Odoo. Disparar manual, validar ~14-20 factores activos.
4. Crear cron mensual día 1 02:00.

### Fase C — Motor HM-SI v3.47 (~1.5 hrs)

Aplicar al productivo `02_forecast/HM SI Forecast.py` los cambios YA escritos durante esta sesión + 1 cambio adicional:

1. ✅ VERSION_ID, header reglas vivas (hecho)
2. ✅ Constantes y CTX init (hecho)
3. ✅ `_load_categ_calib_context()` loader (hecho)
4. ✅ Pre-loop `categ_calib_ctx` (hecho)
5. **PENDIENTE — modificar bloque aplicación** para implementar:
   - Cascada con fallback: probar `(L2, abc)` → `abc` → 1.0
   - Régimen gate: solo aplicar si `regimen_local in {REG-1, REG-2, REG-4, REG-8}`
6. ✅ Persistencia 3 campos en x_hm_si_forecast (hecho)
7. ✅ Notify message (hecho)

**Lo que SÍ necesita reescribir** del código actual: el bloque de aplicación está hardcoded a `(int(categ_id), abc_letter)` plano. Debe reescribirse a cascada + gate.

### Fase D — Backtest validatorio (~30 min)

1. Disparar `OH Forecast Backtest` con la nueva config motor.
2. Comparar WAPE/BIAS sobre últimas 4 sem cerradas vs corrida previa.
3. Si BIAS baja en cervezas y WAPE no degrada > 0.5pp → commit a repo.
4. Si degrada → desactivar via context `{"apply_categ_calib": False}` y diagnosticar.

### Fase E — Bias correction residual (OPCIONAL v3.48, post-validación de D)

Solo si después de 2 semanas con v3.47 estabilizado el BIAS residual sigue > 5%, considerar implementar L2.

---

## 5. Rollback

Disponible en 2 niveles sin tocar código:

1. **Context override** en el cron del motor: `{"apply_categ_calib": False}` → motor ignora la capa, comportamiento idéntico v3.46.
2. **Desactivar registros**: `UPDATE x_categ_calib_factor SET x_studio_active=false` → loader devuelve contexto vacío, factores=1.0.

Rollback de código completo: revertir VERSION_ID + 9 cambios al motor. ~10 min.

---

## 6. Monitoreo post-implementación

Métricas a vigilar en `x_hm_si_forecast` semanal:
- `count(*) where categ_calib_factor != 1.0` → cobertura (target ~50-65% de filas)
- `sum(qty_sold - mu_week) / sum(qty_sold)` por régimen → BIAS por régimen (target REG-1 < 3%)
- `count distinct categ_calib_level` → ratio de fallback a abc vs L2 directo (target 80% L2)

Si en 2 corridas seguidas el BIAS residual de REG-1 sube > 8%, refrescar factores manualmente (no esperar al cron mensual).

---

## 7. Orden de ejecución concreta (próximos pasos)

1. **Marco aprueba este plan**
2. Crear `test_L1A_hierarchical_calib.py` y ejecutar (10-15 min compute)
3. Si pasa criterio → reescribir bloque aplicación en `02_forecast/HM SI Forecast.py` con cascada + gate
4. Re-validar simulación full A/B/C/D actualizada con la versión final
5. **Si BIAS residual queda < 5%**: NO implementar L2, ir directo a Fase A (Studio en Odoo)
6. Fase B (SA Calc)
7. Fase C (Motor productivo)
8. Fase D (Backtest validation post-promoción)
9. Monitorear 2 semanas
10. (Opcional) Fase E si BIAS residual persistente

---

## Archivos asociados

**Producidos esta sesión:**
- `propuesta_integracion_categ_calib.md` — primera propuesta detallada (será reemplazada por este doc)
- `simulacion_final_v347.txt` / `.parquet` / `_summary.json` — backtest A/B/C/D
- `analisis_nivel_bias.txt` / `_summary.json` — discriminación por nivel
- `analisis_calib_x_regimen.txt` — interacción factor × régimen
- `simulacion_final_v347.py`, `analisis_nivel_bias.py`, `analisis_calib_x_regimen.py` — scripts

**Producidos previamente (Test 2 / Test 3):**
- `test_2_categ_factors.json` — 50 factores `(L3, abc)` originales
- `test_3_summary.json` / `test_3_baseline_16w.parquet` — 16 sem baseline + Tracking Signal

**Pendientes de crear:**
- `test_L1A_hierarchical_calib.py` — validar cascada + gate sobre 10 sem
- (Opcional) `test_L2A_residual_bias.py` — validar cap global

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Factor `(L2, abc)` over-correge en una sub-categoría específica (ej. Cervezas Premium dentro de Cervezas L2) | Auditoría post-promoción: si una L3 muestra BIAS opuesto al de su L2 padre, refinar a `(L3, abc)` para esa L2 |
| Régimen gate excluye demasiado volumen | El gate cubre REG-1+2+4+8 = ~243k unid de 257k (94%). Riesgo bajo |
| Factor mensual queda obsoleto durante el mes | Aceptable: el SI captura estacionalidad sub-mensual; el factor capta sesgo estructural de mediano plazo |
| Calc Factors falla y no actualiza | Motor sigue corriendo con factores anteriores (loader graceful empty si modelo vacío) |
