# Fair Share CD→salas — Regla C: igualar días de cobertura (run-out leveling)

Fecha: 2026-06-29
Script afectado: `03_stock/OH Analisis de Stock.py`
Versión: v9.3.1 → **v9.4.0**

## Fase 0

### 1. Qué problema se resuelve
Cuando el stock físico del CD (`central_stock_real_map[tmpl_id]`) NO alcanza
para cubrir Σ `need` de todas las salas, el reparto actual sirve **en cascada
por prioridad**: la sala #1 se lleva el 100% de su need, luego la #2, etc.,
hasta vaciar el CD. La cola de prioridad recibe **cero** y starvea semana a
semana (peor desempate por `team_id`).

### 2. Qué decisión se toma con el resultado
Cuántas unidades transfiere el CD a cada sala (`transfer_qty`) → genera los
pickings internos en `OH Generacion de Documentos.py`.

### 3. Qué pasa si el modelo se equivoca
Sub-reparto a una sala de baja cobertura = quiebre. Sobre-reparto: imposible
(cap por sala = `need`). Riesgo del cambio: redistribuir desde salas hoy
servidas primero hacia la cola → salas top reciben algo menos. Es el objetivo
(equidad de cobertura), no un bug.

### 4. Cómo lo resuelve la teoría / ERPs grandes
Problema canónico de DRP: **Fair Share Allocation** cuando ATD < demanda total.
**Regla elegida = C: igualar días de cobertura (run-out time leveling /
water-filling).** Es el estándar de facto en retail DC→tienda:
- SAP APO/SNP — *Fair Share Rule C* (distribución que iguala cobertura/target).
- Oracle RDF/AIP, Blue Yonder (JDA), Manhattan — *fair share* balanceando
  weeks/days of supply.

No inventamos fórmula: water-filling clásico (equalizar el nivel de cobertura
post-transfer, como llenar agua sobre un terreno: sube primero a las salas más
bajas hasta nivelarlas).

### 5. Enfoques posibles
- **A. Proporcional a demanda (μ_week)** — ignora stock actual. ✗
- **B. Proporcional al need (gap-a-target)** — incorpora stock, pero no iguala
  cobertura si las demandas difieren. ✗ (descartado tras revisión)
- **C. Igualar días de cobertura (water-filling)** — ✓ **ELEGIDO**. Lleva a
  todas las salas a la MISMA cobertura post-transfer (semanas), priorizando las
  de menor cobertura. Cap por sala = need (no pasa de su target).

### 6. Qué se elige y qué NO se hace
Algoritmo (helper `_runout_level_alloc`):
- Por sala: `s_i = stock_proyectado`, `d_i = max(demanda_semanal, DEMAND_FLOOR)`,
  `need_i = qty_neta_pre_central`, cobertura actual `c_i = s_i/d_i`, cobertura
  target `t_i = c_i + need_i/d_i`.
- **Búsqueda binaria** (60 iter) del nivel común `L` tal que
  `Σ clamp(d_i·(L − c_i), 0, need_i) = avail`. `transfer_i = d_i·(L − c_i)`
  capeado a `[0, need_i]`.
- Enteros por **largest-remainder** (Hamilton); el remanente se asigna por mayor
  resto, desempatando por prioridad (`_priority_tuple`, sala más crítica primero).
- NO se hace: piso de emergencia separado (híbrido) ni Rule A/B. Prioridad solo
  como desempate del remanente entero.
- Invariante: si `stock_CD ≥ Σ need` → cada sala recibe su need completo (sin
  cambio vs hoy). El nuevo reparto solo actúa bajo escasez.
- Base de cobertura = `stock_proyectado` (incluye inbound pendiente), coherente
  con la definición de `need = target_units − stock_proyectado`. Evita sobre-
  enviar a una sala que ya tiene un traslado en tránsito.
- Downstream intacto: `qty_net = need − transfer_qty`, modelo CD pass-through
  `solo_bodega` (compra_cd id 26), supply_source/buy_action_final sin cambios.

### 7. Casos canónicos de validación
Demanda d en u/sem; cobertura en semanas.
1. **Sin escasez**: stock_CD=100, need {30,20,10} → {30,20,10} (idéntico a hoy).
2. **Igualar cobertura**: 2 salas, d={10,10}, stock_proy={0,30}, target={50,50}
   → need={50,20}, c={0,3}. stock_CD=40. Water-fill: la sala vacía sube hasta
   alcanzar a la otra (c=3 → 30u), quedan 10u → ambas suben +0.5 sem → {35,5}.
   Post: cobertura {3.5, 3.5} **igualada**. Cascada vieja daba {40,0}.
3. **Cap por target**: stock_CD muy alto pero < Σneed; ninguna sala supera su
   need (transfer ≤ need_i) → cobertura no pasa del target.
4. **Remanente entero**: 3 salas need {7,7,7}, stock_CD=10 a cobertura igual →
   reparto entero suma 10, leftover va a la sala de mayor prioridad.
5. **CD vacío**: stock_CD=0 → todo 0; gap a `compra_cd` (id 26) sin cambio.
6. **Demanda ~0**: d→DEMAND_FLOOR; cobertura alta → no recibe bajo escasez (ok).

## Validación
Correr el pipeline en Odoo y filtrar SKUs con `stock_CD < Σ need_salas`.
Esperado: cobertura post-transfer ≈ igual entre salas que recibieron;
ninguna sala en 0 si el CD tiene stock; Σ transfers = stock_CD (± reserva).
Comparar contra el run anterior (cascada) que dejaba salas en 0.
