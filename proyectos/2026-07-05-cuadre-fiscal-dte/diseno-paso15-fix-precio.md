# Diseño — PASO 1.5: fix de precio pisado en OH Cuadre Fiscal DTE

**Fecha:** 2026-07-06
**Autor:** Marco + Claude
**Estado:** aprobado en brainstorming, pendiente escribir plan
**Proyecto padre:** `proyectos/2026-07-05-cuadre-fiscal-dte/` (SA productivo en `06_contabilidad/OH Cuadre Fiscal DTE.py` v0.5)

---

## 1. Problema y decisión comercial

**Hoy:** `OH Cuadre Fiscal DTE` (v0.5) aplica la posición fiscal (`action_update_fpos_values`)
a facturas de compra draft del mes y postea (draft→posted) solo las que quedan
LIMPIAS y cuadran al `MntTotal` del DTE dentro de `TOL=2`. Las que descuadran por
**precio pisado** (el `onchange` de `product_id` pisó `price_unit` con el precio
histórico del maestro al vincular el código) quedan gateadas como `NO cuadra` y se
quedan en draft para arreglo **manual** (con el SA del skill `corregir-facturas-dte`).

**Decisión que se quiere automatizar:** que el propio cuadre, tras la fpos, **arregle
el precio pisado** de las líneas donde el descuadre es inequívoco (la cantidad de
Odoo coincide con la del DTE), para que esas facturas también lleguen a `posted` sin
intervención manual. El backlog de precio pisado es la mayor fuente de facturas
"pegadas" del mes.

**Qué pasa si se equivoca:** el script **postea** (draft→posted, difícil de revertir).
Un fix de precio incorrecto contabilizaría una factura mal. Por eso el fix es
**conservador** (solo el caso inequívoco), **todo-o-nada** (solo si tras aplicarlo la
factura entera cuadra) y **desacoplado del posteo** (la factura arreglada NO se postea
en la misma corrida; se posteará en la siguiente, dejando un ciclo de auditoría).

## 2. Cómo lo resuelve la teoría / el codebase existente

No se inventa parseo ni fórmula: se **reutiliza** lo ya construido y probado en el repo.

- **`parse_items(xml)`** (de `OH Detector Error DTE.py`, función pura): DTE → lista de
  items en orden con `codigo / ean / qty / monto / imp` (CodImpAdic). Es el parseo de
  las líneas del DTE.
- **Fórmula del precio correcto** (rama `precio` de `clasificar_linea`, misma fuente):
  `price_unit = round((MontoItem / QtyItem) × factor, 2)`, donde
  `factor = 1 + Σ(amount/100)` de los impuestos **`price_include`** de la línea. Grosear
  por el factor es lo correcto cuando el ILA es `price_include=True`: el `price_unit`
  a digitar es mayor que el neto para que, tras descontar el impuesto incluido, el
  `price_subtotal` caiga en `MontoItem`. **Esto es más correcto que el `MontoItem/qty`
  simple del skill** (que ignora el factor y falla si hay tax `price_include`).
- **`x_error_dte`** (modelo Studio poblado por el detector, Cron 1): ya es la cola de
  clasificación por factura/línea. El detector deja cada fila **accionable**
  (`x_studio_line_id`, `x_studio_valor_correcto`, `x_studio_tipo_error`) — su header lo
  declara: *"deja cada fila accionable para el fixer de Fase 2"*. El PASO 1.5 **ES ese
  fixer**.

## 3. Alcance (enfoque A, aprobado)

**Incluye:**
- PASO 1.5: fix de precio pisado, todo-o-nada, sin postear en la misma corrida.
- La clasificación para revisión humana la sigue produciendo el **detector** (dueño
  único de `x_error_dte`); el cuadre solo se **abstiene de postear** lo no resuelto.
- **Nota interna en el chatter** de la factura cuando el cuadre no la puede cuadrar
  (`message_post`, subtype `mail.mt_note`), con el motivo + Δ, **deduplicada** para no
  spamear en cada corrida del cron. Ver §7.

**NO incluye (fuera de alcance de este cambio — una versión, un cambio):**
- **Anti-clog / skip-de-lote**: que las facturas ya marcadas no ocupen slot del lote
  en cada corrida (requiere change-detection sobre `write_date`). Queda para el paso
  siguiente (Tarea 8 del plan padre). Por ahora una no-resuelta reaparece en el lote y
  se re-evalúa (idempotente, sin daño: el savepoint hace rollback y no toca nada).
- **Residual de ILA / `uom_no_cuadra` / conteo de líneas distinto**: no se auto-arreglan;
  quedan en la cola humana del detector.
- **Escribir marcadores propios en `x_error_dte`** desde el cuadre (opción (b),
  descartada): el detector hace `unlink()` de todo cada corrida y borraría el marcador.

