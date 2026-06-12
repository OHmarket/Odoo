# Reporte CD/INT — barcode en vez de Entregado + HS

## Problema
El Delivery Slip de las **transferencias internas** (CD/INT, lista previa al
envío a sala) muestra columnas `PRODUCTO | PEDIDO | ENTREGADO | CÓDIGO HS`.
- `ENTREGADO` siempre 0,00 en la lista previa (no aporta).
- `CÓDIGO HS` vale "B" en todos (campo `hs_code` sin uso real).
- Falta el **código de barra** (EAN) para pickear/escanear en bodega.

## Decisión
Formato nuevo SOLO para internas y SOLO en la lista previa (state != 'done'):

`PRODUCTO | CÓDIGO DE BARRA | PEDIDO`

- Saca `Entregado` y `Código HS`.
- Agrega `move.product_id.barcode` (número EAN puro).
- El resto de guías de entrega (salientes a cliente, etc.) y el reporte de
  picking ya validado quedan **sin tocar**.

## Origen de las columnas (Odoo core, NO editar)
- `stock.report_delivery_document` (vista 805): tabla `stock_move_table`
  (se usa cuando state != 'done'). Da Product / Ordered(PEDIDO) / Delivered(ENTREGADO).
- `stock_delivery.report_delivery_document2` (vista 2384, prio 16): agrega la
  columna `HS Code` (`move.product_id.hs_code`).

## Implementación
Una vista heredada nueva sobre `stock.report_delivery_document`, **prioridad 99**
(se aplica después de la 2384 para poder condicionar el HS). No usa xpath de
borrado: condiciona visibilidad por `picking_type_id.code` con `t-if`, así las
demás guías no cambian.

- Barcode: th/td nuevos con `t-if="...code == 'internal'"`, insertados después de Producto.
- Entregado: añade `t-if="...code != 'internal'"` al th_sm_quantity y a su celda.
- HS Code: cambia su `t-if` a `has_hs_code and ...code != 'internal'`.

Campo barcode validado: `product.product.barcode` trae el EAN puro
(ej. 7802107000937). Picking 4219179 = tipo "CD: Transferencias internas".

## Encabezado estilo Guía de Despacho (agregado 2026-06-11)
El header pobre del delivery slip (solo Orden + Fecha de envío) se reemplaza —solo
en internas— por el mismo encabezado de la Guía de Despacho SII:
Fecha / Cliente / VAT / GIRO / Domicilio / Orden + Chofer / Rut Chofer / Patente.

Reutiliza el template `l10n_cl_edi_stock.stock_informations` vía `t-call`
(NO se copia el HTML), que ya incluye Driver/Driver vat/Patent por la vista
heredada `l10n_cl_edi_stock_mods.report_delivery_guide_inherit` (2486). Así el
encabezado queda idéntico a la guía y sincronizado a futuro.

Datos validados en CD/INT (type 145):
- `partner_id` = la sala (ej. "OH! Market Limitada, Nueva Imperial") → siempre presente.
- `l10n_cl_driver` / `l10n_cl_patent` → presentes cuando se cargaron en el traslado
  (08735: Hugo Rojas / SDSX10); si no, esas líneas salen en blanco (t-if las protege).

Implementación: A1 oculta el bloque Order+ShippingDate en internas; A2 inyecta
`stock_informations` después del `<h2>` del nº de documento.

## Cómo aplicar en Odoo
Settings > Técnico > Vistas > Nueva:
- Vista heredada = `stock.report_delivery_document`
- Prioridad = 99
- Arquitectura = contenido de `view_cd_int_barcode.xml`
