# Proceso Forecast Ideal vs Actual

**Fecha:** 2026-05-23  
**Estado:** documento estratégico de referencia  
**Alcance:** forecast, segmentación, corrección de precio, backtest y consumo operativo por stock  
**Tipo de cambio:** documentación; no toca código productivo

---

## 0. Lectura ejecutiva

El sistema actual no está en cero. Hay una base bastante superior a un forecast simple: segmentación ABC/XYZ, ADI/CV², lifecycle, regímenes, motor HM-SI, corrección por precio/promoción, backtest y consumo por análisis de stock.

El problema no es que “falte un modelo”. El problema es que el proceso todavía no está cerrado como sistema industrial:

1. La demanda observada aún no está completamente separada de la demanda real esperada.
2. La segmentación existe, pero falta formalizar cuándo dirige modelo, cuándo dirige política de stock y cuándo solo reporta diagnóstico.
3. El motor ha evolucionado por parches razonables, pero el canon productivo no está congelado como contrato estable.
4. El backtest existe, pero aún no opera como gate automático de promoción.
5. La promoción a producción sigue siendo manual y dependiente de revisión humana, no de un flujo shadow/champion/challenger.

**Conclusión:** antes de abrir auto-tuning agresivo, bake-off grande o modelos más sofisticados, el próximo paso correcto es documentar y cerrar el proceso end-to-end. Optimizar el motor sin corregir data foundation y governance puede mejorar WAPE y, aun así, empeorar decisiones de compra.

### Nota de consistencia documental

El plan original menciona un norte basado en `HM_SI_v3_42_CANON.py`. En el repo revisado, la fuente viva disponible es `02_forecast/HM SI Forecast.py`. El header registra evolución hasta fair share v3.41, pero el `VERSION_ID` operativo expuesto en el archivo declara `FWD_v3_39_AUTO_MODEL`. Esta diferencia no se trata como bug funcional en este documento, pero sí como **gap de governance**: antes de promover cualquier mejora, debe quedar explícito cuál es el champion productivo real.

**Referencias internas base:**

- `CLAUDE.md:1-117` — principios de diseño, pipeline y orden de ejecución.
- `02_forecast/HM SI Forecast.py:1-220` — evolución HM-SI, fair share, auto-model, SBA revertido, colapso de demanda y price cleanup.
- `01_segmentacion/OH Calculo ABCXYZ.py:1-260` — ABCXYZ, ADI/CV², lifecycle, regímenes y GMROI.
- `02_forecast/OH Price Correccion.py:1-240` — detector externo de precio/promos y elasticidad por ABC.
- `02_forecast/OH Forecast Backtest.py:1-260` — backtest v11.1, compatibilidad REG-0..REG-8 y estructura multi-semana.
- `03_stock/OH Analisis de Stock.py:1-220` — consumo operativo del forecast por análisis de stock, safety, CD/sala, MOQ y compra mensual.
- `CHANGELOG.md:1-260` — trazabilidad histórica del motor de stock y política de auditoría.

---

## 1. Data Foundation — insumos de demanda

### Norte estrella canónico

Un proceso industrial tipo SAP IBP / Oracle / Blue Yonder no trata la venta POS cruda como demanda final. Primero construye una capa de **demand sensing / demand cleansing**:

- POS limpio y deduplicado.
- Unidades, signos, producto, local y fecha validados antes de llegar al motor.
- Eventos causales separados de la demanda base: promoción, cambio de precio, feriado, quiebre de stock, cierre local, liquidación, discontinuación.
- Outlier detection previo al modelo, idealmente MAD/Tukey/robusto por SKU-local.
- Distinción explícita entre `venta = 0 porque no hubo demanda` y `venta = 0 porque no había stock`.
- Contrato de datos único: granularidad, timezone, lunes de inicio de semana, product.product vs product.template, local/team, unidad de venta y unidad de compra.

### Estado actual

El pipeline declarado en `CLAUDE.md` ya ordena el flujo base: segmentación → corrección de precio → motor HM-SI → análisis de stock → generación de documentos, con backtest como validación posterior (`CLAUDE.md:78-103`).

