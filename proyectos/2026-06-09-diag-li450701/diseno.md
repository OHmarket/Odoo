# Diseño — Ciclo de vida transferir → compra_cd (gate = traslado done)

**Fecha:** 2026-06-09
**Origen:** diagnóstico LI45701 (Jagermeister 700cc) / proveedor 96568970-2.
**Estado:** Fase 0 — diseño. NO codear hasta cerrar este doc.

## 1. Problema

Las líneas de sala con necesidad de reposición cuando el CD tiene stock se
etiquetan `compra_cd` (supply=`central+buy`) y cargan `qty_transferir>0` con
`qty_a_pedir=0`. El generador de documentos:

- Envío a sala filtra `buy_action=='transferir_desde_cd'` → las salta.
- Compra CD filtra `compra_cd` con `qty_a_pedir_cajas>0` → las salta (su pedir=0; la
  compra está consolidada en la fila del CD, team 26).

**Resultado:** la cantidad a transferir nunca se materializa. Medido en toda la
tabla: **124 filas de sala orphan** (compra_cd, transfer>0, pedir=0) que logística
nunca recibe. 0 filas de sala con compra propia (el buy siempre se consolida en CD).

## 2. Decisión comercial

Logística filtra la tabla por `buy_action`. Necesita que cada fila accionable
corresponda a UN documento, con prioridad clara: **primero mover lo que el CD ya
tiene; comprar sólo lo que falta, y recién después de despachar.**

## 3. Qué pasa si el modelo se equivoca

- Sub-envío (lo actual): salas en quiebre con stock disponible en CD que nadie mueve.
  Pérdida de venta evitable + capital inmóvil en CD.
- Sobre-compra: si se compra antes de despachar, se reordena CD contra stock que en
  realidad ya está comprometido a salir → infla inventario muerto en CD.

## 4. Modelo canónico (ERPs)

DRP / reposición de centro de distribución, dos escalones (SAP min/max en el DC,
Oracle, Manhattan). Patrón estándar:

1. **Stock Transfer Order (STO)** DC→tienda: despacha lo disponible. Prioridad.
2. **Punto de reorden del DC** dispara la **Planned PO** al proveedor, *después* de
   que el DC se depleta por los despachos.

Son objetos/órdenes distintas, ligadas por pegging. OH ya separa por grano
(sala=traslado, CD=compra); falta el **secuenciamiento** (compra gateada al despacho).

## 5. Enfoque elegido — MODELO FINAL (confirmado Marco 2026-06-09)

**CD = consolidador pass-through. El buffer/safety vive en las salas, no en el CD.**

- **Salas que necesitan → `transferir_desde_cd`:** distribuye el stock del CD entre ellas
  (prioridad). transfer_total = min(Σ necesidad_salas, stock_CD).
- **id 26 (Bodega Central) → `compra_cd` por el diferencial:** una sola línea consolidada.

  ```
  compra_cd = max(0, Σ necesidad_salas − stock_CD − OC_pendiente_CD)   [redondeo MOQ]
  Σ necesidad_salas = Σ max(0, target_sala − stock_proy_sala)
  ```

- **Se ELIMINA el target forward propio del CD** (`solo_bodega_cd_replenish`, las 63,75 =
  demanda_red × período + safety). Era la fuente del doble conteo (dimensionaba el CD como
  si las salas tuvieran 0). El CD ya no se dimensiona aparte: solo tapa el diferencial.

**El gate=done queda satisfecho por construcción:** el diferencial es justo lo que el CD
NO puede transferir (demanda − stock_CD). Nunca se compra la porción que se está
transfiriendo, así que no hace falta esperar el `done` del traslado. La OC pendiente
(`stock_pedido_compra`) evita re-comprar en la corrida siguiente.

### Ejemplo numérico (modelo Marco)
demanda salas = 50, stock CD = 24 → distribuye 24 en salas, compra_cd (id 26) = 50−24 = **26**.

### LI45701 real hoy (red NO está corta)
Σ target salas ≈ 60, stock red (CD 24 + salas 37) ≈ 61 → diferencial ≈ **0**. Distribuye 24,
compra ~0. Los **36 que compra hoy son el over-buy del doble conteo** → este modelo lo corrige.

### Propiedad aceptada
CD queda lean (tiende a 0, sin buffer propio). El colchón está en las salas. Riesgo de lead
acotado porque las salas cargan su safety. Coherente con prioridad de no sangrar inventario.

---

## 5-bis. Enfoque elegido (versión previa, superada)

**Ciclo de vida en 2 fases por línea de sala, gate = traslado en estado `done`:**

- **Fase 1 `transferir_desde_cd` (prioridad):** `qty_transferir = min(necesidad_sala,
  stock_CD_disponible)`. Genera traslado CD→sala. La compra del faltante queda PENDIENTE
  (no se emite).
- **Gate:** mientras exista un traslado CD→sala para ese SKU en estado distinto de
  `done`/`cancel`, se **suprime** la contribución a `compra_cd`.
- **Fase 2 `compra_cd`:** una vez el traslado está `done`, el stock físico del CD baja
  → en la corrida diaria siguiente la `compra_cd` se libera para reponer el CD por el
  faltante / punto de reorden.

