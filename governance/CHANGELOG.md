# CHANGELOG — OH Market Pipeline

Histórico detallado de versiones de todos los scripts del pipeline.
La versión activa y el resumen operativo (reglas vivas) están en el header
del propio script. Aquí queda el detalle de cada fix, snapshot de impacto y
métrica histórica para auditoría.

Convención de versionado por script: cada script lleva su propio contador
(`vMAJOR.MINOR.PATCH` o `vN`). El orden dentro de cada sección es
descendente (versión más reciente arriba).

---

## 01_segmentacion / OH Calculo ABCXYZ.py

### v19.4 — Vista corta de series_type (2026-05-12)

Vista corta de series_type (Syntetos-Boylan sobre ultimas 12 semanas) ademas de la larga (52 sem).

- `x_studio_series_type`: largo (52 sem), comportamiento existente.
- `x_studio_series_type_short`: corto (12 sem), nuevo.
- `x_studio_series_type_active`: el corto si difiere del largo (y no es no_signal); si no, el largo. Es el que consume el motor HM-SI.
- Regimen ahora se calcula con `series_type_active`.

**Motivo**: SKUs en ramp-up tienen comportamiento corto distinto al largo. Caso real: Cerveza Coors 620 BX smooth (largo) pero en ult. 12 sem vende 121/sem (era 29 promedio anual) -> es smooth con mu alto. Cae en Z4 por `mu<2` global y el motor lo pronostica en 0.

---

### v19.3 — GMROI desde stock.quant (anterior)

GMROI ahora lee inventario directamente de `stock.quant` (primario Odoo) en lugar de `x_analisis_de_stock` (modelo derivado).

- Filtro: `location_id.usage='internal'`, `quantity>0`, `company_id`.
- Costo: usa el `cost_unit` que ABCXYZ ya calcula por producto (COST_MODEL con fallback a `standard_price`).
- Cobertura: incluye TODO el catalogo con stock real, sin depender de que `x_analisis_de_stock` haya corrido o filtre por team activo.
- Sigue siendo SNAPSHOT (al momento de correr ABCXYZ).
- Fase 2 TODO: convertir a PROMEDIO historico sobre 26w leyendo `x_stock_balance_daily`.

---

### v19.2 — Bandas estacionales eliminadas (anterior)

- Eliminada la separacion de semanas BASE vs ALL (bandas estacionales).
- HM-SI descuenta estacionalidad con SI -> ABCXYZ no necesita pre-filtrar.

---

### v19.1 — Refactor multi-dimensional sobre v18.3

Refactor del ABCXYZ para que sea la unica fuente de verdad de la segmentacion de productos. Anade tres dimensiones nuevas:

**A) ADI + CV² (Syntetos-Boylan)**

- ADI = `total_weeks / weeks_with_demand` (intervalo promedio de demanda).
- CV² = `(sigma/mu)²` sobre periodos POSITIVOS unicamente.
- Reemplazan la inferencia de `series_type` via letra XYZ (que mezclaba intermittent con lumpy). La matriz ADI×CV² distingue 4 patrones: `smooth | erratic | intermittent | lumpy`.

**B) REGIMEN de forecast (REG-0..REG-8)**

- Reemplaza las zonas Z1-Z4 (calculadas hoy en HM-SI con caps P6).
- Triplete: `(abcxyz_letter_volumen, series_type, ciclo_de_vida)`.
- HM-SI lee `x_studio_regimen` y aplica la regla directamente.

**C) GMROI + GMROI_CLASS (G_A/G_B/G_C/G_D)**

- Dimension financiera paralela. Mide retorno sobre inversion en stock.
- Cuartiles empiricos sobre el catalogo activo.
- Decide CUANTO invertir en stock (no afecta la regla de forecast).

**Nuevas columnas escritas**:

- `x_studio_adi` (float, intervalo promedio de demanda)
- `x_studio_cv2` (float, CV² sobre periodos con qty>0)
- `x_studio_series_type` (smooth/erratic/intermittent/lumpy/no_signal)
- `x_studio_regimen` (REG-0..REG-8)
- `x_studio_gmroi` (float, margen anual / inv promedio)
- `x_studio_gmroi_class` (G_A/G_B/G_C/G_D)
- `x_studio_inv_valor_avg` (float, $ inventario agregado sobre locales)

**Helpers nuevos**: `_classify_series_type`, `_assign_regimen`, `_load_inv_valor_by_product`, `_compute_gmroi`, `_classify_gmroi_by_quartiles`. Acumuladores `sum_qty_pos`, `sum_sq_pos` en el loop XYZ.

**Mantiene de v18.3**: usar `x_studio_product_id` como `product.product`; ABC, XYZ, ranking, ciclo de vida y eliminacion; letra XYZ y `x_studio_cv` (CV sobre todos los periodos) intactos; NO escribe campos de forecast / cobertura / safety / compra; compatibilidad con `_filter_vals` (si el campo nuevo no existe en Studio, se omite sin error).

**Alcance**:

- Solo ventas POS para ABC/XYZ.
- GMROI lee inventario SNAPSHOT desde `stock.quant`. Si no es accesible, GMROI=0 -> G_D.

Requiere que `x_studio_product_id` sea Many2one a `product.product`.

---

## 02_forecast / HM SI Forecast.py

### v3.42 — Fair share canon SAP IBP / Blue Yonder (2026-05-23)

**Problema que resuelve**: v3.41 rescato 72 pares (60 San Jose + 12 otras salas) con criterio `mu_week==0 AND abc=='A' AND lifecycle in (mature, ramp_up)`. El analisis canon de cobertura ([04_analitica/Cobertura ABCXYZ por Sala.py](04_analitica/Cobertura%20ABCXYZ%20por%20Sala.py)) identifico 265 pares totales con priority_score canon alto: 87 EXPANSION MASIVA (abc=A AND gap_total>=7) + 178 TERMINAR COBERTURA (abc IN (A,B) AND 1<=gap_total<=2).

v3.41 sub-cubria estos casos porque:
- No rescataba clase B con gap pequeno (quick wins).
- Aplicaba factor_normalizado sin penalizar baja confianza (n_active=1).
- Inflaba mu_fs en SKUs nicho con mu_global bajo (sin cap por techo).

**Enfoque canon (SAP IBP / Blue Yonder / Oracle RDF)**: `Priority_Score = Opportunity x Confidence x Tried_Penalty`.

1. Confianza por N salas activas (canon SAP IBP):
   - `n_active = 1` -> conf_n = 0.30
   - `n_active = 2` -> conf_n = 0.50
   - `n_active = 3-4` -> conf_n = 0.75
   - `n_active >= 5` -> conf_n = 1.00

2. Growth cap por mu_global y XYZ (canon Blue Yonder):
   - `mu_cap_total = mu_global x growth_cap(xyz)`
   - `growth_cap = {X: 3.0, Y: 2.0, Z: 1.5}`
   - Por par: `mu_cap = mu_cap_total / max(1, gap_count)`

3. Penalty "probo y fallo" en sala target (canon Blue Yonder):
   - `if active_weeks_local_target > 0: mu_fs *= 0.15`
   - SIN floor cuando se aplico tried_penalty (insight empirico OH: 97% flacos son "probo y fallo").

4. Trigger expandido:
   - `abc_global == 'A'` -> EXPANSION MASIVA (cualquier gap)
   - `abc_global == 'B' AND gap_count <= 2` -> TERMINAR COBERTURA
   - `abc_global == 'C'` -> NO rescatar

Nuevo scope: `core_canon_v42` (distinguible de `core_fair_share` v3.41).

**Resultado en produccion**: 256 pares con mu_week>0 (vs 72 v3.41). 0 pares en `core_fair_share` antiguo. Top: Royal Guard Lata Conaripe (mu=92), Turron Galleta San Jose (31), Bon o Bon (29).

---

### v3.41 — Fair share v2 con share NORMALIZADO por categoria (2026-05-23)

Reemplaza la formula de v3.40 (`mu_global × share_categoria`) que estaba sesgada por el tamano de las salas activas. v3.41 calcula el "peso del SKU en su categoria" promediado SIN ponderar por volumen, capturando un invariante de share independiente del tamano de cada sala.

**Formula**:

```
# Para cada sala activa i (con mu_sku>0 y mu_categ>0):
share_sku_categ_i = mu_sku_en_sala_i / mu_categoria_en_sala_i
factor_normalizado = mean(share_sku_categ_i)   # invariante a tamano

# Sala objetivo:
if historia_categ_target >= 12 semanas:
    mu_categ_target = mu_categoria_real_target
else:
    # Sala nueva: promedio del bottom-N% de salas (default 50%) por
    # mu_categoria, EXCLUYENDO la sala objetivo.
    mu_categ_target = mean(mu_categ for bottom-N salas)

mu_raw = factor_normalizado × mu_categ_target × bias
mu_fs = max(mu_raw, FAIR_SHARE_MIN_UNITS)   # min ahora 1.0 (no 2.0)
```

**Por que el cambio**: el backtest 2026-05-23 (v3.40) mostro que 57 de 61 pares hit el floor=2 flat. El share_categoria pesaba demasiado a las salas grandes -> SKUs con presencia desigual quedaban subestimados, y el floor fijo no compensaba la heterogeneidad.

**Parametros nuevos**:
- `FAIR_SHARE_BOTTOM_PCT` (default 0.5): % de salas a usar como bottom para sala objetivo nueva.
- `FAIR_SHARE_MIN_UNITS` reducido de 2.0 a 1.0 (el factor normalizado ya escala con velocidad real).

Condicion de trigger (heredada de v3.40 FIX): `mu_week==0 AND ABC global=='A' AND lifecycle in ('mature','ramp_up') AND len(shares_activas) >= 3`.

---

### v3.40 — Fair share allocation inicial (2026-05-23)

Cierra el gap medido en Fase 1: 728 pares (sala, clase-A) caian en `no_forecast` => stock no compraba => ausencia se autoperpetuaba.

**Enfoque** (Oracle Retail Demand Forecasting / Blue Yonder "fair share by category share"): cuando una sala no tiene historia local de un SKU clase A global, `forecast = demanda_global × share_categoria_sala × bias_conservador`.

**Reglas (Fase 0 cerrada con usuario, FIX 2026-05-23)**:
- Aplica solo si: `mu_week==0 AND letra_global_ABC=='A' AND lifecycle_local in ('mature','ramp_up') AND n_salas_activas>=3`.
- El trigger es `mu_week==0` (NO `forecast_scope=='no_forecast'`). Motivo: el motor v3.39 tiene rescue rules v3.28/v3.30 que envian clase A con poca demanda a `core_hm_si` (no a `no_forecast`) ANTES del catch-all. La condicion original nunca disparaba.
- Lifecycle whitelist (no blacklist): solo mature/ramp_up reciben fair share. Excluido seasonal (487 pares mu=0 son baja temporada esperada), intermittent (65 son demanda real esporadica), declining/dead (saliendo).
- `n_salas_activas` = numero de salas con qty>0 en data_si para ese SKU. Si <3, NO se aplica (validado empiricamente: 97% de SKUs flacos son "probo y fallo", no oportunidades de expansion).
- Si `historia_categ(sala) < 12 sem`, se usa share_uniforme=1/N_SALAS. Caso San Jose (team_id=11, sala nueva).
- Bias 1.00 + floor 2.0 u/sem (Oracle "minimum forecast quantity"). La asimetria de error se INVIERTE para fair share: el riesgo dominante NO es over-forecast sino el under-forecast que impide a stock comprar -> el SKU nunca llega a la sala -> la ausencia se autoperpetua.

