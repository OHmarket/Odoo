# Envío del periodo + Fair Share — diseño

**Fecha:** 2026-06-28
**Estado:** Diseño validado por simulación (POC). No promovido.
**Toca:** `03_stock/OH Analisis de Stock.py` (nueva versión). Pass-through CD v9.2.0 se mantiene.

---

## 1. Problema y decisión comercial

**Problema:** reducir viajes / preparaciones de envío CD→sala sin perder servicio.

**Causa raíz (modelo actual v9.2.0):** la sala calcula un target de `period_weeks` y
**rellena hasta ese target cada semana**. Es un base-stock continuo: la sala queda
casi topada todo el tiempo → muchas transferencias chicas + capital alto parado.

**Decisión:** cambiar el patrón de reposición de **base-stock continuo** a
**periódico (s,S)**: cargar el periodo completo de una vez, dejar drenar sin
top-up, y recargar al cumplir el periodo. Sumar **fair-share DRP** cuando el CD
no alcanza para la cadena.

**Qué se decide con el resultado:** cuánto stock manda cada envío, cuándo se gatilla,
y cómo se reparte el CD escaso entre salas.

**Si el modelo se equivoca:** sub-envío → quiebre en sala; sobre-envío → capital
parado. El refuerzo crítico es la red de seguridad contra el sub-envío.

---

## 2. Canon (Fase 0 — nada inventado)

- **Revisión periódica order-up-to (s,S)** — Silver-Pyke-Peterson; es el "min-max"
  de SAP / período-lote de reposición.
- **Fair Share allocation (DRP)** — reparto por igualación de cobertura cuando el
  suministro central no cubre la demanda de los puntos. SAP APO / Oracle DRP.
- **Safety de revisión periódica:** `SS = z·σ·√(lead + ciclo_revisión)`.

---

## 3. Modelo

Premisa logística: **el camión sigue yendo semanal** (no se alarga la cadencia).
El envío es **manual**, se arma por sala (todos los SKU) y una ruta junta 2-3 salas.
El script **asiste**, no decide rutas.

### 3.1 Cuánto manda un envío (order-up-to S)
Por SKU:
```
S = period_weeks(SKU)·mu_week  +  safety
safety = z · σ · √(lead + ciclo_logístico)     # ciclo_logístico = 3d (cadencia real medida)
```
- `period_weeks(SKU)` = periodo de compra por producto. **Ya existe** en el modelo
  (`fwd['lead_weeks']`, fallback `PURCHASE_CYCLE_WEEKS`).
- **El safety cubre el intervalo de reacción (3d), NO el periodo.** Se midió en
  producción que el CD entrega a cada sala cada **2-3 días** (no semanal). Se
  compromete cadencia = **3d**. Lo único aleatorio a amortiguar es lo que sorprende
  antes del próximo camión (3d). Esto baja el safety fuerte vs el modelo viejo
  (√3 vs √periodo).

### 3.2 Cuándo se gatilla (nivel-based)
En cada review semanal, por SKU:
```
proyección_próxima_review = stock_sala − mu_día · días_hasta_próximo_camión
si proyección < safety  →  hay que reponer
```
- Si la venta salió como el forecast, el stock drena predecible y **no gatilla
  nada** hasta cumplir el periodo. (El "quedó a la mitad a la semana" es sano.)
- El reorden nivel-based se autoajusta al consumo real.

### 3.3 Envío del periodo vs refuerzo crítico
Cuando gatilla, dos casos:
- **Envío del periodo** (gatilla al cumplir el periodo / reorden normal):
  rellena a `S` completo. Es el bloque grande.
- **Refuerzo crítico** (gatilla antes, porque la venta se calentó y perforó el
  safety): manda **lo justo para llegar al próximo camión**, no `S`. Viaje de
  excepción, se cuela en la próxima ruta.

### 3.4 Fair-share cuando el CD no alcanza — alcance CADENA
Por SKU, si `Σ necesidad_salas > stock_CD`:
- **Igualar cobertura (water-filling):** subir a todas las salas al mismo nivel de
  cobertura (días de venta) hasta agotar el CD, **contando el stock que cada sala
  ya tiene**, capado al target `S`.
- Alcance = **toda la cadena**, no la ruta del día (si no, la primera ruta vacía
  el CD y las siguientes quedan sin nada).
