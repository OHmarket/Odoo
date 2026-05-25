# Scripts Inventory — OH Market

Pipeline de Odoo Studio. Orden de ejecución productivo:
ABCXYZ → Cambio Precio → Price Correccion → HM SI Forecast → Stock Analisis → Generacion Docs.
Paralelo diario: Stock Balance Daily, Presupuesto ventas, Flujo de Caja.
Validación post-pipeline: Forecast Backtest.

---

## 1. OH Calculo ABCXYZ.py

**Ruta:** `01_segmentacion/OH Calculo ABCXYZ.py`
**Versión:** v19.4 (2026-05-12)
**Rol:** productivo-core · paso 1 obligatorio del pipeline
**Advisory lock:** 99009611

**Propósito:** Clasifica cada producto activo con la matriz ABC (valor) × XYZ (variabilidad de
demanda) por equipo/sucursal. Calcula GMROI (snapshot), ADI (Average Demand Interval), CV²
(coeficiente de variación), regimen (REG-0..REG-8), ciclo de vida
(ramp_up/mature/declining/dead) y tipo de serie (smooth/erratic/lumpy/no_signal, ventana de
52 y 12 semanas). Persiste en `x_calculo_abc_xyz`.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `HARD_RESET_DEFAULT` | `True` | Borra y recrea todos los registros del equipo |
| `DEMAND_WINDOW_WEEKS` | `30` | Semanas de historial para ADI/CV² |
| `SERIES_SHORT_WEEKS` | `12` | Ventana corta para `series_type_short` (v19.4) |
| `COST_MODEL` | `'standard'` | Fallback a `standard_price` si falta `cost_unit` |
| `MIN_UNITS_YEAR` | `1.0` | Umbral mínimo para clasificar (bajo esto → dead/no_signal) |

**Salida:** `x_calculo_abc_xyz` (granularidad: team × product)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `x_studio_abcxyz` | char | AX / AY / … / CZ |
| `x_studio_regimen` | char | REG-0..REG-8 (descriptivo) |
| `x_studio_series_type` | char | smooth / erratic / lumpy / no_signal (52 sem) |
| `x_studio_series_type_short` | char | ídem en ventana 12 sem (v19.4) |
| `x_studio_series_type_active` | char | La que consume HM SI (corta si difiere de larga) |
| `x_studio_gmroi` | float | Snapshot al momento |
| `x_studio_adi_weeks` | float | Average Demand Interval |
| `x_studio_cv2` | float | Coeficiente de variación² |
| `x_studio_ciclo_de_vida` | char | ramp_up / mature / declining / dead |

**Notas:** SAFE_EVAL. El regimen es descriptivo: **NO** interviene en el cálculo del forecast
(per `docs/forecast/HM_SI_v4_proceso.md`).

---

## 2. OH Cambio de Precio.py

**Ruta:** `02_forecast/OH Cambio de Precio.py`
**Versión:** v5
**Rol:** cron-diario · captura snapshots de eventos de precio
**Advisory lock:** 99009414

**Propósito:** Detecta cambios reales de precio por producto desde ventas POS. Agrupa por
semana + producto + price bucket (redondeo a $50), identifica el precio dominante (mayoría de
unidades vendidas), y persiste solo la primera semana en que cambia el régimen de precio.
Implementado con SQL puro + CTEs complejas (no ORM). Modo incremental: reconstruye ventana
de 12 semanas.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `REBUILD_WEEKS` | `12` | Ventana de reconstrucción (incremental) |
| `PRICE_BUCKET` | `50.0` | Redondeo de precio para detección de régimen |
| `MIN_ABS_CHANGE` | `50.0` | Cambio absoluto mínimo para registrar (CLP) |
| `MIN_PCT_CHANGE` | `0.05` | Cambio porcentual mínimo (5%) |
| `DRY_RUN` | `False` | Valida sin persistir |
| `PURGE_EXISTING` | `True` | Elimina previos en ventana antes de INSERT |

**Salida:** `x_price_change_event` (granularidad: product × semana de cambio)

