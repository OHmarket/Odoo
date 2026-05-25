# HM SI Forecast - Proceso del codigo

Documento descriptivo del runner `5- HM SI Forecast.py`. Describe que hace,
en que orden, y con que criterio. La version productiva actual es **v3.39
AUTO_MODEL** (2026-05-20), evolucion del linaje v3.24 con varias capas
agregadas (collapse detector, validacion empirica de correccion, auto-model
selection per SKU al estilo SAP IBP).

## Estado actual (2026-05-20)

- **Runner productivo**: `5- HM SI Forecast.py` (`VERSION_ID =
  "FWD_v3_39_AUTO_MODEL"`). Snapshot del dia en
  `analisis backtest/2026-05-20/HM_SI_v3_39_productivo.py`.
- **WAPE global**: 66.94% (backtest W18-W20/2026).
  BIAS -4.5%, en rango aceptable `[-15%, +5%]`.
- **REG-1 control intacto**: WAPE 53.69% (vs 53.68% pre-v3.39), confirma
  que el bake-off per-SKU + heuristic-bias 10% protege el core.
- **Cierre del dia 2026-05-20**: ver
  `analisis backtest/2026-05-20/CIERRE.md` para metricas detalladas,
  archivos del dia y pendientes priorizados.
- **v4.3-revert archivado** como descartado en
  `analisis backtest/2026-05-12/HM_SI_v4_3_canonical_descartado.py`. El
  nombre comunica que fue medido y no supero el backtest pareado.
- **v3.24 de respaldo** intacto en
  `analisis backtest/2026-05-12/HM_SI_v3_24_referencia.py`.

### Por que se hizo rollback

Backtest pareado sobre la semana 2026-05-04 (mismo SKU, mismas ventas
reales en ambos metodos):

| Version | WAPE | BIAS | Forecast (real=32,548) |
|---|---|---|---|
| **v3.24** (respaldo) | **75.07%** | **-10.13%** | 35,843 |
| v4.3-revert (canonico puro) | 140.55% | -73.37% | 56,429 |
| OLD baseline (`x_forecast_weekly_data`) | 80.77% | -31.23% | 42,713 |

- v3.24 era 65pp mejor que v4.3-revert y 5pp mejor que el OLD baseline.
- 1,174 SKUs de 1,960 (60%) empeoraron con v4.3-revert.
- Cervezas con peaks navideños se proyectaron en mayo a 22-30x el real
  (CRISTAL LATA 12X470: real 47, v4.3-revert pronostico 1,401).

La hipotesis "modelos canonicos puros bastan" resulto falsa en este
contexto. Las salvaguardas que v3.24 acumulo (caps P1/P3/P6, SI
multi-nivel con clamps, deteccion up/hold/down en `_calc_base_demand`,
ajuste por precio con decay, table PRICE_FACTOR_TABLE_L2) eran lo que
mantenia el forecast en rango. Quitarlas en v4.x desmantelo la
performance.

## Changelog

- **v3.39 AUTO_MODEL** (2026-05-20, productivo): auto-model selection per
  SKU al estilo SAP IBP. Bake-off entre heuristico, SBA(0.15),
  Croston(0.10), seasonal_naive_52 sobre holdout de 4 sem cerradas.
  Heuristic-bias 0.90: el heuristico solo pierde si otro modelo tiene MAE
  >=10% menor. WAPE global mejoro de 67.36% a 66.94%, REG-1 intacto.
  Helpers `_croston`/`_sba`/`_mae_of_forecast` portados a nivel modulo
  (sin closures — Odoo Server Action sandbox rechaza
  LOAD_CLOSURE/STORE_DEREF/MAKE_CELL).
- **v3.38 SMA(8)** (DESCARTADO 2026-05-20): probado subir
  SERVICE_BASE_SHORT_WEEKS de 6 a 8. WAPE neutro pero colas devastadas
  (AZ BIAS -39.9% a -48.9%, CZ -35.5% a -47.8%). Revertido.
- **v3.38 SBA REG-7** (DESCARTADO 2026-05-20): dispatcher por regimen con
  SBA(alpha=0.05) en REG-7. WAPE +1.6pp peor, BIAS -4.5pp peor (sub-forecast).
  Razon: SBA dogmatico por regimen es muy conservador para intermitentes con
  periodos cortos. El patron correcto es bake-off per-SKU (v3.39).
