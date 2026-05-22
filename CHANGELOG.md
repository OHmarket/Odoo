# CHANGELOG — OH Análisis de Stock

Histórico detallado de versiones del script `3- OH Analisis de Stock.py`.
La versión activa y el resumen operativo (reglas vivas) están en el header
del propio script. Aquí queda el detalle de cada fix, snapshot de impacto y
métrica histórica para auditoría.

Convención: `vMAJOR.MINOR.PATCH`. La versión activa al momento de esta
limpieza es **v9.1.86**.

---

## v9.1.86 — Trazabilidad de OC pendientes

- Trazabilidad de OC y pickings que originan el stock_pedido.
  - **Antes**: `stock_pedido_compra` y `stock_pedido_transfer` mostraban solo
    la cantidad agregada, sin indicar qué documento(s) la disparaban. Revisar
    requería abrir Odoo y buscar manualmente las OC/pickings abiertos por SKU
    y locación.
  - **Ahora**: por cada fila (local-SKU o CD-SKU) se persiste un nuevo campo
    de texto `x_studio_oc_pendientes` con los nombres distintos de las
    OC (P00xxx) y pickings internos (CD/OUT/xxx) que tienen movimientos
    abiertos hacia la locación destino. Listado separado por coma, ordenado
    alfabéticamente.
- Fuente: queries adicionales en `_build_open_incoming_maps` que hacen JOIN a
  `purchase_order_line`/`purchase_order` y a `stock_picking`, sin alterar el
  cálculo de qty (queries originales sin cambio).
- Persistencia condicional: el campo solo se escribe si `x_analisis_de_stock`
  tiene definido `x_studio_oc_pendientes` en Studio. Crear el campo como
  Texto (Char/Text) antes de correr para verlo.
- Sin cambios en lógica de compra, target, MOQ, transferencias, GMROI,
  presupuesto mensual, phantom pool ni routing sala/CD. Solo agrega
  trazabilidad para revisión humana.

---

## v9.1.85 — CD usa period_weeks por SKU

- Reposición automática CD para `solo_bodega` ahora usa `period_weeks` por
  SKU (mismo horizonte que la sala) en lugar del `CD_TARGET_WEEKS` fijo (30/7).
  - **Antes (v9.1.81-v9.1.84)**: `target_cd = mu_red * CD_TARGET_WEEKS + safety`.
    `CD_TARGET_WEEKS = 30/7 ~ 4.286 sem` (un mes plano para todos). Problema:
    SKUs con periodicidad real <30d (entrega semanal/quincenal) atascaban
    capital y espacio en CD; SKUs con ciclos >30d quedaban sub-comprados
    respecto a la realidad del proveedor.
  - **Ahora**: `target_cd = mu_red * period_weeks_sku + safety`, con
    `period_weeks_sku` tomado del FWD del SKU (`fwd['lead_weeks']`, que en
    este proyecto es PERIODICIDAD de compra, no lead real). Si ningún record
    del SKU aporta `period_weeks > 0`, fallback a `PURCHASE_CYCLE_WEEKS` (1 sem),
    igual que sala.
- Mantiene `safety = Z * sigma_red * sqrt(period_weeks_sku)`. Mismo Z por
  ABCXYZ que sala/v9.1.82. Coherencia total de horizonte y safety entre
  sala `solo_bodega` y reposición CD->proveedor.
- Threshold de `cover_label_cd` ('bajo' vs 'normal') ahora compara contra
  `period_weeks_sku` (antes: `CD_TARGET_WEEKS`). `_smart_moq_box_or_wait`
  recibe `period_weeks_sku` como `target_weeks` (antes: `CD_TARGET_WEEKS`).
- `decision_reason` expone `cd_target_w` con el `period_weeks_sku` efectivo.
- Sin cambios en:
  - Routing sala vs CD (`COVER_WEEKS_THRESHOLD_FOR_CD` intacto).
  - `compra_cd` consolidada desde locales (ya usaba `period_weeks` por SKU
    via sala desde antes; sin doble cambio).
  - MOQ, phantom, transferencias, retornos, GMROI, presupuesto mensual.
- En esta limpieza (post v9.1.86) se eliminaron las constantes
  `CD_TARGET_WEEKS_DEFAULT` y `CD_TARGET_WEEKS` que quedaban como vestigio
  sin uso operativo.

---

## v9.1.84 — Techo financiero por proveedor

- Techo financiero (`financial_ceiling_sku`) ahora se calcula por proveedor.
  - **Antes (v9.1.83)**: `PAYMENT_DAYS=30` global → `FINANCIAL_CEILING_WEEKS=4.29`
    para todos los SKUs no `solo_bodega`. Mismo techo para BAT (pago a 15d)
    que para CCU (30d) que para Embonor (45d).
  - **Ahora**: lee `res.partner.property_supplier_payment_term_id` por
    proveedor y deriva días efectivos. Cada SKU usa el techo de su supplier.
