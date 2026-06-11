# Logística de Refuerzo (stock crítico + quiebre) — Diseño

Fecha: 2026-06-11
Estado: en diseño (no productivo)

## 1. Qué problema se quiere resolver

El generador productivo `OH Generacion de Documentos.py` (gen_type
`envio_a_sala`) crea traslados CD → sala para **todo** SKU que el motor marcó
`buy_action = 'transferir_desde_cd'`, sin distinguir urgencia. Eso mezcla en un
mismo picking reposición rutinaria con SKUs que ya están en **quiebre** o
**cobertura crítica**.

Operaciones necesita un documento de **refuerzo**: un traslado CD → sala acotado
SOLO a los SKUs urgentes (quiebre + crítico), para despacharlo primero y rápido.

## 2. Qué decisión se toma con el resultado

Bodega Central arma y despacha un traslado de refuerzo a la sala con la lista
corta de SKUs urgentes. Es la "guía" física: dirección de la sala destino,
código, descripción y cantidad por SKU.

## 3. Qué pasa si el modelo se equivoca

- Falso urgente (incluye un SKU no tan crítico): se manda algo de más al refuerzo.
  Costo bajo, reversible (queda en borrador, revisión humana).
- Falso no-urgente (omite un SKU crítico): el SKU sigue en el `envio_a_sala`
  normal del mismo día. No se pierde reposición, solo no entra al despacho rápido.
- El documento queda en **Borrador** (modo adopción), igual que el resto del
  pipeline. Nada se confirma automático.

## 4. Cómo lo resuelve la teoría / ERPs grandes

Es el patrón clásico de **emergency / expedite replenishment** (SAP IM/EWM
"emergency stock transfer", Oracle "expedite"): cuando la cobertura cae bajo el
punto crítico, se gatilla un traslado prioritario desde el nodo que sí tiene
stock (el CD) en vez de esperar el ciclo normal. No se inventa fórmula: la
señal de criticidad ya la calcula el motor de stock vía `cover_label` /
`severity` (que a su vez sale de cover_weeks vs. umbrales). Aquí solo se
**filtra y empaqueta** esa señal en un documento.

## 5. Enfoques posibles

- **A. Nuevo gen_type en el generador productivo.** Requiere agregar el valor
  `refuerzo_sala` a la selección Studio `x_studio_generation_type` (cambio fuera
  de código) y tocar el archivo productivo. Mezcla cambio Studio + código.
- **B. Server Action standalone en proyectos/ (ELEGIDO).** Mismo patrón de
  `envio_a_sala` (lock, snapshot fresco, idempotencia, picking borrador) pero
  como acción aparte, sin tocar el productivo ni Studio. Reusa la infra leyendo
  el mismo registro-formulario (team_id). Testeable ya.
- **C. Reporte/export.** Descartado: el usuario quiere documento Odoo (picking),
  no solo lista.

## 6. Enfoque elegido y por qué

**B.** Es additivo, no toca el pipeline productivo en operación y respeta
"experimentos siempre en proyectos/" + "una versión, un cambio". Cuando se valide
en la instancia, se promueve a `03_stock/` (o se fusiona como gen_type en el
generador, ya como cambio productivo confirmado).

Qué se decide NO hacer:
- NO confirmar el picking (queda borrador, revisión humana).
- NO incluir compras a proveedor: el refuerzo es solo lo despachable HOY desde el
  CD (`transferir_desde_cd` con `qty_transferir > 0`). Un SKU crítico sin stock
  en CD necesita compra (otro flujo), no entra al refuerzo.
- NO tocar el cálculo de criticidad: se consume `cover_label` tal cual.
- La "pistola / restricción de códigos no incluidos en guía" es un proceso
  aparte, fuera de alcance.

## 7. Criterio de inclusión (definición de "refuerzo")

Una fila de `x_analisis_de_stock` entra al refuerzo si TODO se cumple:

- `x_studio_team_id == sucursal` del formulario.
- `x_studio_cover_label in ('sin_stock', 'critico')`  ← quiebre + crítico.
- `x_studio_buy_action == 'transferir_desde_cd'`       ← despachable desde CD.
- `x_studio_qty_transferir > 0`.

Orden de armado: `severity desc, valor_reponer desc` (lo más urgente y de mayor
valor primero).

## 8. Formato de la guía (dirección, código, cantidad, descripción)

- **Dirección**: `picking.partner_id = warehouse_destino.partner_id`. Así la
  dirección de la sala destino imprime en la guía de traslado.
- **Código + descripción**: cada `stock.move` lleva el producto
  (`default_code` + `display_name`).
- **Cantidad**: `product_uom_qty = x_studio_qty_transferir` (unidades).

## 9. Casos canónicos de validación

1. Sala con 3 SKUs en `sin_stock` + 2 en `critico` + 5 en `bajo`/`normal`
   → el picking de refuerzo trae 5 moves (los `bajo/normal` quedan fuera).
2. Sala sin SKUs críticos → mensaje "no hay líneas de refuerzo", sin picking.
3. SKU crítico pero `buy_action != transferir_desde_cd` (necesita compra)
   → NO entra al refuerzo (se documenta).
4. Re-ejecución con mismo snapshot → idempotente (no duplica picking).