- **v3.37 CORR_VALIDATION** (2026-05-20, productivo): validacion empirica
  del factor de correccion externo. Si tenemos >=3 sem post-cambio, comparar
  base_vals pre vs post. Si la realidad muestra menos impacto del predicho
  (empirical_factor > correccion_factor + 0.15), atenuar a (factor + emp)/2
  clampeado a 1.0. Caso testigo: SKU 0154 Coca Cola Paillaco, factor 0.814
  -> ~0.9. Asimetrica: solo atenua over-corrections.
- **v3.36 COLLAPSE** (2026-05-20, productivo): detector de colapso de
  demanda en `_calc_base_demand`. Tercer umbral en branch de bajada cuando
  ratio < SERVICE_RATIO_COLLAPSE (0.30) devuelve sma_short puro. El ratio
  se evalua sobre raw_vals (no base_vals) para no enmascarar caidas reales
  con baja estacionalidad. Caso testigo: SKU 451500 Royal Guard Futrono,
  caida 330 -> 6 u/sem. Nuevo campo de auditoria `x_studio_collapse_detected`.

- **v3.24 + regimen** (2026-05-12, productivo previo): rollback al runner
  v3.24 con 5 inyecciones puntuales:
  1. `regimen_field = _first_field(Abc, ['x_studio_regimen', 'x_regimen'])`
  2. Incluido en `read_fields` del router context.
  3. `'regimen'` agregado al dict del router context.
  4. `router_regimen = rctx.get('regimen', '')` leido por SKU en el
     loop principal.
  5. `_put_field(vals, fwd_fields, 'x_studio_regimen', router_regimen, 20)`
     persiste el regimen en `x_hm_si_forecast`.

  Cero cambios a `_route_forecast_scope` (sigue devolviendo Z1-Z4),
  cero cambios a P1/P3/P6, cero cambios a `_calc_base_demand`, cero
  cambios al SI multi-nivel ni al ajuste por precio.

- **v4.3-revert** (DESCARTADO): vuelta a 2 ciclos sobre v4.3 inicial. El
  motor seguia siendo canonico puro y el backtest pareado mostro 65pp
  peor que v3.24. Archivado como referencia.
- **v4.3** (DESCARTADO): aumento a 3 ciclos (`DEMAND_WINDOW_WEEKS=156`).
  Empeoraba aun mas la performance vs v3.24. Revertido a v4.3-revert,
  luego ambos descartados.
- **v4.2** (descartado): primera version con HW seasonal realmente
  activado (ventana 104) y reporting honesto en `_fc_dispatch`. Igual
  inferior al v3.24 cuando se midio.
- **v4.1** (descartado): cambio de Croston a SBA en REG-6/7. Buena teoria
  (Syntetos-Boylan 2005), mala performance practica en este dataset.
- **v4.0** (descartado): motor reescrito sobre modelos canonicos puros
  (Holt-Winters, Croston, SBA). Elimino router Z1-Z4, P1/P3/P6, SI
  multi-nivel, ajuste por precio. La hipotesis "teoria limpia bastara"
  no se confirmo contra el backtest pareado.

El linaje v4.0-v4.3-revert vive ahora solo en
`analisis backtest/2026-05-12/HM_SI_v4_3_canonical_descartado.py` y en
`_forecast_models.py` (modelos canonicos como funciones puras con tests
16/16). El codigo canonico no se borra: queda disponible para experimentos
puntuales donde un regimen especifico del v3.24 sea malo y se quiera
probar HW/SBA solo para ese regimen.

- **v3.24** (`FWD_v3_24_CMP5`): version sobre la que se opera. Cambios
  detallados en el header del propio archivo.

## Proposito

Generar un forecast semanal de demanda por producto y local (team).
Escribir el resultado en `x_hm_si_forecast`, que es el insumo del
backtest (`4- OH Forecast Backtest.py`) y del analisis de stock
(`3- OH Analisis de Stock.py`).

El motor combina:
- **Calculo base de demanda** con SMA corto/largo y deteccion de
  regimen up/hold/down (`_calc_base_demand`).
- **Indice estacional multi-nivel**: SKU -> categoria/local ->
  categoria global -> global (con piso y techo).
