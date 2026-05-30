# HM-SI FORECAST — Motor de Demanda Semanal OH Market
## Resumen Ejecutivo de Proyecto (v3.48, 2026-05-29)

---

## 1. Propósito y Contexto

**Objetivo:** Calcular pronóstico semanal de demanda (`mu_week`, `sigma_week`) por cada par **(sala, SKU)** usando heurística SMA blend con estacionalidad SI multi-nivel, validación empírica y correcciones estratificadas (precio, tendencia, sesgo).

**Alcance:** 
- **Input:** 26 semanas de ventas históricas desde POS (product.product activos y vendibles).
- **Output:** Registros en tabla `x_hm_si_forecast` con pronóstico + campos de auditoria.
- **Ejecución:** Server Action en Odoo (corre en Odoo 17 EE, hosting AWS).
- **Posición en Pipeline:** Script 3 de 5 en el pipeline productivo de reabastecimiento.

**Usuarios finales:**
- Script 4 (`OH Analisis de Stock`) consume `mu_week` para calcular compra/transferencia.
- Analistas vía backtest (`4- OH Forecast Backtest.py`) para auditoria semanal de WAPE/BIAS.

---

## 2. Arquitectura del Sistema

### 2.1 Pipeline de 7 Capas (Motor v3.48)

El motor aplica transformaciones secuenciales sobre `mu_base` (demanda base SI-deflactada):

```
1. DEMANDA BASE (SMA blend heurístico + auto-model bake-off SAP IBP)
   ↓
2. ESTACIONALIDAD SI (multi-nivel: local_categ → categ_global → global)
   ↓
3. CORRECCIONES P1/P3/P6 (declinantes/dead → 0, zero-gate Z4, caps anti-spike)
   ↓
4. CORRECCIÓN POR PRECIO (factor externo desde detector v5.8)
   ↓
5. CALIBRACIÓN POR CATEGORÍA (v3.47: sesgo estructural categ×abc)
   ↓
6. TREND CORRECTION (v3.43: YoY asimétrico por team, clamp 0.70-1.00)
   ↓
7. BIAS-OUTLIER CORRECTION (v3.48: Pareto-80% limpio de quiebre, clamp asim 0.65-4.0)
   ↓
✓ mu_week (flotante) + sigma_week + auditoria
```

### 2.2 Componentes Críticos

#### A. **Demanda Base — Heurística SMA Blend**
- **Corto:** SMA(6 sem) — sensible a cambios recientes.
- **Largo:** SMA(16 sem) — estabilidad de fondo.
- **Ratio-rule:** compara short vs long para detectar tendencia (up/hold/collapse).
- Deflactada por SI para separar "efecto estacional real" de "cambio de velocidad".
- **v3.36 fix:** ratio calculado sobre raw_vals (sin SI) para detectar colapso real.

**Auto-model Selection (v3.39):**
- Bake-off per SKU: heurístico vs SBA(α=0.15) vs Croston(α=0.10) vs seasonal_naive_52.
- Holdout 4 sem. MAE decide ganador.
- Heuristic-bias 0.90: heur gana a menos que otro sea ≥10% mejor.
- Resultado: mejora marginal sin regresión en REG-1 (control).

#### B. **Estacionalidad SI (Índice de Estacionalidad)**
- **Niveles (jerarquía):**
  1. SI local_categ (team × categ): ≥12 sem historia → robusto.
  2. SI categ_global (categ): fallback cuando no hay datos locales.
  3. SI global: fallback universal (52 semanas).

- **Ajuste SKU (v3.31+):** si n_years_sku ≥ 3 años, aplicar α ∈ {0.15 (bajo), 0.30 (alto)}.
- **Clamps:** SI ∈ [0.05, 5.0] para evitar divisiones patológicas.

#### C. **Router Forecast (Clasificación → Pronóstico)**
- Input: ABCXYZ (ABC global + XYZ local), series_type, lifecycle, mu_week.
- Output: forecast_zone (Z1-Z4) + scope + model_code.