**Formula**:

```
mu_raw      = mu_week_global × share_used × FAIR_SHARE_BIAS
mu_week_fs  = max(mu_raw, FAIR_SHARE_MIN_UNITS)
sigma_week_fs = mu_week_fs × FAIR_SHARE_SIGMA_CV  # CV sin historia local
```

**Impacto esperado**: 146 pares clase A en lifecycle mature con mu_week=0 + ~65 en ramp_up.

---

### v3.39 — Auto-model selection per SKU SAP-style (2026-05-20)

Nuevo wrapper `_select_best_model`. Reemplaza al dispatcher por regimen.

- Para cada SKU corre 4 modelos en paralelo: heuristico, SBA(0.15), Croston(0.10), seasonal_naive_52. Holdout de 4 sem cerradas para evaluar. MAE como metrica. Gana el modelo con menor MAE.
- Heuristic-bias 0.90: el heuristico solo pierde si otro modelo es >=10% mejor en MAE. Protege REG-1 (gold standard) y SKUs estables.
- Sin Holt-Winters (memoria v4: HW destruyo WAPE 90% en REG-1).
- Seasonal naive lag-52 solo participa si `len(base_vals)>=56`. Con `DEMAND_WINDOW_WEEKS=26` actual, no entra; queda hook para v3.40 cuando se amplie la ventana.
- El ganador per-SKU se persiste en `x_studio_demand_method`.
- Sigma reutiliza el del heuristico aun cuando gana otro modelo, para no degradar el calculo de safety stock.
- Fallback al heuristico cuando: `len(base_vals)<12`, modelo ganador devuelve <=0, o ningun candidato produce forecast valido.

---

### v3.38 — DESCARTADO: SBA REG-7 / SMA8 (2026-05-20)

**v3.38 REG-7 SBA** (revertido):
Backtest 3 sem (W18-W20):
- REG-7 WAPE 90.02% -> 91.58% (+1.6pp PEOR)
- REG-7 BIAS -15.48% -> -20.00% (-4.5pp PEOR, sub-forecast)
- WAPE global 67.36% -> 67.79% (+0.4pp)
- BIAS global -3.27% -> -4.29% (-1pp)

Razon: SBA con alpha=0.05 sobre base_vals SI-deflated produce forecast mas conservador que SMA dilution para intermitentes. Helpers `_croston/_sba` quedan en el codigo (no-op) por si se retoma con alpha distinto.

**v3.38 SMA8** (revertido):
`SERVICE_BASE_SHORT_WEEKS_DEFAULT 6 -> 8`. Backtest 3 sem: WAPE neutro pero BIAS global -6.47% vs -3.27% (3pp peor sub-forecast). Colas devastadas: AZ -48.9%, CZ -47.8%, BY -24%. SMA(8) suaviza demasiado SKUs erraticos/lumpy. Vuelta a `SERVICE_BASE_SHORT_WEEKS_DEFAULT = 6`.

---

### v3.37 — Validacion empirica del factor de correccion externo (2026-05-20)

- Cuando `correccion_factor < 0.90` y hay >=3 semanas post-cambio cerradas, se calcula `empirical_factor = avg(base_vals post) / avg(base_vals pre)` usando ventanas de `min(weeks_since_real, 8)` post y 8 pre.
- Si `empirical_factor > correccion_factor + 0.15` (la realidad muestra menos impacto del predicho), el factor se atenua a `(factor + emp)/2`, clampeado a 1.0. La razon se anota con `[emp X.XX adj Y.YYY]`.
- **Asimetrica**: solo atenua over-correcciones, NO aumenta cuts. Aplica la memoria: sub-forecast cuesta mas que over-forecast.
- Caso testigo: SKU 0154 Paillaco BEBIDA COCA COLA DES 3L. Factor teorico 0.814 (predice -18.6%) vs realidad post-cambio +16%. Con validacion, empirical ~1.36 -> factor ajustado a 1.0 -> mu_week 13 -> 17.

---

### v3.36 — Detector de colapso de demanda (2026-05-20)

- Tercer umbral en el branch de bajada: `ratio < SERVICE_RATIO_COLLAPSE (0.30)` devuelve sma_short puro (en lugar del blend 0.7/0.3 que arrastraba ~30% de SMA(16) como inercia fantasma).
- Caso testigo: SKU 451500 Futrono, caida 330 u/sem -> 6 u/sem en 6 semanas. Con el blend antiguo el forecast salia 43 u (real 8); con collapse branch `mu_base = SMA(6)` directo, forecast esperado ~3 u.
- Nueva firma de `_calc_base_demand`: retorna 4-tupla agregando `collapse_detected` (bool) para trazabilidad.
- Nuevo campo de auditoria `x_studio_collapse_detected` (Boolean) en `x_hm_si_forecast`.
- Ajuste (2026-05-20): el ratio que dispara collapse_detected se evalua sobre `raw_vals` (ventas crudas), NO sobre `base_vals` (SI-deflated). La SI deflation enmascara caidas reales cuando coinciden con baja estacionalidad. `mu_base` sigue calculandose sobre `base_vals` para que `si_next` no double-counte estacionalidad.

---

### v3.35 — Limpieza sistema legacy de ajuste de precio (2026-05-13)

ELIMINADO sistema legacy de ajuste de precio inline.
- Removidos: `PRICE_FACTOR_TABLE_L2`, `_lookup_calibrated_factor`, `_apply_decay`, `_load_price_context`, `_price_segment`, `_price_at_week`, `_categ_l2_from_complete_name`, `_norm_categ`, `_classify_price_range`.
- Removidas variables del bucle: `price_factor`, `q_adj`, `base_vals_no_adj`, etc.
- Removidos campos del write: `x_studio_units_sold_adjusted` (legacy).
- El ajuste por cambio de precio se delega 100% al detector externo (Detector v5.8 en `02_forecast/OH Price Correccion.py`) via modelo `x_price_coreccion`. El motor solo consume el factor pre-calculado via `_load_correccion_context` y lo aplica al `mu_week` despues de los caps P1/P3/P6.

---

### v3.34 — Regimen local por team (2026-05-13)

Bajada COMPLETA del regimen por team. El motor ahora consume `xyz_local`, `series_type_local`, `lifecycle_local` y `regimen_local` calculados sobre la serie local del team. Cada variable contiene el valor a usar: si el calculo local tiene senal suficiente, es el local; si no, se hereda el global del router (escrito por archivo 1).

- `series_type_local`: matriz Syntetos-Boylan (ADI + CV2) sobre serie local.
- `lifecycle_local`: presencia trimestral local sobre 8 trimestres.
- `regimen_local`: combinacion (ABC_global, series_type_local, lifecycle_local).
- El motor (caps P1/P3/P6, forecast_zone routing) consume las variables locales. `mu_week` y `sigma_week` resultan distintos por team con respecto al motor anterior que usaba el regimen global del producto.
- Persiste source de cada clasificacion (`local` | `global`) para auditoria.
- ABC sigue global (criterio economico).

---

### v3.33 — XYZ local por team (2026-05-13)

Persiste XYZ local por team derivado de la serie local del producto (`base_vals`). Mismo metodo que el XYZ global (archivo 1): una sola pasada CV simple = `sigma/mu` sobre la ventana completa, umbrales 0.45 / 0.90, `min_active_weeks` alineado al global (4 sem).

- Si `active_weeks_local < MIN` o el calculo local queda vacio, se hereda el XYZ global del producto desde `router_ctx` y se marca `source='global'` para trazabilidad.
- Si el global tampoco esta poblado, `xyz_local` queda vacio y archivo 3 fuerza CZ via regla anti-blanco.
- Escribe en `x_hm_si_forecast`: `x_studio_xyz_local`, `x_studio_xyz_local_source`, `x_studio_active_weeks_local`.
- Consumidor (archivo 3) compone `abcxyz_efectivo = ABC_global + XYZ_local` y elige Z del safety segun esa combinacion. Toggle `ENABLE_XYZ_LOCAL` en archivo 3 controla el rollout. ABC sigue global.

---

### v3.32 — series_type_active de ABCXYZ v19.4 (2026-05-12)

Consume `x_studio_series_type_active` (ABCXYZ v19.4) con fallback a `x_studio_series_type` largo si el field nuevo no existe. Permite que el router actue sobre el comportamiento RECIENTE (12 sem) en lugar del historico largo (52 sem). Resuelve casos como Cerveza Coors 620 que vendia 30/sem historico pero ahora vende 120+/sem y caia en Z4 por mu<2 por team.

---

### v3.31 — Redondeo medio-arriba del mu_week final (2026-05-12)

- `mu_week < 0.5` -> 0 (drop demanda muy debil).
- `mu_week >= 0.5` con fraccion >= 0.5 sube al siguiente entero (ej 1.5->2).
- `mu_week >= 0.5` con fraccion < 0.5 baja al entero actual (ej 1.3->1).
- `sigma_week` y `mu_week_pre_corr` quedan continuos para trazabilidad.
- Formula: `float(int(mu_week + 0.5))`. Sin import math.

---

### v3.30 — AX/AY rescue + suavizar P3 (2026-05-12)

2 cambios contra forecast=0 con ventas reales.

a) Rescate AX/AY no terminales con `mu_week < 2.0` (patron v3.28 AZ rescue). 256 filas, 511 unid. P6 cap activo. Cambio limpio sin dano en WAPE.

b) Suavizar P3 zero-gate de `nz_recent <= 1` a `nz_recent == 0`. SKUs con 1 venta en 8 sem son intermitentes vivos. Forecast=0+ventas reales: 1,940 -> 821 (-58%). Real perdido sub-forecast: 3,200 -> 1,300 unid.

Trade-off WAPE: +0.74pp global (BZ/CZ over-forecast en colas con volumen bajo). Costo aceptado: el objetivo es cobertura, no WAPE.

---

### v3.29 — Integracion detector x_price_coreccion (2026-05-12)

Integra detector `x_price_coreccion` (typo intencional de Studio).

- `_load_correccion_context`: 1 query batch antes del loop, filtra `target_week_start <= target_date AND active=True`, toma mas reciente.
- Aplica `factor_corr` DESPUES de caps P1/P3/P6 (declining/dead siguen en 0; los caps protegen contra over-forecast del motor base, pero el factor es senal externa intencional que puede superarlos).
- Persiste `x_studio_correccion_factor` / `tipo` / `razon` / `mu_week_pre_corr` para auditoria.

---

### v3.28 — AZ rescue del catch-all Z4 (2026-05-12)

Rescatar AZ del catch-all Z4 (whisky/vino premium).

- Diagnostico: backtest 2026-05-04 mostro 40 SKUs AZ (ABC=A, XYZ=Z) con BIAS +48.31% sub-forecast severo. El router v3.24 los mandaba a Z4 por la regla `mu_week < 2.0` -> forecast=0 mayoritariamente.
- Fix: agregar regla en `_route_forecast_scope` ANTES del catch-all Z4: `if (abc == 'AZ') and (lc not in ('declining', 'dead')): return 'Z1', ...`
- Resultado: los AZ no terminales reciben motor activo (SMA + SI + ajuste precio) y P6 cap por `max_obs * 1.2` los protege contra over-forecast extremo.
- Impacto medido: 40 SKUs, 3,494 unid reales en 3 sem, 3.2% volumen A.
- v3.27 (Holt doble en REG-1/2/3) fue REVERTIDO antes de medir: no se justifico tocar REG-1 que ya funcionaba (BIAS -1.2% en AX).