- Helper nuevo `_payment_days_from_term(term, default_days)`:
  - Estructura observada en OH (Mayo 2026): 1 line por term con
    `value='percent'` y `nb_days=X`. NO usan `value='balance'`.
  - Estrategia: si hay line balance se usa; sino `max(nb_days)` de las lines.
  - Fallback al `PAYMENT_DAYS` global si no hay term o `nb_days=0`.
- Nuevo mapa `supplier_payment_days_map: {partner_id: days}` construido una
  sola vez al inicio leyendo todos los `partner_ids` relevantes (purchase_map,
  local_fwd_map, global_fwd_map). Lectura via ORM porque `property` es
  company-dependent (`ir.property`), no es columna SQL en `res_partner`.
- Impacto medido contra snapshot 2026-05-13:
  - BAT CHILE (cigarros, $40.7M/mes): techo 4.29 → 2.14 sem. Lucky Strike
    Purple Wild 20 y similares (caja deja 6-10 sem) caen del filtro post-MOQ.
    Reduce sobre-stock cigarros baja rotación.
  - CCU (30d): sin cambio.
  - EMBONOR (45d, $57M/mes): techo 4.29 → 6.43 sem. Permite 50% más stock en
    bebidas Coca-Cola si la rotación lo justifica.
  - PARAISO DEL SUR / PISQUERA PORTUGAL (60d): techo 4.29 → 8.57 sem.
  - Proveedores sin payment_term configurado (TABACOS AUSTRAL, DIP,
    SCORE ENERGY): fallback global 30d = sin cambio.
  - `solo_bodega`: techo independiente (`max(1.5, sala_H*2)`), sin cambio.
- Auditoría en `decision_reason`: `pay_days_supplier=X | fcw=Y` cuando el SKU
  no usa el techo global.
- Sin cambios operativos en: `MOQ_COVER_GUARD` (sigue 2.5), `_SAFETY_FACTOR`,
  política `compra_cd`, retornos, presupuesto mensual, phantom pool.

---

## v9.1.83 — Cobertura de caja + exclusión por categoría

- Reemplaza la regla v9.1.74 de `capital_atascado` (monto x tiempo) por una
  regla simple basada en COBERTURA DE CAJA y EXCLUSIÓN POR CATEGORÍA.
  Motivo: la fórmula `valor_caja * cobertura` no medía "capital" sino
  "capital x tiempo", inflando artificialmente productos chicos baratos de
  baja rotación (Halls $4.464 caja con cobertura 24 sem → "capital" $107K
  → CD), generando picking lento en CD para productos donde no aporta valor.
- Nueva regla:
  1. `solo_bodega=True` → CD (sin cambio, manda primero por negociación).
  2. Categoría padre in [Cafeteria, Cigarrillos y Tabacos, Congelados,
     Esenciales Hogar, Impulso, Snack y Coctel] → SALA siempre. Estas
     categorías son productos de picking físico complejo o muy baratos por
     unidad; consolidar en CD destruye eficiencia.
  3. `cobertura_caja = moq / demanda_semanal > 30 días (4.286 sem)` → CD.
     Si una sola caja deja >30 días de stock en sala, se consolida.
  4. Resto → SALA.
- Elimina `LOCAL_PURCHASE_MAX_CAPITAL_LOCK_CLP` (DEFAULT y CTX). Reemplazado
  por `COVER_WEEKS_THRESHOLD_FOR_CD` y `NO_CD_PARENT_CATEGORY_IDS`.
- `decision_reason` cambia de `moq_excede_capital_local` a
  `cobertura_caja_alta_cd` con `cobertura_w` y `umbral_w`.
- Las categorías excluidas se expanden recursivamente desde los 6 IDs padre
  via `product.category child_of`, llegando a 46 categorías en total. La lista
  de IDs padre es parametrizable por CTX.
- Impacto estimado vs v9.1.82:
  - SKUs forzados a CD por esta regla: 384 → ~256 (-33%).
  - 321 SKUs liberados de CD (Cigarrillos Lucky/Kent, galletas Trencito, Halls,
    chocolates, snacks).
  - 193 SKUs nuevos a CD (cervezas premium Austral/Kunstmann/Heineken/Coors,
    vinos tetra Clos de Pirque, Red Bull, Mixer Fentimans con cobertura 50-900 sem).
  - Solo Bebidas Alcohólicas (146 SKUs) y No Alcohólicas (110 SKUs) caen ahora
    en el check de cobertura.
- Sin cambios en CD→proveedor, MOQ, phantom, transferencias, GMROI,
  presupuesto mensual, retornos.

---

## v9.1.82 — Sala solo_bodega con safety stock

