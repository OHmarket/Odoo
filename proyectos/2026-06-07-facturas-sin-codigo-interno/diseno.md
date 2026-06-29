# Facturas de compra 2026 sin contraparte en código interno

## Problema
Líneas de factura de compra (DTE) cargadas en 2026 que NO quedaron vinculadas a
un producto interno (`product_id` vacío). El proveedor mandó descripción + su
código (`<CdgItem><TpoCodigo>INTERNA</TpoCodigo><VlrCodigo>…`), pero Odoo no
encontró un `product.product` con ese `default_code`.

## Decisión que se toma
Mapear / crear los productos faltantes para que el costo desde facturas
(proyecto costo-desde-facturas) deje de tener huecos.

## Hallazgos de diagnóstico (read-only XML-RPC)
- 9.619 líneas de producto (`display_type='product'`) sin `product_id` en 2026.
- 3.200 son producto real; 6.419 son ruido (flete, recargo, servicio, vacío).
- El código del proveedor del XML (`VlrCodigo`, TpoCodigo=INTERNA) está en el
  mismo espacio que el `default_code` de OH: cuando existe, Odoo auto-vincula;
  cuando no, queda sin match.
- `dte_product_string` en la línea está VACÍO en toda la base → el código del
  XML solo se recupera parseando el adjunto `DTE_*.xml` (ir.attachment).

## Causa (clasificación pedida)
- (a) `VlrCodigo` existe hoy como `default_code` → el código cambió o no se
  vinculó al ingresar la factura.
- (b) `VlrCodigo` NO existe → producto nunca creado / código eliminado.

## Salida
Una fila por **código de proveedor único** (`VlrCodigo`). Sin duplicados.
Columnas: codigo_proveedor, descripcion, causa (a/b), proveedores, n_lineas,
n_facturas, monto_total, factura_ejemplo. Formato Excel-CL (`;`, decimal `,`,
utf-8-sig).

## Límites
- Match línea↔XML por `name == NmbItem`. Si la descripción fue editada y no
  aparece en el XML, el código queda "NO_RECUPERABLE".
- Solo facturas con adjunto DTE XML.
