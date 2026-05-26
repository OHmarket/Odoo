# AGENTS.md - Proceso OH Market

Documento de referencia para Codex y asistentes tecnicos. Leer antes de tocar
scripts productivos de OH Market.

## Principio

**Lento pero correcto > rapido y con bugs acumulados.**

Un script que corre pero calcula mal es peor que no tener script: genera
decisiones comerciales basadas en data falsa.

**Hacer las cosas como los grandes.** Frente a cualquier problema de forecast,
inventario, demanda, margen o segmentacion, la pregunta de partida es: como lo
resuelve SAP, Oracle, Microsoft Dynamics, NetSuite, Manhattan Associates. Si
ya existe modelo canonico aceptado por la industria (Wilson EOQ, Croston,
Holt-Winters, Syntetos-Boylan, GMROI rolling, Bass, PLC), se usa ese. No
inventamos formulas propias para problemas resueltos hace decadas.

## Fase 0: Diseno

No escribir codigo hasta cerrar estas preguntas:

1. Que problema se quiere resolver o medir.
2. Que decision se tomara con el resultado.
3. Que pasa si el modelo se equivoca.
4. Como lo resuelve la teoria establecida y los ERPs grandes (SAP, Oracle,
   Microsoft Dynamics, NetSuite, Manhattan Associates). Citar el modelo
   concreto (paper, libro, manual del ERP) antes de codear una formula
   propia. Si el problema esta resuelto hace 30 anos en literatura o ya
   esta implementado en un ERP grande, partir de ahi.
5. Que 2-4 enfoques posibles existen, con supuestos y limites.
6. Cual enfoque se elige, por que, y que se decide no hacer.
7. Que casos canonicos validaran el resultado.

Si no esta claro que estamos midiendo, detenerse y volver a disenar.

## Fase 1: Implementacion Controlada

Trabajar en ciclos pequenos:

1. **Validar estado actual:** que existe hoy, si corre, y si los numeros son
   creibles.
2. **Analizar causa raiz:** confirmar el problema con diagnostico o inspeccion,
   no con intuicion.
3. **Elegir un solo cambio:** una version debe corregir una hipotesis concreta.
4. **Arreglar minimo:** tocar solo lo necesario y mantener la version anterior
   como referencia.
5. **Medir:** comprobar que el cambio produjo el efecto esperado en casos
   conocidos.
6. **Promover:** solo usar la nueva version si la medicion fue satisfactoria.

Despues de promover, volver a validar antes del siguiente cambio.

## Reglas No Negociables

- **Teoria probada antes que invencion:** si existe modelo canonico para el
  problema (Wilson EOQ, Croston, Holt-Winters, Syntetos-Boylan, GMROI rolling,
  PLC, Bass), usarlo. No inventar formulas propias para problemas resueltos.
  Si el codigo se desvia del canon (por simplicidad, por falta de datos, por
  preferencia de negocio), documentar la razon en el header y marcar como
  PROXY en el comentario de la funcion. Un proxy aceptado hoy es deuda
  tecnica visible, no una formula nueva.
- **Validar campos y unidades antes de codear:** confirmar nombres tecnicos,
  tipo de campo, unidad, signo, granularidad y dimension. No tapar dudas con
  `getattr(..., 0)` si el campo es critico.
- **Modelos Studio personalizados: x_name es required.** Studio crea siempre el
  campo `x_name` (Descripcion) como NOT NULL en todo modelo `x_*`. Al hacer
  `create()` desde Server Action hay que setearlo explicitamente; sino, falla
  con `NotNullViolation` en el primer batch. Convencion: usar las claves
  logicas del registro como display name. Ej: `'x_name': '%s:%s:%s' %
  (team_id, product_id, week_start)`.
- **Una version, un cambio:** no mezclar formula, fuente de datos, nombres y
  features en una misma version.
- **Preguntar o diagnosticar lo incierto:** no asumir modelos Studio, relaciones,
  fechas, snapshots, descuentos, costos ni signos.
- **No hacer "ya que estoy":** cada cambio adicional aumenta el riesgo de bug y
  hace mas dificil validar.