---

### v3.26 — Consolidacion fallback XYZ->series_type (2026-05-12)

Cosmetica. El fallback (X->smooth, Y->erratic, Z->lumpy cuando series_type no viene poblado desde ABCXYZ) aparecia duplicado en dos lugares (antes del router y dentro de `_route_forecast_scope`). Consolidado en helper unico `_infer_series_type_from_xyz`. Cero cambio funcional.

---

### v3.25 — Excluir REG-8 seasonal del P3 zero-gate (2026-05-12)

Diagnostico: backtest 2026-05-04 mostro BIAS +49.54% en REG-8 (5,291 SKUs). Causa: los SKUs estacionales tienen ventanas de cero entre temporadas que NO indican declive, pero P3 (forecast_zone=Z4 + nz_recent<=1 -> mu_week=0) los anulaba. Cuando llega la temporada, el motor esta en cero.

Fix: 1 linea — agregar `and router_regimen != 'REG-8'` al guard de P3. El regimen se lee de `x_calculo_abc_xyz.x_studio_regimen` (matriz canonica de ABCXYZ v19.3). v3.24 inyectaba el regimen pero NO lo usaba en el calculo. v3.25 es la primera version donde el regimen modula la logica del motor.

---

### v3.24 + regimen — Rollback desde v4.3 + injection x_studio_regimen (2026-05-12)

Rollback desde v4.3-revert tras backtest pareado mostrar que v4.3 era 65pp peor (WAPE 140 vs 75). Unica modificacion vs v3.24 original: inyeccion de `x_studio_regimen` desde ABCXYZ (5 lineas), sin alterar la logica de calculo.

Cambios activos:
- Mantenido: correccion de nivel mixto en ajuste SKU — usa `local_categ` como referencia cuando `si_main` proviene de `local_categ` (antes mezclaba niveles).
- Mantenido: `PRICE_FACTOR_TABLE_L2` limpia (sin duplicados, sin None, normalizado).
- Revertido v3.22: `_calc_si_from_weekly` vuelve a divisor `len(clean)` y `len(avg_by_week)` porque `/expected_n` y `/52` inflaban SI en semanas presentes -> deflactaban `mu_base` via `q_base = q_adj/si_w` -> underforecast cronico en Z-class (AZ +19.7pp wMAPE).
- Revertido v3.22: semanas faltantes SI=1.0 (neutro) en vez de 0.0.

---

### v3.21 — Limpieza PRICE_FACTOR_TABLE_L2 (2026-05-12)

- Eliminados 4 duplicados sin tilde (Cocteles, Snack, Isotonicas, Electronicos).
- Todos los None reemplazados por valor DEFAULT correspondiente (tabla autoexplicativa).
- Lookup normalizado via `_norm_categ()` — resiste variaciones de tilde/mayuscula.

---

## 02_forecast / OH Forecast Base.py

### v1.5 — Cleansing de quiebre POR DIA ponderado por perfil dia-semana (2026-06-02)

`_cleanse_stockout` deja de borrar la semana entera y reemplazarla por el baseline historico. Ahora de-censura por la fraccion de VENTA que estuvo disponible (proportional unconstraining, canon SAP IBP):

- Calcula un **perfil de venta por dia-de-semana GLOBAL** de la cadena (runtime, ultimas `dow_profile_weeks`=12 sem): peso por dia que suma 1 (Sab ~22%, Vie ~19%, Dom ~18%, Lun ~9%). El peso es por VOLUMEN DE VENTA del dia, NO por frecuencia de quiebre (aunque correlacionan: mas venta → mas rotacion → mas probabilidad de agotarse).
- **Quiebre leve** (`peso_perdido < cleanse_severe_weight`, default 0.5): `demanda = venta / (1 - peso_perdido)`, donde `peso_perdido` = suma del peso-venta de los dias que quebraron. Un quiebre de sabado levanta mas (perdiste ~22% de la venta-semana) que uno de lunes (~9%). Sigue la demanda reciente.
- **Quiebre severo** (`peso_perdido >= cleanse_severe_weight`): la semana perdio demasiada venta → promedio de las `cleanse_base_weeks` semanas in-stock previas (baseline, comportamiento anterior).
- Siempre solo-levanta.

**Bug que corrige** (validado, caso Royal Guard Golden 28382, cerveza estacional que cayo −95% verano→otono): con `min_days=1`, v1.4 marcaba la semana entera como suprimida con 1 solo dia de quiebre y la subia al promedio de las 6 in-stock previas, que arrastraba el verano (~182). El SES quedaba anclado arriba → forecast en **sentido contrario a la venta** (fc 121→153→169 mientras vendia ~20). Reconstruccion offline: fc v1.4=169 vs v1.5-dow=18 (venta real 30); el quiebre de sabado se pondero 0.22 y el de lunes 0.09. El driver del over de `ses_a0.50` (smooth+A, BIAS −15.5% limpio) era este.

- Costo de calculo: +1 query agregada (perfil dow, GROUP BY isodow) — barata; la query de quiebre suma isodow al GROUP BY. Sigue en ~5s.
- Nuevos params `cleanse_severe_weight` (default 0.5) y `dow_profile_weeks` (default 12). Ver memoria `cleansing-min-days1-ancla-baseline`.

---

### v1.4 — no_signal vivo via SMA(6) en vez de Mediana(4) (2026-06-02)

La rama `no_signal` pasa de `Mediana(4)` a `SMA(SMA_TAIL_WEEKS=6)` con `model_code='sma6_ns'`. Ataca el sub-forecast de los intermitentes lentos VIVOS sin inflar los obsoletos.

- **Diagnostico (backtest W20-W22)**: de 12.379 filas `median4`, 10.641 estaban OK en cero (muertos reales), pero ~1.230 combos vendian esporadico (2.017 u medidas) y recibian forecast 0 — caian en `no_signal` por `MIN_ACTIVE_WEEKS=4` (vendio en <4 de 26 sem) → Mediana(4)=0. BIAS de la clase: **+74.9%** (sub severo).
- **Por que SMA(6) y no recencia explicita**: el SMA(6) ya da 0 a quien no vendio en las ultimas 6 sem (muerto real) y >0 al que vendio reciente (vivo) → la recencia se auto-regula, sin parametro extra. Canon: proxy de **TSB (Teunter-Syntetos-Babai)**, el modelo de intermitente con obsolescencia. Decidido NO implementar TSB completo (mas codigo; memoria previa de SBA con alpha bajo fue negativa).
- `model_code='sma6_ns'` distinto del intermittent `sma6` para auditar el corte por separado en el backtest.
- **Casos canonicos**: (a) SKU con 3 ventas en 26 sem, ultima ≤6 sem → mu>0 (antes 0); (b) muerto real sin venta en 6 sem → SMA(6)=0 (sigue 0, no se infla); (c) SKU que vendio al inicio y nada en ult. 6 sem → SMA(6)=0 (no revive).
- Sin tocar el resto de ramas (smooth/erratic/intermittent/lumpy) ni la de-censura.

---

### v1.3 — Persiste series_type para auditoria (2026-06-02)

Persiste `x_studio_series_type` en `x_hm_si_forecast` junto al `forecast_model_code`. El motor ya clasificaba la forma de serie LOCAL (Syntetos-Boylan) para elegir el modelo; ahora la escribe en vez de descartarla. Sin cambio de `mu_week`/`sigma_week` ni de la seleccion de modelo: es solo metadato.

- **Motivo**: el backtest agrupaba por `series_type` y salia vacio (0 de 18.058 filas) porque el motor Base no lo persistia — solo lo hacia el HM-SI v4.3+. Recupera el desglose smooth/erratic/intermittent/lumpy/no_signal en el backtest sin tocar el forecast.
- `forecast_zone` / `regimen` siguen sin escribirse: el Base clasifica por `series_type` local, no por el regimen REG-X global (decision de diseno documentada en el header).

---

## 02_forecast / OH Forecast Backtest.py

### v11.2 — Limpieza de código muerto post-OLD (2026-06-02)

Barrido de solo borrado, sin cambio de fórmula ni de fuente de datos. No altera ninguna métrica del backtest (WAPE/BIAS/real/forecast idénticos). Elimina definiciones huérfanas que quedaron tras v11.0 (que dejó de llamarlas) y la columna CV2 cuya fuente murió.

- Borra funciones sin llamadores: `_first_existing_field_or_label`, `_selection_accepts`, `_load_real_sales` (no-batched, reemplazado por `_load_real_sales_batched`), y `_load_computed_segment_rows_from_pos`.
- Borra helpers que solo usaba la función de segmentación eliminada: `_series_type_from_metrics`, `_calc_adi_from_vals`, `_quarter_abs`, `_infer_lifecycle_simple`, `_seasonal_band_for_week`, `_week_range`.
- Elimina la columna CV2: `cv2_map` ya no se poblaba (su fuente era la función borrada), por lo que el campo `x_studio_cv2` se escribía siempre como `0.0`. Se quita la resolución `BT_CV2`, la var `cv2_map` y el write. La columna deja de poblarse (queda vacía en vez de 0.0).
- Elimina la var muerta `seasonal_band_map`.
- `_variant_template_map` se conserva: sigue en uso en el fallback legacy de `_load_abcxyz_map`.

---

### v11.1 — Soporte REG-0..REG-8 en _zone_code

- `_zone_code()` ahora acepta REG-0..REG-8 como valores validos. Antes cualquier valor que no fuera Z1-Z4 caia silenciosamente a SIN_ZONA. Esto rompia el backtest contra HM-SI v4.3+ que escribe REG-X en `x_studio_forecast_zone` (nueva semantica).
- Lectura de `x_studio_regimen` y `x_studio_forecast_model_code` desde `x_hm_si_forecast`. Se persisten en columnas paralelas del modelo `x_forecast_backtest` (best-effort: si no existen, se omiten).
- Mantiene compatibilidad backward: si HM-SI no escribe regimen, `x_studio_forecast_zone` sigue siendo la fuente de la dimension de segmentacion para reportes.

Alcance B pendiente (Etapa 2.4 profunda del roadmap):

- Reemplazar `zone_metrics` por `regimen_metrics` como dimension primaria.
- Adaptar mensajes de log y reportes para usar regimen.
- Migrar analisis posteriores (pandas) a regimen.

---

### v11.0 — PERF: lecturas batch + cache

- Elimina `_load_computed_segment_rows_from_pos` por semana: lee `series_type` y `lifecycle` directamente desde `x_hm_si_forecast` (ya calculado por HM-SI).
- Batch de `_load_real_sales`: una sola query cubre todas las semanas.
- `_load_abcxyz_map` se llama una vez por semana en vez de una vez por metodo.
- `BT_CV2` queda en 0.0 (CV2 no persiste en `x_hm_si_forecast`).

---

### v10.4 — Persiste mu_week_pre_bias

- Lee `x_studio_mu_week_pre_bias` desde `x_hm_si_forecast`.
- Lo persiste en `x_forecast_backtest` para medir efecto real del bias.
- Forecast final sigue en `x_studio_mu_week` / `x_studio_forecast_qty`.

---

### v9 — Unifica llave operativa en product.product