- Sala `solo_bodega`: agrega safety stock al target.
  - **Antes (v9.1.81)**: `target = mu * sala_target_weeks_base` (plano, sin
    safety). AX/AY=1.28, BX/BY/AZ=1.0, BZ/CY=0.84, CZ=0.52, default=1.0.
  - **Problema**: aunque CD estuviera lleno, locales con sigma alto quebraban
    antes del próximo ciclo de transferencia CD→sala (1 vez por semana).
    6 SKUs con CD sano + 29 locales en quiebre (Coctel Secreto Peruano,
    Jagermeister, Misiones Cab Sauv, Jack Daniels).
  - **Ahora**: misma regla que proveedor→CD pero con horizonte de 1 sem
    (frecuencia real de entrega CD→sala). `H = 1.0 + CD_DELIVERY_EXTRA_WEEKS`,
    `safety = Z * sigma * sqrt(H)` (Z por ABCXYZ, igual que v9.1.75),
    `target = mu * H + safety`. Mismo Z que CD/proveedor, mismo sigma local.
    Coherencia total.
- Sube `CD_DELIVERY_EXTRA_DAYS_DEFAULT` de 1.0 a 2.0 días (buffer logístico
  si camión se atrasa, e.g. martes en vez de lunes).
- Elimina `_SOLO_BODEGA_SALA_TARGET` y `_solo_bodega_target_weeks` (no usados).
- Elimina `sala_target_weeks_base` / `sala_target_weeks` del payload de
  auditoría (campo no persistido; se reemplaza con la fórmula nueva implícita
  en `safety_stock_units` y `reorder_target_weeks`).
- Sin cambios en CD→proveedor (v9.1.81), MOQ, phantom, `compra_cd`, retornos,
  transferencias, GMROI, presupuesto mensual.
- Impacto esperado:
  - Coctel Secreto Peruano Limón AY: target/local sube de ~1.5 u a ~3.0 u.
  - 29 locales en quiebre AY/AX/BX vuelven a target en próxima corrida.
  - ~6.000 u extra distribuidas en sala (traslado desde CD, no compra
    adicional al proveedor de inmediato).
  - CD se vacía, motor v9.1.81 dispara compras al proveedor para reponer.

---

## v9.1.81 — Reposición automática CD para solo_bodega

- Agrega reposición automática del CD para SKUs `solo_bodega` elegibles.
- Si locales necesitan el SKU, el CD está bajo target y no hay `compra_cd`
  previa por `capital_atascado`, la fila CD compra al proveedor.
- `target CD = mu_red * cd_target_weeks + z * sigma_red * sqrt(cd_target_weeks)`.
  Default `cd_target_weeks = 30/7`, configurable por contexto.
- Elegibles por defecto: AX, AY, AZ, BX, BY, BZ. CY/CZ quedan fuera.
- Excluye padres phantom y no toca `compra_sala`, transferencias, retorno,
  presupuesto mensual, GMROI ni lectura de OC abiertas.
- Auditoría en `decision_reason`: `solo_bodega_cd_replenish=1` con target,
  mu_red, sigma_red, safety y z usados.
- (Nota v9.1.85: este `cd_target_weeks` fijo se reemplazó por `period_weeks`
  por SKU.)

---

## v9.1.80 — Fix crítico lectura ABC/XYZ (variant vs template)

- FIX crítico de lectura ABC/XYZ. Bug originado al unificar scripts:
  `x_calculo_abc_xyz.x_studio_product_id` apunta a `product.product` (variant),
  pero el código guardaba `abc_map[variant_id]` mientras que el loop principal
  busca con `tmpl_id`. Solo coincidían SKUs donde por casualidad
  `variant_id == tmpl_id`.
- Resultado del bug: 1.069 de 1.969 SKUs locales (54%) terminaban como
  SIN_CLAS aunque tenían clasificación válida en `x_calculo_abc_xyz`. Entre
  ellos: Budweiser 9413 (rank 2 AX), Quilmes 9430 (rank 8 AX), Royal Guard
  451500 (rank 16 AY), Hielo Gourmet 1KG (rank 4 AX), Cusqueña 9958 (rank 36 AY).
- Efecto operativo: SKUs SIN_CLAS calculaban safety stock con `z=0.84`
  (default fallback) en lugar del z real (~2.05 para AX en v9.1.75).
  Target subdimensionado → más casos `box_or_wait_no_qty` → menos cajas
  pedidas. Operaciones reportaba esto como subcompra.
- Fix: convertir `variant_id → tmpl_id` en lectura ABC, idéntico al patrón
  que ya usaba el bloque FWD.
- Sin cambios en target/safety/policy/redondeo/MOQ/CD/phantom. Una versión,
  un cambio.

---

## v9.1.79 — Limpieza operativa box_or_wait_no_qty

- Si la política caja-o-esperar deja `reponer_ahora` sin `qty_a_pedir` ni
  transferencia, cambia la acción a `no_comprar_esta_semana`.