`OH Price Correccion.py` ya externaliza parte de la causalidad: cambios de precio, promociones, lookback diferenciado, elasticidad por ABC y persistencia de factor en `x_price_coreccion` (`02_forecast/OH Price Correccion.py:1-122`). Eso es correcto: el motor HM-SI no debería recalcular toda la causalidad comercial adentro.

`HM SI Forecast.py` también reconoce problemas reales de data: price cleanup, corrección externa, detector de colapso de demanda y uso de raw values para evitar que la deflación estacional oculte caídas reales (`02_forecast/HM SI Forecast.py:191-220`).

`OH Analisis de Stock.py` consume demanda local desde HM-SI, calcula safety, cobertura, compra/transferencia y presupuesto mensual (`03_stock/OH Analisis de Stock.py:1-59`). Por eso un error en demanda base se transforma directamente en una orden de compra errónea.

### Gap explícito

#### G-CRÍTICO — Quiebre de stock no separado formalmente de demanda cero

Hoy el sistema puede observar venta cero, pero todavía no queda como contrato único si ese cero significa:

- no hubo demanda real,
- no había stock,
- el producto estaba bloqueado/no disponible,
- la sala no trabaja ese SKU,
- hubo cierre operativo,
- el producto está en salida comercial.

Esto genera sub-forecast estructural: si un SKU no vende porque no hay stock, el forecast baja, stock no compra y la ausencia se autoperpetúa.

#### G-CRÍTICO — Outlier/promoción todavía no es gate canónico de entrada

La corrección por precio/promoción existe, pero la capa de demanda limpia todavía no está formalizada como “actual demand enriquecida” antes del motor. Parte de la lógica vive en Price Correccion, parte en HM-SI y parte en interpretación humana.

#### G-MEDIO — Exclusiones por lista negra, no por características detectables

Hay exclusiones operativas razonables, pero el norte debería ser que el sistema detecte patrones: always-on promo, quiebre, discontinuación, sala nueva, SKU nuevo, evento calendario, etc. Una lista negra sirve como parche; no escala como proceso.

#### G-BAJO — Falta contrato formal de `x_hm_si_demanda_history`

El documento futuro debería especificar, como contrato:

- clave operativa: product.product + crm.team + semana,
- timezone: America/Santiago,
- semana: lunes-start,
- venta neta vs venta bruta,
- tratamiento de combos/packs,
- flags causales mínimos,
- campos obligatorios y opcionales.

### Implementación práctica sugerida

Antes de tocar modelos, crear una **tabla/contrato de demanda limpia**:

1. `raw_qty`: venta POS cruda.
2. `clean_qty`: venta limpia después de outlier/promo/stockout rules.
3. `is_stockout_suspected`.
4. `is_promo`.
5. `price_event_id`.
6. `holiday_code`.
7. `data_quality_flag`.
8. `cleaning_reason`.

El motor debería leer `clean_qty` como demanda base y los flags como variables explicativas/auditoría.

---

## 2. Segmentación que dirige al modelo

### Norte estrella canónico

La segmentación no debería ser solo reporte. En un forecast serio, la segmentación define:

- qué modelo se usa,
- cuánto historial se usa,
- qué guardrails se aplican,
- qué nivel de safety stock corresponde,
- qué SKUs no deben pronosticarse automáticamente.

El norte recomendado:

- ABC por importancia económica/volumen/margen.
- XYZ por variabilidad.
- ADI/CV² tipo Syntetos-Boylan para distinguir smooth, erratic, intermittent y lumpy.
- Lifecycle: new, ramp_up, mature, seasonal, declining, dead.
- Histéresis para evitar que un SKU cambie de régimen por ruido semanal.
- Re-segmentación periódica y auditable.

### Estado actual

`OH Calculo ABCXYZ.py` ya está cerca del norte estrella. La versión v19.4 incorpora:

- `x_studio_series_type` largo de 52 semanas,
- `x_studio_series_type_short` de 12 semanas,
- `x_studio_series_type_active` como señal activa para HM-SI,
- ADI/CV²,
- régimen REG-0..REG-8,
- GMROI,
- lifecycle basado en presencia trimestral (`01_segmentacion/OH Calculo ABCXYZ.py:1-92`).

