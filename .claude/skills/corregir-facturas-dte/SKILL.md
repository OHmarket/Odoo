---
name: corregir-facturas-dte
description: Use when reviewing or correcting Odoo purchase invoices (facturas de compra) against the attached DTE XML — mismatched totals (descuadre Odoo vs DTE), price_unit overwritten by the product master on code re-linking, wrong or duplicated ILA/Beb.Analc tax, "cuadrar factura al XML". Chilean l10n_cl, CCU y otros proveedores.
---

# Corregir Facturas DTE

## Overview

Al cargar facturas de compra, el proceso manual es: (1) vincular códigos no
encontrados, (2) actualizar posición fiscal, (3) cuadrar montos al XML. **El
paso 1 dispara el `onchange` de `product_id` que pisa `price_unit` con el precio
histórico del maestro** — por eso casi toda factura recién cargada descuadra
contra el DTE. Ver [[feedback-vincular-product-id-pisa-precio]].

Este skill diagnostica (read-only) y **genera un Server Action** para cuadrar.
No escribe en Odoo. **El paso 3 debe ser el último: re-vincular `product_id`
después de cuadrar vuelve a pisar el precio.**

## Cuándo usar

- "revisá/cuadrá la factura 179103055", "descuadre Odoo vs DTE", "revisá las FAC de CCU de hoy".
- Después de cargar facturas de compra con XML DTE adjunto, antes de contabilizar (`draft`).

## Qué corrige (dos causas, dos mecanismos)

| Problema | Detección | Corrección en el SA |
|---|---|---|
| **Precio pisado** | `price_subtotal` ≠ `MontoItem` **y `qty_odoo == QtyItem`** | `price_unit = MontoItem/qty_odoo` + `discount=0` |
| **ILA sin mapear** | línea con impuesto ORIGEN "Compra (OC)" (ids 26/28/31/33/34) | re-aplicar posición fiscal: `fp.map_tax(product.supplier_taxes_id)` |
| **Qty redondeada** (fracción de pack) | `qty_odoo != QtyItem` (DTE trae >2 decimales, ej `0,166666`) | **NINGUNA — se excluye.** Se reporta como warn, no entra al SA |

**Por qué se excluye la qty redondeada:** `decimal.precision` de *Product Unit of
Measure* = **2 decimales** (config global), así que Odoo guarda `0,166666`→`0,17`.
En esas líneas el `price_unit` **ya es el correcto del DTE**; el descuadre (siempre
diminuto, <$20 / <0,1%) es puro ruido de redondeo. Forzar `pu = MontoItem/qty_odoo`
para cuadrar el total al peso **desviaría el precio unitario correcto** y
contaminaría costo/WAC ([[project-costo-desde-facturas]], trampa UoM). Decisión de
negocio 2026-07-06: **dejar el descuadre de redondeo fuera**, no tocar el precio.
Solo se cuadra precio cuando `qty_odoo == QtyItem` (pisado genuino).

**El ILA NO se corrige con tabla inventada** — lo mapea la posición fiscal id 12
"Facturas de Compra" (mecanismo nativo de Odoo). Mapeo origen→destino:
`26→12` (ILA 31,5%), `31→11` (Vinos/cerveza 20,5%), `33→10` (18%), `34→9` (10%),
`28→2` (IVA). El impuesto correcto sale de `product.supplier_taxes_id`, no de una
regla propia. Cubre bebidas, vinos, cerveza, pisco/licores por igual.

El moves ya suele tener `fiscal_position_id=12` asignada, pero las líneas quedaron
con el impuesto origen sin re-mapear — el SA re-dispara `map_tax` por línea.
Cód `14` (IVA margen tabaco) Odoo lo calcula aparte, no está en el XML.

## Uso

```bash
# por folio(s):
python .claude/skills/corregir-facturas-dte/revisar_facturas_dte.py 179103055 179103059
# lote por proveedor + fecha (todas las draft de ese día):
python .claude/skills/corregir-facturas-dte/revisar_facturas_dte.py --proveedor CCU --fecha 2026-07-02
```

Imprime la tabla folio → Δtotal → líneas malas, y **emite un Server Action**
(`corregir_facturas_dte_SA.py`). Pegarlo en Odoo (`ir.actions.server`, modelo
`account.move`, safe_eval), correr con `DRY_RUN=True` para ver el diff, luego
`DRY_RUN=False` para aplicar. Por cada factura afectada el SA: (1) re-aplica la
posición fiscal a cada línea (`map_tax`) y (2) cuadra el precio. Salta moves
no-`draft` y **no toca `product_id`** (re-vincularlo vuelve a pisar el precio).

**Orden del proceso de carga:** vincular códigos → aplicar posición fiscal →
cuadrar precio. El SA hace los dos últimos juntos; correrlo *después* de vincular
todos los códigos (si re-vinculás un código después, vuelve a pisar el precio).

## Gotchas

- **Read-only.** El diagnóstico usa `shared/odoo_xmlrpc.py`; las escrituras van por
  el Server Action generado. No ampliar el cliente a write.
- **Query cara prohibida:** NO filtrar por `l10n_latam_document_number` (no-stored
  vía RPC, se ignora silencioso y barre `account.move` ~17M filas → satura el POS).
  Resolver por `name='FAC <folio>'` o `partner+fecha`, siempre con `limit`.
- **El SA safe_eval** sigue [[ref-odoo-server-action-oh]]: sin `import`, `.write()`
  (no `obj.attr=`), retorno en `action`. Setea `discount=0` (arregla también
  descuentos fantasma) y usa `fp.map_tax(product.supplier_taxes_id)` para el ILA.
- **Producto sin `supplier_taxes_id`** → el SA no toca sus impuestos (evita dejar la
  línea sin ILA); se ve en el DRY_RUN. El flete (sin producto) queda con solo IVA.
- **Correr DRY_RUN=True siempre primero** y leer el diff antes de aplicar. `map_tax`
  no se puede probar por XML-RPC (read-only); la prueba real es el DRY_RUN en Odoo.
- **Nunca cuadrar precio contra una qty redondeada.** Si `qty_odoo != QtyItem` la
  línea se excluye del fix (el precio ya está bien; el descuadre es redondeo de la
  UoM cap a 2 decimales). Desviar `pu` ahí es la trampa UoM. Una factura cuyo único
  descuadre es de redondeo sale `OK` y **no emite SA**.
- Casos de validación (lote CCU 2026-07-02): 49/53 facturas descuadraban; ramas
  cubiertas: bebida (ILA 10/18), vino/cerveza (20,5%), pisco/ron/licor (31,5%).