- Agrega auditoría `box_or_wait_no_qty` para explicar esos casos.
- Compra mensual estimada se fuerza a 0 en acciones que no deben generar caja:
  `congelar_compra`, `liquidar`, `retorno_a_cd`, `no_disponible_de_compra`,
  phantom child bloqueado y casos `box_or_wait_no_qty`.
- No cambia target, safety stock, `compra_cd`, transferencias ni pool pack/unidad.

---

## v9.1.78 — Pool pack/unidad: padre absorbe pool

- Corrige política de pools pack/unidad: la demanda de hijos/componentes se
  consolida hacia el padre phantom comprable en unidad equivalente de compra.
- El SKU padre compra para el pool completo:
  `mu_padre_total = mu_padre + mu_hijo / qty_per_parent`.
- Sigma del pool se combina por raíz de suma de cuadrados para no sobreestimar
  riesgo.
- Los hijos/componentes quedan visibles para análisis, pero bloqueados para
  compra, transferencia y presupuesto mensual.
- Cambia default `phantom_procurement_mode` a `buy_parent_block_children`.
- Cambia default `phantom_cost_source` a `product_first` para usar
  costo/proveedor del SKU padre.

---

## v9.1.77 — Fix sigma scaling para FWD local

- Fix crítico: `sigma_week` NO debe escalarse por `sqrt(share_demanda)` cuando
  la fuente es FWD LOCAL (`fwd_source='local'`).
  - **Antes**: `sigma_week = sigma_week * (share_demanda ** 0.5)` SIEMPRE.
  - **Problema**: el FWD local ya tiene sigma calculado a nivel sucursal por
    el estimador FWD v3.0.2. Subdividirlo por `share_demanda` lo reduce
    incorrectamente, como si fuera un sigma de la red completa.
- Ejemplo: Coñaripe Cristal 12x470cc
  - `sigma_local = 5.0` (FWD v3.0.2 local, correcto).
  - `share_demanda = 0.202` (13.33 / 65.96 red completa).
  - `sigma_bug = 5.0 * sqrt(0.202) = 2.248` (subdimensionado 55%).
  - `SS_bug = 2.05 * 2.248 = 4.61 u`.
  - `sigma_fix = 5.0` (sin escala, ya es local).
  - `SS_fix = 2.05 * 5.0 = 10.25 u`.
- El escalado `sqrt(share_demanda)` SOLO es correcto para FWD GLOBAL donde
  `sigma_week` representa la variabilidad de la red completa y debe
  prorratearse a nivel sucursal.
- Impacto esperado: todos los SKUs con `fwd_source='local'` que tenían
  `share_of_pool < 1.0` verán su `safety_stock` aumentado. SKUs con
  `share_of_pool=1.0` (mayoría) no se ven afectados.

---

## v9.1.76 — Auditoría sigma en decision_reason

- Agrega `sigma=` al motivo de decisión para auditoría.
- Antes el motivo mostraba `z=2.05` pero no el sigma que multiplicaba.
- Ahora muestra `z=2.05 | sigma=5.000` para verificar de dónde vino el valor.
- Diagnóstico que motivó el cambio: `sigma_week` en `x_forecast_weekly_data`
  viene del estimador FWD v3.0.2 (que calcula sobre semanas BASE, corregido
  por precio). Si el FWD no está actualizado cuando corre el `stock_analysis`,
  puede quedar un sigma viejo (ej: 2.248 en vez de 5.0 para Coñaripe Cristal).
- La fuente correcta de sigma sigue siendo `x_studio_sigma_week` del modelo
  `x_forecast_weekly_data` (escrito por Estimacion_Demanda_V3.0.2, NO por
  Calculo_ABCXYZ_V14_0.py).
- ORDEN DE EJECUCIÓN CRÍTICO: ABCXYZ → FWD v3.0.2 → Stock Analysis.

---

## v9.1.75 — Service level top movers

- Subida de service level en `_SAFETY_FACTOR` para top movers:
  - AX: Z 1.645 → 2.05 (~95% → ~98% service level).
  - AY: Z 1.645 → 2.05 (~95% → ~98% service level).
  - BX: Z 1.48 → 1.65 (~93% → ~95% service level).
  - Resto sin cambios (BY=1.28, AZ=1.04, BZ=0.84, CX=0.84, CY=0.52, CZ=0.0).
  - Default fallback se mantiene en 0.84.
- Justificación: en botillería el quiebre en SKUs AX/AY (cervezas top,
  bebidas, cigarros premium) es muy visible al cliente y genera pérdida de
  venta inmediata. Subir el service level del 95% al 98% en estos SKUs reduce
  ~3pp la probabilidad de stockout en quiebres normales.
- Impacto cuantificado contra xlsx vigente:
  - AX (2.861 líneas): +686 u SS, +CLP 2.2M.
  - AY (3.007 líneas): +609 u SS, +CLP 2.0M.
  - BX (573 líneas): +30 u SS, +CLP 0.1M.
  - TOTAL: +1.325 u SS, +CLP 4.3M en safety stock.