El mismo archivo documenta umbrales canónicos ADI/CV² y la matriz Syntetos-Boylan: smooth, erratic, intermittent y lumpy (`01_segmentacion/OH Calculo ABCXYZ.py:116-139`). También define lifecycle como proxy, no como PLC canónico completo (`01_segmentacion/OH Calculo ABCXYZ.py:189-260`).

El motor HM-SI registra que en v3.34 comenzó a consumir variables locales: `xyz_local`, `series_type_local`, `lifecycle_local` y `regimen_local`, con fallback global cuando no hay señal local suficiente (`02_forecast/HM SI Forecast.py:216-220`).

### Gap explícito

#### G-CRÍTICO — Falta contrato estable entre segmentación y motor

La segmentación existe, pero el contrato operativo aún debe quedar congelado:

- qué campo manda: `series_type`, `series_type_short` o `series_type_active`,
- si el régimen local manda sobre global,
- cuándo se permite fallback global,
- cuándo un SKU pasa a no_forecast,
- qué pasa si faltan campos.

Hoy el header del motor muestra varias capas: regímenes, auto-model, fair share, rescates AX/AY/AZ, P3 zero-gate, collapse detector. Todas son razonables, pero necesitan una matriz final de decisión.

#### G-CRÍTICO — No hay histéresis documentada

Si un SKU cambia de smooth a erratic o de mature a declining por una ventana corta, el modelo podría cambiar de política demasiado rápido. Para operación de compras, eso es peligroso: genera compra/paralización/retorno con ruido.

La regla industrial debería ser: un SKU cambia de régimen solo si el nuevo régimen se mantiene N semanas o si el cambio es crítico y validado por causa fuerte.

#### G-MEDIO — Lifecycle es proxy y puede confundir quiebre con declive

El propio código documenta que lifecycle es proxy basado en presencia trimestral, no PLC completo (`01_segmentacion/OH Calculo ABCXYZ.py:189-260`). Si no hay stock, baja la presencia; si baja la presencia, puede parecer declining; si parece declining, el motor puede apagar forecast.

#### G-BAJO — GMROI está correcto como capa financiera, pero no debe contaminar demanda

GMROI decide inversión en stock. No debería alterar demanda base. Debe influir en política de inventario, priorización bajo caja limitada y nivel de cobertura, no en la estimación de unidades esperadas.

### Implementación práctica sugerida

Crear una matriz explícita de routing:

| Segmento | Modelo permitido | Fallback | Política de stock | Gate |
|---|---|---|---|---|
| AX/AY smooth mature | HM-SI / ETS challenger | HM-SI | alta protección | no apagar por 1 semana mala |
| AZ/BZ lumpy alto valor | SBA/Croston/median challenger | HM-SI capped | protección controlada | requiere stockout flag |
| intermittent | Croston/SBA/TSB challenger | demanda mínima/floor | baja cobertura | no usar WAPE aislado |
| seasonal | seasonal naive + SI | HM-SI SI | pre-temporada | feriado/calendario obligatorio |
| dead/declining | no_forecast salvo excepción | manual | liquidar/retorno | requiere lifecycle estable |

---

## 3. Motor de pronóstico — best-fit por serie

### Norte estrella canónico

El norte no es “un modelo único para todo”. El norte es un panel de modelos con selección controlada:

- **Series suaves:** ETS/Holt-Winters, ARIMA, HM-SI si demuestra mejor desempeño operativo.
- **Intermitentes:** Croston, SBA, TSB.
- **Estacionales puras:** seasonal naive / seasonal indices.
- **SKU nuevo o sala nueva:** analog/fair share/Bass-like proxy.
- **Erráticas:** median/robust baseline con caps.
- **Selección:** rolling-origin CV, WAPE primario, BIAS secundario, guardrails por bucket.
- **Salida:** forecast puntual + intervalo/rango + razón del modelo.

### Estado actual

El motor HM-SI ya tiene varias piezas maduras:

- fair share v3.41 con share normalizado por categoría para SKU clase A sin historia local (`02_forecast/HM SI Forecast.py:1-44`),
- fair share v3.40 para evitar ausencia autoperpetuada cuando una sala no tiene historia local (`02_forecast/HM SI Forecast.py:45-115`),
- auto-model v3.39 con heurístico, SBA, Croston y seasonal naive 52, usando holdout de 4 semanas y MAE (`02_forecast/HM SI Forecast.py:116-147`),
- reversión explícita de SBA en REG-7 cuando empeoró WAPE/BIAS (`02_forecast/HM SI Forecast.py:148-174`),
- reversión de SMA(8) por aumentar sub-forecast en colas (`02_forecast/HM SI Forecast.py:175-190`),
- detector de colapso de demanda y uso de raw ratio para no ocultar caídas con SI (`02_forecast/HM SI Forecast.py:191-220`),
- delegación del ajuste de precio al detector externo (`02_forecast/HM SI Forecast.py:216-220` y `02_forecast/OH Price Correccion.py:1-122`).

Esto es positivo: hay aprendizaje empírico y reversión de cambios que no funcionaron. Eso es mejor que enamorarse del modelo.

### Gap explícito

#### G-CRÍTICO — El champion productivo no está congelado documentalmente

El header muestra evolución hasta v3.41, mientras el `VERSION_ID` leído declara v3.39. Para un proceso auditable, el documento de versión debe responder:

- cuál versión está realmente corriendo,
- qué versión es champion,
- qué versiones son challengers,
- qué backtest la validó,
- qué fecha y qué owner la promovieron.

Sin esto, el equipo puede discutir resultados de una versión que no es la que está en producción.

#### G-CRÍTICO — Falta capa formal de eventos futuros

El motor corrige eventos históricos/recientes, pero el forecast ideal debe incorporar eventos futuros conocidos:

- promociones planificadas,
- feriados,
- temporada alta/baja,
- cambios de precio ya programados,
- apertura/cierre de sala,
- campañas comerciales.

Si el evento es futuro y conocido, no debería aparecer como “sorpresa” en el backtest.

#### G-MEDIO — Auto-model existe, pero falta protocolo de reintroducción con guardrails

v3.39 ya implementa selección de modelo por SKU. Pero la historia muestra que SBA/otros cambios pueden empeorar buckets específicos. Por eso el camino correcto no es activar todo de golpe, sino:

1. fijar buckets donde el modelo actual falla,
2. definir challenger por bucket,
3. correr shadow,
4. promover solo si supera gates.

#### G-MEDIO — Sigma no es aún prediction interval formal

El sistema entrega `mu_week` y `sigma_week`, útil para safety stock. Pero un prediction interval formal debería expresar rango esperado, nivel de confianza y limitaciones. Para compras, esto permite distinguir entre demanda estable y demanda incierta aunque tengan igual promedio.

#### G-BAJO — Falta modelo explícito para SKU nuevo

Fair share cubre parte del problema, especialmente sala/SKU sin historia local. Pero el proceso ideal debería distinguir:

- SKU nuevo en la cadena,
- SKU conocido en sala nueva,
- SKU conocido con baja historia local,
- producto sustituto/analogable.

### Implementación práctica sugerida

No partir con “meter Holt-Winters a todo”. El camino práctico:

1. Congelar el champion real.
2. Elegir 2-3 buckets malos del backtest.
3. Para cada bucket, proponer solo un challenger.
4. Correr shadow 4-8 semanas o backtest rolling-origin equivalente.
5. Promover por gate, no por intuición.

---

## 4. Validación / Backtest

### Norte estrella canónico

El backtest debe funcionar como tribunal, no como reporte posterior.

Proceso ideal:

- rolling-origin evaluation,
- WAPE como métrica primaria operativa,
- BIAS como métrica de riesgo de sobre/subcompra,
- MAE/RMSE como diagnóstico secundario,
- MASE/sMAPE si se necesita comparar buckets heterogéneos,
- service-level proxy: cuántos quiebres habría evitado/provocado,
- reporte por bolsón accionable: régimen × ABCXYZ × lifecycle × velocidad,
- casos canónicos protegidos,
- gate automático para promover o rechazar challenger.

