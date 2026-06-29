# Diseño v1.1 — Detector Error DTE: validación fina por línea + remediación estructurada

Fecha: 2026-06-18
Estado: Fase 0 (diseño) — en revisión
Extiende: `OH Detector Error DTE.py` v1.0 (Cron 1) y el modelo `x_error_dte`.
Reemplaza el intento paralelo `proyectos/2026-06-18-comparador-dte-lineas/` (obsoleto, se fusiona aquí).

## Norte

El detector v1.0 ya marca línea por línea, pero (a) deja fuera líneas sin
producto fuera de la cuenta ALM, (b) no distingue precio de cantidad, (c) no
detecta impuesto mal clasificado cuando el monto coincide, y (d) no deja el error
en forma que un fixer (Cron 2) pueda aplicar sin re-adivinar.

Esta iteración cierra esas brechas **manteniendo el modo solo-detección**. La
remediación automática es Fase 2; el detector solo debe dejar la fila
**accionable** (línea exacta + valor correcto).

## Decisión comercial

Habilita el fixer determinístico de Fase 2: cada fila de `x_error_dte` trae el
remedio exacto (qué línea, qué campo, qué valor). Sin eso, el fixer tendría que
re-parsear el DTE y volver a decidir, duplicando lógica y riesgo.

## Si se equivoca

Falso positivo = se revisa/corrige una línea que estaba bien (bajo costo, draft).
Falso negativo = se postea factura con precio/cantidad/impuesto malo → costo/WAC
sucio. Por eso el discriminador compara precio unitario y cantidad por separado,
no solo el total de la línea.

---

## Brechas y cambios

### Brecha 1 — Código no identificado, sin omitir ninguno (SOLO Mercadería)
**Hoy:** `codigo_no_vinculado` exige proveedor Mercadería **Y** línea en cuenta ALM
(`CUENTAS_ALM`) **Y** no flete. Una línea sin producto de proveedor Mercadería en
otra cuenta se omite.
**Cambio:** mantener el filtro `es_merc` (proveedor Mercadería), **quitar la
compuerta de cuenta ALM**. Marcar toda línea `display_type='product'` sin
`product_id` (o cuyo código DTE no matchea ningún producto) de un proveedor
Mercadería, salvo fletes/cargos (`FLETE`). La cuenta pasa a ser dato informativo.
**Alcance:** solo proveedores Mercadería (no-Mercadería NO se marca).

**Recomendación de producto (acelera el fix manual de Marco):** el detector
propone el candidato en `x_studio_product_id` (sugerencia, NO vínculo) según
escalera de confianza:

| Señal del DTE | Fuerza | Acción |
|---|---|---|
| `barcode`/EAN calza con un producto | alta | recomienda |
| Nombre `=ilike` con match único | media | recomienda |
| Nombre fuzzy o >1 candidato | baja | deja vacío + sugerencia "revisar" |

Si el producto existe pero su `default_code` ≠ código DTE, la sugerencia incluye
*"poblar default_code con \<cod\>"* (para que el próximo DTE calce solo). Marco
confirma/vincula a mano; el fixer **nunca** escribe `product_id`
([[feedback_vincular_product_id_pisa_precio]]).

### Brecha 2 — Impuesto mal clasificado con monto igual
**Hoy:** `diferencia_impuesto` compara el **monto** del ILA esperado vs Odoo; si
coinciden, no detecta nada.
**Caso real (FAC 007086 Brebajes):** línea declara `CodImpAdic=26` (cervezas),
Odoo aplicó tax con `l10n_cl_sii_code=25` (vinos) — ambos 20,5%, monto cuadra,
**clasificación mal**.
**Cambio:** nuevo tipo `impuesto_mal_clasificado`. Comparar el `CodImpAdic` del DTE
de la línea vs el `l10n_cl_sii_code` de los `tax_ids` adicionales de la línea Odoo
(excluyendo IVA, sii_code 14). Si difieren aunque el monto calce → fila.

### Brecha 3 — Sugerir el impuesto adecuado concreto
**Hoy:** sugerencia = tasa en texto.
**Cambio:** resolver el `account.tax` correcto por
`search([('l10n_cl_sii_code','=',CodImpAdic), ('type_tax_use','=','purchase')], limit=1)`
y guardarlo en el nuevo campo `x_studio_tax_sugerido`. Nombrarlo en la sugerencia.