| Zone | Scope | Trigger | Ejemplo |
|------|-------|---------|---------|
| **Z1** | core_hm_si | AX/AY/BX smooth+mu≥2 o AZ no-terminal | Cerveza Heineken local |
| **Z2** | controlled_hm_si | AX/AY erratic+mu≥2 | Cerveza Premium intermitente |
| **Z3** | secondary_model | BY/BZ, seasonal, fallback | Sidra, productos estacionales |
| **Z4** | no_forecast | CX/CY/CZ, no_signal, dead/declining | Fast-moving bajo margen |

#### D. **Fair Share Canon (v3.42, SAP IBP / Blue Yonder)**
- **Trigger:** ABC ∈ {A, B} + mu_week=0 + lifecycle ∈ {mature, ramp_up}.
- **Gating:** Clase B solo si gap_count ≤ 2 (TERMINAR COBERTURA).
- **Fórmula:**
  ```
  mu_fs = factor_norm × conf_n × mu_categ_target × bias × growth_cap / gap_count
  ```
  donde:
  - `factor_norm` = promedio del share de SKU en otras salas.
  - `conf_n` = confianza estadística (1 sala=0.30, ≥5 salas=1.00).
  - `growth_cap` = techo por XYZ (X=3.0, Y=2.0, Z=1.5).
  - `tried_penalty` = 0.15 si la sala ya probó y fracasó.

- **Diagnóstico:** 60 SKUs A con <3 salas → 97% "probó y falló" → regla correcta.

#### E. **Correcciones de Sobre-Forecast (P1/P3/P6)**
1. **P1:** declining/dead → mu=0 (terminal).
2. **P3:** Z4 sin actividad reciente (nz_recent_8w=0) excluyendo REG-8 → mu=0.
3. **P6:** caps absolutos anti-spike por segmento:
   - BZ: máx 0.8× max_obs (lumpy extremo).
   - AZ/CZ/AY-smooth/CY: máx 1.2× max_obs.

#### F. **Corrección por Precio (Detector v5.8)**
- **Fuente:** x_price_coreccion (escrita por Server Action paralelo).
- **Aplicación:** DESPUÉS de P1/P3/P6, ANTES de redondeo.
- **Validación empírica (v3.37):** si factor < 0.90 y hay ≥3 sem post-cambio, comparar real vs esperado.
  - Si la demanda real NO cayó lo predicho, blendear hacia 1.0 (atenuar over-corrección).
  - Solo atenúa, no amplifica (asimetría: sub-forecast cuesta más).

#### G. **Calibración por Categoría (v3.47)**
- **Fuente:** x_categ_calib_factor (refrescada mensualmente).
- **Entrada:** (categ_id, abc_letter) → factor ∈ [0.70, 1.30].
- **Aplicación:** DESPUÉS de correccion_factor (precio), ANTES de trend_factor (team).
- **Propósito:** capturar sesgo estructural del motor por segmento (Cervezas Premium A: +22%, Cervezas Tradicionales A: -6%) que precio+trend no capturan.
- **Gate:** por regimen (campo x_studio_regimenes_aplicables, default "REG-1,REG-2,REG-4,REG-8").

#### H. **Trend Correction (v3.43)**
- **Fórmula:** trend_factor[team] = clamp(1 + mean(YoY_i), 0.70, 1.00).
  - YoY_i = units[week_i] / units[week_i-52] - 1 (últimas 8 sem).
  - Asimétrico: recorta en alza YoY, pero NUNCA amplifica.

- **Aplicación:** DESPUÉS de precio + categ_calib, ANTES de bias-outlier.
- **Por qué asimétrico:** teams en alza YoY ya están over-forecast por SI suave (bebidas/verano). Amplificar rompe esos teams.
- **Resultado validado:** Mar-16 BIAS -15.0% → -9.9% (+5.1pp mejora).