### Estado actual

`OH Forecast Backtest.py` ya existe y tiene buena base. Declara como objetivo comparar HM-SI vs forecast anterior contra venta real POS (`02_forecast/OH Forecast Backtest.py:1-37`). La versión v11.1 agrega lectura de régimen y modelo desde HM-SI y mantiene compatibilidad con Z1-Z4 y REG-0..REG-8 (`02_forecast/OH Forecast Backtest.py:38-55`).

También soporta multi-semana, semana cerrada y purga idempotente por rango (`02_forecast/OH Forecast Backtest.py:75-83`). Esto es la base correcta para rolling-origin operacional.

### Gap explícito

#### G-CRÍTICO — No hay criterio formal de promoción

Hoy una mejora se evalúa mirando resultados, pero falta una regla dura:

- global WAPE no empeora más de X,
- bucket objetivo mejora al menos Y pp,
- BIAS no se mueve fuera de rango,
- top-N SKU críticos no regresan,
- ningún proveedor crítico genera compra explosiva,
- casos canónicos pasan.

Sin este gate, se puede promover una versión que mejora el promedio y destruye un segmento importante.

#### G-CRÍTICO — No hay casos canónicos bloqueantes

El sistema ya tiene casos reales conocidos: Royal Guard, Coca-Cola, Coors, San José/sala nueva, cigarros, packs/unidad, seasonal. Esos casos deberían vivir como set de regresión.

Si una versión nueva falla en un caso canónico crítico, no se promueve aunque el WAPE global mejore.

#### G-MEDIO — Falta dashboard por bolsón priorizado

El backtest guarda datos, pero el proceso necesita una vista ejecutiva:

- peor WAPE por régimen,
- peor BIAS por régimen,
- volumen afectado,
- margen afectado,
- número de SKU/local,
- proveedor/categoría más afectada,
- recomendación: tocar motor / tocar data / tocar stock / no tocar.

#### G-BAJO — Falta proxy de servicio

WAPE mide error de forecast. Operación sufre quiebres, sobrestock y caja inmovilizada. El backtest debería estimar también impacto operacional:

- forecast habría generado compra suficiente,
- forecast habría sobredimensionado caja,
- forecast habría apagado SKU vivo.

### Implementación práctica sugerida

Crear archivo de política de promoción:

```text
PROMOTION_GATE_FORECAST.md
```

Contenido mínimo:

1. Métricas obligatorias.
2. Umbrales de aceptación.
3. Buckets protegidos.
4. Casos canónicos.
5. Regla de rollback.
6. Quién aprueba.

---

## 5. Promoción y monitoreo en producción

### Norte estrella canónico

En un sistema industrial, la versión nueva no reemplaza a la anterior de golpe:

- champion productivo,
- challenger en shadow mode,
- comparación cuantitativa,
- changelog auditable,
- owner y fecha,
- drift detection,
- rollback simple,
- no más de X% de SKU cambiando de modelo en una corrida,
- monitoreo post-promoción.

### Estado actual

`CLAUDE.md` ya establece una filosofía sana: lento pero correcto, una versión/un cambio, validar estado actual, analizar causa raíz, medir y promover solo si la medición fue satisfactoria (`CLAUDE.md:1-77`). También declara el pipeline completo y la validación post-pipeline (`CLAUDE.md:78-103`).

`CHANGELOG.md` muestra disciplina de trazabilidad, al menos para stock: versión activa, detalle de fixes, impacto esperado y razones de cambios (`CHANGELOG.md:1-260`).

El motor HM-SI también documenta reversión de cambios que no funcionaron, por ejemplo SBA en REG-7 y SMA(8), lo que es una buena práctica de aprendizaje controlado (`02_forecast/HM SI Forecast.py:148-190`).

### Gap explícito

#### G-CRÍTICO — No hay shadow mode documentado

Hoy el cambio parece ser manual/atómico: se reemplaza la lógica productiva después de revisar. El proceso ideal es correr challenger en paralelo sin afectar compra, comparar y recién ahí promover.

#### G-CRÍTICO — Drift se detecta tarde

