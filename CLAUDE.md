# CLAUDE.md

## Contexto de empresa (compartido con Hermes)

Leer tambien `D:\Desarrollo\OH Market\CONTEXTO.md`: mapa de las areas, regla
del .env maestro (unica fuente de credenciales, se propaga con sync_env.py),
modelo de ejecucion y punteros a la memoria destilada de otros asistentes.
No duplicar credenciales ni editar los .env de los subrepos a mano.

## Principio

**Lento pero correcto > rapido y con bugs acumulados.**

Un script que corre pero calcula mal es peor que no tener script: genera
decisiones comerciales basadas en data falsa.

**Hacer las cosas como los grandes.** Frente a cualquier problema de forecast,
inventario, demanda, margen o segmentacion, la pregunta de partida es: como lo
resuelve SAP, Oracle, Microsoft Dynamics, NetSuite, Manhattan Associates. Si
existe modelo canonico (Wilson EOQ, Croston, Holt-Winters, Syntetos-Boylan,
GMROI rolling, Bass, PLC, Fourier/RegARIMA, credibilidad de Buhlmann), se usa
ese y se cita. No inventamos formulas para problemas resueltos hace decadas.

Si el codigo se desvia del canon (por simplicidad, falta de datos o preferencia
de negocio), documentar la razon en el header y marcar **PROXY** en el
comentario de la funcion. Un proxy aceptado hoy es deuda tecnica visible, no
una formula nueva.

## Fase 0: Diseno

No escribir codigo hasta cerrar estas preguntas:

1. Que problema se quiere resolver o medir.
2. Que decision se tomara con el resultado.
3. Que pasa si el modelo se equivoca.
4. Cual es el modelo canonico (ver Principio) y donde esta documentado.
5. Que 2-4 enfoques posibles existen, con supuestos y limites.
6. Cual enfoque se elige, por que, y que se decide no hacer.
7. Que casos canonicos validaran el resultado.

Si no esta claro que estamos midiendo, detenerse y volver a disenar.

## Fase 1: Implementacion controlada

Ciclos pequenos:

1. **Validar estado actual:** que existe hoy, si corre, si los numeros son creibles.
2. **Analizar causa raiz:** confirmar con diagnostico o inspeccion, no con intuicion.
3. **Elegir un solo cambio:** una version corrige una hipotesis concreta.
4. **Arreglar minimo:** tocar solo lo necesario; mantener la version anterior como referencia.
5. **Medir:** comprobar el efecto esperado en casos conocidos.
6. **Promover:** solo si la medicion fue satisfactoria.

Despues de promover, volver a validar antes del siguiente cambio.

## Reglas No Negociables

- **Validar campos y unidades antes de codear:** confirmar nombre tecnico, tipo,
  unidad, signo, granularidad y dimension. No tapar dudas con `getattr(..., 0)`
  si el campo es critico.
- **Modelos Studio: `x_name` es required.** Studio lo crea NOT NULL en todo
  modelo `x_*`. Al hacer `create()` hay que setearlo o falla con
  `NotNullViolation` en el primer batch. Convencion: las claves logicas del
  registro. Ej: `'x_name': '%s:%s:%s' % (team_id, product_id, week_start)`.
- **Una version, un cambio:** no mezclar formula, fuente de datos, nombres y
  features en la misma version.
- **Preguntar o diagnosticar lo incierto:** no asumir modelos Studio, relaciones,
  fechas, snapshots, descuentos, costos ni signos.
- **No hacer "ya que estoy":** cada cambio extra aumenta el riesgo y hace mas
  dificil validar.
- **Reportar incertidumbre:** si el resultado depende de forecast, baseline o
  demanda estimada con bias alto, marcarlo como estimacion. No reportar montos
  absolutos como verdad dura sin rango o nivel de confianza.
- **Marcar contaminacion:** always-on, promos superpuestas, baseline sucio o
  pocas semanas con venta deben quedar visibles en el resultado.
- **Experimentos SIEMPRE en `proyectos/<YYYY-MM-DD>-<slug>/`, nunca en raiz.**
  Estructura: `diseno.md` (que/por que), `plan.md` (tareas y validacion),
  `*.py` (scripts, incluidos los DIAG read-only), `resultados/` (output).
  Al promover, el script productivo se mueve a su dominio (`02_forecast/`,
  `03_stock/`, ...) y la carpeta queda como historial.

## Modelo de ejecucion (arquitectura tecnica)

Entender esto antes de leer cualquier script:

- **Los scripts productivos NO se corren localmente.** Son `ir.actions.server`
  que se pegan en Odoo y corren bajo **safe_eval** con `env`, `cr`, `model`,
  `log` inyectados. No hay `import`, `fields`, `getattr` ni `open`. Antes de
  escribir o depurar uno, usar la skill `odoo-server-action-safe-eval` (gotchas:
  `datetime.date.today`, `.write()` en vez de `obj.attr=x`, retorno en `action`,
  sin closures/lambdas con variables libres).
- **Dos mundos en `shared/`:**
  - `*_reader.py`, `field_map.py`, `calendar_rules.py`, `combo_explosion.py`,
    `cost_reader.py`, `odoo_safe_eval_helpers.py` son **PLANTILLAS**, no
    importables desde safe_eval: se copian dentro del Server Action.
  - `odoo_xmlrpc.py` es lo opuesto: corre **DESDE FUERA** (tu PC) via XML-RPC,
    **read-only** (create/write/unlink lanzan `PermissionError`). Via para
    diagnostico, inspeccion de estructura y backtests. Credenciales en `.env`.