| Campo | Descripción |
|-------|-------------|
| `x_studio_product_id` | M2O product.product |
| `x_studio_period_start` | Semana en que inicia el nuevo régimen |
| `x_studio_base_price` | Precio régimen anterior |
| `x_studio_price_eff` | Precio nuevo régimen |
| `x_studio_delta_pct` | Variación porcentual |
| `x_studio_direction` | 'Sube' / 'Baja' |
| `x_studio_support_weeks` | Duración del régimen anterior (semanas) |

---

## 3. OH Price Correccion.py

**Ruta:** `02_forecast/OH Price Correccion.py`
**Versión:** v5.8 (2026-05-12)
**Rol:** productivo-core · ajusta factor de demanda por cambios de precio
**Advisory lock:** 99009612

**Propósito:** Genera alertas de corrección de demanda basadas en cambios de precio
(`x_price_change_event`) y promos activas (`x_loyalty_promo_event`). Calcula factor de
corrección (0.76–1.20) por SKU usando elasticidad por categoría L2, peso ABC del competidor
(CPI ponderado), y tipo de evento. Lookback 52 semanas para precios (v5.8 extendido), 4
semanas para promos.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `LOOKBACK_PRICE_WEEKS_DEFAULT` | `52` | Extendido en v5.8 para cambios sostenidos |
| `LOOKBACK_PROMO_WEEKS_DEFAULT` | `4` | Ventana promos |
| `HARD_RESET_DEFAULT` | `True` | Purge + recrear |
| `PESO_ABC` | `{'A':1.0,'B':0.2,'C':0.03}` | Peso canibalización por competidor |
| `ELASTICIDAD_ABC` | `{'A':1.30,'B':1.00,'C':0.70}` | Amplifica factor según ABC propio |

**Salida:** `x_price_coreccion` (granularidad: product × semana alerta)

| Campo | Descripción |
|-------|-------------|
| `x_studio_factor_corr` | Factor ajuste demanda (0.76–1.20) |
| `x_studio_tipo_alerta` | PROMO_DISPARO/SATURACION, SUBIDA/BAJADA _LEVE/_FUERTE/_CANIBAL |
| `x_studio_indice_canibal` | CPI ponderado por ABC competidor (0.0–1.0) |
| `x_studio_source` | 'price_change' o 'promo' |
| `x_studio_sub_cat` | Subcategoría L3 |

**Notas:** SAFE_EVAL. El modelo tiene typo Studio intencional: `x_price_coreccion` (una 'r').

---

## 4. HM SI Forecast.py

**Ruta:** `02_forecast/HM SI Forecast.py`
**Versión:** v3.39 AUTO_MODEL (2026-05-20) · runner productivo
**Rol:** productivo-core · motor de demanda
**Advisory lock:** 99009438

**Propósito:** Genera pronóstico semanal de demanda (mu_week + sigma) por (product, team,
semana_objetivo). Combina: (1) SMA corto/largo con detección up/hold/down/collapse, (2) índice
estacional (SI) multi-nivel SKU→local-categ→categ-global→global (clamp 0.05–5.00), (3) ajuste
por precio con elasticidad por L2 y decay 16 semanas, (4) caps anti-spike (lifecycle gate P1,
intermittence gate P3, máximo histórico P6). Versión v3.39 agrega bake-off automático por SKU:
heurístico vs SBA vs Croston vs seasonal_naive evaluados con MAE en holdout de 4 semanas.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `DEMAND_WINDOW_WEEKS` | `26` | Ventana base de demanda |
| `HISTORY_WEEKS` | `104` | Historial para SI (2 años) |
| `SERVICE_RATIO_COLLAPSE` | `0.30` | Umbral detector colapso de demanda |
| `AUTO_MODEL_ENABLED` | `True` | Activar bake-off v3.39 |
| `HEURISTIC_BIAS` | `0.90` | Heurístico gana si MAE gap < 10% |
| `HARD_RESET_DEFAULT` | `True` | Purge + recrear |

**Salida:** `x_hm_si_forecast` (granularidad: team × product × semana)