- **Ajuste por precio** con elasticidad calibrada por categoria L2 y
  decay temporal.
- **Caps anti-spike** P1/P3/P6 segmentados por abcxyz x zona.

El **regimen** (REG-0..REG-8) NO interviene en el calculo. Es un dato
descriptivo heredado de ABCXYZ que se persiste para que el backtest
pueda agrupar los resultados de v3.24 por la matriz canonica de 9
segmentos. Permite identificar en que regimen especifico el motor
v3.24 esta haciendo mal forecast, sin alterar la operacion estable.

## Flujo de ejecucion

1. **Lock advisory**: `pg_try_advisory_lock(99009438)`. Aborta si otra
   corrida esta activa.

2. **Validacion de schema**: verificar campos requeridos en
   `x_hm_si_forecast`. Si faltan, abortar con notificacion.

3. **Purge si HARD_RESET**: borra filas previas para los teams del scope.
   Idempotente.

4. **Calculo de ventanas temporales**:
   - `date_to`: ultima semana cerrada (hora Chile).
   - `history_from`: 24 meses atras desde `date_to` (POS para SI).
   - `demand_from`: 26 semanas (`DEMAND_WINDOW_WEEKS`) sobre las que se
     calcula la demanda base.
   - `target_date`: 1 semana adelante.

5. **Universo de productos**: SQL sobre `product_product` activos,
   vendibles, no servicio ni combo.

6. **Carga POS multi-team con combo handling**: query SQL que agrega
   ventas semanales por `(team_id, product_id, week)`. Hijos de combo
   heredan revenue prorrateado del padre.

7. **Calculo de SI multi-nivel**:
   - **SKU**: `si_weekly_sku[product_id][iso_week]`.
   - **Categoria/local**: `si_weekly_local_categ[(team_id, categ_id)]`,
     solo si la combinacion tiene >= 12 semanas con datos.
   - **Categoria global**: `si_weekly_categ_global[categ_id]`.
   - **Global**: fallback ultimo.
   Cada nivel se calcula con `_calc_si_from_weekly` (promedio normalizado
   por iso_week).

8. **Carga del contexto de precio** (`_load_price_context`): para cada
   producto, lee `x_price_change_event` y calcula:
   - Segmento (`stable_price`, `frequent_price_core`, etc.).
   - Factor de ajuste por semana usando `PRICE_FACTOR_TABLE_L2` y
     decay temporal con `_apply_decay`.

9. **Carga del router context** (`_load_forecast_router_context`):
   lee de `x_calculo_abc_xyz` los atributos:
   - `abcxyz`, `series_type`, `lifecycle` (usados por v3.24).
   - **`regimen`** (NUEVO 2026-05-12): leido pero NO usado en el
     calculo, solo persistido en la salida.

10. **Loop principal por (team, product)**:

    a. **Construir base_vals**: para cada semana de la ventana,
       multiplicar por price_factor y dividir por si_w (deflactar).
       Esta es la "demanda base" sin estacionalidad ni efectos de
       precio.

    b. **`_calc_base_demand(base_vals, ...)`**: calcula `mu_base`
       con regla:
       - n < long_weeks (16): promedio simple.
       - ratio = sma_short / sma_long >= 1.15: `sma_short` (subida).
       - ratio >= 0.90: `sma_long` (hold).
       - else: `0.7 * sma_short + 0.3 * sma_long` (bajada).

    c. **Calcular si_next, si_current** para target_isoweek y
       current_isoweek con SI multi-nivel y ajuste por SKU.

    d. **`mu_week = mu_base * si_next`**: re-estacionalizar.

    e. **Router de zona** (`_route_forecast_scope`): asigna
       `forecast_zone` Z1/Z2/Z3/Z4 segun `(abcxyz, series_type,
       lifecycle, mu_week)`.

    f. **Caps anti-spike** (v3.17):
       - **P1**: si `lifecycle in ('declining', 'dead')` ->
         `mu_week = 0`.
       - **P3**: si `forecast_zone == 'Z4'` y no es ramp_up y las
         ultimas 8 semanas tienen <= 1 con venta -> `mu_week = 0`.
       - **P6**: cap por (abcxyz x zone):
         - BZ -> `cap = max_obs * 0.8`.
         - AZ/CZ/BY-Z3Z4/AY-smooth-Z2/CY-Z4 -> `cap = max_obs * 1.2`.

    g. **Persistir en `x_hm_si_forecast`** con `_put_field` (saltea
       campos que no existen).