- Unifica la llave operativa en `product.product`.
- Venta real POS se agrupa por `pp.id`, no por `product_template`.
- Segmentacion calculada desde POS se agrupa por `pp.id`.
- ABCXYZ se carga directo desde `x_calculo_abc_xyz` por `product.product`.
- No usa `default_code`, nombre ni template para cruzar ABCXYZ.

No toca: stock, compras, transferencias, ordenes de compra.

Resultado: backtest por semana + local + product.product + metodo.

---

## 02_forecast / OH Price Correccion.py

### v5.9 — REVERTIDO: canibalizacion pasiva con lista blanca L2 (2026-05-12)

Probada: canibalizacion pasiva con lista blanca de categ L2. Resultado: WAPE +0.04pp neutro, no agarro los outliers reales (Royal Guard quedo igual). Probable causa: CPI por sub-cat L3 separa "Cervezas Tradicionales" de "Cervezas Promocion".

Revertido por decision: evitar acoplar el motor a casuisticas especificas del negocio al inicio. Se puede retomar mas adelante subiendo CPI a nivel L2 + listando intercambios manuales.

---

### v5.8 — Lookback de precios extendido a 52 sem (2026-05-12)

- `LOOKBACK_PRICE_WEEKS = 52` (era 12). Captura cambios sostenidos viejos. Caso real detectado: cervezas Royal Guard / Cristal Ultra con bajada de hace ~20 sem que sigue vigente, generaba canibal activa pero el detector la ignoraba por estar fuera de ventana.
- Subidas con `weeks_since >= 12` quedan con factor=1.0 por decay (no generan ruido). Bajadas son sostenidas - factor sigue activo.

---

### v5.7 — Ponderacion ELASTICIDAD_ABC

- Ponderacion `ELASTICIDAD_ABC` sobre el factor base para cambios de precio (solo en la rama "sin promo"):
  - A: x1.3 (commodities con alternativas, mas elastico)
  - B: x1.0 (sin cambio)
  - C: x0.7 (cola cautiva, menos elastico)
- Se aplica como `1 + (factor - 1) * mult`, asi es coherente para subidas (factor<1) y bajadas (factor>1).
- Promos y BAJADA_DISCONTINUACION NO se ponderan (el lift de promo ya viene medido del SKU; discontinuacion siempre factor=1.0).
- `_put_field` selection ahora es case-insensitive (fallback).
- Diagnostico en notificacion: `abcxyz_field` / `con_valor` / `vacio`.

---

### v5.6 — target_week_start = period_start del evento

- `target_week_start` ahora = `period_start` del evento (no proxima semana). Permite auditar contra backtest historico y reutilizar la fila por varias semanas mientras el efecto siga activo.
- Filtro: solo SKUs con `product.product.active=True AND sale_ok=True` (excluye archivados, no-vendibles, liquidaciones cerradas).
- Persiste `x_studio_abcxyz` (string completo AX/AY/AZ/BX...) en cada fila.
- Purge inicial: ya no por target_week (ahora varia por SKU); purga todos los activos y recrea el snapshot.

---

### v5.5 — Bug fix: detector no leia cambios de precio

- Bug fix: el detector no leia cambios de precio porque el campo fecha real en `x_price_change_event` es `x_studio_period_start` (no `x_studio_fecha` como suponiamos). Sin `date_field` detectado, `_first_field` devolvia False y todo el bloque se salteaba en silencio -> 0 alertas de cambio de precio.
- Agregado filtro `is_real_change=True` opcional para descartar fluctuaciones espurias.

---

### v5.4 — Lookback diferenciado por fuente

- Lookback diferenciado:
  - Precios: 12 sem (cubre decay 12s de subidas + bajadas sostenidas que pueden tener varios meses).
  - Promos: 4 sem (las promos son cortas; mas atras es ruido).
- Sin regex en `_extract_mecanica` (Odoo safe_eval rechaza `IMPORT_NAME`).

---

### v5.3 — Nombre modelo destino corregido al typo de Studio

- Nombre modelo destino corregido al typo real de Studio: `x_price_coreccion` (una sola 'r').
- Quitado write a `x_studio_company_id` (campo no existe en Studio).
- Selection `x_studio_tipo_alerta` extendida en Studio con todos los tipos granulares; el runner los persiste tal cual (sin mapeo).

---

### v5.2 — Decay por tipo de cambio + clasificacion de promo

- BAJADA de precio = promo sostenida -> sin decay (factor vive hasta nuevo cambio).
- SUBIDA de precio = decay 12 sem (era 8, adaptacion mas gradual).
- Promo clasificada por `minimum_qty` (no solo por nombre):
  - `min_qty <= 2`: pareo, no alertar salvo lift extremo.
  - `min_qty 3-4`: mixto.
  - `min_qty >= 6`: stock-up (DISPARO_W1, SATURACION_W3+).

---

## 03_stock / OH Analisis de Stock.py

### v9.1.87 — Phantom: reposicion CD compra el padre, no el hijo (2026-06-08)

Fix de dirección en el loop de **reposición automática CD para `solo_bodega`**.

- **Síntoma**: packs phantom comprables (ej. 450684 CERVEZA ROYAL GUARD LATA
  6X470) no generaban compra. La que compraba era la **lata unidad** (hijo,
  7802100002747) por su demanda directa (~22/sem → 2 cajas), mientras el pack
  (padre) quedaba en `no_comprar` con target 0 — pese a tener demanda pooled
  consolidada al CD (`cd_demanda_origen≈95/sem`, `pool_parent_demand=1`).
  Resultado: exactamente la regla al revés (`buy_parent_block_children`).
- **Causa raíz**: el loop de reposición CD (solo_bodega) tenía
  `if kit_components_tmpl.get(tid): continue`, que saltaba **siempre** al padre
  phantom y **nunca** al hijo. Esa exclusión sólo era correcta bajo el modo
  legacy `block_parent`; nunca se hizo *mode-aware* al pasar el default a
  `buy_parent_block_children`. El bloqueo del hijo a nivel sala (línea ~2636) sí
  funcionaba, pero este loop del CD lo pasaba por encima y le compraba igual.
- **Fix**: el skip ahora depende de `PHANTOM_PROCUREMENT_MODE`:
  - `buy_parent_block_children` (default): salta el **hijo**, repone el **padre**.
  - `block_parent` (legacy): salta el padre (comportamiento anterior).
  - `allow_parent`: no salta a ninguno.
- **Efecto esperado**: el pack compra sobre la demanda pooled (en cajas de 6) y
  la lata cae a 0 en el CD. Alcance: 61 padres phantom comprables (cervezas
  multipack: Cristal, Escudo, Austral, Coors, Heineken, etc.).
- Sin cambios en el cálculo de qty ni en otros caminos (compra_sala / path de
  consolidación por `qty_compra_cd`). Un solo bloque tocado.
- **Validar al correr**: que el stock del padre phantom en el CD venga derivado
  de componentes (`_apply_kit_stock`) y no doble-cuente con el stock de la lata.

### v9.1.86 — Trazabilidad de OC pendientes

- Trazabilidad de OC y pickings que originan el stock_pedido.
  - **Antes**: `stock_pedido_compra` y `stock_pedido_transfer` mostraban solo
    la cantidad agregada, sin indicar qué documento(s) la disparaban. Revisar
    requería abrir Odoo y buscar manualmente las OC/pickings abiertos por SKU
    y locación.
  - **Ahora**: por cada fila (local-SKU o CD-SKU) se persiste un nuevo campo
    de texto `x_studio_oc_pendientes` con los nombres distintos de las
    OC (P00xxx) y pickings internos (CD/OUT/xxx) que tienen movimientos
    abiertos hacia la locación destino. Listado separado por coma, ordenado
    alfabéticamente.
- Fuente: queries adicionales en `_build_open_incoming_maps` que hacen JOIN a
  `purchase_order_line`/`purchase_order` y a `stock_picking`, sin alterar el
  cálculo de qty (queries originales sin cambio).
- Persistencia condicional: el campo solo se escribe si `x_analisis_de_stock`
  tiene definido `x_studio_oc_pendientes` en Studio. Crear el campo como
  Texto (Char/Text) antes de correr para verlo.
- Sin cambios en lógica de compra, target, MOQ, transferencias, GMROI,
  presupuesto mensual, phantom pool ni routing sala/CD. Solo agrega
  trazabilidad para revisión humana.

---

### v9.1.85 — CD usa period_weeks por SKU

- Reposición automática CD para `solo_bodega` ahora usa `period_weeks` por
  SKU (mismo horizonte que la sala) en lugar del `CD_TARGET_WEEKS` fijo (30/7).
  - **Antes (v9.1.81-v9.1.84)**: `target_cd = mu_red * CD_TARGET_WEEKS + safety`.
    `CD_TARGET_WEEKS = 30/7 ~ 4.286 sem` (un mes plano para todos). Problema:
    SKUs con periodicidad real <30d (entrega semanal/quincenal) atascaban
    capital y espacio en CD; SKUs con ciclos >30d quedaban sub-comprados
    respecto a la realidad del proveedor.
  - **Ahora**: `target_cd = mu_red * period_weeks_sku + safety`, con
    `period_weeks_sku` tomado del FWD del SKU (`fwd['lead_weeks']`, que en
    este proyecto es PERIODICIDAD de compra, no lead real). Si ningún record
    del SKU aporta `period_weeks > 0`, fallback a `PURCHASE_CYCLE_WEEKS` (1 sem),
    igual que sala.
- Mantiene `safety = Z * sigma_red * sqrt(period_weeks_sku)`. Mismo Z por
  ABCXYZ que sala/v9.1.82. Coherencia total de horizonte y safety entre
  sala `solo_bodega` y reposición CD->proveedor.
- Threshold de `cover_label_cd` ('bajo' vs 'normal') ahora compara contra
  `period_weeks_sku` (antes: `CD_TARGET_WEEKS`). `_smart_moq_box_or_wait`
  recibe `period_weeks_sku` como `target_weeks` (antes: `CD_TARGET_WEEKS`).
- `decision_reason` expone `cd_target_w` con el `period_weeks_sku` efectivo.
- Sin cambios en:
  - Routing sala vs CD (`COVER_WEEKS_THRESHOLD_FOR_CD` intacto).
  - `compra_cd` consolidada desde locales (ya usaba `period_weeks` por SKU
    via sala desde antes; sin doble cambio).
  - MOQ, phantom, transferencias, retornos, GMROI, presupuesto mensual.
- En esta limpieza (post v9.1.86) se eliminaron las constantes
  `CD_TARGET_WEEKS_DEFAULT` y `CD_TARGET_WEEKS` que quedaban como vestigio
  sin uso operativo.

---

### v9.1.84 — Techo financiero por proveedor

- Techo financiero (`financial_ceiling_sku`) ahora se calcula por proveedor.
  - **Antes (v9.1.83)**: `PAYMENT_DAYS=30` global → `FINANCIAL_CEILING_WEEKS=4.29`
    para todos los SKUs no `solo_bodega`. Mismo techo para BAT (pago a 15d)
    que para CCU (30d) que para Embonor (45d).
  - **Ahora**: lee `res.partner.property_supplier_payment_term_id` por
    proveedor y deriva días efectivos. Cada SKU usa el techo de su supplier.
- Helper nuevo `_payment_days_from_term(term, default_days)`:
  - Estructura observada en OH (Mayo 2026): 1 line por term con
    `value='percent'` y `nb_days=X`. NO usan `value='balance'`.
  - Estrategia: si hay line balance se usa; sino `max(nb_days)` de las lines.
  - Fallback al `PAYMENT_DAYS` global si no hay term o `nb_days=0`.