| Campo | Descripción |
|-------|-------------|
| `x_studio_mu_week` | Pronóstico unidades semana objetivo |
| `x_studio_sigma_week` | Desviación estándar |
| `x_studio_si_current` / `si_next` | Índice estacional actual y próxima semana |
| `x_studio_si_level` | Nivel donde se resolvió el SI (sku/local_categ/global) |
| `x_studio_forecast_zone` | Z1/Z2/Z3/Z4 (router) |
| `x_studio_demand_method` | Modelo ganador: heuristic/sba/croston/seasonal_naive (v3.39) |
| `x_studio_regimen` | Descriptivo heredado de ABCXYZ (NO afecta cálculo) |
| `x_studio_collapse_detected` | Boolean (v3.37) |

**Router de zonas:**

| Zona | Condición | Tratamiento |
|------|-----------|-------------|
| Z1 | AX/AY/BX smooth, mature/ramp_up, mu≥2.0 | core_hm_si |
| Z2 | AX/AY erratic/lumpy, mature/ramp_up, mu≥2.0 | controlled_hm_si |
| Z3 | seasonal lifecycle, BY/BZ/AZ erratic/lumpy | secondary_model |
| Z4 | no_signal, CX/CY/CZ, declining/dead, mu<2.0 | no_forecast |

**Notas:** SAFE_EVAL. Ver `docs/forecast/HM_SI_v4_proceso.md` para decisiones de diseño y
linaje de versiones (v3.24 → v3.39).

---

## 5. OH Forecast Backtest.py

**Ruta:** `02_forecast/OH Forecast Backtest.py`
**Rol:** validación post-pipeline
**Advisory lock:** ninguno

**Propósito:** Compara el forecast HM-SI generado (`x_hm_si_forecast`) contra la venta real
POS en semanas ya cerradas. Calcula WAPE, BIAS y MAE desagregados por zona (Z1–Z4),
regimen (REG-0..REG-8) y categoría. **No escribe en ningún modelo Studio** — solo reporta
mediante notificaciones y log de consola.

**Parámetros principales:**
- `BACKTEST_WEEKS` — semanas a evaluar (últimas 4–8 semanas cerradas)
- `team_ids` — equipos a evaluar

**Salida:** Solo notificaciones con métricas WAPE/BIAS/MAE por zona y regimen.

---

## 6. OH Analisis de Stock.py

**Ruta:** `03_stock/OH Analisis de Stock.py`
**Rol:** productivo-core · paso 4 del pipeline
**Advisory lock:** ninguno (ejecuta vía acción servidor ID 1502)

**Propósito:** Calcula necesidades de compra y transferencia interna por sucursal/producto.
Lee stock actual (`stock.quant`), movimientos históricos (`stock.move`), clasificación
ABC-XYZ desde `x_calculo_abc_xyz`, y genera cantidades a pedir en cajas (valida que UoM de
compra sea caja). Calcula GMROI rolling, severidad de quiebre y días de cobertura.

**Parámetros principales:**

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `ACTION_STOCK_ANALYSIS_ID` | `1502` | ID de la server action |
| `CENTRAL_WAREHOUSE_ID` | `15` | Almacén central |
| `CENTRAL_TEAM_ID` | `26` | Equipo central |
| `STRICT_PURCHASE_UOM_BOX` | `True` | Valida que UoM compra = caja |
| `TEAM_WAREHOUSE_MAP_FALLBACK` | dict | Fallback team_id → warehouse_id |

**Salida:** `x_analisis_de_stock` (granularidad: team × product × snapshot)

| Campo | Descripción |
|-------|-------------|
| `x_studio_stock_real` | Stock actual |
| `x_studio_qty_a_pedir` | Cantidad a pedir en cajas |
| `x_studio_abcxyz` | Clasificación heredada |
| `x_studio_snapshot_date` | Fecha del cálculo |

**Notas:** SAFE_EVAL. Ver `docs/stock/Analisis_de_Stock_proceso.md` para deficiencia conocida:
stock en tránsito no se refleja (propuesta: campo `x_studio_stock_en_transito`).