11. **Log y unlock**: log estructurado con conteos por zona y por
    metodo. Liberar advisory lock.

## El router de zonas Z1-Z4 (v3.24 nativo)

El campo `x_studio_forecast_zone` se popula con Z1/Z2/Z3/Z4/SIN_ZONA segun
`_route_forecast_scope(abcxyz, series_type, lifecycle, mu_week)`:

- **Z1 (core_hm_si)**: AX/AY/BX smooth, mature/ramp_up, mu >= 2.0.
  AX smooth con mu >= 1.0 entra antes (regla v3.13).
- **Z2 (controlled_hm_si)**: AX/AY erratic/lumpy, mature/ramp_up,
  mu >= 2.0.
- **Z3 (secondary_model)**: seasonal lifecycle, o BY/BZ/AZ
  erratic/lumpy. Fallback general.
- **Z4 (no_forecast)**: no_signal, o CX/CY/CZ, o declining/dead, o
  mu < 2.0.

Las zonas mezclan dimensiones (abcxyz x series_type x lifecycle x
volumen) y por eso son utiles operativamente pero no semanticamente
limpias. La intencion del rollback es mantener esta logica probada y
ortogonalmente cortar las metricas por el regimen canonico de 9
segmentos.

## El dato adicional: `x_studio_regimen`

ABCXYZ v19.3 calcula y persiste `x_studio_regimen` con la matriz
canonica de 9 segmentos:

| Regimen | Tipico | Modelo recomendado por teoria |
|---|---|---|
| REG-0 | dead/declining o C+no_signal | forecast = 0 |
| REG-1 | A x smooth x mature | Holt-Winters conservador |
| REG-2 | B x smooth x mature | Holt-Winters |
| REG-3 | C x smooth | Holt-Winters mas suave |
| REG-4 | any x erratic | Holt-Winters reactivo |
| REG-5 | A/B x lumpy | SBA |
| REG-6 | C x lumpy | SBA conservador |
| REG-7 | intermittent/no_signal | SBA muy suave |
| REG-8 | seasonal lifecycle | HW con gamma alto |

**v3.24 NO USA el regimen** para calcular. Lo lee de ABCXYZ y lo
persiste tal cual en `x_hm_si_forecast.x_studio_regimen`. Esto permite
al backtest agrupar los resultados de v3.24 por el regimen canonico y
medir performance por segmento.

Si un regimen sale con WAPE catastrofico en v3.24, ese sera el candidato
a intervencion targeted: reemplazar la logica de `_calc_base_demand` +
SI + caps para ese regimen especifico, usando el modelo canonico
correspondiente desde `_forecast_models.py`. Las intervenciones se
hacen una por una, validadas contra el backtest, no en masa como en
v4.x.

## Decisiones de diseno (lo que se conserva de v3.24)

### Router Z1-Z4 (no se toca)

Si bien las zonas mezclan dimensiones, el backtest mostro que la
combinacion de zonas + caps P1/P3/P6 + SI multi-nivel produce mejor
WAPE que las 9 regimenes canonicos sin caps. La aparente "limpieza
semantica" del modelo canonico no compensa la perdida de las
salvaguardas calibradas.

### SI multi-nivel con clamps

`_get_si_final` busca SI en el orden:
1. `(team_id, categ_id, iso_week)` -> local_categ (si >= 12 semanas con
   datos).
2. `(categ_id, iso_week)` -> categ_global.
3. `iso_week` -> global.

Sobre el factor encontrado se aplica ajuste por SKU (si tiene >= 1 ano
de historia, deviation entre `si_sku / si_categ`) ponderado por alpha
(0.15 si < 3 anos, 0.30 si >= 3 anos). Resultado clampeado a
`[SI_FLOOR=0.05, SI_CEIL=5.00]`.

Los clamps evitan que un SI exagerado deflacte la demanda base y luego
re-infle el forecast a magnitudes irreales.

### Caps P1/P3/P6 anti-spike