- **Reportar incertidumbre:** si un resultado depende de forecast, baseline o
  demanda estimada con bias alto, marcarlo como estimacion. No reportar montos
  absolutos como verdad dura sin rango, disclaimer o nivel de confianza.
- **Marcar contaminacion:** always-on, promos superpuestas, baseline sucio o
  pocas semanas con venta deben quedar visibles en el resultado.

## Estructura del repo y orden de ejecucion

Los scripts estan agrupados por dominio funcional (sin numeracion en el nombre).
El orden de ejecucion del pipeline productivo es:

```
1. 01_segmentacion/  OH Calculo ABCXYZ.py          (segmentacion base)
2. 02_forecast/      OH Price Correccion.py        (ajusta factor por precio)
3. 02_forecast/      HM SI Forecast.py             (motor de demanda)
4. 03_stock/         OH Analisis de Stock.py       (calcula compra/transfer)
5. 03_stock/         OH Generacion de Documentos.py (crea OC + traslados)
```

Paralelo / cron diario:
- `03_stock/Stock Balance Daily.py` (reconstruye stock diario, incremental)
- `05_finanzas/OH Presupuesto ventas.py` (recalc ayer + futuro)

Validacion post-pipeline:
- `02_forecast/OH Forecast Backtest.py` (HM-SI vs venta real POS)

Capas paralelas (no bloquean el pipeline):
- `02_forecast/OH Cambio de Precio.py` (snapshot de eventos -> insumo de Price Correccion)
- `04_analitica/` (Team, Categoria, SKU, Margen)
- `05_finanzas/OH Flujo de Caja.py` (proyeccion 90 dias)

Laboratorio (solo backtests):
- `02_forecast/analisis backtest/` — ~60 experimentos HM-SI. El espejo
  productivo del motor esta en `2026-05-20/HM_SI_v3_39_productivo.py`.
  Esta carpeta es exclusiva para backtests; los proyectos en diseno NO
  viven aqui.

Proyectos en diseno:
- `proyectos/<YYYY-MM-DD>-<slug>/` — un proyecto = una carpeta. Contiene
  todos los artefactos del cambio: `diseno.md` (que/por que), `plan.md`
  (tareas y validacion), y los scripts en desarrollo (incluidos los DIAG
  read-only de Fase 1). Cuando el proyecto se promueve a productivo, el
  script productivo se mueve al dominio correspondiente (`02_forecast/`,
  `03_stock/`, etc.) y la carpeta del proyecto queda como historial.

Legacy:
- `_legacy/OH Forecast Semanal.py` (reemplazado por HM-SI Forecast el 2026-05-13).

## Checklist Rapido

Antes de tocar codigo:

- Entiendo la decision comercial que depende del cambio.
- El origen de datos esta validado: campos, unidades, signos y granularidad.
- Hay una sola hipotesis de mejora.
- Se como medir si funciono.
- Tengo casos canonicos para comparar.
- El resultado reportara incertidumbre si depende de demanda base o forecast.
- Si la solucion ya existe en literatura o en SAP/Oracle, la uso. Si me
  desvio, dejo PROXY documentado.

Si alguna respuesta es "no", detenerse y resolver eso primero.

## Sincronizacion con GitHub

El repo local `C:\Users\sanhu\Odoo` esta vinculado a `OHmarket/Odoo` en GitHub.
Cada cambio promovido a productivo debe quedar reflejado en el repo remoto para
que el historial sea auditable.

Flujo:

1. Claude propone un cambio de codigo.
2. Usuario lo acepta.
3. Usuario lo copia a Odoo (servidor o instancia) y lo ejecuta.
4. Usuario confirma explicitamente que corrio bien (ej: "corrio", "ok",
   "funciono", "subir"). Sin confirmacion explicita, no se sugiere subir.
5. Claude entrega los comandos git listos para pegar en la terminal:
   `git add <archivo>`, `git commit -m "<mensaje>"`, `git push`.
6. Usuario los ejecuta. Claude no corre estos comandos por su cuenta.

Mensaje de commit: una linea corta describiendo el cambio funcional (no el
nombre del archivo). Ej: "forecast: corrige factor de precio en HM-SI" en lugar
de "modifica HM_SI_v3_39_productivo.py".