---

## 7. OH Generacion de Documentos.py

**Ruta:** `03_stock/OH Generacion de Documentos.py`
**Versión:** v1.5 (modo adopción: documentos en borrador)
**Rol:** productivo-core · paso 5 del pipeline
**Advisory lock:** 99123041

**Propósito:** Crea documentos de suministro (RFQ de compra + traslados internos) a partir del
análisis de stock (`x_analisis_de_stock`). Genera siempre en **BORRADOR** — requiere
confirmación manual en Odoo. Usa idempotencia por `origin_key` para evitar duplicados.
Soporta 4 tipos de generación: compra_sala, compra_bodega, envio_a_sala,
transferencia_interna_retiro.

**Parámetros (campos del formulario `x_supply_generation`):**

| Campo | Descripción |
|-------|-------------|
| `x_studio_generation_type` | Tipo: compra_sala / compra_bodega / envio_a_sala / transferencia_interna_retiro |
| `x_studio_supplier_id` | Proveedor (obligatorio para compras) |
| `x_studio_team_id` | Sucursal destino |
| `x_studio_inc_top / inc_medium / inc_low` | Selección ABC-XYZ a incluir |
| `x_studio_use_budget / budget_amount` | Presupuesto máximo opcional |

**Salida:**
- `purchase.order` con líneas en cajas (qty_product_uom = cajas)
- `stock.picking` con movimientos de traslado
- Actualiza `x_supply_generation` con conteo de documentos generados

**Notas:** SAFE_EVAL. Los documentos se crean en BORRADOR. Confirmar manualmente.

---

## 8. Stock Balance Daily.py

**Ruta:** `03_stock/Stock Balance Daily.py`
**Versión:** v2.0 (dual-mode: backfill | incremental)
**Rol:** cron-diario
**Advisory lock:** 99009440

**Propósito:** Reconstruye balance diario de stock por (team, warehouse, product, día) usando
roll-backward desde el snapshot de `stock.quant` actual. Detecta quiebres de stock completos
(balance≤0) y parciales (inicio>0 y fin≤0). Modo incremental recalcula cola de días (default
7); modo backfill procesa rango explícito.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `mode` | `'incremental'` | 'backfill' \| 'incremental' |
| `tail_window_days` | `7` | Días a recalcular en modo incremental |
| `date_from` / `date_to` | — | Rango explícito solo para backfill |
| `team_ids` | `FILTERED_TEAM_IDS` | Lista de equipos |

**Salida:** `x_stock_balance_daily` (granularidad: team × product × día)

| Campo | Descripción |
|-------|-------------|
| `x_qty_balance` | Stock al cierre del día |
| `x_qty_start` | Stock al inicio del día |
| `x_qty_in` / `x_qty_out` | Entradas / salidas del día |
| `x_stockout` | True si balance≤0 |
| `x_stockout_partial` | True si inicio>0 y fin≤0 |
| `x_abcxyz` | Clasificación ABC-XYZ |
| `x_run_id` | UUID corto del run |
| `x_mode` | 'backfill' o 'incremental' |

---

## 9. OH Analisis Ventas SKU.py

**Ruta:** `04_analitica/OH Analisis Ventas SKU.py`
**Versión:** v12 (combo explode)
**Rol:** analitica
**Advisory lock:** ninguno

**Propósito:** Calcula KPI semanales (lunes–domingo) por SKU y sucursal desde POS: cantidad
vendida, ventas brutas, crecimiento vs LY-364, respuesta vs categoría, banda estacional,
feriados. Maneja combos separando unidades del hijo real (SQL standalone + children con
prorrateo de venta bruta). SAFE_EVAL friendly (sin lambdas, sin imports complejos).

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `run_mode` | `'range'` | 'last_closed' \| 'range' |
| `date_from` | `DEFAULT_FROM` | Inicio rango |
| `date_to` | último domingo | Fin rango |
| `team_ids` | `FILTERED_TEAM_IDS` | Equipos |
| `dry_run` | `False` | Valida sin escribir |