Son la red de seguridad que mantuvo a v3.24 dentro de rango:
- **P1 (lifecycle gate)**: declining/dead nunca generan demanda.
- **P3 (intermittence gate)**: Z4 sin actividad reciente -> 0.
- **P6 (max histórico cap)**: el forecast no supera 1.2x (o 0.8x para
  BZ) el maximo observado en la ventana.

Estos caps son la version operativa de literatura mas reciente: lifecycle
gate (politica), intermittence filter (Teunter-Syntetos-Babai 2011),
robust forecasting (Gardner 2006).

### Ajuste por precio con elasticidad y decay

`PRICE_FACTOR_TABLE_L2` calibra factores por categoria L2 (Cervezas,
Vinos, etc.) y rango de cambio (BAJADA_FUERTE / LEVE / SUBIDA_LEVE /
FUERTE). El factor se aplica multiplicativamente a la demanda
historica para "normalizar" semanas con descuento o promocion, antes
de calcular `mu_base`. El factor decae a 1.0 en `PRICE_DECAY_WEEKS=16`
semanas desde el cambio.

Sin este ajuste, los descuentos del pasado contaminan el calculo de
demanda base.

### Deteccion up/hold/down de demanda

`_calc_base_demand` no usa solo el promedio: compara SMA(6) vs SMA(16)
y elige una estrategia segun el ratio. Esto detecta caidas o subidas
recientes sin esperar a que la tendencia se establezca por completo
(que es lo que harian HW level + trend con beta=0.10).

## I/O del runner

### Lee

- `pos_order` + `pos_order_line` (ventas POS).
- `product_product`, `product_template`, `product_category` (catalogo).
- `pos_config` (mapeo team/store).
- `x_price_change_event` (cambios de precio para ajuste).
- `x_calculo_abc_xyz` (abcxyz, series_type, ciclo_de_vida,
  **regimen** [nuevo 2026-05-12]).

### Escribe

A `x_hm_si_forecast`, una fila por `(team, product, target_week)`:

**Columnas principales del calculo:**
- `x_studio_product_id`, `x_studio_team_id`, `x_studio_categ_id`
- `x_studio_week_start` (target_date)
- `x_studio_mu_week`, `x_studio_mu_week_pre_bias`, `x_studio_sigma_week`
- `x_studio_mu_base`, `x_studio_sigma_base`
- `x_studio_si_current`, `x_studio_si_next`, `x_studio_si_n_years`
- `x_studio_si_level`, `x_studio_si_main_factor`, `x_studio_si_sku_factor`

**Auditoria de precio (v3.24 nativo):**
- `x_studio_units_sold_adjusted`
- `x_studio_price_dynamics_segment`, `x_studio_price_events_104w`,
  `x_studio_price_events_12w`
- `x_studio_price_current_eff`, `x_studio_price_adjust_weeks`,
  `x_studio_price_adj_factor_avg`/`max`/`min`
- `x_studio_price_adjust_enabled`, `x_studio_price_elasticity_used`
- `x_studio_mu_week_price_delta`

**Auditoria del router (v3.24 nativo):**
- `x_studio_forecast_zone` (Z1/Z2/Z3/Z4/SIN_ZONA)
- `x_studio_forecast_scope`, `x_studio_forecast_model_code`,
  `x_studio_forecast_scope_reason`
- `x_studio_abcxyz`, `x_studio_series_type`, `x_studio_ciclo_de_vida`

**Inyeccion 2026-05-12:**
- **`x_studio_regimen`** (REG-0..REG-8 heredado de ABCXYZ, NO afecta
  el calculo).

## Robustez

### Campo `x_studio_regimen` no existe en Studio

`_put_field` silenciosamente omite campos no presentes en `fwd_fields`.
La columna saldra vacia en el xlsx exportado, el runner no falla. Si
ABCXYZ tampoco escribe el campo (version vieja), `router_regimen` queda
en string vacio y se persiste vacio.

### ABCXYZ sin `x_studio_regimen` (version anterior a v19)

`_load_forecast_router_context` lo detecta via `_first_field`, el
campo regresa `False`, y el dict del router queda con `'regimen': ''`.
HM-SI sigue corriendo normal con Z1-Z4 nativo. La columna sale vacia.

### Productos sin historia

`base_vals = []` -> `mu_base = 0.0`, `mu_week = 0.0`. No hay division
por cero.

