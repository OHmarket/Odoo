# Diseño — Registro automático de facturas de compra (touchless AP)

Fecha: 2026-06-17
Estado: Fase 0 (diseño) — en revisión
Slug: `2026-06-17-cuadre-facturas-xml-odoo`

**Norte:** que las facturas de compra (DTE) se registren en la contabilidad de
Odoo **automáticamente y sin error**, con las líneas vinculadas al código
correcto. Esto es *touchless AP / straight-through processing* (patrón
SAP/Oracle/Coupa). No se logra con un script de posteo más listo, sino
**eliminando las causas de error en origen** hasta que postear automático sea
seguro. La métrica del sistema es el **% touchless** (facturas que postean solas).

**Esta fase entrega el INSTRUMENTO (Fase 1, el monitor).** Las fases 2–3
(reproceso + auto-post) se diseñan/implementan después, con datos del monitor.

---

## 0. ARQUITECTURA FINAL (2026-06-18) — modelo `x_error_dte` + crons

Tras el trabajo del 2026-06-18, la arquitectura se concreta en **un modelo único
clasificado por tipo de error** + dos crons. Reemplaza la idea de escribir
`x_studio_reg_*` sobre `account.move` (§5.5) — se evita poner campos en
account.move (17M filas; ver [[feedback_stored_field_account_move_backfill]]).

### Modelo `x_error_dte` (cola de errores de registro)
Una fila por problema detectado. Filtrar/agrupar por `x_studio_tipo_error` da
cada "informe"; el conteo por tipo es la **métrica de convergencia (→ 0)**.

| Campo | Tipo |
|---|---|
| `x_name` | required — clave `factura:tipo:codigo` |
| `x_studio_factura` | Many2one account.move |
| `x_studio_proveedor` | Many2one res.partner |
| `x_studio_tipo_error` | Selección: codigo_no_vinculado, diferencia_impuesto, uom_no_cuadra, draft, sin_xml, duplicado (extensible) |
| `x_studio_codigo` | Char — código DTE proveedor (`VlrCodigo`), el problema |
| `x_studio_product_id` | **Many2one product.product** — producto a vincular (la solucion; vacio si ambiguo). Variable nativa del vinculo |
| `x_studio_monto_riesgo` | Monetario |
| `x_studio_sugerencia` | Char — accion legible |
| `x_studio_estado` | Selección: pendiente, auto_arreglado, revisado, descartado |
| `x_studio_fecha_check` | Fecha |

Granularidad: una fila por (factura × código) para `codigo_no_vinculado`; una por
factura para los de nivel-factura.

Reglas por tipo:
- `codigo_no_vinculado`: linea mercaderia (cuenta 210230) sin product_id. product_id
  sugerido por match unico default_code/EAN/nombre.
- `diferencia_impuesto`: total Odoo ≠ total DTE por impuesto adicional (ILA/tabaco)
  no sumado. sugerencia = CodImpAdic del DTE.
- `uom_no_cuadra`: valor cuadra (subtotal=MontoItem) PERO quantity Odoo ≠ QtyItem
  DTE (trampa pack/unidad). Revision, no auto. Ver [[project_costo_desde_facturas]].
- `draft` / `sin_xml` / `duplicado`: nivel factura.

### Cron 1 — Detector
Recorre las facturas de compra del período, aplica las reglas (cuenta 210230 sin
product_id; total Odoo ≠ total DTE; draft; sin XML; duplicado) y hace
upsert en `x_error_dte` (clave x_name). Pendientes que ya no aplican → cierra.

### Cron 2 — Remediación
Toma los `pendiente` auto-arreglables y los corrige; marca `auto_arreglado`.
- **SKU:** match ÚNICO por `default_code`/`EAN13` → vincula con MÉTODO SEGURO:
  `line.write({'product_id': pid, 'price_unit': pu_orig, 'quantity': qty_orig})`
  (re-asertar precio — vincular product_id PISA el price_unit, incidente
  2026-06-18; ver [[feedback_vincular_product_id_pisa_precio]]).
- **Impuesto:** NO auto-asigna (cambia el maestro). El detector deja la
  `sugerencia` (CodImpAdic del DTE) y un humano confirma por categoría.
- Lo ambiguo (match difuso, código nuevo) queda `pendiente` para humano.

Frecuencia: diario, off-peak, server-side (no XML-RPC). LOCK_KEY propio
([[ref_lock_keys]]).

### Verdad y matching
DTE adjunto en `l10n_cl_dte_file`; identidad `(partner.vat, tipo, folio)`
(el folio NO es unico entre proveedores). Totales/Detalle por string sobre el XML
decodificado con `b64decode` (CodImpAdic = ILA/tabaco; MontoItem = neto de linea
= verdad para restaurar precio).

---

## 1. Problema y decisión comercial

Hoy las facturas entran importando el XML del DTE; verificar que entraron sin
error y con SKU correcto es manual. Se quiere llegar a registro automático.