- Reemplaza la prioridad greedy actual (1..6).

### 3.5 Compra del CD
Pass-through v9.2.0 **sin cambios**: el CD compra el diferencial consolidado
(`compra_cd` en la fila id 26 = `max(0, Σ necesidad_salas − stock_CD)`).

---

## 4. Qué NO se hace (descartado en el diseño)

- **NO** joint-replenishment con cadencia larga por sala: el camión sigue semanal;
  el ahorro viene del patrón de reposición, no de espaciar el camión.
- **NO** reparto proporcional a necesidad: ignora el stock existente de cada sala
  (la sala que ya tenía stock termina sobre-cubierta). Igualar cobertura es mejor.
- **NO** greedy por prioridad: concentra el quiebre en las últimas salas.
- **NO** safety sobre el periodo completo: sobre-estima el colchón (el camión
  semanal ya da la reacción).

---

## 5. Validación (POC, read-only sobre cervezas reales — 93 días)

**Cadencia real medida (stock.picking type 145, 90d):** el CD entrega a cada sala
cada **2-3 días** (p90 3-7d), no semanal. 519 viajes/90d en la cadena. El modelo
"actual" simulado da 29,6 envíos/SKU = calza con las ~30 entregas/sala medidas →
**confirma que la cadencia 2-3d la genera el top-up cada visita** (waste corregible,
no restricción de ruta). Cadencia comprometida post-cambio = **3d**.

Con `period=15d, review=3d, z=1,28`:

| Métrica | Actual (topa cada visita, ~3d) | Nuevo (envío del periodo) | Δ |
|---|---|---|---|
| Envíos / preparaciones | 1.775 (29,6/SKU) | 358 (6/SKU) | **−80%** |
| Fill rate | 99,98% | 99,59% | −0,39pp |
| Stock promedio en sala | 415 u | 285 u | **−31%** |

**Sensibilidad** (lever = periodo, no z): a más periodo, menos envíos y menos stock,
fill siempre >99,4%. Trade-off real: viajes↓ vs capital↑ (absoluto). z casi no mueve
envíos; afina fill en colas.

**Fair-share** (escenario 6 salas, CD cubre 55%):

| Regla | Cob. mín | Spread | Salas que quiebran |
|---|---|---|---|
| Greedy | 1,3d | 15,4d | 3 de 6 |
| Proporcional | 9,3d | 0,6d | 0 |
| **Igualar cobertura** | **9,5d** | **0,0d** | **0** |

Scripts: `sim_envio_periodo.py`, `sim_sensibilidad.py`, `sim_fairshare.py`.

---

## 6. Parámetros (las palancas)

| Parámetro | Fuente | Estado |
|---|---|---|
| `period_weeks(SKU)` | ya en el modelo | OK |
| `ciclo_logístico` (safety horizon) | 7d (camión semanal) | fijo |
| tabla `z` por ABCXYZ | Marco la tunea por run | **CONFIRMAR cuál corre hoy** |
| `σ` por SKU | últimas ~4 sem serie limpia | ⚠ doble conteo de-censura (ver §7) |

---

## 7. Pendientes / riesgos abiertos

1. **Realismo por sala:** el POC usa demanda agregada de cadena (pooling esconde
   varianza → fill real por sala será algo menor que 99,6%). Falta pull XML-RPC
   **por sala** para fill real y para medir cuán seguido el CD queda corto.
2. **Cola C/Z errática:** el POC es cervezas (movedores regulares). Validar el
   ahorro donde la venta es intermitente.
3. **σ doble conteo:** la de-censura infla μ y σ a la vez (memoria
   `engine_sigma_usa_serie_cleansed`). Decidir si se capa al integrar el safety.
4. **z productiva:** confirmar la tabla vigente antes de codear.
5. **PROXY:** días sin venta en el cache se tratan como 0 demanda (puede ser
   quiebre → fill algo optimista).

---

## 8. Cómo se valida en Fase 1
Backtest no aplica (no es cambio de forecast). Validación = simulación sobre POS
histórico **por sala**, política actual vs nueva: nº de envíos/sala/mes, fill rate,
stock promedio. Objetivo: menos preparaciones con fill igual o mejor.