#### I. **Bias-Outlier Correction (v3.48)**
- **ÚLTIMA capa, post-write a DB.** Corre sobre filas ya escritas.
- **Mecanica:**
  1. Acumula por SKU (unidades, no %) comparando mu_ensamblado vs real reciente limpio de quiebre.
  2. Toma Pareto-80% del error absoluto (atenúa ruido).
  3. Guard de persistencia 2/3 sem en dirección del delta.
  4. Aplica+marca factor multiplicativo GLOBAL por SKU.

- **Clamp asimétrico:** [0.65 (piso prudente), 4.0 (techo generoso)].
  - Piso: cortar suave lo largo (over-forecast).
  - Techo: corregir lo corto (sub-forecast cuesta más).

- **Costo:** despreciable (real reusa pull, quiebre se consulta solo al subset Pareto ~90%).
- **Safety:** envuelto en try/except. Un fallo de esta capa NUNCA rompe el forecast productivo.

---

## 3. Evolución del Proyecto (Hitos)

| Versión | Fecha | Cambio | Resultado |
|---------|-------|--------|-----------|
| **v3.31** | 2026-05-12 | Redondeo medio-arriba, reader de x_price_coreccion | WAPE 70.85% (baseline) |
| **v3.35** | 2026-05-20 | Eliminado ajuste precio interno, delegado al detector | Arquitectura limpia |
| **v3.39** | 2026-05-20 | Auto-model selection per SKU (bake-off SAP IBP) | WAPE 66.94% (-0.42pp) |
| **v3.43** | 2026-05-26 | Trend correction YoY asimétrico por team | Mar BIAS -15.0% → -9.9% |
| **v3.44** | 2026-05-27 | Fix lifecycle 'declining' (falso positivo Apr-06) | 4,926 SKUs reclasificados |
| **v3.45** | 2026-05-28 | Removido threshold mu<2.0 del router (canon SAP IBP) | Z3 secondary rescata SKUs B/C |
| **v3.46** | 2026-05-28 | Removido redondeo (persistir float, canon SAP IBP) | mu ∈ [0.2, 0.8] rescatado |
| **v3.47** | 2026-05-28 | Calibración por (categ, abc_letter) refrescada mensualmente | Sesgo estructural por segmento |
| **v3.48** | 2026-05-29 | Bias-outlier correction (Pareto-80% limpio de quiebre) | Última capa, PROXY in-sample |

---

## 4. Metricas y Resultados Actuales

### 4.1 Backtest Productivo (W17-W19, 2026)

**v3.31 Baseline:**
- WAPE global: 70.85%
- BIAS global: -3.16% (leve sub-forecast)
- forecast=0 + real>0: 3,870 filas / 5.41% del real

**v3.43 + Trend Correction:**
- WAPE total: 64.1% → 63.7% (-0.36pp)
- **Panguipulli:** factor 0.82, BIAS -28.8 → -8.2 (+20.6pp mejora)
- **Futrono:** factor 0.85, BIAS -17.2 → -2.7 (+14.5pp mejora)
- **Los Lagos:** factor 0.86, BIAS -12.1 → +0.2 (+12.3pp mejora)
- Trade-off: Feb-16 empeora +2.65pp (compresión uniforme por team afecta categorías en sub).

### 4.2 Validación por Régimen

| Régimen | Descripción | WAPE | BIAS | Notas |
|---------|-------------|------|------|-------|
| REG-1 | Smooth A (core control) | 53.69% | -2.1% | Intacto, auto-model sin regresión |
| REG-2 | Smooth B | 62.4% | -1.8% | Control OK |
| REG-4 | Erratic | 75.2% | -4.5% | Riesgo de amplificación |
| REG-5 | Lumpy A/B | 101.86% | -8.2% | Croston/SBA aportan |
| REG-6 | Lumpy C | 171.33% | -15.3% | Ultra-esporádico, no rescatable |
| REG-7 | Intermittent | 89.27% | -5.8% | SBA(α=0.05) descartado, SMA suficiente |
| REG-8 | Seasonal | 73.88% | -2.2% | PLC + feriados, sin gate |