- El SS adicional se traduce en `qty_a_pedir` mayor en próximas corridas para
  AX/AY/BX, pero solo cuando el `stock_proyectado` esté bajo el target nuevo.
- Sin cambios operativos en lógica: `target_units` sigue calculándose con la
  misma fórmula, solo cambia el factor Z aplicado a `sigma_week`.

---

## v9.1.74 — Capital atascado (OBSOLETA, reemplazada por v9.1.83)

- Cambio de criterio en la regla que forzaba SKUs sin `solo_bodega` a
  `compra_cd` cuando el MOQ excedía un techo de semanas
  (`financial_ceiling_sku`).
- Nueva regla (en su momento): evalúa el CAPITAL ATASCADO esperado por compra.
  `capital_atascado = (moq * purchase_price_cash_unit) * (moq / demanda_semanal)`.
  Si ≤ `LOCAL_PURCHASE_MAX_CAPITAL_LOCK_CLP` → `compra_sala`; si excede →
  `compra_cd`.
- Default umbral: 75.000 CLP (configurable via context). Calibrado contra
  xlsx vigente: descentraliza ~308 líneas de 1.816.
- **Reemplazada en v9.1.83**: la fórmula `valor_caja * cobertura` no medía
  "capital" sino "capital x tiempo", inflando artificialmente productos chicos
  baratos de baja rotación.

---

## v9.1.73 — Fix double counting venta_bruta CD

- Fix bug introducido en v9.1.72: `venta_bruta_mensual_estimada` en filas CD
  generaba DOUBLE COUNTING (~CLP 75M sobreestimación).
- Cada línea local ya reporta su venta mensual completa
  (`demanda * 4.4 * pvp`). En v9.1.72 las filas CD también reportaban
  (`demanda_origen * 4.4 * pvp`), donde `demanda_origen_cd` es la suma de
  demandas de los locales en `compra_cd`. Esa suma es la MISMA demanda
  contada en los locales → duplicación.
- Caso ejemplo: Quilmes 710cc reportaba 14.9M de venta mensual (real: 7.6M).
- Fix: vuelve a `x_studio_venta_bruta_mensual_estimada = 0` en filas CD.
- `compra_mensual_estimada` en CD se MANTIENE (no tiene double counting porque
  v9.1.72 ya forzó `compra_mensual=0` en líneas locales con `buy_action=compra_cd`).
- Sin cambios operativos.

---

## v9.1.72 — Fix double counting compra_cd

- Fix 4: `compra_cd` se presupuesta UNA SOLA VEZ a nivel SKU-red, no por local.
- **Antes**: cada línea local con `buy_action='compra_cd'` calculaba su propio
  gap mensual contra su stock local, sumando ~CLP 18M de double counting.
- **Ahora**:
  - Líneas locales con `buy_action='compra_cd'` fuerzan `compra_mensual=0`.
  - La fila CD calcula `compra_mensual` a nivel red:
    - `demanda_mes_cd = demanda_origen_cd * MONTH_REMAINING_WEEKS`.
    - `stock_red_cd = stock_cd + stock_proyectado_origen_cd`.
    - `gap_residual = max(demanda_mes_cd - stock_red_cd - qty_a_pedir, 0)`.
    - `compra_mes = (qty_a_pedir + gap_residual) * precio`.
  - También `venta_bruta_mensual_estimada` se reporta en la fila CD para
    consistencia con el presupuesto (luego revertido en v9.1.73 por
    duplicación).
- Acumulación: se agrega `stock_proyectado_origen_cd` en `central_team_map`,
  sumando stock proyectado de los locales que originan cada `compra_cd`.
- Excluye `phantom_block_procurement` de la fila CD (los componentes ya
  presupuestan localmente).
- Impacto estimado: ~CLP 18M adicionales de reducción.
- Sin cambios operativos.

---

## v9.1.71 — Fix phantom block compra mensual

- Fix 3: `phantom_block_procurement` fuerza `compra_mensual = 0`.
- Los packs/kit phantom padre están bloqueados de generar OC operativa (la
  compra/reposición se hace por componentes). Sin embargo, la fórmula de
  presupuesto mensual seguía calculando (`demanda * remaining_weeks * costo`)
  sobre el SKU padre, lo que generaba doble conteo.
- Casos típicos: Lemon Stones, Morenita y otros packs.
- Impacto estimado: ~CLP 21M de reducción en presupuesto mensual total.
- Sin cambios operativos.

---

## v9.1.70 — Fix compra mensual: no_disponible + stock_pedido

- Fix 1: `buy_action='no_disponible_de_compra'` fuerza `compra_mensual = 0`.
  Estos productos están marcados para descatalogar (`purchase_ok=False` y no
  son `solo_bodega`). No se comprarán este mes ni nunca. Antes: ~CLP 2.6M de
  presupuesto fantasma. Ahora: 0.
