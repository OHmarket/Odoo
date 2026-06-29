# Diseño — Go-live Odoo v19 limpio + capa de historia de ventas (`x_sales_fact`)

Fecha: 2026-06-14
Estado: Fase 0 cerrada (diseño aprobado). Pendiente `plan.md` + implementación.
Slug: `2026-06-14-v19-golive-fact-historia`

---

## 1. Problema y decisión comercial

Se implementa **Odoo v19 desde cero (no migración)** para aprovechar y **limpiar
historia**: modelos Studio/`x_` legacy, maestro sucio (productos/partners),
movimientos viejos (stock/contab) y config acumulada (cuentas, diarios, POS,
warehouses, impuestos).

**Tensión central:** la instancia debe arrancar limpia, pero los motores de
estadística (ABCXYZ, Forecast Base, Análisis de Stock) necesitan **historia de
ventas** para clasificar y pronosticar. Sin historia, el pipeline arranca ciego
(warm-up de meses).

**Decisión que depende del diseño:** cómo alimentar la historia a los motores sin
re-ensuciar la instancia transaccional v19.

**Qué pasa si se equivoca:** si la historia se carga mal (empalme incompleto,
unidades/signos errados, doble conteo de devoluciones), ABCXYZ clasifica mal y el
forecast compra mal → decisiones de inventario sobre data falsa. Principio del
repo: *lento pero correcto > rápido con bugs*.

---

## 2. Cómo lo resuelven los grandes (Fase 0, pregunta 4)

Go-live de ERP en SAP / Oracle / NetSuite separa dos cosas:

- **Instancia transaccional**: arranca limpia con **maestro activo + saldos
  iniciales** (stock on hand, AR/AP, GL opening). **No** se migran transacciones
  históricas.
- **Historia para analítica/forecast**: vive en una **capa separada**
  (data warehouse / star schema, p.ej. SAP BW) con una **tabla de hechos de
  ventas** denormalizada. El ERP no carga la historia transaccional.

Patrón canónico adoptado: **sales fact table** (grano diario, denormalizado).
No es fórmula propia.

---

## 3. Enfoques evaluados (Fase 0, preguntas 5-6)

| Enfoque | Veredicto |
|---|---|
| **A. Tabla de hechos dedicada (`x_sales_fact`)** | ✅ **Elegido.** v19 transaccional limpio; motores leen tabla plana indexada; historia desacoplada del desorden viejo |
| B. Recargar `pos.order` real en v19 | ❌ Revive el desorden que se quiere limpiar; pesado; reintroduce devoluciones/anulaciones/duplicados |
| C. v17 read-only como archivo, v19 sin historia | ❌ Warm-up de meses; ABCXYZ/Forecast necesitan ≥26-52 sem para clasificar → arranca ciego |

**Lo que NO se hace (YAGNI):**
- No se migran `pos.order`/`stock.move`/`account.move` históricos a v19.
- No se construye un cron permanente que alimente el fact (ver §6: lectura híbrida).
- No se arrastran modelos `x_` legacy ni experimentos del repo viejo.

---

## 4. Decisiones cerradas (Fase 0)

| # | Decisión | Valor |
|---|---|---|
| D1 | Alcance de limpieza | Greenfield total: modelos, maestro, movimientos y config desde cero |
| D2 | Dónde vive la historia | Tabla de hechos dedicada `x_sales_fact` (no recargar `pos.order`) |
| D3 | Grano | **Diario**, por `(fecha, SKU, sucursal activa)` |
| D4 | Llave de empalme v17↔v19 | **Barcode** (auditar unicidad + no-vacío antes; bloqueante) |
| D5 | Profundidad de historia | **Fecha fija: desde 2025-01-01** hasta el cutover (~17 meses) |
| D6 | Extracción v17 | Solo XML-RPC / Server Action (no hay SQL directo); barrido server-side por lotes en horario muerto |
| D7 | Rol del fact table | **Archivo histórico congelado**, no se mantiene con cron |
| D8 | Lectura post-cutover | **Híbrida**: `x_sales_fact` (`fecha < cutover`) ∪ `pos.order` v19 (`fecha >= cutover`) |
| D9 | Ciclo de vida del fact | Puente **transitorio**: se jubila cuando v19 acumule ~17 meses de historia propia |

**Por qué 2025-01-01 (D5):** ancla fija reproducible. Cubre verano 2025 completo
+ verano 2026 → da **YoY gratis** justo en la temporada de eventos que más importa
(irrenunciables, verano), sin pagar 24 meses enteros. Mitad de volumen de backfill
vs 24 meses, lo que importa porque la extracción es por XML-RPC.