### 4.3 Validación Fair Share

**Diagnóstico SKUs A con <3 salas activas:**
- Total: 60 SKUs clase A en 12 salas (720 pares posibles).
- Gap: 97% son "probó y falló" (active_weeks>0, mu_local=0).
- **Conclusión:** regla fair_share_min_salas=1 es correcta; tried_penalty=0.15 bien calibrada.

### 4.4 Validación Auto-Model

**REG-1 Control (Smooth A):**
- v3.37 baseline: WAPE 53.68%
- v3.39 auto-model: WAPE 53.69% (intacto, +0.01pp varianza)
- **Conclusión:** heuristic-bias=0.90 protege el core sin sacrificio.

**REG-5/6 (Lumpy):**
- Croston/SBA ganan en ~15-20% de SKUs (donde MAE >10% mejor).
- WAPE marginal -2.6pp a -10.9pp en regímenes esporádicos.

---

## 5. Diagnósticos Conocidos y Limitaciones

### 5.1 Contaminación por Quiebre (Stock-Out)

**Problema:** cuando `x_stock_balance_daily` registra stockout, la demanda real cae artificialmente. El motor puede interpretarlo como "colapso real" (sub-forecast resultante).

**Solución (v3.48):** bias-outlier correction descarta celdas (team, sku) con ANY quiebre en ventana 3 sem. Esto asegura que solo se corrije sobre demanda "verdadera".

**Marca:** `x_studio_bias_outlier=TRUE` + `x_studio_bias_outlier_factor` ∈ [0.65, 4.0].

### 5.2 Feriados y Cambio de Día de Semana

**Problema:** feriados fijos (Dec-25, Jan-01, etc.) pueden caer en lunes o viernes, alterando el patrón semanal. SI no captura "feriado en lunes" vs "feriado en viernes".

**Solución pendiente:** capa `x_promo_plan` futura (ver memory [[si_no_captura_dia_semana_feriado]]).

### 5.3 Trend Correction Uniforme por Team

**Limitación:** trend_factor es global por team, no desagregado por categoría.

**Efecto:** Feb-16 empeora +2.65pp porque Pisco/Whisky estaban en sub-forecast, y el factor uniforme los recorta más.

**Solución arquitectural potencial:** granularidad trend_factor[team × categ_L1], pero no implementada (trade-off complejidad vs ganancia marginal).

### 5.4 April-6 Motor Cutoff Bug (Pendiente Diagnóstico)

**Síntoma:** cuando cutoff < 8 sem de hoy, ~99% de SKUs caen en min_stock_or_manual (forecast=0). Típicamente al inicio de un Q (April-6, May-4 en backtests).

**Causa probable:** presencia trimestral `u_q0=0` (Q actual) genera lifecycle "declining" falso → router envía a REG-0 → forecast=0.

**v3.44 fix:** agregado check `nz_recent_8w` (SMA-style) para validar que el SKU sigue vendiendo. Pero aún requiere diagnóstico a fondo.

---

## 6. Stack Técnico

| Componente | Detalles |
|------------|----------|
| **Hosting** | AWS, Odoo 17 EE |
| **Base de Datos** | PostgreSQL (advisory locks, SAVEPOINT defensivos) |
| **Tablas Core** | x_hm_si_forecast, x_price_coreccion, x_categ_calib_factor, x_demanda_normalizada, x_stock_balance_daily |
| **Lenguaje** | Python 3 (Odoo Server Action sandbox) |
| **Dependencias** | Cero (sin numpy/scipy, solo built-ins) |
| **Testing** | Backtest via `4- OH Forecast Backtest.py` (comparación semanal WAPE/BIAS) |
| **Lock** | PostgreSQL advisory lock LOCK_KEY=99009438 para mutual exclusion |

---

## 7. Cómo Retomar el Proyecto

### 7.1 Ejecutar el Motor