- Fix 2: Descuenta `stock_pedido_total` (OC y transferencias abiertas) del
  cálculo del gap residual. Antes la fórmula usaba solo `stock_effective`, lo
  que ignoraba inventario en tránsito que llegará durante el mes.
- Aclaración clave del usuario: `x_studio_lead_weeks` NO es tiempo de entrega
  del proveedor, es PERIODICIDAD de compra. Los proveedores nacionales (CCU,
  Embonor, BAT) entregan en días; cualquier `stock_pedido` abierto
  razonablemente llegará dentro del mes en curso.
- Cambio: `stock_eff` → `stock_proyectado` en el cálculo del gap. Impacto
  chico hoy (~CLP 0.9M) pero conceptualmente correcto.
- Sin cambios operativos: `qty_a_pedir`, OC, transferencias, MOQ intactos.

---

## v9.1.69 — Compra mensual estimada → presupuesto operativo

- Reemplaza `compra_mensual_estimada` de "presupuesto financiero teórico" por
  "presupuesto operativo realista" para flujo de caja por proveedor.
- Nueva fórmula:
  - `compra_w1 = qty_a_pedir` (o aporte a `compra_cd`, o transfer si solo CD).
  - `demanda_mes = demanda_semanal * MONTH_REMAINING_WEEKS`.
  - `gap_residual = max(demanda_mes - stock_effective - compra_w1, 0)`.
  - `total_units = compra_w1 + gap_residual`.
  - `monto = total_units * purchase_price_cash_unit`.
- Refleja lo que el `plan_de_compra` realmente mandará a comprar durante el
  mes corriendo semanalmente, NO el presupuesto teórico con buffer de target.
- Quita `target_units` de la fórmula: no es presupuesto de stock objetivo,
  es presupuesto de caja operativa.
- Maneja 3 casos por `buy_action`:
  - `'compra_cd'`: usa `qty_compra_cd_consolidada_local` (el aporte real de
    la línea local a la compra CD que va al proveedor).
  - `'transferir_desde_cd'`: transferencia interna no cuenta como compra a
    proveedor; el campo descuenta el monto transferido.
  - Resto: usa `qty_a_pedir` directo.
- Resultado esperado: ~243M/mes vs 341M de v9.1.68.
- Uso: presupuesto de caja por proveedor (CCU, Embonor, BAT, etc).

---

## v9.1.67 — Compra mensual estimada (presupuesto teórico)

- Agrega `x_studio_compra_mensual_estimada`.
- Calcula monto estimado de compra desde `snapshot_date` hasta fin de mes:
  `max(demanda_semanal * semanas_restantes_mes + target_units - stock_proyectado, 0)`
  `* purchase_price_cash_unit`.
- Es un indicador financiero/proveedor; no modifica `qty_a_pedir`, OC,
  transferencias, MOQ, CD, phantom ni reglas operativas.
- Reemplazado por la fórmula operativa en v9.1.69.

---

## v9.1.66 — Bloqueo procurement phantom padre

- Bloquea abastecimiento documental del producto padre phantom.
- El pack/kit phantom queda visible para análisis, cobertura y valorización,
  pero NO genera `qty_a_pedir`, `compra_cd`, transferencia ni retorno.
- Evita duplicar OC con pack + componentes, caso Lemon Stones / Morenita.
- Default: `phantom_procurement_mode='block_parent'`.
- Auditoría: `phantom_procurement=blocked_parent`.

---

## v9.1.65 — Fix NameError purchase_row

- Fix NameError: reemplaza referencia obsoleta `purchase_row` por
  `purchase_map.get(tid)`.
- No cambia lógica de cálculo, compra, transferencia ni valorización phantom.

---

## v9.1.64 — Valorización phantom kits

- Corrige valoración de stock en productos tipo pack/kit phantom.
- **Antes**: si el SKU era `pool=phantom`,
  `stock_value_cash_physical/effective` se forzaba a 0.
- **Ahora**: se puede valorizar el pack virtual usando costo derivado de
  componentes o costo propio del producto, controlado por contexto.
- Defaults:
  - `value_phantom_kits=True`.
  - `phantom_cost_source='component_first'`.
- Auditoría en `decision_reason`:
  `pool=phantom | phantom_value=on | kit_cost_source=...`.

---

## v9.1.63 — Cigarros display_mult

- Corrige bajo impacto de v9.1.62: el target de cigarros estaba dominado por
  reserva de exhibición.
- Aplica `CIGARROS_DISPLAY_MULT` a la reserva de exhibición de Cigarros.
- Default `cigarros_display_mult = 0.0` para no sumar stock artificial de
  exhibición en cigarros.
- Mantiene intacta lógica de cajas/MOQ/documentos.

---

## v9.1.62 — Ajuste safety cigarros