### Selection con keys incompletas

Si `x_studio_forecast_zone` es Selection con solo Z1-Z4, no hay
problema (v3.24 escribe Z1-Z4). Si `x_studio_regimen` es Selection con
REG-0..REG-8, ABCXYZ ya valida la integridad. Si es Char, acepta
cualquier string.

## Validacion

### Que comparar y contra que

El criterio operativo es:

| Metrica | Target v3.24+regimen | Notas |
|---|---|---|
| WAPE global | <= 75% | medido en 2026-05-04 |
| BIAS global | en `[-15%, +5%]` | v3.24 dio -10.13% |
| Forecast/Real ratio | en `[0.9, 1.2]` | v3.24 dio 1.10 |

Contra el OLD baseline (`x_forecast_weekly_data`, WAPE 80.77%) la regla
es: NO regresar. Si v3.24+regimen sale peor que OLD, hubo error en el
rollback.

### Flujo de validacion

1. Ejecutar el runner desde Odoo Server Action.
2. Verificar log: `created`, `zones=Z1:...,Z2:...,Z3:...,Z4:...`.
3. Inspeccionar 5-10 filas en `x_hm_si_forecast`:
   - `forecast_zone` poblado con Z1/Z2/Z3/Z4.
   - `regimen` poblado con REG-0..REG-8 (si el campo existe).
4. Correr `4- OH Forecast Backtest.py` con `BACKTEST_WEEKS=3`.
5. Exportar `x_forecast_backtest` a xlsx.
6. Correr `analisis backtest/2026-05-12/_bt_compare.py` apuntando al
   xlsx nuevo. Esta vez la dimension `regimen` saldra poblada para
   ambos metodos (hm_si y old), permitiendo cortar por los 9 segmentos
   canonicos.

## Roadmap

### Inmediato (proximas 1-2 semanas)

1. **Medir v3.24+regimen contra los 9 regimenes canonicos**.
   Ejecutar backtest y producir tabla:

   | Regimen | n | real | forecast | WAPE | BIAS |
   |---|---|---|---|---|---|
   | REG-0 | ... | ... | ... | ... | ... |
   | REG-1 | ... | ... | ... | ... | ... |
   | ... | ... | ... | ... | ... | ... |
   | REG-8 | ... | ... | ... | ... | ... |

2. **Identificar regimenes problematicos**. Criterio tentativo:
   - WAPE > 100% (peor que predecir cero) -> candidato fuerte a
     intervencion.
   - WAPE entre 80-100% y BIAS sistematico -> revisar caps P6.
   - WAPE < 75% -> regimen sano, no tocar.

### Iterativo (un plan separado por regimen problematico)

Para cada regimen identificado como malo:

1. **Diagnostico**: que SKUs concentran el error? que zonas Z1-Z4
   estan asignadas a ese regimen? que codigo de `_calc_base_demand` se
   esta ejecutando (`avg_base`, `sma_up`, `sma_hold`, `blend_down`)?

2. **Intervencion targeted**: reemplazar el calculo para SKUs en ese
   regimen especifico con el modelo canonico apropiado desde
   `_forecast_models.py` (que sigue valido, tests 16/16 pasan):
   - REG-5/6/7 problematicos -> probar SBA (`_fc_sba`) con alpha
     calibrado.
   - REG-8 problematico -> probar HW seasonal (`_fc_holt_winters` con
     gamma alto).
   - REG-1/2/3/4 problematicos -> revisar primero el ajuste de precio
     y los caps; modelo canonico solo si el problema persiste.

3. **Validacion**: backtest A/B sobre la misma semana. Solo
   incorporar al runner si mejora el WAPE del regimen sin degradar el
   global.

4. **Naming**: las versiones del runner se enumeran ahora como
   v3.25, v3.26, etc. (continuacion del linaje productivo), NO como
   v4.x (linaje descartado).

### Ideas pendientes (sin orden estricto)

- **Hampel filter** sobre `base_vals` antes de `_calc_base_demand`,
  para limpiar outliers (Hampel 1974). Riesgo: en SKUs lumpy puede
  borrar la senal real. Aplicar selectivamente.