- **Odoo es PRODUCTIVO, no hay staging.** Cuidado con el COSTO de las queries:
  `search_count`/`read_group`, NO `search_read` masivo (cientos de miles de
  filas matan la cache del POS). Llenar modelos `x_*` de prueba esta OK; el
  riesgo es la query cara, no el dato.
- **Campos Studio dinamicos.** Prefijos `x_studio_*`, varian entre versiones
  (`detailed_type` vs `type`, `crm_team_id` vs `team_id`). Inspeccionar
  on-demand via `ir.model.fields` o `fields_get()`, nunca asumir.
- **No hay build / lint / test suite.** Sin `requirements.txt`, `pytest` ni CI.
  La prueba es el **backtest** (`02_forecast/OH Forecast Backtest.py`): forecast
  vs venta real POS. Validar = correr backtest y comparar WAPE/BIAS/FVA en casos
  canonicos. Para funciones puras, el patron es un par
  `<algo>_ref.py` + `test_<algo>.py` en el proyecto, que se corre con `python`
  y se copia literal dentro del Server Action.

## Estructura del repo y orden de ejecucion

Scripts agrupados por dominio funcional. Pipeline productivo:

```
1. 01_segmentacion/  OH Calculo ABCXYZ.py           (segmentacion base)
2. 02_forecast/      OH Forecast Base.py            (motor de demanda + buckets t0..t5)
3. 03_stock/         OH Analisis de Stock.py        (calcula compra/transfer)
4. 03_stock/         OH Generacion de Documentos.py (crea OC + traslados)
```


La version vigente de cada script esta en su propio header — no se duplica aqui
para que no quede desactualizada.

Cron / paralelo:

- `02_forecast/OH Factor Semanal.py` (curva estacional + factor de evento; MENSUAL)
- `03_stock/OH Quiebre de Stock.py` (quiebres por evidencia; insumo de de-censura)
- `05_finanzas/OH Presupuesto ventas.py` (recalc ayer + futuro)
- `02_forecast/OH Cambio de Precio.py` (snapshot de eventos -> Price Correccion)
- `04_analitica/` (Team, Categoria, SKU, Margen)
- `05_finanzas/OH Flujo de Caja.py` (proyeccion 90 dias)

Laboratorio: `02_forecast/analisis backtest/` — experimentos HM-SI (motor
legacy). Solo backtests; los proyectos en diseno NO viven aqui.

`_legacy/` es historial, no usar: `HM SI Forecast.py`, `OH Forecast Semanal.py`,
`OH SMA4 Forecast.py`, `OH Calib Factors.py`, `OH Cobertura ABCXYZ por Sala.py`,
`OH Normalizacion Demanda.py`, `OH Price Correccion.py` (archivado 2026-09-13:
no funciono bien; el motor nunca lo leyo y su modelo Studio no llego a existir). Backtests con model codes `hm_si_*` son del motor
viejo; `ses_*`/`sma6_*` del actual.

## Documentacion de gobierno

`governance/` tiene los contratos que un cambio debe respetar: `CHANGELOG.md`,
`VALIDATION_CHECKLIST.md`, `IMPACT_MATRIX.md`, `BACKTEST_SNAPSHOT_FORMAT.md`,
`HANDOFF_GUIDE.md`, `contracts/`. Consultar antes de promover.
`SISTEMA_REABASTECIMIENTO_COMPLETO.md` (raiz) es el documento maestro del
pipeline de reabastecimiento.

## Sincronizacion con GitHub

Repo local vinculado a `OHmarket/Odoo`. Cada cambio promovido a productivo debe
quedar reflejado en el remoto para que el historial sea auditable.

Flujo: Claude propone (opciones con su riesgo, no codigo de entrada) -> el
usuario lo pega en Odoo y lo corre -> **confirma explicitamente que corrio bien**
("corrio", "ok", "funciono") -> Claude muestra los comandos git y espera un
"dale" inequivoco -> Claude los ejecuta. Sin confirmacion clara en cualquiera de
los dos puntos, no se avanza.

**Cada version promovida lleva su entrada en `governance/CHANGELOG.md`. Sin
excepcion.** Auditado 2026-09-13: habia 15 versiones productivas de Analisis de
Stock documentadas solo en el header del .py, mas Price Correccion, Generacion
de Documentos y Quiebre de Stock completo. El header no reemplaza al CHANGELOG.

**Validar repo == produccion.** El .py del repo y el `python_code` del Server
Action deben coincidir; si divergen, el repo miente. Lectura read-only:

```python
o.search_read('ir.actions.server', [('state','=','code'), ('name','like','OH')], ['name','code'])
```

Ojo: hay Server Actions DUPLICADOS por script (motor + wrapper que el cron
invoca con `browse(<motor>).run()`). Comparar contra el MOTOR, no el wrapper.

Mensaje de commit: una linea corta del cambio **funcional**, no del archivo.
Ej: "forecast: corrige factor de precio en HM-SI", no "modifica HM_SI_v3_39.py".

Nota: `proyectos/` y `consultas/` estan en `.gitignore` (con whitelist puntual),
asi que el commit lleva los scripts productivos + `governance/CHANGELOG.md`.