## 4. Arquitectura y flujo

Un solo SA safe_eval (el existente), con un PASO 1.5 nuevo entre PASO 1 y PASO 3.
Flujo por factura del lote:

```
gates de entrada:  es_tabaco -> SKIP ;  not sku_ok -> SKIP (falta_sku)
PASO 1  (fpos):    si |delta| > TOL and not DRY_RUN -> action_update_fpos_values()
                   recalcular delta (post-fpos)
PASO 1.5 (fix):    si |delta| > TOL:
                       items = parse_items(xml)
                       fixes = lineas con (alineada, qty==QtyItem, |sub-monto|>1, no flete)
                                -> price_unit = (monto/qty)*factor
                       si hay fixes:
                           SAVEPOINT
                           aplicar fixes (write price_unit, discount=0) ; flush
                           new_delta = amount_total - MntTotal
                           si |new_delta| <= TOL and not DRY_RUN:
                               RELEASE            -> fixed_now = True (queda draft)
                           si no:
                               ROLLBACK ; invalidate   (DRY siempre cae acá)
                       recalcular delta
PASO 3  (post):    si |delta| <= TOL and not fixed_now and limpia and not dup
                          and posteadas < MAX_POST and not DRY_RUN and DO_POST:
                       action_post()
                   si no y |delta| > TOL (no pudo cuadrar):
                       motivo = motivo_no_cuadra(prod_lines, items, delta)
                       nota = '[Cuadre DTE] no cuadra Δ=$%d vs DTE. Motivo: %s' % (delta, motivo)
                       si not DRY_RUN and nota != ultima_nota_cuadre(m):   # dedup
                           m.message_post(body=nota, subtype_xmlid='mail.mt_note')
                       log del motivo (queda draft = cola humana del detector)
```

**`fixed_now`** = `True` solo cuando el PASO 1.5 escribió `price_unit` en esta corrida
(rama RELEASE). Una factura que cuadró **solo con fpos** (sin fix de precio) sí se
postea esta corrida (comportamiento actual, bajo riesgo). Una arreglada por precio
espera a la corrida siguiente.

## 5. Mecanismo todo-o-nada (savepoint)

El "todo-o-nada" se implementa con un savepoint SQL vía `env.cr` (el SA ya usa
`env.cr.execute` para el advisory lock, así que el patrón está disponible en safe_eval):

```python
env.cr.execute("SAVEPOINT cuadre_fix")
for (line, pu) in fixes:
    line.write({'price_unit': pu, 'discount': 0.0})
env.flush_all()                              # empuja los writes a SQL
new_delta = round(m.amount_total - total_dte, 2)   # Odoo recomputa el total (motor de impuestos)
if abs(new_delta) <= TOL and not DRY_RUN:
    env.cr.execute("RELEASE SAVEPOINT cuadre_fix")
    fixed_now = True
else:
    env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_fix")
    m.invalidate_recordset()                 # resincroniza cache ORM con el rollback
```

**Por qué savepoint y no predicción en Python:** el total post-fix depende del motor de
impuestos de Odoo (price_include, redondeos por línea). Predecirlo en Python es frágil;
dejar que Odoo lo compute y solo confirmar si cuadró es exacto. `DRY_RUN` siempre hace
`ROLLBACK` → es un trial 100% seguro que muestra el `amount_total` resultante sin
persistir nada. Marco valida el comportamiento en `DRY_RUN=True` antes de aplicar.

**Notas de implementación (validar en DRY_RUN en Odoo):**
- `env.flush_all()` antes de leer `amount_total` para que el recompute refleje los writes.
- `m.invalidate_recordset()` tras el rollback para limpiar la cache ORM (si no, el ORM
  cree que escribió valores que la DB ya revirtió).
- El savepoint es anidado dentro de la transacción del SA; `RELEASE` la fusiona y el
  commit final del cron la persiste.

## 6. Cómo se computa y filtra el fix

**Alineación DTE↔Odoo:** por **posición** (igual que el detector). Líneas de producto
ordenadas por `(sequence, id)`; `items` en orden del XML. Guard:
`alineada = (len(prod_lines) == len(items) and len(items) > 0)`. Si no alinea → no se
arregla nada (va a cola humana).

**Una línea entra al fix SOLO si (todas):**
- `alineada`, y
- `abs(quantity - QtyItem) <= 0.001` (qty coincide con el DTE = precio pisado genuino), y
- `abs(price_subtotal - MontoItem) > 1.0` (subtotal desviado), y
- la línea **no es flete** (`_es_flete(name)` False).

→ `price_unit = round((MontoItem / QtyItem) * factor, 2)`, `discount = 0`, con `factor`
calculado sobre los `tax_ids` **post-fpos** de la línea.

**Excluidas del fix (no se tocan → cola humana del detector):**