- Nuevo mapa `supplier_payment_days_map: {partner_id: days}` construido una
  sola vez al inicio leyendo todos los `partner_ids` relevantes (purchase_map,
  local_fwd_map, global_fwd_map). Lectura via ORM porque `property` es
  company-dependent (`ir.property`), no es columna SQL en `res_partner`.
- Impacto medido contra snapshot 2026-05-13:
  - BAT CHILE (cigarros, $40.7M/mes): techo 4.29 → 2.14 sem. Lucky Strike
    Purple Wild 20 y similares (caja deja 6-10 sem) caen del filtro post-MOQ.
    Reduce sobre-stock cigarros baja rotación.
  - CCU (30d): sin cambio.
  - EMBONOR (45d, $57M/mes): techo 4.29 → 6.43 sem. Permite 50% más stock en
    bebidas Coca-Cola si la rotación lo justifica.
  - PARAISO DEL SUR / PISQUERA PORTUGAL (60d): techo 4.29 → 8.57 sem.
  - Proveedores sin payment_term configurado (TABACOS AUSTRAL, DIP,
    SCORE ENERGY): fallback global 30d = sin cambio.
  - `solo_bodega`: techo independiente (`max(1.5, sala_H*2)`), sin cambio.
- Auditoría en `decision_reason`: `pay_days_supplier=X | fcw=Y` cuando el SKU
  no usa el techo global.
- Sin cambios operativos en: `MOQ_COVER_GUARD` (sigue 2.5), `_SAFETY_FACTOR`,
  política `compra_cd`, retornos, presupuesto mensual, phantom pool.

---

### v9.1.83 — Cobertura de caja + exclusión por categoría

- Reemplaza la regla v9.1.74 de `capital_atascado` (monto x tiempo) por una
  regla simple basada en COBERTURA DE CAJA y EXCLUSIÓN POR CATEGORÍA.
  Motivo: la fórmula `valor_caja * cobertura` no medía "capital" sino
  "capital x tiempo", inflando artificialmente productos chicos baratos de
  baja rotación (Halls $4.464 caja con cobertura 24 sem → "capital" $107K
  → CD), generando picking lento en CD para productos donde no aporta valor.
- Nueva regla:
  1. `solo_bodega=True` → CD (sin cambio, manda primero por negociación).
  2. Categoría padre in [Cafeteria, Cigarrillos y Tabacos, Congelados,
     Esenciales Hogar, Impulso, Snack y Coctel] → SALA siempre. Estas
     categorías son productos de picking físico complejo o muy baratos por
     unidad; consolidar en CD destruye eficiencia.
  3. `cobertura_caja = moq / demanda_semanal > 30 días (4.286 sem)` → CD.
     Si una sola caja deja >30 días de stock en sala, se consolida.
  4. Resto → SALA.
- Elimina `LOCAL_PURCHASE_MAX_CAPITAL_LOCK_CLP` (DEFAULT y CTX). Reemplazado
  por `COVER_WEEKS_THRESHOLD_FOR_CD` y `NO_CD_PARENT_CATEGORY_IDS`.
- `decision_reason` cambia de `moq_excede_capital_local` a
  `cobertura_caja_alta_cd` con `cobertura_w` y `umbral_w`.
- Las categorías excluidas se expanden recursivamente desde los 6 IDs padre
  via `product.category child_of`, llegando a 46 categorías en total. La lista
  de IDs padre es parametrizable por CTX.
- Impacto estimado vs v9.1.82:
  - SKUs forzados a CD por esta regla: 384 → ~256 (-33%).
  - 321 SKUs liberados de CD (Cigarrillos Lucky/Kent, galletas Trencito, Halls,
    chocolates, snacks).
  - 193 SKUs nuevos a CD (cervezas premium Austral/Kunstmann/Heineken/Coors,
    vinos tetra Clos de Pirque, Red Bull, Mixer Fentimans con cobertura 50-900 sem).
  - Solo Bebidas Alcohólicas (146 SKUs) y No Alcohólicas (110 SKUs) caen ahora
    en el check de cobertura.
- Sin cambios en CD→proveedor, MOQ, phantom, transferencias, GMROI,
  presupuesto mensual, retornos.

---

### v9.1.82 — Sala solo_bodega con safety stock

- Sala `solo_bodega`: agrega safety stock al target.
  - **Antes (v9.1.81)**: `target = mu * sala_target_weeks_base` (plano, sin
    safety). AX/AY=1.28, BX/BY/AZ=1.0, BZ/CY=0.84, CZ=0.52, default=1.0.
  - **Problema**: aunque CD estuviera lleno, locales con sigma alto quebraban
    antes del próximo ciclo de transferencia CD→sala (1 vez por semana).
    6 SKUs con CD sano + 29 locales en quiebre (Coctel Secreto Peruano,
    Jagermeister, Misiones Cab Sauv, Jack Daniels).
  - **Ahora**: misma regla que proveedor→CD pero con horizonte de 1 sem
    (frecuencia real de entrega CD→sala). `H = 1.0 + CD_DELIVERY_EXTRA_WEEKS`,
    `safety = Z * sigma * sqrt(H)` (Z por ABCXYZ, igual que v9.1.75),
    `target = mu * H + safety`. Mismo Z que CD/proveedor, mismo sigma local.
    Coherencia total.
- Sube `CD_DELIVERY_EXTRA_DAYS_DEFAULT` de 1.0 a 2.0 días (buffer logístico
  si camión se atrasa, e.g. martes en vez de lunes).
- Elimina `_SOLO_BODEGA_SALA_TARGET` y `_solo_bodega_target_weeks` (no usados).
- Elimina `sala_target_weeks_base` / `sala_target_weeks` del payload de
  auditoría (campo no persistido; se reemplaza con la fórmula nueva implícita
  en `safety_stock_units` y `reorder_target_weeks`).
- Sin cambios en CD→proveedor (v9.1.81), MOQ, phantom, `compra_cd`, retornos,
  transferencias, GMROI, presupuesto mensual.
- Impacto esperado:
  - Coctel Secreto Peruano Limón AY: target/local sube de ~1.5 u a ~3.0 u.
  - 29 locales en quiebre AY/AX/BX vuelven a target en próxima corrida.
  - ~6.000 u extra distribuidas en sala (traslado desde CD, no compra
    adicional al proveedor de inmediato).
  - CD se vacía, motor v9.1.81 dispara compras al proveedor para reponer.

---

### v9.1.81 — Reposición automática CD para solo_bodega

- Agrega reposición automática del CD para SKUs `solo_bodega` elegibles.
- Si locales necesitan el SKU, el CD está bajo target y no hay `compra_cd`
  previa por `capital_atascado`, la fila CD compra al proveedor.
- `target CD = mu_red * cd_target_weeks + z * sigma_red * sqrt(cd_target_weeks)`.
  Default `cd_target_weeks = 30/7`, configurable por contexto.
- Elegibles por defecto: AX, AY, AZ, BX, BY, BZ. CY/CZ quedan fuera.
- Excluye padres phantom y no toca `compra_sala`, transferencias, retorno,
  presupuesto mensual, GMROI ni lectura de OC abiertas.
- Auditoría en `decision_reason`: `solo_bodega_cd_replenish=1` con target,
  mu_red, sigma_red, safety y z usados.
- (Nota v9.1.85: este `cd_target_weeks` fijo se reemplazó por `period_weeks`
  por SKU.)

---

### v9.1.80 — Fix crítico lectura ABC/XYZ (variant vs template)

- FIX crítico de lectura ABC/XYZ. Bug originado al unificar scripts:
  `x_calculo_abc_xyz.x_studio_product_id` apunta a `product.product` (variant),
  pero el código guardaba `abc_map[variant_id]` mientras que el loop principal
  busca con `tmpl_id`. Solo coincidían SKUs donde por casualidad
  `variant_id == tmpl_id`.
- Resultado del bug: 1.069 de 1.969 SKUs locales (54%) terminaban como
  SIN_CLAS aunque tenían clasificación válida en `x_calculo_abc_xyz`. Entre
  ellos: Budweiser 9413 (rank 2 AX), Quilmes 9430 (rank 8 AX), Royal Guard
  451500 (rank 16 AY), Hielo Gourmet 1KG (rank 4 AX), Cusqueña 9958 (rank 36 AY).
- Efecto operativo: SKUs SIN_CLAS calculaban safety stock con `z=0.84`
  (default fallback) en lugar del z real (~2.05 para AX en v9.1.75).
  Target subdimensionado → más casos `box_or_wait_no_qty` → menos cajas
  pedidas. Operaciones reportaba esto como subcompra.
- Fix: convertir `variant_id → tmpl_id` en lectura ABC, idéntico al patrón
  que ya usaba el bloque FWD.
- Sin cambios en target/safety/policy/redondeo/MOQ/CD/phantom. Una versión,
  un cambio.

---

### v9.1.79 — Limpieza operativa box_or_wait_no_qty

- Si la política caja-o-esperar deja `reponer_ahora` sin `qty_a_pedir` ni
  transferencia, cambia la acción a `no_comprar_esta_semana`.
- Agrega auditoría `box_or_wait_no_qty` para explicar esos casos.
- Compra mensual estimada se fuerza a 0 en acciones que no deben generar caja:
  `congelar_compra`, `liquidar`, `retorno_a_cd`, `no_disponible_de_compra`,
  phantom child bloqueado y casos `box_or_wait_no_qty`.
- No cambia target, safety stock, `compra_cd`, transferencias ni pool pack/unidad.

---

### v9.1.78 — Pool pack/unidad: padre absorbe pool

- Corrige política de pools pack/unidad: la demanda de hijos/componentes se
  consolida hacia el padre phantom comprable en unidad equivalente de compra.
- El SKU padre compra para el pool completo:
  `mu_padre_total = mu_padre + mu_hijo / qty_per_parent`.
- Sigma del pool se combina por raíz de suma de cuadrados para no sobreestimar
  riesgo.
- Los hijos/componentes quedan visibles para análisis, pero bloqueados para
  compra, transferencia y presupuesto mensual.
- Cambia default `phantom_procurement_mode` a `buy_parent_block_children`.
- Cambia default `phantom_cost_source` a `product_first` para usar
  costo/proveedor del SKU padre.

---

### v9.1.77 — Fix sigma scaling para FWD local

- Fix crítico: `sigma_week` NO debe escalarse por `sqrt(share_demanda)` cuando
  la fuente es FWD LOCAL (`fwd_source='local'`).
  - **Antes**: `sigma_week = sigma_week * (share_demanda ** 0.5)` SIEMPRE.
  - **Problema**: el FWD local ya tiene sigma calculado a nivel sucursal por
    el estimador FWD v3.0.2. Subdividirlo por `share_demanda` lo reduce
    incorrectamente, como si fuera un sigma de la red completa.
- Ejemplo: Coñaripe Cristal 12x470cc
  - `sigma_local = 5.0` (FWD v3.0.2 local, correcto).
  - `share_demanda = 0.202` (13.33 / 65.96 red completa).
  - `sigma_bug = 5.0 * sqrt(0.202) = 2.248` (subdimensionado 55%).
  - `SS_bug = 2.05 * 2.248 = 4.61 u`.
  - `sigma_fix = 5.0` (sin escala, ya es local).
  - `SS_fix = 2.05 * 5.0 = 10.25 u`.