```sql
-- Server Action: `HM SI FORECAST - FWD_v3_48_BIAS_OUTLIER`
-- Parámetros típicos via context:
SELECT ir_actions_server.run_server_actions(
    server_action_id=X,  -- ID del SA en Odoo
    context={
        'fwd_model': 'x_hm_si_forecast',
        'hard_reset': True,
        'team_ids': [5,6,7,8,9,10,11,12,13,16,17,18],
        'demand_history_months': 24,
        'demand_window_weeks': 26,
        'apply_trend_correction': True,
        'apply_categ_calib': True,
        'apply_bias_outlier': True,
    }
);
```

### 7.2 Validar Resultados

1. Backtest: ejecutar `4- OH Forecast Backtest.py`.
   - Input: `x_hm_si_forecast` de últimas 3 semanas cerradas.
   - Output: CSV con WAPE/BIAS por team, regimen, categoría.

2. Dashboard: revisar campos en x_hm_si_forecast:
   - `x_studio_mu_week` (pronóstico final flotante).
   - `x_studio_forecast_zone` (Z1-Z4 router).
   - `x_studio_correccion_factor` (efecto precio).
   - `x_studio_categ_calib_factor` (efecto categ).
   - `x_studio_mu_week_pre_bias` (pre-trend, para auditoria).
   - `x_studio_bias_outlier` (TRUE si corregido, raro ~1-2%).

### 7.3 Pendientes Activos

1. **Normalizacion de Demanda (Proyecto 2026-05-25):**
   - Flag USE_DEMAND_NORMALIZATION_DEFAULT = True (en prueba).
   - Overlay x_demanda_normalizada corrige censura de quiebre.
   - Post-validación → default permanente.

2. **Detector Aprende Factores (v5.9+):**
   - Reemplazar tabla hardcoded de elasticidad ABC por factores empíricos por SKU.
   - Relacionado: memory [[project-detector-aprendido]].

3. **Fair Share Extendido:**
   - Posible granularidad categ_L2 en lugar de categ global.
   - Diagnosticado: regla actual es correcta, pero marginal gain potencial.

4. **Presupuesto Integracion:**
   - Script 5 (`OH Presupuesto Ventas`) consume el backtest y calibra baseline.
   - Coordinación: presupuesto usa patrón "baseline + evento" idéntico a correcciones.

---

## 8. Referencias Documentales

**Código:**
- [02_forecast/HM SI Forecast.py](02_forecast/HM SI Forecast.py) — motor productivo v3.48.
- [02_forecast/OH Price Correccion.py](02_forecast/OH Price Correccion.py) — detector v5.8.
- [04_analitica/OH Calib Factors.py](04_analitica/OH Calib Factors.py) — capa categ calibration (v3.47).

**Backtests / Análisis:**
- [02_forecast/OH Forecast Backtest.py](02_forecast/OH Forecast Backtest.py) — validación semanal.
- [proyectos/2026-05-26-backtest-3-no-consecutivas/](proyectos/2026-05-26-backtest-3-no-consecutivas/) — laboratorio v3.43+.

**Memoria Distribuida:**
- [[project-motor-productivo-2026-05-12]] — snapshot v3.31 baseline.
- [[hm-si-v3-43-trend-correction]] — trend correction impl.
- [[auto-model-per-sku-funciona]] — bake-off SAP IBP.
- [[forecast-backtest-context]] — CSV backtest schema.
- [[forecast-noise-feedback]] — filtrado de quiebre en backtest.

**Decisiones Arquitecturales:**
- [[modelo-separacion-responsabilidades]] — x_calculo_abc_xyz vs x_analisis_de_stock.
- [[feedback-evitar-casuisticas]] — preferir motor genérico estable.
- [[feedback-objetivo-declarado]] — sub-forecast cuesta más que over.

---

## 9. Contacto y Escalación

**Propietario:** Marco Sanhueza (usuario@ohmarket.cl)  
**Última Actualización:** 2026-05-29 (v3.48)  
**Próxima Revisión:** post-rollout bias-outlier correction (validar impact real en stock).

---

**Fin de Documento.**