**Salida:** `x_pos_week_sku_sale` (granularidad: team × product × semana)

| Campo | Descripción |
|-------|-------------|
| `x_studio_qty_sold` | Unidades vendidas |
| `x_studio_sales_gross` | Ventas brutas |
| `x_studio_response_vs_category_pct` | Crecimiento SKU − crecimiento categoría (pts) |
| `x_studio_seasonal_band` | VERANO_BAJO/MEDIO/ALTO, FIESTAS_PATRIAS, HALLOWEEN, FIN_ANIO, BASE |
| `x_studio_has_holiday` | Boolean |
| `x_studio_holiday_days` | Días feriados en la semana |

---

## 10. OH Analisis ventas Categoria.py

**Ruta:** `04_analitica/OH Analisis ventas Categoria.py`
**Versión:** v10
**Rol:** analitica
**Advisory lock:** ninguno

**Propósito:** Calcula KPI semanales por categoría y sucursal desde POS: unidades, ventas,
tickets, líneas, factor estacional (semana vs promedio anual de 52 semanas). Combos exploded.
Soporta backfill rango o modo incremental última semana cerrada.

**Parámetros principales:**
- `run_mode` / `date_from` / `date_to`
- `pos_week_purge_all` — borra empresa completa vs solo rango objetivo
- `dry_run`

**Salida:** `x_x_pos_week_sku_fact` (granularidad: team × categ × semana)

| Campo | Descripción |
|-------|-------------|
| `x_studio_units` / `x_studio_sales` | Unidades y ventas |
| `x_studio_orders_count` / `x_studio_lines_count` | Tickets y líneas |
| `x_studio_season_factor_units` | Factor estacional unidades (semana/promedio anual) |
| `x_studio_season_factor_sales` | Factor estacional ventas |
| `x_studio_var_sales_pct` / `x_studio_var_units_pct` | Variación vs LY |

---

## 11. OH Analisis ventas Team.py

**Ruta:** `04_analitica/OH Analisis ventas Team.py`
**Versión:** v13 (combo explode)
**Rol:** analitica
**Advisory lock:** ninguno

**Propósito:** Calcula KPI mensual por sucursal (POS only): ventas brutas, tickets, unidades,
ATV (average ticket value), UPT (units per ticket), crecimiento YoY, color semáforo basado en
`AVG_DROP = -10.9%`, y driver code (CROW|TCK|MIX|ATV|PRC). SAFE_EVAL friendly.

**Parámetros principales:**
- `run_mode` — 'last_closed' | 'range'
- `date_from` / `date_to`
- `dry_run`

**Salida:** `x_sales_month_team_kpi` (granularidad: team × mes)

| Campo | Descripción |
|-------|-------------|
| `x_studio_sales_gross` / `x_studio_sales_gross_ly` | Ventas TY/LY |
| `x_studio_tickets` / `x_studio_units` | Tickets y unidades |
| `x_studio_atv` | Average Ticket Value |
| `x_studio_units_per_ticket` | UPT |
| `x_studio_yoy_sales_pct` | YoY ventas % |
| `x_studio_driver_code` | CROW / TCK / MIX / ATV / PRC |
| `x_studio_color` | 1=rojo, 2=amarillo, 3=gris, 4=verde |

---

## 12. OH Calculo de Margen.py

**Ruta:** `04_analitica/OH Calculo de Margen.py`
**Rol:** analitica
**Advisory lock:** ninguno

**Propósito:** Calcula margen real por producto (POS + SO) sin ILA venta. Lee
`raw_product_price` → costo neto → aplica ILA/IVA compra → compara venta neta contra costo.
Clasifica con semáforo (verde/amarillo/rojo) con reglas especiales para cigarrillos. Usa
`_flatten_taxes` recursivo para manejar grupos de impuestos anidados.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `date_from` / `date_to` | mes actual | Período de análisis |
| `ila_sales_mode` | `'none'` | 'none' \| 'so' \| 'all' — incluir ILA en venta |
| `cigarette_category_ids` | `[1628]` | IDs categoría cigarrillos (reglas especiales) |