- El escalado `sqrt(share_demanda)` SOLO es correcto para FWD GLOBAL donde
  `sigma_week` representa la variabilidad de la red completa y debe
  prorratearse a nivel sucursal.
- Impacto esperado: todos los SKUs con `fwd_source='local'` que tenían
  `share_of_pool < 1.0` verán su `safety_stock` aumentado. SKUs con
  `share_of_pool=1.0` (mayoría) no se ven afectados.

---

### v9.1.76 — Auditoría sigma en decision_reason

- Agrega `sigma=` al motivo de decisión para auditoría.
- Antes el motivo mostraba `z=2.05` pero no el sigma que multiplicaba.
- Ahora muestra `z=2.05 | sigma=5.000` para verificar de dónde vino el valor.
- Diagnóstico que motivó el cambio: `sigma_week` en `x_forecast_weekly_data`
  viene del estimador FWD v3.0.2 (que calcula sobre semanas BASE, corregido
  por precio). Si el FWD no está actualizado cuando corre el `stock_analysis`,
  puede quedar un sigma viejo (ej: 2.248 en vez de 5.0 para Coñaripe Cristal).
- La fuente correcta de sigma sigue siendo `x_studio_sigma_week` del modelo
  `x_forecast_weekly_data` (escrito por Estimacion_Demanda_V3.0.2, NO por
  Calculo_ABCXYZ_V14_0.py).
- ORDEN DE EJECUCIÓN CRÍTICO: ABCXYZ → FWD v3.0.2 → Stock Analysis.

---

### v9.1.75 — Service level top movers

- Subida de service level en `_SAFETY_FACTOR` para top movers:
  - AX: Z 1.645 → 2.05 (~95% → ~98% service level).
  - AY: Z 1.645 → 2.05 (~95% → ~98% service level).
  - BX: Z 1.48 → 1.65 (~93% → ~95% service level).
  - Resto sin cambios (BY=1.28, AZ=1.04, BZ=0.84, CX=0.84, CY=0.52, CZ=0.0).
  - Default fallback se mantiene en 0.84.
- Justificación: en botillería el quiebre en SKUs AX/AY (cervezas top,
  bebidas, cigarros premium) es muy visible al cliente y genera pérdida de
  venta inmediata. Subir el service level del 95% al 98% en estos SKUs reduce
  ~3pp la probabilidad de stockout en quiebres normales.
- Impacto cuantificado contra xlsx vigente:
  - AX (2.861 líneas): +686 u SS, +CLP 2.2M.
  - AY (3.007 líneas): +609 u SS, +CLP 2.0M.
  - BX (573 líneas): +30 u SS, +CLP 0.1M.
  - TOTAL: +1.325 u SS, +CLP 4.3M en safety stock.
- El SS adicional se traduce en `qty_a_pedir` mayor en próximas corridas para
  AX/AY/BX, pero solo cuando el `stock_proyectado` esté bajo el target nuevo.
- Sin cambios operativos en lógica: `target_units` sigue calculándose con la
  misma fórmula, solo cambia el factor Z aplicado a `sigma_week`.

---

### v9.1.74 — Capital atascado (OBSOLETA, reemplazada por v9.1.83)

- Cambio de criterio en la regla que forzaba SKUs sin `solo_bodega` a
  `compra_cd` cuando el MOQ excedía un techo de semanas
  (`financial_ceiling_sku`).
- Nueva regla (en su momento): evalúa el CAPITAL ATASCADO esperado por compra.
  `capital_atascado = (moq * purchase_price_cash_unit) * (moq / demanda_semanal)`.
  Si ≤ `LOCAL_PURCHASE_MAX_CAPITAL_LOCK_CLP` → `compra_sala`; si excede →
  `compra_cd`.
- Default umbral: 75.000 CLP (configurable via context). Calibrado contra
  xlsx vigente: descentraliza ~308 líneas de 1.816.
- **Reemplazada en v9.1.83**: la fórmula `valor_caja * cobertura` no medía
  "capital" sino "capital x tiempo", inflando artificialmente productos chicos
  baratos de baja rotación.

---

### v9.1.73 — Fix double counting venta_bruta CD

- Fix bug introducido en v9.1.72: `venta_bruta_mensual_estimada` en filas CD
  generaba DOUBLE COUNTING (~CLP 75M sobreestimación).
- Cada línea local ya reporta su venta mensual completa
  (`demanda * 4.4 * pvp`). En v9.1.72 las filas CD también reportaban
  (`demanda_origen * 4.4 * pvp`), donde `demanda_origen_cd` es la suma de
  demandas de los locales en `compra_cd`. Esa suma es la MISMA demanda
  contada en los locales → duplicación.
- Caso ejemplo: Quilmes 710cc reportaba 14.9M de venta mensual (real: 7.6M).
- Fix: vuelve a `x_studio_venta_bruta_mensual_estimada = 0` en filas CD.
- `compra_mensual_estimada` en CD se MANTIENE (no tiene double counting porque
  v9.1.72 ya forzó `compra_mensual=0` en líneas locales con `buy_action=compra_cd`).
- Sin cambios operativos.

---

### v9.1.72 — Fix double counting compra_cd

- Fix 4: `compra_cd` se presupuesta UNA SOLA VEZ a nivel SKU-red, no por local.
- **Antes**: cada línea local con `buy_action='compra_cd'` calculaba su propio
  gap mensual contra su stock local, sumando ~CLP 18M de double counting.
- **Ahora**:
  - Líneas locales con `buy_action='compra_cd'` fuerzan `compra_mensual=0`.
  - La fila CD calcula `compra_mensual` a nivel red:
    - `demanda_mes_cd = demanda_origen_cd * MONTH_REMAINING_WEEKS`.
    - `stock_red_cd = stock_cd + stock_proyectado_origen_cd`.
    - `gap_residual = max(demanda_mes_cd - stock_red_cd - qty_a_pedir, 0)`.
    - `compra_mes = (qty_a_pedir + gap_residual) * precio`.
  - También `venta_bruta_mensual_estimada` se reporta en la fila CD para
    consistencia con el presupuesto (luego revertido en v9.1.73 por
    duplicación).
- Acumulación: se agrega `stock_proyectado_origen_cd` en `central_team_map`,
  sumando stock proyectado de los locales que originan cada `compra_cd`.
- Excluye `phantom_block_procurement` de la fila CD (los componentes ya
  presupuestan localmente).
- Impacto estimado: ~CLP 18M adicionales de reducción.
- Sin cambios operativos.

---

### v9.1.71 — Fix phantom block compra mensual

- Fix 3: `phantom_block_procurement` fuerza `compra_mensual = 0`.
- Los packs/kit phantom padre están bloqueados de generar OC operativa (la
  compra/reposición se hace por componentes). Sin embargo, la fórmula de
  presupuesto mensual seguía calculando (`demanda * remaining_weeks * costo`)
  sobre el SKU padre, lo que generaba doble conteo.
- Casos típicos: Lemon Stones, Morenita y otros packs.
- Impacto estimado: ~CLP 21M de reducción en presupuesto mensual total.
- Sin cambios operativos.

---

### v9.1.70 — Fix compra mensual: no_disponible + stock_pedido

- Fix 1: `buy_action='no_disponible_de_compra'` fuerza `compra_mensual = 0`.
  Estos productos están marcados para descatalogar (`purchase_ok=False` y no
  son `solo_bodega`). No se comprarán este mes ni nunca. Antes: ~CLP 2.6M de
  presupuesto fantasma. Ahora: 0.
- Fix 2: Descuenta `stock_pedido_total` (OC y transferencias abiertas) del
  cálculo del gap residual. Antes la fórmula usaba solo `stock_effective`, lo
  que ignoraba inventario en tránsito que llegará durante el mes.
- Aclaración clave del usuario: `x_studio_lead_weeks` NO es tiempo de entrega
  del proveedor, es PERIODICIDAD de compra. Los proveedores nacionales (CCU,
  Embonor, BAT) entregan en días; cualquier `stock_pedido` abierto
  razonablemente llegará dentro del mes en curso.
- Cambio: `stock_eff` → `stock_proyectado` en el cálculo del gap. Impacto
  chico hoy (~CLP 0.9M) pero conceptualmente correcto.
- Sin cambios operativos: `qty_a_pedir`, OC, transferencias, MOQ intactos.

---

### v9.1.69 — Compra mensual estimada → presupuesto operativo

- Reemplaza `compra_mensual_estimada` de "presupuesto financiero teórico" por
  "presupuesto operativo realista" para flujo de caja por proveedor.
- Nueva fórmula:
  - `compra_w1 = qty_a_pedir` (o aporte a `compra_cd`, o transfer si solo CD).
  - `demanda_mes = demanda_semanal * MONTH_REMAINING_WEEKS`.
  - `gap_residual = max(demanda_mes - stock_effective - compra_w1, 0)`.
  - `total_units = compra_w1 + gap_residual`.
  - `monto = total_units * purchase_price_cash_unit`.
- Refleja lo que el `plan_de_compra` realmente mandará a comprar durante el
  mes corriendo semanalmente, NO el presupuesto teórico con buffer de target.
- Quita `target_units` de la fórmula: no es presupuesto de stock objetivo,
  es presupuesto de caja operativa.
- Maneja 3 casos por `buy_action`:
  - `'compra_cd'`: usa `qty_compra_cd_consolidada_local` (el aporte real de
    la línea local a la compra CD que va al proveedor).
  - `'transferir_desde_cd'`: transferencia interna no cuenta como compra a
    proveedor; el campo descuenta el monto transferido.
  - Resto: usa `qty_a_pedir` directo.
- Resultado esperado: ~243M/mes vs 341M de v9.1.68.
- Uso: presupuesto de caja por proveedor (CCU, Embonor, BAT, etc).

---

### v9.1.67 — Compra mensual estimada (presupuesto teórico)

- Agrega `x_studio_compra_mensual_estimada`.
- Calcula monto estimado de compra desde `snapshot_date` hasta fin de mes:
  `max(demanda_semanal * semanas_restantes_mes + target_units - stock_proyectado, 0)`
  `* purchase_price_cash_unit`.
- Es un indicador financiero/proveedor; no modifica `qty_a_pedir`, OC,
  transferencias, MOQ, CD, phantom ni reglas operativas.
- Reemplazado por la fórmula operativa en v9.1.69.

---

### v9.1.66 — Bloqueo procurement phantom padre

- Bloquea abastecimiento documental del producto padre phantom.
- El pack/kit phantom queda visible para análisis, cobertura y valorización,
  pero NO genera `qty_a_pedir`, `compra_cd`, transferencia ni retorno.
- Evita duplicar OC con pack + componentes, caso Lemon Stones / Morenita.
- Default: `phantom_procurement_mode='block_parent'`.
- Auditoría: `phantom_procurement=blocked_parent`.

---

### v9.1.65 — Fix NameError purchase_row

- Fix NameError: reemplaza referencia obsoleta `purchase_row` por
  `purchase_map.get(tid)`.
- No cambia lógica de cálculo, compra, transferencia ni valorización phantom.

---

### v9.1.64 — Valorización phantom kits

- Corrige valoración de stock en productos tipo pack/kit phantom.
- **Antes**: si el SKU era `pool=phantom`,
  `stock_value_cash_physical/effective` se forzaba a 0.
- **Ahora**: se puede valorizar el pack virtual usando costo derivado de
  componentes o costo propio del producto, controlado por contexto.