| Caso | Detección | Tipo detector |
|---|---|---|
| Redondeo fracción de pack | `abs(quantity - QtyItem) > 0.001` | `uom_no_cuadra` / `linea_descuadrada` |
| Conteo de líneas distinto | `not alineada` | (sin item alineado) |
| Flete descuadrado | flete + `d_sub` | `flete_descuadrado` |
| Producto sin SKU | gate `sku_ok` (previo) | `codigo_no_vinculado` |

El **redondeo de fracción de pack se excluye a propósito**: con `decimal.precision` de
*Product Unit of Measure* = 2 decimales (config global de Odoo), Odoo guarda `0,166666`→
`0,17`; el `price_unit` de esas líneas **ya es el correcto del DTE** y el descuadre
(<$20, <0,1%) es puro ruido de redondeo. Desviar el precio para cuadrar el total al
peso corrompería el costo/WAC (trampa UoM). Solo se cuadra precio cuando `qty` coincide.

## 7. Clasificación para revisión humana (opción a)

El **detector (Cron 1)** es el dueño único de `x_error_dte`: cada corrida hace
`Err.search([]).unlink()` y recrea las filas clasificadas (`precio`, `uom_no_cuadra`,
`linea_descuadrada`, `codigo_no_vinculado`, `impuesto_mal_clasificado`, `draft`,
`duplicado`, `sin_xml`). El cuadre **no escribe** en `x_error_dte`.

La "cola de revisión humana" = filas pendientes de `x_error_dte` tras el fix+post. Tras
que el cuadre arregla y postea, la corrida siguiente del detector deja de crear las
filas resueltas (ya no descuadran) y mantiene las no resueltas. Es eventualmente
consistente y con un solo escritor por modelo (separación limpia).

**Nota interna en el chatter (complemento visible en la factura).** Cuando el cuadre
**no puede cuadrar** una factura (`|delta| > TOL` tras fpos+fix), postea una nota interna
en el chatter de esa factura con el motivo y el Δ, para que el humano que la abra sepa
por qué quedó pegada sin tener que leer `ir.logging`:

- Mecanismo: `m.message_post(body=nota, subtype_xmlid='mail.mt_note')` — **nota interna**
  (log note), no notifica seguidores, no manda mail. Va a `mail.message`, **no** es un
  campo stored en `account.move` (no dispara backfill que satura el POS).
- Formato: `[Cuadre DTE] no cuadra Δ=$<delta> vs DTE. Motivo: <motivo>` (ver taxonomía
  de motivos en §9).
- **Dedup (obligatorio, el cron corre cada 30 min):** antes de postear, comparar contra
  la última nota con prefijo `[Cuadre DTE]` de la factura (`ultima_nota_cuadre(m)`, lee
  `m.message_ids`). Si el body nuevo es idéntico → **no repostear** (nada cambió). Solo
  postea si cambió el motivo/Δ o no había nota. Así el chatter guarda un rastro de
  estado sin ruido.
- En `DRY_RUN` no postea (solo loguea la nota que pondría).
- No reemplaza a `x_error_dte`: la cola estructurada sigue siendo del detector; la nota
  es solo el aviso humano en la propia factura. El scope se acota a *"cuando no puede
  cuadrar"*; tabaco / `falta_sku` conservan su gate/log actual.

## 8. Restricciones (no negociables)

- **safe_eval:** sin `import` (`b64decode`/`datetime` inyectados); `.write()`/métodos,
  NO `obj.attr=x`; retorno en `action`. Ref skill `odoo-server-action-safe-eval`.
- **Nunca campo nuevo en `account.move`** (stored en tabla ~17M dispara backfill que
  satura el POS). El estado estructurado vive en `x_error_dte` (detector); la nota de
  aviso va a `mail.message` vía `message_post` (tabla aparte, sin columna en account.move).
- **El único write del cuadre sobre la factura**, además de la fpos, es `price_unit` +
  `discount=0` en las líneas elegibles, y la **nota interna** (`message_post`, solo
  cuando no cuadra, deduplicada). NO tocar `product_id` (re-vincularlo re-pisa el
  precio), NO tocar `quantity`.
- **Tabaco** (`PROV_TABACO`) y **`falta_sku`** siguen fuera del fix y del posteo.
- **Fix solo si `qty_odoo == QtyItem`**; redondeo de fracción de pack excluido.
- **Perillas:** `DRY_RUN=True` de arranque, `TOL=2.0`, `BATCH=10`, `MAX_POST=20`,
  `LOCK_KEY=99123055`. Arranca en DRY.
- **Ubicación:** desarrollo/tests en `proyectos/2026-07-05-cuadre-fiscal-dte/`; el SA
  productivo se re-promueve a `06_contabilidad/OH Cuadre Fiscal DTE.py` tras
  confirmación explícita de Marco de que corrió OK en Odoo (regla del repo).