### Brecha 4 — Precio: solo cuando es inequívoco (no se puede detectar UoM)
**Hallazgo (DIAG 2026-06-18, draft real):** NO existe forma confiable de distinguir
un error de cantidad de una diferencia de UoM/pack — el DTE viene en `DP`/`BU` y
Odoo en unidades, sin mapa. Lo único unit-agnóstico y confiable es el **subtotal
neto** (`MontoItem` vs `price_subtotal`). Además, sobre las 124 draft con líneas
alineadas **no apareció ni un caso de cantidad distinta**: todas las discrepancias
reales son de precio o de impuesto.

**Regla revisada (orden importa — el impuesto se valida ANTES):**

1. Primero la validación de impuesto (Brechas 2, 3, 5). Un tax mal puesto —en
   especial `price_include`— distorsiona el subtotal neto y se disfraza de precio.
2. Solo si el impuesto está correcto y el subtotal sigue sin calzar:

| `quantity` vs `QtyItem` | subtotal neto | tipo | ¿auto? |
|---|---|---|---|
| **igual** | distinto | `precio` (la dif es precio sí o sí) | sí → `valor_correcto = (MontoItem / QtyItem) × factor` |
| distinto | distinto | `linea_descuadrada` (ambiguo: UoM vs error real) | no, humano |
| distinto | calza (compensado) | `uom_no_cuadra` (representación pack; importa para costo unitario) | no, informativo |

**Líneas de flete (`_es_flete`: delivery, despacho, reparto, acarreo, recargo…):**
NO son producto, pero su descuadre de monto igual rompe el total vs DTE. Se
validan en monto pero se etiquetan **`flete_descuadrado`** (no `precio`),
**revisión humana, sin auto-fix** (el flete puede ser negociado/distinto; no se
digita a ciegas). Ej. FAC 007088 "Delivery Latas": Odoo $171.216 vs DTE $312.000.

\*El valor correcto sale de **`MontoItem` (neto de línea, ya con descuento)**, NO de
`PrcItem`: `PrcItem` es precio lista e ignora los descuentos del DTE
(`DescuentoMonto`/`DescuentoPct`). Validado en FAC 7468844 (PEUMO vino): PrcItem
18.710 pero MontoItem/Qty = 12.306 = neto real. La detección compara `MontoItem`
vs `price_subtotal` (neto, post-descuento); el `factor` aplica las tasas
`price_include`. Tolerancia: `max(2, 1% del valor)`. **No se crea un tipo
`cantidad` auto** (no se puede separar de UoM con confianza).

### Brecha 5 — Tabaco: IVA No Recuperable faltante/mal (regla por proveedor)
**Hallazgo (FAC 17263580 BAT, draft):** las líneas de cigarrillos están con el
impuesto roto — unas sin ningún tax (`tax_ids=[]`), otras con triple 19%
(`[2, 28, 17]`: IVA normal + IVA OC price_include + IVA No Recup.). Cabecera Odoo
tax $111.576 vs DTE $53.520 (el doble). El IVA de cigarrillos es **no recuperable**
(va a costo); el tax correcto es **id 17 "IVA Compra 19% No Recup."**.
**Regla de negocio (no derivable del DTE — todos los IVA comparten `sii_code=14`):**
para proveedores de la lista **tabaco** (default `PROV_TABACO = {'885029000'}` =
BAT CHILE 88502900-0, extensible a Chiletabacos), toda línea de producto debe
llevar **exactamente** el IVA No Recuperable (id 17), sin IVA normal (id 2) ni IVA
OC price_include (id 28).
**Detección:** si proveedor ∈ tabaco y `tax_ids` de la línea ≠ `{17}` →
`impuesto_mal_clasificado` con `x_studio_tax_sugerido = 17`.
**Alcance:** la lista de RUT tabaco es configurable en el header del Server Action.

---

## Cambios de modelo (`x_error_dte`)

Tres campos nuevos (Studio), para dejar la fila accionable por el fixer:

| Campo | Tipo | Para qué |
|---|---|---|
| `x_studio_line_id` | Many2one `account.move.line` | la línea exacta a corregir (hoy solo hay factura+codigo) |
| `x_studio_valor_correcto` | Float | valor objetivo: precio a digitar (`precio`) o cantidad (`cantidad`) |
| `x_studio_tax_sugerido` | Many2one `account.tax` | impuesto correcto (Brecha 2 y 3) |