**Validación de ventana en código** (no es opinión, se midió):
- ABCXYZ: `HISTORY_MONTHS_DEFAULT = 24` (parámetro `CTX.get('history_months')`),
  pero ABC/XYZ usan solo 26 sem y active/lifecycle hasta 52 sem. El piso real de
  la lectura lo fija el fact table (2025-01-01).
- Forecast Base: `DEMAND_WINDOW_WEEKS = 26` (clasificación + universo activo).
- Análisis de Stock: ventana sigma ~4-26 sem.
- Desde 2025-01-01 (~17 meses) cubre con holgura los 26-52 sem que pide el pipeline.

---

## 5. Arquitectura — dos mundos separados

```
2025-01-01 ──────────────── CUTOVER ──────────────── hoy
│   x_sales_fact (v17, CONGELADO)   │   pos.order v19 (VIVO, limpio)  │
└────────────── lectura UNION en cada motor ───────────────────────────┘

┌─────────────────────────────┐      ┌──────────────────────────────┐
│  v19 TRANSACCIONAL (limpio)  │      │  CAPA ANALÍTICA (historia)    │
│  • maestro activo depurado    │      │  • x_sales_fact (archivo)     │
│  • config nueva               │      │    venta diaria sku×sala       │
│  • saldos iniciales (stock)   │      │    2025-01-01 → cutover        │
│  • SIN transacciones viejas   │      │  • empalme por BARCODE         │
└─────────────────────────────┘      └──────────────────────────────┘
```

- v19 transaccional arranca limpio (maestro activo + saldos iniciales, cero
  transacciones viejas).
- `x_sales_fact` = backfill estático de v17 (una sola carga). No crece.
- Post-cutover, **v19 nativo (`pos.order`) es la verdad** forward; no pasa por el fact.
- El barcode-empalme **solo** importa para la cola histórica; v19 usa su
  `product_id` nativo directo.

---

## 6. Componentes

### C1. Modelo `x_sales_fact` (Studio)

Grano: una fila por `(fecha, producto, sala)` con venta. Sparse (solo combos
vendidos). Fuente única: backfill v17.

| Campo | Tipo | Nota |
|---|---|---|
| `x_name` | Char (required) | Studio NOT NULL. Convención: `'<fecha>:<barcode>:<team_id>'` |
| `x_studio_date` | Date | Fecha local CL (ya convertida de UTC) |
| `x_studio_barcode` | Char | Llave de empalme histórico (indexada) |
| `x_studio_product_id` | Many2one `product.product` | Resuelto en v19 vía barcode; **nullable** si no empalma |
| `x_studio_team_id` | Many2one `crm.team` | Sala (resuelta de `pos.config` → team) |
| `x_studio_qty` | Float | Unidades **netas** (devoluciones restadas) |
| `x_studio_neto` | Float | Monto neto sin IVA |
| `x_studio_bruto` | Float | Monto con IVA (`list_price` es con IVA en OH) |
| `x_studio_source` | Selection | `'v17_backfill'` (trazabilidad) |

Índices recomendados: `(product_id, team_id, date)` y `(date)`.

⚠️ **x_name es required** (regla del repo): setear explícito en cada create/insert
o falla `NotNullViolation` en el primer batch.

### C2. Extractor v17 → CSV (one-time)

Server Action en **v17** que barre server-side (`self.env.cr.execute`, **no**
XML-RPC masivo — regla: no cargar el POS) y agrega `pos.order.line` por
`(fecha local CL, barcode del producto, pos.config → team)` desde 2025-01-01.

- Paginar **por mes** para no explotar memoria.
- Devoluciones/anulaciones: incluir líneas con qty negativa → el agregado da
  **venta neta** (no doble conteo).
- Conversión TZ: `(date_order AT TIME ZONE 'UTC' AT TIME ZONE TZ)::date`
  (mismo patrón que Análisis de Stock).
- Mapeo sala: `pos.config` → `crm.team`. ⚠️ `pos.config.warehouse_id` está mal
  (todos apuntan a WH=1); usar `picking_type_id.warehouse_id` o el mapeo
  team↔warehouse verificado. El nombre real de la sala vive en `pos.config.name`
  (los 12 `crm.team` se llaman "Sales").
- Output: CSV (attachment base64) o staging. Formato técnico estándar (sep=`,`,
  utf-8); no Excel-CL (lo consume un script, no una persona).

### C3. Cargador CSV → `x_sales_fact` (v19)

1. Lee CSV.
2. Empalma `barcode` → `product.product` en v19. Filas sin empalme: `product_id`
   queda nulo, pero **se conservan** con el barcode para auditoría.
3. **Reporte de empalme (bloqueante):** % de `qty` y de filas empalmadas;
   lista de barcodes huérfanos (top por `qty`). Si la cobertura es baja, parar.