Decisión que habilita: postear con confianza y cerrar el mes; saber qué corregir
en el maestro de productos; y, a futuro, automatizar el posteo de las limpias.

Si se equivoca: falso negativo = se contabiliza/paga mal → por eso el cuadre de
montos usa el **XML del SII como verdad** y la completitud usa el **RCV del SII**,
no la confianza en que "el XML llegó".

## 2. Cómo lo resuelven los grandes

Touchless AP (SAP, Oracle, Coupa, Basware): ingesta → validación → matching →
auto-posteo → excepciones. En Chile la verdad fiscal es el **RCV del SII**
(Registro de Compras) y, por documento, el DTE (folio único, `Encabezado/Totales`,
detalle). Patrón interno reutilizado: **Monitor de error por impacto-$** del
forecast (rank por plata, no por conteo).

## 3. El proceso "sin error" (5 etapas) y dónde se arregla cada cosa

```
DTE del proveedor / SII
   │
   ▼
1. INGESTA + COMPLETITUD   ¿está en Odoo TODO lo del RCV del SII del mes?
   │                        verdad = archivo SII cargado (no el XML que llegó)
   ▼
2. VALIDACIÓN              cuadre aritmético/tributario (neto+IVA+ILA=total),
   │                        folio único, tipo válido, DTE aceptado (no reclamado)
   ▼
3. MATCHING               línea → SKU por código (determinista)
   │
   ▼
4. AUTO-POSTEO            si pasó TODO → action_post(); si no → excepción
   │
   ▼
5. EXCEPCIONES           solo lo que falló lo ve un humano
```

| Etapa | Causa de error hoy (medido 2026-06-17) | Dónde se arregla |
|---|---|---|
| 1. Completitud | 9.112 facturas sin XML → no se sabe si falta algo | conciliar contra archivo SII |
| 2. ILA / tributario | descuadre de impuesto ILA mal configurado | **maestro de productos** (config tributaria del SKU) |
| 3. Matching | 23% de líneas sin `product_id` (89.5K líneas) | **maestro de productos** (`default_code`/`barcode`) |
| 4. Posteo | 77 draft / $32M sin contabilizar | script de auto-post (Fase 3) |

**Clave:** etapas 2 y 3 son el mismo lever — **limpiar el maestro de productos**.
El monitor entrega las dos listas (códigos sin vínculo + ILA descuadrado); ambas
disparan corrección en el maestro.

## 4. Roadmap por fases

| Fase | Qué | Entregable | Estado |
|---|---|---|---|
| **1** | **Monitor de error** (detección): completitud vs SII + códigos sin vínculo + descuadre tributario + draft | Server Action que mide y deja veredicto por factura | **este diseño** |
| **2** | **Reproceso de vinculación** + corrección de maestro | Server Action que re-vincula líneas históricas tras limpiar maestro | diseño posterior |
| **3** | **Auto-post** de las "verdes" | script que cambia estado; excepciones a humano | diseño posterior |

Principio del repo (*lento pero correcto*): no se activa el auto-post hasta que el
monitor muestre el error de cada etapa cerca de cero.

### Viabilidad del reproceso (Fase 2) — verificado read-only 2026-06-17
- `account.move.line.product_id`: `readonly = False`, `states = None` → el campo no
  está declarado de solo-lectura (señal positiva).
- **No definitivo:** el bloqueo de moves *posted* se aplica en `write()`, no en el
  atributo. Confirmación dura = test empírico de 1 línea (Server Action mínima) en Fase 2.
- Universo: 89.306 líneas sin SKU están en facturas **posted** (132 draft) → la
  editabilidad en posted es el cuello del reproceso.

---

## 5. Diseño de la Fase 1 (el monitor)

Solo **detección**. Sin auto-fix, sin gate, sin auto-post.

### 5.1 Universo
`account.move` con `move_type = in_invoice`, `invoice_date` en el período (default:
mes en curso). Junio 2026 = 431 facturas (medido).

### 5.2 Completitud contra el SII (etapa 1)
Marco **carga el archivo del RCV del SII del mes** (CSV de compras: tipo, RUT
proveedor, folio, fecha, neto, IVA, total). El monitor lo cruza contra Odoo por
identidad `(RUT, tipo, folio)` y lista:
- **Falta en Odoo** (está en SII, no en Odoo) → 🔴 completitud.
- **Sobra en Odoo** (en Odoo, no en SII) → 🟡 revisar.
El archivo se sube como `ir.attachment`; la Server Action lo lee con `b64decode`
y lo parsea por líneas/`;` (string ops, sin `import csv`).

### 5.3 Fuente de verdad y matching por documento
- XML del DTE: `l10n_cl_dte_file` (m2o a `ir.attachment`; `datas` = base64 XML).
- Identidad = `(partner_id.vat, l10n_latam_document_type_id_code, l10n_latam_document_number)`.
- Totales del XML SII: `b64decode(att.datas)` + extracción de tags fijos por string
  (`MntNeto`, `IVA`, `MntExe`, `OtrosImp` (ILA), `MntTotal`). Son enteros simples.
