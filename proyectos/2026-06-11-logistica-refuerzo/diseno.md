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

## 7. Modelo de entrega: order-up-to a N días (base stock)

El selector de días NO es un filtro de urgencia: es el **target de cobertura**.
El usuario elige cuántos días EXTRA cubrir al generar el documento (campo Studio
`x_studio_dias_cobertura_refuerzo`, Selection '3'/'4'/'5'... o Integer). El doc
lleva cada SKU hasta esa cobertura enviando solo el faltante.

Política canónica (R,S) / order-up-to-level (base stock, Silver-Pyke-Peterson):
el nivel objetivo S se fija por la demanda sobre el horizonte elegido y se ordena
la brecha contra la posición de inventario.

Por SKU:

```
demanda_diaria  = x_studio_demanda_semanal / 7
objetivo_N      = demanda_diaria * N            (N = días seleccionados)
faltante        = objetivo_N - x_studio_stock_real   (físico en sala)
enviar          = min(max(0, faltante), x_studio_stock_central)  (tope CD)
qty             = round(enviar)  -> unidades enteras
```

Universo (decisiones cerradas con el usuario):
- **Alcance**: `x_studio_buy_action == 'transferir_desde_cd'` (los que el motor
  rutea CD→sala). No se filtra por `cover_label` ni `qty_transferir`: la cantidad
  se RECALCULA a N días.
- **Stock base del faltante**: `x_studio_stock_real` (físico vendible en sala).
- **Tope**: `x_studio_stock_central` (no se envía más de lo que hay en el CD).

Caso de uso: logística central el martes; refuerzo el viernes para cubrir
sáb/dom/lun → el operador selecciona esos días extra. Default si el campo está
vacío: 3 días (`REFUERZO_DAYS_DEFAULT`).

Se reportan en el resumen: `moves` creados, `ya_cubiertos` (faltante ≤ 0) y
`sin_cd` (faltante > 0 pero CD sin stock).

Pendiente Studio (fuera de código): crear `x_studio_dias_cobertura_refuerzo` en
el modelo del formulario y ponerlo como selector en la vista.

Abierto a revisar en práctica (dicho por el usuario): si conviene acotar además a
solo críticos, o ajustar el redondeo. El motor ya reusa demanda y stock, así que
cambiar el alcance es solo tocar el dominio.

Orden de armado: `severity desc, valor_reponer desc` (lo más urgente y de mayor
valor primero).

## 8. Formato de la guía (dirección, código, cantidad, descripción)

- **Dirección**: `picking.partner_id = warehouse_destino.partner_id`. Así la
  dirección de la sala destino imprime en la guía de traslado.
- **Código + descripción**: cada `stock.move` lleva el producto
  (`default_code` + `display_name`).
- **Cantidad**: `product_uom_qty = qty` (faltante a N días, topado por CD; ver §7).
- **Días de cobertura**: la cobertura ACTUAL (semanas×7) y el target N se inyectan
  en `name` y `description_picking` de cada `stock.move`, para que aparezcan en la
  pantalla del documento y en la guía impresa. Formato:
  `<producto> | Cob. actual: X.X d → refuerzo a N d (cover_label)`.

## 9. Casos canónicos de validación

1. SKU demanda 7 u/sem (1 u/día), stock sala 0, CD 50, N=4 →
   objetivo=4, faltante=4, enviar=min(4,50)=4. Move qty=4.
2. Mismo SKU pero stock sala 6 → objetivo 4 ≤ 6 → faltante ≤ 0 → no entra
   (cuenta en `ya_cubiertos`).
3. SKU demanda 14 u/sem (2 u/día), stock sala 0, CD 5, N=4 → objetivo=8,
   faltante=8, topado por CD → enviar=5. Move qty=5 (`sin_cd` no aplica).
4. SKU con `buy_action != transferir_desde_cd` → fuera del universo (no es
   CD→sala).
5. Re-ejecución con mismo snapshot → idempotente (no duplica picking).
6. Toda la sala ya cubre N días o CD vacío → sin moves; error con conteo
   `ya_cubiertos` / `sin_cd`.