- Defaults:
  - `value_phantom_kits=True`.
  - `phantom_cost_source='component_first'`.
- Auditoría en `decision_reason`:
  `pool=phantom | phantom_value=on | kit_cost_source=...`.

---

### v9.1.63 — Cigarros display_mult

- Corrige bajo impacto de v9.1.62: el target de cigarros estaba dominado por
  reserva de exhibición.
- Aplica `CIGARROS_DISPLAY_MULT` a la reserva de exhibición de Cigarros.
- Default `cigarros_display_mult = 0.0` para no sumar stock artificial de
  exhibición en cigarros.
- Mantiene intacta lógica de cajas/MOQ/documentos.

---

### v9.1.62 — Ajuste safety cigarros

- Agrega ajuste de estimación para categoría Cigarrillos y Tabacos / Cigarros.
- Categoría Cigarros = `product.category ID 1628`.
- Aplica multiplicador `CIGARROS_SAFETY_MULT=0.778` sobre el safety factor
  global.
- No modifica redondeo de cajas/MOQ, `compra_cd`, transferencias ni generación
  documental.
- El ajuste afecta solo:
  - `x_studio_safety_factor_used`.
  - `x_studio_safety_stock_units`.
  - `x_studio_target_units`.
  - `x_studio_reorder_target_weeks`.
  - `qty_neta_pre_central` antes de reglas de abastecimiento.
- Auditoría en `decision_reason`:
  `cat=cigarros | cigar_safety_mult=0.778`.

---

### v9.1.61 — Reserva exhibición + top cash safety

- Agrega reserva comercial de exhibición como % de demanda semanal.
- La reserva de exhibición se suma al target operativo, no a la demanda.
- En el redondeo MOQ crítico, la cobertura post-floor se evalúa sobre stock
  vendible: `stock_vendible = stock_post_compra - display_stock_units`.
- Sube factor de seguridad a 1.68 solo para SKU top caja/venta estimada
  dentro de AX/AY/BX/BY, manteniendo 1.48 para AX normal.
- Parámetros testeables por contexto: `display_stock_enabled`,
  `display_pct_top_cash`, `display_max_units`, `top_cash_weekly_min`,
  `top_cash_rank_max`, `top_cash_safety_factor`.

---

### v9.1.60 — MOQ crítico segmentado por ABCXYZ

- Segmenta la excepción crítica MOQ por ABCXYZ.
- La protección fuerte de ceil crítico aplica solo a AX, AY, AZ, BX, BY, BZ.
- CX, CY y CZ mantienen política caja-o-esperar para no inflar cola larga.
- `force_min` operacional se conserva para redondeos de filas CD sin cover
  crítico.

---

### v9.1.59 — MOQ ceil en críticos

- Corrige redondeo MOQ en productos críticos/sin_stock.
- Si el floor de caja deja cobertura post-compra menor a la cobertura mínima
  crítica o todavía bajo el target técnico, se usa ceil de caja.
- Mantiene política caja-o-esperar para SKU normales/bajos, evitando
  sobrecompra.

---

### v9.1.58 — Consolidación compra_cd antes de MOQ

- Corrige `compra_cd`: consolida primero la necesidad exacta por SKU entre
  locales y recién después aplica MOQ/caja una sola vez en Bodega Central.
- Evita el error tipo Norkoshe: sumar MOQ por local antes de consolidar.
- La pseudo-fila CD ahora acumula `venta_bruta_estimada` de las líneas locales
  que originan la `compra_cd`, para explicar compra vs venta por cobertura.

---

### v9.1.57 — Venta bruta semanal estimada

- Agrega estimación de venta bruta semanal por SKU/local:
  - `x_studio_pvp_bruto_sku = product.template.list_price`.
  - `x_studio_demanda_estimada_entera = demanda_semanal` redondeada a entero.
  - `x_studio_venta_bruta_estimada = pvp_bruto_sku * demanda_estimada_entera`.
- La estimación es de venta bruta teórica semanal, independiente de la compra
  sugerida.
- Si los campos no existen en Studio, `_filter_vals` los omite sin romper la
  corrida.

---

### v9.1.56 — Política caja-o-esperar global

- Aplica al motor completo una política de caja-o-esperar.
- No compra una caja solo por cerrar una brecha menor que el MOQ.
- El floor de MOQ es válido si deja el stock post-compra dentro del tamaño de
  caja respecto al target técnico; el ceil se usa solo si es necesario o si
  hay riesgo crítico.
- Mantiene `lead_weeks = 0.0` y `protection_weeks = period_weeks`.

---

### v9.1.55 — Sin lead extra en target

- Prueba sin días extra de lead en el target: `protection_weeks = period_weeks`.
- `x_studio_lead_weeks` queda en 0.0 para aislar el efecto del extra de llegada.
- Compra operativa usa redondeo MOQ al múltiplo más cercano, no ceil automático.
- Si el SKU está `sin_stock`/crítico, fuerza caja mínima para evitar quiebre.
- Objetivo: reducir sobreestimación por ciclos acumulados + redondeo a caja.

---

### v9.1.52 — Stock proyectado CD lee OC/transfers abiertas

- Corrige stock proyectado de Bodega Central: ahora la pseudo-sucursal CD lee
  compras y transferencias entrantes abiertas hacia el warehouse central.
- `x_studio_stock_pedido_compra` / `transfer` / `total` se escriben también
  en la fila CD.
- `x_studio_stock_proyectado` de CD = `stock_real_cd + stock_pedido_total_cd`.
- Conservador: la asignación de transferencias desde CD sigue usando solo
  stock físico, no stock entrante pendiente.
- Corrige lectura de `stock_move` abierto convirtiendo UoM del movimiento a
  UoM base del producto; evita subcontar OC creadas en cajas.

---

### v9.1.51 — Elimina VERANO_*

- Elimina efecto operativo/auditoría de bandas `VERANO_*` en este análisis:
  `VERANO_BAJO`, `VERANO_MEDIO` y `VERANO_ALTO` se normalizan a `BASE`.
- Elimina lectura/payload de `x_studio_ciclo_de_vida` desde FWD porque no se
  usa.
- Nota: si el `mu_week` ya viene inflado desde `x_forecast_weekly_data`, la
  corrección principal debe aplicarse también en el motor FWD.

---

### v9.1.50 — Retorno a CD via qty_transferir

- No usa/escribe `x_studio_qty_retorno_cd`. El retorno a CD se informa en
  `x_studio_qty_transferir` con `buy_action = retorno_a_cd`.
- Elimina escritura de campos no existentes/no usados:
  - `x_studio_financial_ceiling_weeks`.
  - `x_studio_protection_weeks`.
  - `x_studio_sala_target_weeks`.
  - `x_studio_cd_delivery_extra_weeks`.
- Limpia `decision_reason` de auditorías no persistidas: `prot_w`, `sala_w`,
  `cd_xtra_d`.

---

### v9.1.49 — MOQ en compra_cd consolidada

- Corrige `compra_cd` para que la cantidad consolidada en Bodega Central se
  redondee a múltiplos de MOQ/caja antes de generar documentos.
- `x_studio_qty_a_pedir_cajas` queda entero cuando la compra es por caja.
- Mantiene `qty_neta_pre_central` como necesidad técnica y redondea solo la
  cantidad operativa de compra/documento.

---

### v9.1.39 — GMROI y rotación por peso

- Agrega lectura de `costo_oh_unit` y `precio_neto_unit` desde
  `x_margen_por_producto_` (último registro por producto,
  `fecha_hasta DESC`).
- Calcula tres indicadores de priorización de abastecimiento con restricción
  de caja:
  - `x_studio_gmroi_reponer`: margen semanal / `valor_orden_compra`.
  - `x_studio_rotacion_por_peso`: `demanda_semanal / valor_orden_compra`
    (proxy sin margen).
  - `x_studio_margen_unit`: margen unitario real (`pvp_neto - costo_oh`).
- Persiste también campos de auditoría del origen del dato:
  - `x_studio_costo_oh_sku`: costo OH usado.
  - `x_studio_pvp_neto_sku`: pvp neto unitario.
- Fallback silencioso: si `x_margen_por_producto_` no tiene el SKU,
  `gmroi_reponer = 0.0` y `rotacion_por_peso` usa `purchase_price_cash_unit`
  como denominador.
- Tratamos `x_studio_lead_weeks` del FWD como período de reposición (no lead
  real). Estimamos lead real desde ese período:
  - ≤ 7 días → 1.5 días.
  - ≤ 15 días → 3.0 días.
  - > 15 días → 5.0 días.
- El target se calcula con horizonte de protección = período + lead estimado.
- `x_studio_lead_weeks` en `x_analisis_de_stock` pasa a guardar lead real
  estimado.
- Si existe el campo `x_studio_periodo_repos_weeks`, se persiste el período
  usado.
- (Nota v9.1.55+: posteriormente `lead_weeks` se fijó en 0.0 y
  `protection_weeks = period_weeks`.)

---

### v9.1.36 — purchase_ok como criterio base

- Usa `purchase_ok` de `product.template` como criterio base para
  `no_disponible_de_compra`.
- Jerarquía: `solo_bodega` manda primero; si `purchase_ok=False` y no es
  `solo_bodega` → `no_disponible`.
- Si un SKU queda marcado como no disponible de compra, se mantiene visible en
  el análisis pero se bloquea compra externa y transferencia desde CD.
- Usa `buy_action = no_disponible_de_compra` si la opción existe en Studio;
  si no existe, cae seguro a `no_comprar_esta_semana`.
- Mantiene full purge y la lógica vigente de `compra_cd` / transferencia.

---

## Notas históricas eliminadas en esta limpieza

Adicionalmente se eliminaron de los headers del script:

- **Bloque duplicado de v9.1.62**: existía un segundo encabezado
  `# Cambios v9.1.62:` redundante que repetía con menos detalle el primero.
- **Constantes muertas**: `CD_TARGET_WEEKS_DEFAULT`, `CD_TARGET_WEEKS` y
  `AUTO_DERIVE_CENTRAL_DEFAULT` no tenían uso operativo.
- **Función huérfana**: `_lead_time_from_period(period_weeks)` no era llamada
  desde ningún sitio (los cambios v9.1.55+ la dejaron sin consumidores).
- **Tags `# v9.1.XX:` inline** sin contexto funcional se reescribieron o
  borraron en favor de comentarios que explican el "por qué" del código.

---

## 03_stock / OH Generacion de Documentos.py

### v1.6 — Bandas y presupuesto por rank ABCXYZ (2026-06-08)

Redefine el universo de los flags y la prioridad de compra en base al ranking
numerico de margen de la segmentacion (`x_studio_rank_abcxyz`, donde rank 1 =
mayor margen acumulado y el numero crece al bajar la importancia).

- **Flags Top/Medio/Bajo = bandas de rank** (antes: combos de letras ABCXYZ).
  - Top  : `rank 1..300`
  - Medio: `rank 301..800`
  - Bajo : `rank 801..N` (resto)
  Constantes `RANK_BAND_TOP_MAX=300`, `RANK_BAND_MEDIUM_MAX=800`. El dominio
  base ya no filtra por `x_studio_abcxyz in [...]` sino por la(s) banda(s) de
  rank marcada(s) (OR si hay varias). El "300" calza con
  `TOP_CASH_RANK_MAX_DEFAULT` del Analisis de Stock.