**Salida:** `x_margen_por_producto_` (granularidad: product × período)

| Campo | Descripción |
|-------|-------------|
| `x_studio_margin_total` | Margen total CLP |
| `x_studio_margin_pct` | Margen % sobre venta neta |
| `x_studio_costo_neto_unit` | Costo neto por unidad |
| `x_studio_costo_oh_unit` | Costo OH (neto + ILA compra) |
| `x_studio_semaforo_margen` | verde / amarillo / rojo / gris |
| `x_studio_motivo_semaforo` | ok / fuera_rango / margen_extremo / cigarro_* / sin_raw |
| `x_studio_es_cigarro` | Boolean |

---

## 13. OH Presupuesto ventas.py

**Ruta:** `05_finanzas/OH Presupuesto ventas.py`
**Versión:** v13 (holidays from model)
**Rol:** cron-diario
**Advisory lock:** ninguno

**Propósito:** Calcula presupuesto diario de ventas desde ayer hasta fin de 2026 usando factor
rolling robusto (blending 25% corto + 75% largo, ventanas de 45 y 365 días). Maneja bandas
estacionales, feriados desde `x_holiday_occurrence`, pre-feriados con offset, y Año Nuevo
cross-year. Soporte para corrección corta (Pascua). SAFE_EVAL friendly.

**Parámetros principales:**

| Parámetro | Valor por defecto | Descripción |
|-----------|------------------|-------------|
| `ALPHA_BLEND` | `0.25` | Blend corto/largo (25% ventana corta, 75% larga) |
| `ROLL_WINDOW_DAYS` | `45` | Ventana corta rolling |
| `LONG_WINDOW_DAYS` | `365` | Ventana larga |
| `ENABLE_TEAM_DAILY_FLOOR` | `True` | Mata outliers con floor por equipo |
| `FILTERED_TEAM_IDS` | lista | Equipos a procesar |

**Salida:** `x_presupuesto_de_venta` (granularidad: team × día)

| Campo | Descripción |
|-------|-------------|
| `x_proj_2025` | Proyección de ventas |
| `x_bruto_2025` | Venta real (si ≤ ayer, else 0) |
| `x_factor_day` | Factor rolling calculado |
| `x_studio_presupuesto_actualizado` | actual || proyección (campo operativo) |
| `x_studio_tratamiento` | NORMAL / FERIADO_ANO_ACTUAL / FERIADO_ANO_ANTERIOR / PROM_4_SEMANAS |
| `x_studio_floor_team` | True si se aplicó floor |

---

## 14. OH Flujo de Caja.py

**Ruta:** `05_finanzas/OH Flujo de Caja.py`
**Versión:** v1.3
**Rol:** cron-diario
**Advisory lock:** ninguno

**Propósito:** Reconstruye flujo de caja diario con horizonte de 90 días combinando:
ventas POS reales (día D → caja D+1), presupuesto futuro (`x_presupuesto_de_venta`),
facturas de compra pendientes/vencidas (por vencimiento), y estimación IVA operativo F29
(débito ventas − crédito compras, pago proyectado día 20 del mes siguiente).

**Parámetros principales:**

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `HORIZON_DAYS` | `90` | Días de proyección hacia adelante |
| `TIMEZONE` | `'America/Santiago'` | Zona horaria base |

**Salida:** `x_cash_flow` (secciones: 01_sales, 02_suppliers, 03_iva)

| Campo | Descripción |
|-------|-------------|
| `x_source` | pos_sales / sales_invoice / sales_budget / purchase_invoice / iva_projection |
| `x_amount_in` / `x_amount_out` | Flujos de entrada y salida |
| `x_state` | STATE_REAL / STATE_PROJECTED / STATE_PENDING / STATE_OVERDUE |
| `x_partner_id` | Proveedor (solo section 02_suppliers) |
| `x_invoice_id` | Factura origen (solo section 02_suppliers) |

**Notas:** Detecta dinámicamente valores técnicos de selección Studio con tolerancia a espacios
accidentales (bug conocido de Studio al crear campos selection).
