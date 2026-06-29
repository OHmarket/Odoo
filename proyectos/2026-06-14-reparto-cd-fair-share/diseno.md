# Reparto de oportunidad del CD por fair-share de cobertura

Fecha: 2026-06-14

## Que problema resuelve
Vaciar el stock actual de la Bodega Central (CD) empujandolo a las salas en una
operacion puntual (one-shot), repartido para **igualar dias de cobertura** entre
salas, ponderado por la velocidad de venta de cada sala.

No cambia el motor de reabastecimiento productivo. No genera documentos. Read-only.

## Decision que toma
Cuanto despachar de cada SKU del CD hacia cada sala, ahora, como plan de salida
para revisar antes de mover stock.

## Que pasa si se equivoca
El plan es solo CSV para revision humana; no toca Odoo. El riesgo es proponer un
reparto sub-optimo, no operar mal. Marco revisa y promueve manualmente.

## Modelo canonico
Deployment / fair-share por **igualacion de dias de suministro** (equalize
days-of-supply), water-filling. Es la regla estandar de deployment en SAP APO /
Oracle cuando se reparte un pool escaso ponderado por demanda. Referencia:
fair-share allocation, regla "equal days of supply".

## Algoritmo (por SKU con stock CD = Q)
1. Salas elegibles: las que venden el SKU (d_i = mu_week > 0).
2. Cobertura actual c_i = s_i / d_i  (s_i = stock_effective de la sala).
3. Nivel comun de cobertura C*: resolver  N(C) = sum_i d_i * max(C - c_i, 0) = Q
   por biseccion (N es monotona creciente en C). SIN tope superior (vaciar 100%).
4. Asignacion real a_i = d_i * (C* - c_i)  si c_i < C*, si no 0.
5. Redondeo a unidades enteras + pase de residuo por *largest-remainder*
   (unidades sobrantes a la sala con mayor parte fraccionaria) -> sum a_i = Q exacto.

### Reglas de borde
- Sala ya por encima de C* -> recibe 0 (ya esta cubierta).
- Solo se reparte entre salas con d_i > 0.
- SKU que ninguna sala vende -> queda en CD (residual, marcado).
- Se excluyen como destino: CD (warehouse 15) y Camioneta (warehouse 17).

## Datos (read-only)
Fuente: x_analisis_de_stock (run actual del motor).
- Filtro: x_studio_stock_central > 0 (solo SKUs que el CD tiene hoy).
- Campos por fila (sala x SKU): product_id, warehouse_id, mu_week,
  stock_effective, stock_central.
- stock del CD por SKU = stock_central (mismo valor en todas las filas del tmpl).

## Salida (Excel-CL: sep ';', decimal ',', utf-8-sig)
- master.csv     : SKU x sala x qty_asignada (+ mu_week, stock_actual,
                   cover_actual, cover_post, pct_del_cd)
- por_sala/<sala>.csv : lista de despacho por sala (SKU + qty)
- residual.csv   : SKUs con stock CD que ninguna sala vende (se quedan en CD)
- resumen.csv    : unidades repartidas, % del CD vaciado, conteo por sala

## Supuestos
- stock_effective como stock actual de sala (incluye transito/pedidos pendientes;
  evita re-enviar lo que ya viene en camino).
- mu_week como velocidad de venta (ya des-estacionalizada por el motor).
- Unidades enteras (es un push de unidades existentes, no una compra; sin MOQ/caja).