- **Orden de compra unico (sala y CD)**: `x_studio_rank_abcxyz asc,
  x_studio_valor_orden_compra asc`. Compra del rank 1 (mejor margen) hacia
  abajo; desempate por valor de orden ascendente (mas barato). ASC, no desc:
  rank 1 es el mejor. Reemplaza el orden por `severity`/`gmroi` que se uso
  brevemente en una version intermedia.
- **Presupuesto**: greedy simple. Recorre el rank de 1 hacia N acumulando el
  `valor_orden_compra`; agrega cada linea si la suma sigue `<=` monto total y
  salta las que no caben, hasta agotar el presupuesto. Misma logica para
  `compra_sala` y `compra_bodega` (se descarto el `skip_floor` por severidad de
  un diseno intermedio: con rank unico por SKU no aporta).
- **No** se toco el Analisis de Stock: `x_studio_rank_abcxyz` ya se persistia
  en las filas locales y CD.
- Sin cambios en la idempotencia, el modo borrador ni los traslados.
- El gate sigue igual: el tope SOLO corre si `x_studio_use_budget=True` Y
  `x_studio_budget_amount > 0`. Con el flag apagado entra todo, sin tope.
- **Borde**: greedy puede dejar entrar un rank bajo barato con presupuesto
  sobrante despues de saltar un rank alto que no cupo. Si se quisiera prioridad
  estricta (parar al primero que no cabe), seria reintroducir el corte.

---

### v1.5 — Draft mode adoption

- Modo adopcion: NO confirma automaticamente Ordenes de Compra ni Traslados Internos.
- Las OC quedan como RFQ/Borrador para revision de Compras.
- Los pickings quedan en Borrador para revision de Bodega/Operaciones.
- Mantiene idempotencia por `origin_key` contra documentos no cancelados.
- Advertencia operativa: documentos borrador NO deberian entrar a `stock_pedido` hasta ser confirmados.

---

### v1.4 — Retorno a CD via qty_transferir

- Retorno a CD / `transferencia_interna_retiro` usa `x_studio_qty_transferir`.
- Elimina dependencia del campo separado de retorno, que no existe en `x_analisis_de_stock`.
- Filtra retorno por `x_studio_buy_action = retorno_a_cd`.

---

### v1.3 — Correcciones varias

- Corrige `_now_dt()`: Odoo espera datetime naive UTC, no timestamp timezone-aware.
- Mantiene eliminacion de `getattr()`.
- Mantiene validacion de Nombre del Lote.
- Ejecuta `Analisis de Stock` (action 1502) al inicio.
- Exige snapshot fresco posterior al inicio de la ejecucion.
- Idempotencia ignora documentos cancelados.
- Compras en cajas. Traslados en unidades.

---

## 03_stock / Stock Balance Daily.py

### v2.0 — Modo dual (backfill / incremental)

Reconstruye balance diario de stock por `(team, warehouse, producto, dia)` para detectar quiebres reales. Permite separar "error del modelo" de "no habia stock" en el analisis del backtest.

Estrategia: snapshot actual (`stock.quant`) + roll backward sobre `stock.move` completados en la ventana efectiva:

```text
balance[D] = balance[D+1] - qty_in_(D+1) + qty_out_(D+1)
```

Modo dual:

- `mode='backfill'`: reconstruye rango explicito `[date_from, date_to]`. Default range = `[BACKFILL_FLOOR_DEFAULT, hoy]`.
- `mode='incremental'`: detecta ultima fecha procesada y recalcula `tail_window_days` (default 7) + hoy. NO toca dias anteriores. Es lo que corre el cron diario.

El roll backward SIEMPRE ancla en `stock.quant` de HOY. **Aceptacion explicita del usuario**: el balance reconstruido para enero 2026 es una inferencia matematica desde el quant actual, no un snapshot real de ese momento. Suficiente para detectar quiebres operativos.

Backdating > `tail_window_days` NO se captura en incremental. Mitigacion: correr `backfill` manual u opcional cron semanal con `tail_window_days=30`.

### Modelo destino

`x_stock_balance_daily` (crear en Studio antes de correr).

Campos requeridos:

- `x_team_id` (Many2one -> `crm.team`)
- `x_warehouse_id` (Many2one -> `stock.warehouse`)
- `x_product_id` (Many2one -> `product.product`)
- `x_categ_id` (Many2one -> `product.category`)
- `x_supplier_id` (Many2one -> `res.partner`, proveedor principal)
- `x_abcxyz` (Char, clasificacion desde `x_calculo_abc_xyz`)
- `x_date` (Date)
- `x_qty_balance` (Float, balance fin de dia)
- `x_qty_start`, `x_qty_in`, `x_qty_out` (Float)
- `x_stockout` (Boolean, `balance <= 0`)
- `x_stockout_partial` (Boolean, `start > 0 AND end <= 0`)
- `x_run_version` (Char)
- `x_run_at` (Datetime)

Campos opcionales (v2.0, best-effort):

- `x_run_id` (Char indexed, UUID corto)
- `x_mode` (Selection `backfill|incremental`)

Indice recomendado: `(x_team_id, x_warehouse_id, x_product_id, x_date)`.

---

## 04_analitica / OH Analisis Ventas SKU.py

### v12 — COMBO_EXPLODE: prorating de combos en ventas

Persiste venta semanal por SKU desagregando combos: cada componente recibe su `qty/revenue` prorateado segun reglas (`priced_child_count` -> `child_rev`; `weight_sum` -> peso por valor; sino reparto uniforme).

### v11 — Estandar calendario OH

Incorpora estandar calendario OH para que todos los scripts semanales sean comparables:

- Semana OH: lunes a domingo, siempre en hora local Chile.
- `week_start`: lunes. `week_end`: domingo.
- Comparacion LY semanal: -364 dias = 52 semanas exactas.
- ISO week para bandas estacionales (verano alto, verano bajo, otono, invierno, primavera, fiestas).

### Esquema persistido

Modelo destino: `x_pos_week_sku_sale`.
Grano: `company + team (local) + week_start + categ_id + product_id`.

Campos base:

- `x_studio_qty_sold` = `SUM(pos_order_line.qty)`
- `x_studio_sales_gross` = `SUM(pos_order_line.price_subtotal_incl)`
- `x_studio_week_start` = lunes hora local Chile
- `x_studio_week_end` = domingo hora local Chile

Campos principales (independientes de feriados):

- `x_studio_response_vs_category_pct` (Float) = crecimiento SKU vs LY - crecimiento categoria vs LY.
- `x_studio_seasonal_band` (Char/Selection) = banda estacional calculada desde ISO week.

Definicion:

```text
sku_growth_qty   = qty_sku_semana / qty_sku_semana_LY_364 - 1
categ_growth_qty = qty_categoria_semana / qty_categoria_semana_LY_364 - 1
response_vs_category = sku_growth_qty - categ_growth_qty
```

Interpretacion: +0.20 = el SKU crecio 20pp mas que su categoria; -0.15 = crecio 15pp menos.

Fuente feriados:

1. Contexto opcional: `{'holiday_dates': ['2025-01-01', ...]}`.
2. Modelo por defecto: `x_holiday_occurrence.x_studio_holiday_date`.
3. Relacion: `x_holiday_occurrence.x_studio_holiday_id` -> `x_holiday_master`.
4. Contexto opcional: `{'holiday_model': 'x_nombre_modelo'}`.

SAFE_EVAL friendly: sin lambdas, sin closures, sin nested functions. Requiere `datetime` en contexto de Server Action.

---

## 04_analitica / OH Analisis ventas Categoria.py

### v10 — Factor anual por categoria

POS week category fact: TY + LY + factor anual por categoria.

- Mantiene la logica original a nivel `semana x sucursal x categoria`.
- NO baja a SKU (lo hace el script de Ventas SKU).
- Agrega/corrige factor categoria vs promedio semanal anual:
  - `annual_avg_sales` / `annual_avg_units` = promedio semanal del mismo ano ISO comercial, por sucursal x categoria.
  - `season_factor_sales` / `season_factor_units` = semana / promedio anual.
- LY = semana - 364 dias.
- Soporta `run_mode` / `date_from` / `date_to` y tambien `pos_week_start` / `pos_week_end`.
- `x_name` compatible con jsonb.

Modelo destino: `x_x_pos_week_sku_fact`.

---

## 04_analitica / OH Analisis ventas Team.py

### v13 — Combo explode + backfill

KPI mensual por sucursal (POS only).

- Explota combos/sets en unidades usando `combo_parent_id`:
  - Excluye `service` y `combo/set` standalone del conteo de unidades.
  - Baja unidades del SET al SKU hijo real.
  - Ventas brutas y tickets siguen a nivel pedido (no cambian).
- Backfill por rango de meses via contexto `run_mode='range'` con `date_from` / `date_to`.

SAFE_EVAL friendly. Requiere `datetime` disponible en contexto del server action.

Contexto opcional:

- `run_mode`: `'last_closed'` | `'range'` (default: `'last_closed'`).
- `date_from`: `'YYYY-MM-DD'` (default: `'2025-01-01'`).
- `date_to`: `'YYYY-MM-DD'` (default: ultimo dia del mes cerrado).
- `team_ids`: `[18,16,...]` (default: FILTERED_TEAM_IDS).
- `dry_run`: `True/False` (default: `False`).

Modelo destino: `x_sales_month_team_kpi`.

---

## 05_finanzas / OH Flujo de Caja.py

### v1.3 — Facturas venta + IVA SII (2026-04-30)

Generador de flujo de caja diario que persiste en `x_cash_flow`.

Inputs procesados:

1. Ventas POS reales: venta D entra a caja D+1.
2. Presupuesto de venta futuro (`x_presupuesto_de_venta`): presupuesto D entra a caja D+1.
3. Facturas de compra pendientes: fecha flujo = vencimiento.
4. Facturas de compra vencidas: fecha flujo = hoy - 1.
5. IVA estimado: IVA ventas - IVA compras, pago dia 20 del mes siguiente.

Modelos Odoo Studio validados:

- `x_cash_flow` (modelo destino).
- `x_presupuesto_de_venta` (lectura de proyecciones).

No incluye (deuda visible): Bancos, Arriendos, Remuneraciones, TGR, BAT.

Recomendado: ejecutar diariamente a las 06:00.

---

## 05_finanzas / OH Presupuesto ventas.py

### v13 — Feriados desde modelo + offset policy en codigo

Recalc presupuesto de ayer + futuro hasta 31-12-2026.

Cambios vs v12.4:

- La fecha base del feriado YA NO esta hardcodeada en `HOLIDAY_SPECS`.
- Se lee desde `x_holiday_occurrence` + `x_holiday_master`.
- Se mantiene en codigo solo la politica de offsets P/H por codigo.
- Se mantiene logica especial de Ano Nuevo cross-year.

SAFE_EVAL friendly: sin imports, sin `global`, sin `getattr`.

Parametros operativos:

- `ALPHA_BLEND = 0.25` (blend con ventana larga).
- `MIN_BASE_IN_WINDOW = 30,000,000` (umbral minimo para considerar base valida).
- `ROLL_WINDOW_DAYS = 45` (ventana rolling corto plazo).
- `LONG_WINDOW_DAYS = 365` (ventana larga referencia anual).
- `WEEKS_FOR_WD_AVG = 4` (semanas para promedio working-day).
- `FILTERED_TEAM_IDS = [18, 16, 12, 10, 9, 8, 7, 6, 5, 17, 13, 11]`.