4. Escribe en lotes. ⚠️ Volumen alto (ver §8) → preferir **INSERT directo por
   `cr.execute` en batches**, no `create()` ORM fila a fila.

### C4. Repunte de scripts (lectura híbrida)

ABCXYZ, Forecast Base y Análisis de Stock dejan de leer solo `pos.order` y pasan
a **UNION** con `x_sales_fact`:

```sql
-- cola histórica
SELECT date, product_id, team_id, qty, neto, bruto
FROM x_sales_fact
WHERE date >= :date_from AND date < :CUTOVER_DATE
UNION ALL
-- reciente (v19 nativo)
SELECT <misma forma desde pos.order.line>
WHERE date >= GREATEST(:date_from, :CUTOVER_DATE)
```

- Constante nueva: `CUTOVER_DATE` (fecha del go-live).
- **Una versión, un cambio por script** (regla del repo): repuntar de a uno,
  validar caso canónico, recién promover.
- Cuando v19 acumule historia ≥ ventana de los motores, se quita el UNION y se
  jubila `x_sales_fact` (D9).

---

## 7. Secuencia de go-live

1. **Instalar v19** + módulos + config nueva (plan de cuentas, diarios, POS,
   warehouses, impuestos).
2. **Cargar maestro activo depurado** (productos con barcode, partners).
3. **Auditar barcode** (bloqueante): unicidad + no-vacío en SKUs activos.
   Reporte de SKUs sin barcode o con barcode duplicado → resolver antes de seguir.
4. **Crear `x_sales_fact`** (modelo + índices).
5. **Backfill:** extraer v17 (2025-01-01 → cutover) → CSV → cargar a
   `x_sales_fact`. Generar **reporte de empalme**; validar cobertura.
6. **Cargar saldos iniciales de stock** (inventario físico de go-live).
7. **Repuntar y correr pipeline** (ABCXYZ → Forecast Base → Análisis de Stock)
   con lectura híbrida.
8. **Validar casos canónicos** (§9).

---

## 8. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Empalme barcode incompleto** | Ventas históricas perdidas → ABCXYZ/forecast sub-clasifican | Auditoría barcode previa (paso 3); reporte de cobertura bloqueante (C3); fallback manual para huérfanos top |
| **Barcode duplicado** en maestro v19 | Venta histórica asignada a producto equivocado | Auditoría de unicidad antes del empalme |
| **Mapeo sala errado** (`pos.config.warehouse_id` malo) | Venta atribuida a sala equivocada | Usar `picking_type_id.warehouse_id` / mapeo team verificado, no `warehouse_id` |
| **Doble conteo / signo de devoluciones** | Demanda inflada o desinflada | Agregado neto con qty negativas incluidas; validar contra total de ventas v17 conocido |
| **Volumen alto** (~17 meses diario × sparse, potencial millones de filas) | Carga ORM lentísima; modelo Studio pesado | INSERT directo `cr.execute` en batches (no `create()`); evaluar grano semanal para tramo > N meses si el volumen lo exige |
| **TZ mal convertida** | Ventas corridas un día | `AT TIME ZONE` consistente con scripts productivos |
| **Seam en el cutover** (UNION) | Día duplicado o hueco en la frontera | `< CUTOVER` estricto en fact y `>=` en v19; test del día de borde |

---

## 9. Casos canónicos de validación

- **Un SKU conocido, una sala, una semana**: total de unidades y monto en
  `x_sales_fact` == total reportado por v17 para ese corte.
- **Cobertura global**: Σ `qty`/`neto` empalmado vs total de ventas v17 del período
  (debe explicar ≥ X% acordado).
- **ABCXYZ post-carga**: la clasificación de un SKU clase A conocido no cambia de
  forma absurda vs la realidad comercial.
- **Día de borde (cutover)**: la venta de ese día no se duplica ni desaparece en la
  lectura híbrida.
- **Devolución**: un día con devolución neta conocida da qty neta correcta (no la
  bruta, no doble).

---

## 10. Decisiones abiertas / pendientes para `plan.md`

- Fecha exacta de **cutover** (define `CUTOVER_DATE`).
- Umbral de **cobertura de empalme** aceptable para no abortar (% acordado).
- ¿Grano semanal para el tramo más viejo si el volumen diario resulta inmanejable?
  (decidir tras estimar filas reales del backfill).
- Formato de entrega del CSV de v17 (attachment vs export manual).
- Mapeo definitivo `pos.config` (v17) → `crm.team` (v19) — ¿coinciden los IDs/
  nombres de sala entre instancias o hay que re-mapear por nombre?
- Orden de repunte de los 3 scripts y criterio de promoción de cada uno.