- Agrega ajuste de estimación para categoría Cigarrillos y Tabacos / Cigarros.
- Categoría Cigarros = `product.category ID 1628`.
- Aplica multiplicador `CIGARROS_SAFETY_MULT=0.778` sobre el safety factor
  global.
- No modifica redondeo de cajas/MOQ, `compra_cd`, transferencias ni generación
  documental.
- El ajuste afecta solo:
  - `x_studio_safety_factor_used`.
  - `x_studio_safety_stock_units`.
  - `x_studio_target_units`.
  - `x_studio_reorder_target_weeks`.
  - `qty_neta_pre_central` antes de reglas de abastecimiento.
- Auditoría en `decision_reason`:
  `cat=cigarros | cigar_safety_mult=0.778`.

---

## v9.1.61 — Reserva exhibición + top cash safety

- Agrega reserva comercial de exhibición como % de demanda semanal.
- La reserva de exhibición se suma al target operativo, no a la demanda.
- En el redondeo MOQ crítico, la cobertura post-floor se evalúa sobre stock
  vendible: `stock_vendible = stock_post_compra - display_stock_units`.
- Sube factor de seguridad a 1.68 solo para SKU top caja/venta estimada
  dentro de AX/AY/BX/BY, manteniendo 1.48 para AX normal.
- Parámetros testeables por contexto: `display_stock_enabled`,
  `display_pct_top_cash`, `display_max_units`, `top_cash_weekly_min`,
  `top_cash_rank_max`, `top_cash_safety_factor`.

---

## v9.1.60 — MOQ crítico segmentado por ABCXYZ

- Segmenta la excepción crítica MOQ por ABCXYZ.
- La protección fuerte de ceil crítico aplica solo a AX, AY, AZ, BX, BY, BZ.
- CX, CY y CZ mantienen política caja-o-esperar para no inflar cola larga.
- `force_min` operacional se conserva para redondeos de filas CD sin cover
  crítico.

---

## v9.1.59 — MOQ ceil en críticos

- Corrige redondeo MOQ en productos críticos/sin_stock.
- Si el floor de caja deja cobertura post-compra menor a la cobertura mínima
  crítica o todavía bajo el target técnico, se usa ceil de caja.
- Mantiene política caja-o-esperar para SKU normales/bajos, evitando
  sobrecompra.

---

## v9.1.58 — Consolidación compra_cd antes de MOQ

- Corrige `compra_cd`: consolida primero la necesidad exacta por SKU entre
  locales y recién después aplica MOQ/caja una sola vez en Bodega Central.
- Evita el error tipo Norkoshe: sumar MOQ por local antes de consolidar.
- La pseudo-fila CD ahora acumula `venta_bruta_estimada` de las líneas locales
  que originan la `compra_cd`, para explicar compra vs venta por cobertura.

---

## v9.1.57 — Venta bruta semanal estimada

- Agrega estimación de venta bruta semanal por SKU/local:
  - `x_studio_pvp_bruto_sku = product.template.list_price`.
  - `x_studio_demanda_estimada_entera = demanda_semanal` redondeada a entero.
  - `x_studio_venta_bruta_estimada = pvp_bruto_sku * demanda_estimada_entera`.
- La estimación es de venta bruta teórica semanal, independiente de la compra
  sugerida.
- Si los campos no existen en Studio, `_filter_vals` los omite sin romper la
  corrida.

---

## v9.1.56 — Política caja-o-esperar global

- Aplica al motor completo una política de caja-o-esperar.
- No compra una caja solo por cerrar una brecha menor que el MOQ.
- El floor de MOQ es válido si deja el stock post-compra dentro del tamaño de
  caja respecto al target técnico; el ceil se usa solo si es necesario o si
  hay riesgo crítico.
- Mantiene `lead_weeks = 0.0` y `protection_weeks = period_weeks`.

---

## v9.1.55 — Sin lead extra en target

- Prueba sin días extra de lead en el target: `protection_weeks = period_weeks`.
- `x_studio_lead_weeks` queda en 0.0 para aislar el efecto del extra de llegada.
- Compra operativa usa redondeo MOQ al múltiplo más cercano, no ceil automático.
- Si el SKU está `sin_stock`/crítico, fuerza caja mínima para evitar quiebre.
- Objetivo: reducir sobreestimación por ciclos acumulados + redondeo a caja.

---

## v9.1.52 — Stock proyectado CD lee OC/transfers abiertas

- Corrige stock proyectado de Bodega Central: ahora la pseudo-sucursal CD lee
  compras y transferencias entrantes abiertas hacia el warehouse central.
- `x_studio_stock_pedido_compra` / `transfer` / `total` se escriben también
  en la fila CD.
- `x_studio_stock_proyectado` de CD = `stock_real_cd + stock_pedido_total_cd`.
- Conservador: la asignación de transferencias desde CD sigue usando solo
  stock físico, no stock entrante pendiente.