Si el forecast empieza a sesgarse por categoría, proveedor o local, el sistema debería levantar alerta antes de que operación lo descubra por quiebres o sobrestock.

#### G-MEDIO — No hay owner/version card formal

Cada versión productiva debería tener:

- nombre exacto,
- fecha,
- owner,
- hipótesis,
- cambio único,
- backtest asociado,
- buckets impactados,
- decisión de promoción,
- plan de rollback.

#### G-BAJO — Falta límite de cambio masivo

Si una corrida cambia modelo o forecast en demasiados SKU de golpe, debería requerir revisión. No todo cambio matemáticamente válido es operacionalmente digerible.

### Implementación práctica sugerida

Crear una ficha por versión:

```text
02_forecast/releases/FWD_vX_YY.md
```

Estructura:

1. Problema.
2. Hipótesis.
3. Cambio único.
4. Archivos tocados.
5. Backtest.
6. Casos canónicos.
7. Riesgos.
8. Decisión: promover / shadow / rechazar.
9. Rollback.

---

## 6. Tabla resumen ejecutiva

| Etapa | Hoy | Norte estrella | Tamaño gap | Prioridad |
|---|---|---|---|---|
| 1. Data Foundation | POS + corrección precio/promos + HM-SI, pero sin contrato único de demanda limpia | Demand sensing + causal flags + stockout/outlier gate antes del motor | L | P1 |
| 2. Segmentación | ABCXYZ v19.4 con ADI/CV², lifecycle, REG-0..8 y GMROI | Segmentación dirige modelo, stock policy y fallback con histéresis | M/L | P1 |
| 3. Motor | HM-SI con SI, fair share, auto-model parcial, rescates y price correction externa | Best-fit por bucket, causal future events, prediction intervals y champion congelado | M/L | P2 |
| 4. Backtest | Backtest v11.1 con HM-SI vs old, REG/Z y multi-semana | Rolling-origin con gates formales, casos canónicos y service proxy | L | P1 |
| 5. Promoción | Versionado por headers/changelog, revisión humana | Champion/challenger, shadow mode, drift detection y rollback formal | L | P2 |

---

## 7. Próximos 3 movimientos sugeridos

### Movimiento 1 — Cerrar contrato de demanda limpia

**Bloque asociado:** 1. Data Foundation  
**Impacto:** alto  
**Esfuerzo:** medio  
**Razón:** evita que el motor aprenda de ventas contaminadas por quiebres, promos u outliers.

Entregable recomendado:

```text
02_forecast/CONTRATO_DEMANDA_LIMPIA.md
```

Debe definir campos, granularidad, flags causales, reglas de limpieza y qué consume HM-SI.

### Movimiento 2 — Formalizar gates de promoción del backtest

**Bloque asociado:** 4. Validación / Backtest  
**Impacto:** alto  
**Esfuerzo:** bajo/medio  
**Razón:** permite experimentar sin miedo. Un challenger puede probarse, perder y descartarse sin ensuciar producción.

Entregable recomendado:

```text
02_forecast/PROMOTION_GATE_FORECAST.md
```

Debe incluir criterios numéricos, buckets protegidos y casos canónicos.

### Movimiento 3 — Congelar champion real y correr challengers por bucket

**Bloque asociado:** 3. Motor + 5. Promoción  
**Impacto:** alto  
**Esfuerzo:** medio/alto  
**Razón:** hoy hay historia rica de versiones, pero antes de optimizar hay que saber exactamente contra qué versión se compite.

Orden práctico:

1. Confirmar versión real productiva.
2. Crear ficha release.
3. Definir 2 buckets malos.
4. Probar 1 challenger por bucket.
5. Promover solo por gate.

---

## 8. Test de utilidad del documento

Este documento sirve si permite responder, sin mirar código:

1. Qué hace el forecast actual.
2. Qué haría un proceso ideal.
3. Qué brechas son críticas.
4. Qué se debe optimizar primero.
5. Qué NO conviene tocar todavía.

La respuesta ejecutiva es clara: **no partir por tuning fino del motor**. Partir por demanda limpia, gates de backtest y congelamiento de champion. Después, sí, abrir bake-off por segmentos.