Se descarta **splitear en 2 filas**: crearía 124 filas-compra con qty=0 (la compra no
vive en la sala sino en el CD) → ruido + riesgo de doble conteo en consumidores de
valor/severidad. La separación correcta ya existe por grano; falta secuenciar.

## 6. Mecánica técnica (hallazgos confirmados)

- Stock físico disponible = `quantity − reserved_quantity` (Analisis:1043).
- Traslados nacen en **borrador**; `action_confirm` comentado (Generacion:608) → borrador
  NO reserva ni baja stock CD.
- `stock_pedido_transfer/compra` excluyen `draft` (Analisis:1263, 1318); se suman a
  `stock_proyectado` (Analisis:1920).
- CD recompra `qty_neta = target_cd − stock_proy_cd` (Analisis:2570) en la misma corrida.
- Consolidación CD del buy: itera recs de sala con `buy_action=='compra_cd'` y suma
  `qty_compra_cd` a `base['qty_a_pedir']` (Analisis:2494). El `transfer_qty` ya se guarda
  aparte (Analisis:2492).

**Implicación:** el gate=done NO sale solo. Hay que añadir una **supresión** de la
contribución `compra_cd` (Analisis ~2494) cuando para ese SKU×sala exista un traslado
CD→sala no-`done`. Detección barata: leer `stock.picking`/`stock.move` interno CD→sala
del producto con `state not in (done, cancel)` (mismo patrón que ya se usa en 1261-1263).
Persistir un campo de ciclo de vida por fila es OPCIONAL (se puede derivar del picking);
existe precedente en Forecast Base v1.6 si se quiere trazabilidad explícita.

## 7. Cambios (mínimos, una hipótesis)

**IMPORTANTE — el CD tiene DOS rutas de compra; ambas deben gatearse:**
- Ruta A: consolidación de `qty_compra_cd` de salas (línea ~2494).
- Ruta B: reorder automático `solo_bodega_cd_replenish` (línea ~2512+), que corre cuando
  la ruta A da 0. **El caso LI45701 compra por la ruta B** (cd_target − cd_stock = 36),
  no por la A. Gatear solo la 2494 NO difiere la compra de este SKU.

1. **Analisis — Fase 1 (relabel sala):** la sala con traslado pendiente queda
   `transferir_desde_cd`, no `compra_cd`. Su `transfer_qty` ya se guarda aparte (2492).
2. **Analisis — gate de compra (las DOS rutas):** suprimir la compra del CD para el SKU
   mientras exista un traslado CD→sala en estado distinto de `done`/`cancel`:
   - Ruta A (2494): no acumular `qty_compra_cd` de esa sala.
   - Ruta B (2512+): no disparar el reorder automático del CD mientras haya traslados
     pendientes de ese SKU. Cuando los traslados estén `done`, el CD queda depleto y la
     corrida siguiente repone (Fase 2).
3. **Generacion** — sin cambios si las salas quedan siempre `transferir_desde_cd`. (El
   one-liner stopgap deja de ser necesario con el relabel; evaluar si se aplica igual como
   red de seguridad durante la transición.)

### Antes / después de buy_action (LI45701, validado contra datos 2026-06-09)

| team | ANTES | DESPUÉS | cambio |
|---|---|---|---|
| 12,18,8,7 | transferir_desde_cd | transferir_desde_cd | = |
| 13, 6 | compra_cd (orphan, 7 un) | transferir_desde_cd | 🔁 ahora genera traslado |
| 10 | compra_cd (0/0) | compra_cd | = |
| 17 / 16,11,9,5 | congelar / no_comprar | igual | = |
| 26 (CD) | compra_cd (pedir 36) | espera; compra_cd tras done | 🔁 compra difiere a Fase 2 |

## 8. Casos de validación

- **Regresión orphan:** las 124 filas compra_cd/transfer>0/pedir=0 deben pasar a
  `transferir_desde_cd` y generar traslado. Cero orphans tras el cambio.
- **LI45701:** team 13 (4) y team 6 (3) → traslado generado esta corrida; la compra del
  CD (36) NO debe contener su porción hasta que esos traslados estén done.
- **Cobertura CD:** tras done de los traslados, la corrida siguiente repone el CD por el
  faltante real, sin doble pedir.
- **Sin regresión** en `retorno_a_cd`, `reponer_ahora` (no-solo_bodega), `no_comprar`.

## 9. Riesgos / abierto

- **Doble conteo CD target (latente, separado):** `target_cd` se dimensiona con demanda
  de red completa sin restar stock ya en salas (Analisis:2569). Al gatear la compra al
  done, el reorder podría sobre-comprar el CD. Validar en backtest; posible ajuste DRP
  (restar on-hand de salas) en proyecto aparte.
- **Latencia de 1 corrida** entre traslado-done y emisión de compra (cron diario).
  Aceptable para reposición CD; verificar que no genere quiebre en fast-movers AX.
- **Traslados que quedan en borrador para siempre** (logística no valida): la compra
  nunca se libera. Mitigación: alerta de traslados CD→sala añejos en borrador.