Nuevos valores en `x_studio_tipo_error` (selección): `precio`,
`impuesto_mal_clasificado`, `flete_descuadrado`. NO se crea `cantidad` (no
separable de UoM). Se mantienen los existentes (`codigo_no_vinculado`,
`diferencia_impuesto`, `uom_no_cuadra`, `draft`, `sin_xml`, `duplicado`,
`linea_descuadrada`).

---

## Contrato detector → fixer (Fase 2, Cron 2)

El detector NO corrige. Deja la fila; el fixer la consume:

| tipo_error | acción del fixer | ¿auto? |
|---|---|---|
| `codigo_no_vinculado` | **nada** — solo se lista; Marco vincula el código a mano | no, manual (decisión Marco 2026-06-18) |
| `precio` | `line.write({'price_unit': x_studio_valor_correcto})` | sí |
| `uom_no_cuadra` | nada (pack ambiguo) | no, humano |
| `flete_descuadrado` | nada (flete negociado/distinto) | no, humano |
| `impuesto_mal_clasificado` / `diferencia_impuesto` | `line.write({'tax_ids': [(6,0,[x_studio_tax_sugerido])]})` | no, humano confirma (toca clasificación) |
| `linea_descuadrada` (fallback) | nada (ambiguo) | no, humano |

**Por qué el código no se auto-corrige:** Marco prefiere vincular los códigos a
mano (más fácil que mantener el matching) y así se evita el auto-write de
`product_id`, que recalcula `price_unit` desde el producto e infla el total
(incidente 2026-06-18, 14 facturas 3-24×; [[feedback_vincular_product_id_pisa_precio]]).
El único auto-fix es `precio` (write de `price_unit` sobre `draft`); el resto es
detección + revisión humana.

---

## Qué NO se hace (YAGNI)
- No auto-corregir (eso es Fase 2; esta iteración solo deja la fila accionable).
- No tocar `draft` / `duplicado` / `sin_xml`.
- No cambiar el matching por posición.
- No re-clasificar impuesto automático (humano confirma por categoría).

## Orden de promoción (una versión, un cambio)
El impuesto va ANTES que precio: `precio` no puede correr antes de descartar
problemas de impuesto (si no, mislabela cigarrillos/vinos como precio).

- **v1.1** — Brecha 1 (código no identificado sin gate de cuenta, solo Mercadería;
  **solo detección/lista** + recomendación de producto — Marco vincula a mano).
- **v1.2** — Brecha 2 (impuesto mal clasificado ILA por `sii_code`) + Brecha 3
  (`x_studio_tax_sugerido`) + Brecha 5 (tabaco BAT → IVA No Recuperable id 17).
- **v1.3** — Brecha 4 (`precio` con `valor = MontoItem/Qty × factor`; `flete_descuadrado`;
  `uom`/`linea_descuadrada`), corriendo DESPUÉS del impuesto.
- Campos de modelo (`x_studio_line_id`, `x_studio_valor_correcto`,
  `x_studio_tax_sugerido`) se crean antes de la versión que los usa.

## Casos canónicos de validación
1. **FAC 007086 Brebajes** (CodImpAdic 26, Odoo sii_code 25, 20,5%): v1.3 →
   `impuesto_mal_clasificado` con `x_studio_tax_sugerido` = tax cod 26.
2. **FAC 1810046 Hamburgo MOGUL** (código DTE 5131322 ≠ Odoo 5141234): la línea
   tiene producto pero código distinto → no es `codigo_no_vinculado`; queda como
   hallazgo de código (informativo, no rompe el cuadre).
3. **Línea Mercadería sin producto en cuenta no-ALM**: v1.1 → `codigo_no_vinculado`
   (hoy se omite). Solo se lista; Marco la vincula a mano.
4. **FAC 17263580 BAT (cigarrillos)**: líneas con `tax_ids=[]` o `[2,28,17]` →
   v1.3 `impuesto_mal_clasificado` con `x_studio_tax_sugerido = 17` (IVA No Recup.),
   NO `precio`. El tax-first evita que el descuadre de subtotal (por el price_include
   id 28) se etiquete como precio.
5. **Precio puro** (FAC 2377558, factor 1.0, qty calza, subtotal Odoo < DTE): v1.2 →
   `precio` con `valor_correcto = PrcItem`.
6. **Proveedor no-Mercadería con línea sin producto**: NO se marca (alcance B1).