## 9. Componentes y testeo

**Helpers puros nuevos** (en `helpers.py`, testeables con `python` sin Odoo):
- `price_fixes(odoo_lines, items) -> list[(line_id, pu_target)]`
  - `odoo_lines`: list de dicts `{id, name, quantity, price_subtotal, factor}` en orden.
  - `items`: salida de `parse_items`.
  - Aplica el filtro de §6 y devuelve los `(line_id, pu_target)`. `factor` se pasa ya
    calculado (para mantener la función pura, sin `env`).
- `motivo_no_cuadra(odoo_lines, items, delta) -> str` — clasifica **por qué** no cuadró,
  para el texto de la nota. Taxonomía (primer match gana):
  - `conteo_lineas` — `len(prod_lines) != len(items)` (no alineada).
  - `redondeo_uom` — todas las líneas aún descuadradas tienen `qty != QtyItem` (fracción
    de pack; precio ya correcto, descuadre es ruido de UoM).
  - `flete_descuadrado` — la línea descuadrada es flete.
  - `residuo` — cuadró líneas pero el total sigue >TOL por causa no identificada.
- `parse_items` ya existe (copiar del detector, ya testeado allá) — se re-testea aquí
  con un XML de muestra para tener la fuente de verdad local.

**Lo que depende de `env`** (no es helper puro; vive en el SA):
- `ultima_nota_cuadre(m) -> str` — recorre `m.message_ids`, devuelve el body de la nota
  más reciente con prefijo `[Cuadre DTE]` (o `''` si no hay). Sirve para el dedup.

**Tests** (`tests/test_helpers.py`, extender):
- `parse_items`: XML de muestra → items con qty/monto/codigo/imp correctos.
- `price_fixes`: casos canónicos (ver §10).
- `motivo_no_cuadra`: uno por rama de la taxonomía.

**Lo que depende de `env`** (savepoint, `action_update_fpos_values`, `action_post`,
`message_post`, `ultima_nota_cuadre`, `flush_all`, `invalidate_recordset`) se valida con
`DRY_RUN=True` corriendo el SA en Odoo.

## 10. Casos canónicos de validación

| Caso (folio real) | Situación | Resultado esperado del PASO 1.5 |
|---|---|---|
| Gin `179140148` / `179140149` | precio pisado, qty entera coincide | fix aplica, cuadra → RELEASE, `fixed_now`, queda draft; postea corrida siguiente |
| Vino `104036035` / Coca `104036085` | subconjunto de líneas pisadas, qty coincide | fix de esas líneas, cuadra → RELEASE |
| `104046634` | solo redondeo (qty `0,17` vs `0,166666`) | 0 líneas elegibles → sin fix → total no cuadra → NO posteada, cola humana (`uom_no_cuadra`) + **nota `[Cuadre DTE] ... Motivo: redondeo_uom`** |
| Factura ya cuadrada por fpos | delta ≤ TOL sin fix | sin fix; posteada esta corrida (fpos-only); sin nota |
| Precio pisado + residuo de redondeo >TOL | pisada + fracción de pack | fix de la pisada, pero total sigue >TOL → ROLLBACK → NO posteada + **nota Motivo: `redondeo_uom`** |
| No-cuadra dos corridas seguidas, sin cambios | mismo Δ/motivo | 2ª corrida: **no repostea la nota** (dedup) |
| DRY_RUN sobre cualquiera | — | siempre ROLLBACK; log muestra el `amount_total` y la nota que pondría; cero writes |

Validación = correr el SA en `DRY_RUN=True` sobre el lote del mes y cotejar el log
contra estos casos (los folios de julio ya conocidos). Recién con el DRY correcto se
pasa a `DRY_RUN=False` sobre un lote acotado.

## 11. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Fix incorrecto se postea | Desacople fix↔post (`fixed_now`): la arreglada NO se postea en su corrida; queda un ciclo auditables |
| `factor` mal (price_include) deja total off | Savepoint todo-o-nada: si no cuadra, rollback; nunca persiste un fix que no cuadró |
| Alineación posicional errada | Guard `alineada` (conteo exacto); si no alinea, no toca |
| Cache ORM stale tras rollback | `invalidate_recordset()` explícito |
| No-resuelta ocupa slot del lote cada corrida | Aceptado en enfoque A (idempotente); el skip-de-lote es el paso siguiente |
| Desviar precio por redondeo (trampa UoM) | Gate `qty == QtyItem`; fracción de pack excluida por diseño |
| Nota spamea el chatter cada 30 min | Dedup contra `ultima_nota_cuadre(m)`: solo postea si el motivo/Δ cambió |
| Nota agrega columna a account.move (backfill) | No: `message_post` escribe en `mail.message`, tabla aparte; account.move sin cambios |