- **Crear `x_studio_regimen` en Studio** sobre `x_hm_si_forecast` si
  no existe. Sin esto, la inyeccion del 2026-05-12 queda inerte (la
  columna sale vacia en el xlsx).
- **Crear `x_studio_regimen` y `x_studio_forecast_model_code` sobre
  `x_forecast_backtest`** para que el backtest persista ambas
  dimensiones y los analisis posteriores agrupen sin cruzar manual.
- **GMROI canonico** sobre `x_calculo_abc_xyz`. No bloquea forecast.
- **Capa de eventos planificados futuros** (`x_promo_plan`). Capa
  multiplicativa post-forecast, fuera del motor. Trabajo Fase 3+.

## El experimento descartado v4.0-v4.3-revert

Resumen ejecutivo del linaje que vive en
`analisis backtest/2026-05-12/HM_SI_v4_3_canonical_descartado.py`:

**Hipotesis**: los modelos canonicos puros (Holt-Winters, Croston, SBA)
sobre los 9 regimenes canonicos bastarian para superar al v3.24
heuristico.

**Diseno**: motor reescrito de 1679 -> 984 lineas. Eliminado router
Z1-Z4, P1/P3/P6, SI multi-nivel, ajuste por precio. Reemplazado por
dispatcher segun regimen que llama a `_fc_holt_winters`, `_fc_sba`,
`_fc_croston` desde `_forecast_models.py` (con tests 16/16).

**Resultado**: 65pp peor en WAPE, 63pp peor en BIAS, 60% de los SKUs
empeoraron. Cervezas con peaks navideños proyectandose en mayo a
22-30x el real. SBA en REG-5/6/7 catastrofico (WAPE 1,338%, 474%,
341%).

**Causa raiz**: los modelos canonicos puros son **descriptivos** -
describen el pasado. Cuando el pasado tiene peaks no representativos
del futuro, los modelos los proyectan tal cual. Las correcciones
P1/P3/P6 + SI clamps de v3.24 eran el equivalente operativo de:
- P1 = lifecycle gate (politica de negocio).
- P3 = intermittence gate (Teunter-Syntetos-Babai 2011).
- P6 = bounded forecast (Gardner 2006, robust forecasting).
- SI clamps = capped seasonal index (Hyndman & Athanasopoulos cap. 8.3).

Eliminar estas salvaguardas en busca de "limpieza teorica" desmantelo
la performance. La leccion: **literatura sin red operativa no basta en
retail con peaks estacionales fuertes**.

**Que sobrevive del experimento**:
- `_forecast_models.py` con HW/Croston/SBA puros + 16 tests, util para
  intervenciones targeted por regimen.
- `_forecast_baselines.py` con naive/seasonal_naive/MASE + 8 tests, util
  para validacion canonica.
- El campo `x_studio_regimen` en ABCXYZ y la matriz de 9 regimenes en
  `_assign_regimen`, util para reporteria y diagnostico aun sin usarse
  para calculo.
- Backtest v11.1 con `_zone_code` aceptando REG-X, util para futuros
  experimentos.

## Referencias

- Holt, C. C. (1957). "Forecasting seasonals and trends by exponentially
  weighted moving averages".
- Winters, P. R. (1960). "Forecasting sales by exponentially weighted
  moving averages". Management Science.
- Croston, J. D. (1972). "Forecasting and stock control for intermittent
  demands". OR Quarterly.
- Syntetos, A. A. & Boylan, J. E. (2005). "The accuracy of intermittent
  demand estimates". International Journal of Forecasting.
- Hampel, F. R. (1974). "The influence curve and its role in robust
  estimation". JASA.
- Brown, R. G. (1959). "Statistical Forecasting for Inventory Control".
- Hyndman, R. J. & Koehler, A. B. (2006). "Another look at measures of
  forecast accuracy". IJF (MASE).
- Hyndman, R. J. & Athanasopoulos, G. (2018). "Forecasting: Principles
  and Practice".
- Gardner, E. S. (2006). "Exponential smoothing: The state of the art -
  Part II". IJF (robust forecasting).
- Teunter, R. H., Syntetos, A. A. & Babai, M. Z. (2011). "Intermittent
  demand: Linking forecasting to inventory obsolescence". EJOR.

Ver `AGENTS.md` -> Referencias Canonicas por Dominio para la lista
completa.