- Corrige lectura de `stock_move` abierto convirtiendo UoM del movimiento a
  UoM base del producto; evita subcontar OC creadas en cajas.

---

## v9.1.51 — Elimina VERANO_*

- Elimina efecto operativo/auditoría de bandas `VERANO_*` en este análisis:
  `VERANO_BAJO`, `VERANO_MEDIO` y `VERANO_ALTO` se normalizan a `BASE`.
- Elimina lectura/payload de `x_studio_ciclo_de_vida` desde FWD porque no se
  usa.
- Nota: si el `mu_week` ya viene inflado desde `x_forecast_weekly_data`, la
  corrección principal debe aplicarse también en el motor FWD.

---

## v9.1.50 — Retorno a CD via qty_transferir

- No usa/escribe `x_studio_qty_retorno_cd`. El retorno a CD se informa en
  `x_studio_qty_transferir` con `buy_action = retorno_a_cd`.
- Elimina escritura de campos no existentes/no usados:
  - `x_studio_financial_ceiling_weeks`.
  - `x_studio_protection_weeks`.
  - `x_studio_sala_target_weeks`.
  - `x_studio_cd_delivery_extra_weeks`.
- Limpia `decision_reason` de auditorías no persistidas: `prot_w`, `sala_w`,
  `cd_xtra_d`.

---

## v9.1.49 — MOQ en compra_cd consolidada

- Corrige `compra_cd` para que la cantidad consolidada en Bodega Central se
  redondee a múltiplos de MOQ/caja antes de generar documentos.
- `x_studio_qty_a_pedir_cajas` queda entero cuando la compra es por caja.
- Mantiene `qty_neta_pre_central` como necesidad técnica y redondea solo la
  cantidad operativa de compra/documento.

---

## v9.1.39 — GMROI y rotación por peso

- Agrega lectura de `costo_oh_unit` y `precio_neto_unit` desde
  `x_margen_por_producto_` (último registro por producto,
  `fecha_hasta DESC`).
- Calcula tres indicadores de priorización de abastecimiento con restricción
  de caja:
  - `x_studio_gmroi_reponer`: margen semanal / `valor_orden_compra`.
  - `x_studio_rotacion_por_peso`: `demanda_semanal / valor_orden_compra`
    (proxy sin margen).
  - `x_studio_margen_unit`: margen unitario real (`pvp_neto - costo_oh`).
- Persiste también campos de auditoría del origen del dato:
  - `x_studio_costo_oh_sku`: costo OH usado.
  - `x_studio_pvp_neto_sku`: pvp neto unitario.
- Fallback silencioso: si `x_margen_por_producto_` no tiene el SKU,
  `gmroi_reponer = 0.0` y `rotacion_por_peso` usa `purchase_price_cash_unit`
  como denominador.
- Tratamos `x_studio_lead_weeks` del FWD como período de reposición (no lead
  real). Estimamos lead real desde ese período:
  - ≤ 7 días → 1.5 días.
  - ≤ 15 días → 3.0 días.
  - > 15 días → 5.0 días.
- El target se calcula con horizonte de protección = período + lead estimado.
- `x_studio_lead_weeks` en `x_analisis_de_stock` pasa a guardar lead real
  estimado.
- Si existe el campo `x_studio_periodo_repos_weeks`, se persiste el período
  usado.
- (Nota v9.1.55+: posteriormente `lead_weeks` se fijó en 0.0 y
  `protection_weeks = period_weeks`.)

---

## v9.1.36 — purchase_ok como criterio base

- Usa `purchase_ok` de `product.template` como criterio base para
  `no_disponible_de_compra`.
- Jerarquía: `solo_bodega` manda primero; si `purchase_ok=False` y no es
  `solo_bodega` → `no_disponible`.
- Si un SKU queda marcado como no disponible de compra, se mantiene visible en
  el análisis pero se bloquea compra externa y transferencia desde CD.
- Usa `buy_action = no_disponible_de_compra` si la opción existe en Studio;
  si no existe, cae seguro a `no_comprar_esta_semana`.
- Mantiene full purge y la lógica vigente de `compra_cd` / transferencia.

---

## Notas históricas eliminadas en esta limpieza

Adicionalmente se eliminaron de los headers del script:

- **Bloque duplicado de v9.1.62**: existía un segundo encabezado
  `# Cambios v9.1.62:` redundante que repetía con menos detalle el primero.
- **Constantes muertas**: `CD_TARGET_WEEKS_DEFAULT`, `CD_TARGET_WEEKS` y
  `AUTO_DERIVE_CENTRAL_DEFAULT` no tenían uso operativo.
- **Función huérfana**: `_lead_time_from_period(period_weeks)` no era llamada
  desde ningún sitio (los cambios v9.1.55+ la dejaron sin consumidores).
- **Tags `# v9.1.XX:` inline** sin contexto funcional se reescribieron o
  borraron en favor de comentarios que explican el "por qué" del código.