- **PROXY/técnica:** extracción por string, no XML parser real (safe_eval sin
  `import`). Si falta un tag → "XML no parseable" (🔴), no se asume cuadre.
- El `Detalle` NO se parsea: "línea sin SKU" sale de `move.line.product_id` vacío.

### 5.4 Reglas de error (categoría → $ en riesgo)
| Categoría | Regla | $ en riesgo | Color |
|---|---|---|---|
| Completitud | en RCV SII y no en Odoo | monto del RCV | 🔴 |
| No contabilizado | `state = draft` | `amount_total` | 🟡 |
| Descuadre monto/ILA | \|MntTotal_xml − amount_total\| > $1 (ídem Neto/IVA/OtrosImp) | `amount_total` | 🔴 |
| Costo sin asignar | línea `display_type=product` con `product_id` vacío | monto de la(s) línea(s) | 🟡 |
| Sin XML / sin tipo | `l10n_cl_dte_file` vacío o sin `document_type` | `amount_total` | 🔴 |
| Duplicado | (RUT, tipo, folio) en >1 move | `amount_total` | 🔴 |
| OK | posted + cuadra + todas las líneas con SKU | 0 | 🟢 |

Una factura puede disparar varias reglas; color final = el más grave presente
(🔴 > 🟡 > 🟢).

### 5.5 Salida — veredicto por move (la cola vive en Odoo)
La Server Action escribe en cada `account.move` del período (campos Studio `x_*`,
a crear): `x_studio_reg_color`, `x_studio_reg_error` (categorías disparadas),
`x_studio_reg_monto_riesgo` (monetario), `x_studio_reg_accion` (sugerencia),
`x_studio_reg_fecha_check`. La **cola de reparación** = vista lista Studio filtrada
por color ≠ verde, ordenada por `x_studio_reg_monto_riesgo` desc. Rank por **monto
bruto** (PROXY; ponderar por costo/margen = mejora futura).

Para los **códigos de proveedor sin vínculo** (insumo de corrección del maestro):
el monitor agrega una salida `(RUT proveedor, código DTE, descripción, n_líneas,
monto)` — la lista que dispara la limpieza del maestro y habilita el reproceso (Fase 2).

### 5.6 Resumen del período
`display_notification` con conteo y $ por color, total en draft, % líneas sin SKU,
faltantes vs SII. Opcional: `ir.attachment` CSV es-CL descargable.

### 5.7 Arquitectura, safe_eval y costo
- `ir.actions.server` tipo *code*, safe_eval, pensado para **cron diario**. Sin
  `import`; usar `b64decode`, `datetime.date.today()`, `.write()` (no `obj.attr=x`),
  retorno en `action`. Ver skill `odoo-server-action-safe-eval` y [[ref_odoo_server_action_oh]].
- Barrido **server-side** (no XML-RPC). Período mensual chico (~431 moves) → leer
  `datas` y string-parsear es barato. Filtrar por `invoice_date`, no barrer 52K históricos.
- Solo `.write()` sobre moves existentes (no `create`). LOCK_KEY propio si se
  cronea — ver [[ref_lock_keys]].

---

## 6. Qué NO se hace en Fase 1 (YAGNI)
Auto-fix, gate al postear, auto-post, reproceso de vinculación, calce
OC↔recepción. Todo eso es Fase 2–3 o fuera de alcance.

## 7. Casos canónicos de validación (Fase 1)
1. **Factura con ILA** (CCU/Embonor): el cuadre suma `OtrosImp`; 🟢 si Odoo capturó
   el ILA, 🔴 si no (señal de tax mal configurado en el maestro).
2. **NORKOSHE con líneas sin código**: 🟡 "costo sin asignar" + aparece en la lista
   de códigos sin vínculo.
3. **Factura en draft** (de las 77 de junio): 🟡 "no contabilizado".
4. **Exenta (tipo 34)**: sin IVA; no debe marcar descuadre por IVA=0.
5. **Sin XML** (2 en junio): 🔴, no se intenta parsear.
6. **Falta vs SII**: un folio del RCV cargado que no existe en Odoo → 🔴 completitud.

## 8. Campos confirmados (DIAG 2026-06-17)
`l10n_cl_dte_file`, `l10n_latam_document_number`, `l10n_latam_document_type_id`
(+`_code`), `l10n_cl_dte_acceptation_status`, `l10n_cl_dte_status`, `l10n_cl_claim`,
`partner_id.vat`, `amount_untaxed/tax/total`, `state`, `invoice_line_ids.product_id`,
`account.move.line.display_type`, `product_id` (readonly=False).

Scripts DIAG read-only: `diag_localizacion_cl.py`, `diag_estado_registro.py`,
`diag_junio2026.py`, `diag_reproceso.py` (salidas en `resultados/`).
