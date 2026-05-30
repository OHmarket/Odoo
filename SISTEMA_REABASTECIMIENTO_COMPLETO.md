# OH MARKET — SISTEMA INTEGRAL DE REABASTECIMIENTO
## Arquitectura, Pipeline y Modelo de Decisión Completo (2026)

**Documento de Referencia Técnica**  
**Última Actualización:** 2026-05-29  
**Propietario:** Marco Sanhueza (OH Market)

---

## I. RESUMEN EJECUTIVO

### Propósito del Sistema

OH Market es una bebida franquiciada con 12 sucursales en regiones de Chile. El sistema de reabastecimiento automatiza:
- **Pronóstico de demanda** semanal por SKU y sala usando SMA + SI + trend correction.
- **Análisis de stock** operativo (reorden, safety stock, MOQ, reservas).
- **Generación de documentos** (órdenes de compra, traslados internos).
- **Analítica** para seguimiento de margen, cobertura, performance.

### Valores Fundamentales (Filosófia)

1. **Lento pero correcto > rápido y con bugs.** Un script que calcula mal es peor que no tener script.
2. **Hacer las cosas como los grandes.** Usar modelos canónicos (Wilson EOQ, Croston, Holt-Winters, SAP IBP) antes de inventar.
3. **Una versión, un cambio.** No mezclar fórmulas, fuentes y features en una misma versión.
4. **Reportar incertidumbre.** Si un resultado depende de forecast con bias alto, marcarlo explícitamente.

---

## II. PIPELINE PRODUCTIVO (5 SCRIPTS)

### Orden de Ejecución y Dependencias

```
ENTRADA: pos.order, product.product, product.category, stock.quant

    ↓
1. OH CALCULO ABCXYZ
   ├─ Segmentación ABC (margen acumulado 26 sem)
   ├─ Segmentación XYZ (CV sobre todos los periodos)
   ├─ Series Type (Syntetos-Boylan: smooth/erratic/intermittent/lumpy)
   ├─ Lifecycle (PLC: dead/new/ramp_up/mature/seasonal/declining)
   ├─ Régimen REG-0 a REG-8 (matriz ABC × series × lifecycle)
   ├─ GMROI anualizado (margen / stock_value)
   └─ OUTPUT: x_calculo_abc_xyz (unica verdad de segmentacion)

    ↓
2A. OH PRICE CORRECCION (Detector v5.8) [PARALELO, servidor independiente]
    ├─ Lee eventos de precio y promo desde x_loyalty_promo_event
    ├─ Calcula factor de ajuste por elasticidad (A×1.3, B×1.0, C×0.7)
    ├─ Incluye CPI canibal ponderado por importancia competidor
    └─ OUTPUT: x_price_coreccion (escrita vía Server Action)

2B. OH CALCULO DE MARGEN (SA 1435) [PARALELO, agenda diaria]
    ├─ Lee costo desde facturas de OC
    ├─ Actualiza costo_unitario en x_margen_por_producto_
    └─ OUTPUT: margin tracking (insumo para margen en analítica)

    ↓
3. HM SI FORECAST (Motor v3.48) — [CORE]
   ├─ Demanda base: SMA blend (short=6w, long=16w) + auto-model
   ├─ Estacionalidad SI multi-nivel (local_categ → categ_global → global)
   ├─ Fair Share (rescate SKUs A sin historia local)
   ├─ Correcciones P1/P3/P6 (declinantes, zero-gate, anti-spike)
   ├─ Corrección por precio (factor externo detector v5.8)
   ├─ Calibración por (categ, abc_letter) v3.47
   ├─ Trend correction YoY asimétrico por team v3.43
   ├─ Bias-outlier correction Pareto-80% v3.48
   ├─ Router forecast (Z1-Z4, forecast_scope, regimen_local)
   └─ OUTPUT: x_hm_si_forecast (mu_week, sigma_week + auditoria)

    ↓
4. OH ANALISIS DE STOCK (v9.1.86) — [CORE]
   ├─ Lee demanda desde x_hm_si_forecast (fallback x_forecast_weekly_data)
   ├─ Calcula stock físico por sucursal y bodega central
   ├─ Calcula safety stock (Z × sigma × sqrt(period_weeks))
   ├─ MOQ inteligente (SMART_MOQ_ROUNDING)
   ├─ Routing sala vs CD (cobertura_caja, exclusiones categoría)
   ├─ Reserva stock CD entre sucursales por prioridad operativa
   ├─ Cálcula compra_sala vs compra_cd vs transfer vs retorno
   └─ OUTPUT: x_analisis_de_stock (buy_action, qty_a_comprar, etc.)

    ↓
5. OH GENERACION DE DOCUMENTOS (v1.5)
   ├─ Crea purchase.order (compra a proveedor)
   ├─ Crea stock.picking (traslados internos CD <-> sala)
   ├─ Modo adopción: todo Borrador (revisar antes de confirmar)
   ├─ Idempotencia por origin_key
   └─ OUTPUT: purchase.order, stock.picking en estado Borrador

SALIDA: Documentos en Odoo para confirmación manual
        → Stock desciende al confirmar OC/picking
        → Score_view, analytics comen del forecast + stock

---

CAPAS PARALELAS (No bloquean pipeline):

ANALÍTICA (04_analitica/)
├─ OH Analisis ventas Team (por sucursal)
├─ OH Analisis ventas Categoria (margen, cover, GMROI)
├─ OH Analisis ventas SKU (performance, elasticidad)
├─ OH Cobertura ABCXYZ por Sala
├─ OH Precios Competencia Trébol
└─ OH Calculo de Margen (costo histórico)

FINANZAS (05_finanzas/)
├─ OH Presupuesto Ventas (forecast + evento, descontaminado)
└─ OH Flujo de Caja (proyección 90 días)

CRONS DIARIOS:
├─ Stock Balance Daily (x_stock_balance_daily, incremental)
└─ OH Presupuesto Ventas (recalc ayer + futuro)

LABORATORIO (02_forecast/analisis backtest/):
└─ 60 experimentos HM-SI + validaciones per-régimen
    (NO productivo; resguardo histórico)
```

---

## III. MODELO DE DATOS (Studio + Odoo Standard)

### Tablas Studio Críticas

#### A. **x_calculo_abc_xyz** (Segmentación — Tabla MAESTRA)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_name` | Char | Display: `"PP{product_id}"` |
| `x_studio_product_id` | Many2one (product.product) | Variante del SKU |
| `x_studio_categ_id` | Many2one (product.category) | Categoría padre |
| `x_studio_abcxyz` | Selection | "AX", "AY", "AZ", ..., "CZ" |
| `x_studio_abc_letter` | Char(1) | "A", "B", "C" |
| `x_studio_xyz_letter` | Char(1) | "X", "Y", "Z" |
| `x_studio_series_type` | Selection | "smooth", "erratic", "intermittent", "lumpy", "no_signal" |
| `x_studio_series_type_active` | Selection | Corto (12w) si difiere del largo (52w); sino, largo |
| `x_studio_ciclo_de_vida` | Selection | "dead", "new", "ramp_up", "mature", "seasonal", "declining" |
| `x_studio_regimen` | Selection | "REG-0" a "REG-8" (matriz ABC×series×lifecycle) |
| `x_studio_mu_week` | Float | Demanda promedio semanal (semanal) |
| `x_studio_rank_abcxyz` | Integer | Ranking por margen (1=top, top 80 = A) |
| `x_studio_gmroi` | Float | GMROI anualizado (margen / stock_value) |
| `x_studio_gmroi_class` | Selection | "A", "B", "C", "D" (cuartiles) |
| `x_studio_adi` | Float | ADI (Average Demand Interval) Syntetos-Boylan |
| `x_studio_cv2` | Float | CV² (Coefficient of Variation squared) |
| `x_studio_margen_acum_26w` | Float | Margen acumulado última 26w |
| `x_studio_active_weeks` | Integer | Semanas con demanda > 0 |
| `x_studio_marcar_eliminar` | Boolean | TRUE si score >= 3.2 + edad >= 8w |
| `x_studio_fecha_proxima_revision` | Date | Siguiente evaluación |
| `company_id` | Many2one (res.company) | OH Market (única empresa) |
| `active` | Boolean | Soft delete |

**Rol:** Única verdad de segmentación. Actualizada mensualmente por script 1. Consumida por scripts 3, 4, analítica.

---

#### B. **x_hm_si_forecast** (Pronóstico de Demanda — CORE)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_name` | Char | Display: `"HM-SI LOC{team} PP{product_id}"` |
| `x_studio_product_id` | Many2one (product.product) | SKU |
| `x_studio_team_id` | Many2one (crm.team) | Sucursal (12 equipos) |
| `x_studio_categ_id` | Many2one (product.category) | Categoría |
| `x_studio_week_start` | Date | Lunes de la semana objetivo |
| `x_studio_mu_week` | Float | **Pronóstico final (CONSUMIDO POR STOCK)**  |
| `x_studio_sigma_week` | Float | Desviación estándar (safety stock) |
| `x_studio_mu_base` | Float | Demanda base pre-SI |
| `x_studio_sigma_base` | Float | Sigma pre-SI |
| `x_studio_si_current` | Float | SI semana actual |
| `x_studio_si_next` | Float | SI semana próxima (pronóstico) |
| `x_studio_si_level` | Char | "local_categ", "categ_global", "global" [+sku_adj] |
| `x_studio_si_n_years` | Integer | Años de historia del SKU |
| `x_studio_si_main_factor` | Float | SI base (antes ajuste SKU) |
| `x_studio_si_sku_factor` | Float | Factor ajuste SKU (alpha 0.15/0.30) |
| `x_studio_collapse_detected` | Boolean | TRUE si raw_ratio < 0.30 |
| `x_studio_abcxyz` | Char(2) | ABC global + XYZ local |
| `x_studio_xyz_local` | Char(1) | XYZ calculado del team (si hay datos) |
| `x_studio_xyz_local_source` | Char | "local" o "global" |
| `x_studio_active_weeks_local` | Integer | Semanas con demanda > 0 en el team |
| `x_studio_series_type` | Char | Series type EFECTIVO (local + fallback) |
| `x_studio_series_type_source` | Char | "local" o "global" |
| `x_studio_ciclo_de_vida` | Char | Lifecycle EFECTIVO |
| `x_studio_lifecycle_source` | Char | "local" o "global" |
| `x_studio_regimen` | Char | REG-0 a REG-8 (matriz EFECTIVA) |
| `x_studio_adi_local` | Float | ADI Syntetos-Boylan local |
| `x_studio_cv2_local` | Float | CV² local |
| `x_studio_forecast_zone` | Char | "Z1", "Z2", "Z3", "Z4" (router) |
| `x_studio_forecast_scope` | Char | "core_hm_si", "controlled_hm_si", "secondary_model", "no_forecast", "core_canon_v42" |
| `x_studio_forecast_model_code` | Char | Modelo ganador: "heur", "sba_015", "croston_010", "seasonal_naive_52" |
| `x_studio_forecast_scope_reason` | Char | Breve: por qué Z1/Z2/Z3/Z4 |
| `x_studio_demand_method` | Char | Método base: "sma6_base_up", "blend_down_base", etc. |
| `x_studio_correccion_factor` | Float | Factor precio (detector v5.8) |
| `x_studio_correccion_tipo` | Char | Tipo alerta: "promo", "cambio_precio", etc. |
| `x_studio_correccion_razon` | Text | Razon de la correccion |
| `x_studio_mu_week_pre_corr` | Float | mu antes de correccion precio |
| `x_studio_categ_calib_factor` | Float | Factor (categ, abc_letter) v3.47 |
| `x_studio_categ_calib_meta` | Char | Metadata: categ, abc, factor |
| `x_studio_mu_week_pre_calib` | Float | mu antes categ_calib |
| `x_studio_mu_week_pre_bias` | Float | mu antes trend_correction (auditoria útil) |
| `x_studio_bias_outlier` | Boolean | TRUE si corregido por bias-outlier v3.48 |
| `x_studio_bias_outlier_factor` | Float | Factor bias-outlier (ej. 1.5 si sub-forecast) |
| `x_studio_bias_outlier_delta` | Float | Error acumulado (real - mu) |
| `x_studio_mu_week_pre_bias_outlier` | Float | mu antes bias-outlier |

**Rol:** Insumo directo de script 4 (Análisis Stock). Cuerpo completo de auditoria para diagnóstico. Refrescado semanalmente.

---

#### C. **x_analisis_de_stock** (Análisis Operativo + Reorden)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_name` | Char | Display: `"LOC{team} PP{prod_id}"` |
| `x_studio_product_id` | Many2one (product.template) | ⚠️ **NOTA:** product.TEMPLATE, not variant |
| `x_studio_team_id` | Many2one (crm.team) | Sucursal |
| `x_studio_categ_id` | Many2one (product.category) | Categoría |
| `x_studio_week_start` | Date | Snapshot: lunes de la semana de decisión |
| `x_studio_mu_week` | Float | Demanda semanal de x_hm_si_forecast |
| `x_studio_sigma_week` | Float | Sigma para safety stock |
| `x_studio_qty_stock_fisico` | Float | Stock físico hoy (suma por sucursal) |
| `x_studio_qty_stock_cd` | Float | Stock CD (disponible + pedidos) |
| `x_studio_safety_stock` | Float | Z × sigma × sqrt(period_weeks) |
| `x_studio_target_weeks` | Float | Horizonte operativo (lead_weeks from forecast) |
| `x_studio_cobertura_actual` | Float | qty_stock_fisico / mu_week (en semanas) |
| `x_studio_estado` | Selection | "sin_stock", "critico", "bajo", "ok", "alto", "muy_alto" |
| `x_studio_buy_action` | Selection | "compra_sala", "compra_cd", "envio_a_sala", "transferencia_interna_retiro", "no_compra", "retorno_a_cd", "phantom_block" |
| `x_studio_moq` | Float | Cantidad mínima de orden (caja o unidad) |
| `x_studio_qty_a_pedir_cajas` | Float | Cajas a pedir (si compra_sala/compra_cd) |
| `x_studio_qty_a_comprar` | Float | Unidades equivalentes |
| `x_studio_qty_transferir` | Float | Unidades a transferir (si transfer/retorno) |
| `x_studio_compra_mensual_estimada` | Float | Proyección meses próximos (para presupuesto) |
| `x_studio_oc_pendientes` | Text | JSON: [{"oc_id": N, "fecha": "..", "qty": N}, ...] |
| `x_studio_forecast_zone` | Char | Z1-Z4 (copiado de x_hm_si_forecast) |
| `x_studio_forecast_scope` | Char | "core_hm_si", "secondary_model", "no_forecast", etc. |
| `x_studio_regimen` | Char | REG-0 a REG-8 (efectivo del SKU en sala) |
| `x_studio_fair_share_applied` | Boolean | TRUE si se usó fair share (mu_week=0 original) |
| `x_studio_gap_target` | Float | Target - stock_fisico (cuanto comprar) |
| `company_id` | Many2one (res.company) | OH Market |

**Rol:** Fuente de documentos (script 5). Calcula reorden basado en demanda + stock + MOQ. Actualizado semanalmente antes de script 5.

---

#### D. **x_price_coreccion** (Correcciones de Precio — Detector v5.8)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_name` | Char | Display: `"PP{prod_id} {tipo}"` |
| `x_studio_product_id` | Many2one (product.product) | SKU |
| `x_studio_target_week_start` | Date | Semana del evento (period_start del promo) |
| `x_studio_factor_corr` | Float | Factor de ajuste (ej. 0.85 = 15% descuento) |
| `x_studio_tipo_alerta` | Selection | "promo", "cambio_precio", "canibal", "elasticidad" |
| `x_studio_razon` | Text | Motivo del cambio |
| `x_studio_weeks_since_change` | Integer | Semanas desde el evento |
| `x_studio_abcxyz` | Char(2) | ABC global para elasticidad |
| `x_studio_active` | Boolean | Si está vigente |

**Rol:** Fuente de correcciones para script 3. Escrita por detector v5.8 (paralelo, cron diario).

---

#### E. **x_categ_calib_factor** (Calibración por Categoría — v3.47)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_name` | Char | Display: `"CAT{categ_id} {abc_letter}"` |
| `x_studio_categ_id` | Many2one (product.category) | Categoría |
| `x_studio_abc_letter` | Char(1) | "A", "B", "C" |
| `x_studio_factor_corr` | Float | Factor [0.70, 1.30] (simetrico) |
| `x_studio_target_week` | Date | Última semana evaluada (para retroactividad) |
| `x_studio_n_real_units` | Float | Unidades en el backtest de 10w |
| `x_studio_regimenes_aplicables` | Char | CSV "REG-1,REG-2,REG-4,REG-8" (gate por regimen) |
| `x_studio_active` | Boolean | Si aplica |

**Rol:** Calibración por segmento (categ × abc). Refrescada mensualmente por SA OH Calc Categ Calib Factors. Aplicada en script 3 entre correccion_factor (precio) y trend_factor (team).

---

#### F. **x_demanda_normalizada** (Corrección de Quiebre — Proyecto 2026-05-25)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_studio_team_id` | Many2one (crm.team) | Sucursal |
| `x_studio_product_id` | Many2one (product.product) | SKU |
| `x_studio_week_start` | Date | Semana |
| `x_studio_qty_obs` | Float | Demanda observada (cruda) |
| `x_studio_qty_norm` | Float | Demanda normalizada (sin quiebre) |

**Rol:** Overlay en script 3 para reemplazar demanda cruda por normalizada cuando hay stockout. Flag USE_DEMAND_NORMALIZATION_DEFAULT = True (en prueba, será default permanente).

---

#### G. **x_stock_balance_daily** (Stock Diario — Cron Daily)

| Campo | Tipo | Propósito |
|-------|------|----------|
| `x_studio_team_id` | Many2one (crm.team) | Sucursal |
| `x_studio_product_id` | Many2one (product.product) | SKU |
| `x_studio_date` | Date | Día |
| `x_studio_qty_balance` | Float | Cantidad en stock ese día |
| `x_studio_stockout` | Boolean | TRUE si qty_balance <= 0 |
| `x_studio_stockout_partial` | Boolean | TRUE si qty_balance <= safety_stock |

**Rol:** Insumo para bias-outlier correction (v3.48) para filtrar demanda contaminada por quiebre. Refrescado diariamente (incremental).

---

### Tablas Estándar Odoo Consumidas

| Tabla | Campos Clave | Propósito |
|-------|--------------|----------|
| `product.product` | id, product_tmpl_id, active, sale_ok, default_code, list_price | Variantes (ej. PP2489 = Cerveza Heineken Lata) |
| `product.template` | id, categ_id, detailed_type/type, list_price, standard_price | Plantillas (ej. Heineken) |
| `product.category` | id, parent_id, name | Categoría árbol (Bebidas → Cervezas → Pilsner) |
| `crm.team` | id, name | 12 sucursales (Panguipulli 790, Futrono, etc.) |
| `pos.config` | id, warehouse_id, crm_team_id, name | POS por sucursal (≠ actual: todos apuntan a WH=1, se usa TEAM_WAREHOUSE_MAP_FALLBACK) |
| `pos.order` | id, date_order, session_id, state, company_id | Ventas (filtro: state in ['paid','done','invoiced']) |
| `pos.order_line` | id, order_id, product_id, qty, price_subtotal | Líneas (incluye combos) |
| `stock.warehouse` | id, lot_stock_id, in_type_id, out_type_id | Almacenes (1=PA790, 4=LL200, 15=CD) |
| `stock.quant` | product_id, location_id, quantity | Stock físico (snapshot Odoo primario) |
| `stock.picking` | id, picking_type_id, warehouse_id, state | Traslados (cread por script 5) |
| `purchase.order` | id, partner_id, date_order, state | Órdenes compra (creadas por script 5) |
| `res.partner` | id, payment_term_id, name | Proveedores (incluye terms pago) |
| `res.company` | id, name | OH Market (única) |

---

## IV. FLUJO DE DATOS DE PRINCIPIO A FIN

```
ENTRADA (fuentes externas)
│
├─ POS → pos.order + pos.order_line
│        (ventas diarias + combo explosion)
│
├─ Product Master → product.product + product.template
│                   (catálogo, precios, lista)
│
├─ Stock Odoo → stock.quant
│               (inventario snapshot)
│
├─ Promos/Eventos → x_loyalty_promo_event
│                   (entrada detector, v5.x)
│
└─ Facturas OC → cost_unitario
                 (entrada margen SA 1435)

    ↓ AGREGACION Y CALCULO ↓

SCRIPT 1: OH Calculo ABCXYZ
├─ Agregación ventas últimas 26w por (producto, categ)
├─ ABC por Pareto margen (0.80, 0.95)
├─ XYZ por CV (0.45, 0.90)
├─ Series Type por matriz Syntetos-Boylan (ADI, CV2)
├─ Lifecycle por presencia trimestral
├─ Matriz: ABC × series × lifecycle → Régimen (REG-0 a REG-8)
├─ GMROI = margen_anual / stock_value
└─ PERSISTE: x_calculo_abc_xyz (versión única)
            Ej: 5,241 SKUs clasificados

SCRIPT 2A [PARALELO]: Detector Precio v5.8
├─ Entrada: x_loyalty_promo_event (manual o cron)
├─ Calcula elasticidad ABC sobre factor base
├─ Incluye CPI canibal (competencia Trébol)
├─ Descarta promo pasivas (para decisión futura)
└─ PERSISTE: x_price_coreccion
            Ej: 47 eventos activos en la corrida

SCRIPT 2B [PARALELO]: Margen Costo v1435
├─ Agregación facturas OC últimas 26w
├─ Promedia costo_unitario por SKU
└─ PERSISTE: x_margen_por_producto_
            (insumo margen_unit para GMROI)

SCRIPT 3: HM SI Forecast v3.48 [CORE]
├─ Entrada: x_calculo_abc_xyz, x_price_coreccion, x_categ_calib_factor
├─ Demanda base: SMA blend
├─ SI multi-nivel: local_categ → categ_global → global (3-nivel fallback)
├─ Fair Share: rescate A/B sin historia
├─ P1/P3/P6: declinantes→0, zero-gate, anti-spike
├─ Corrección precio (detector v5.8)
├─ Categ calibration v3.47
├─ Trend correction YoY v3.43 (asimetrico: solo recorta)
├─ Bias-outlier correction v3.48 (Pareto-80%)
├─ Router: Z1-Z4 + forecast_scope
└─ PERSISTE: x_hm_si_forecast
            Ej: 5,241 × 12 × 1 = 62,892 registros/semana
            Tiempo ejecución: ~45 seg (12 teams × 5,241 SKUs)

SCRIPT 4: OH Analisis de Stock v9.1.86 [CORE]
├─ Entrada: x_hm_si_forecast, x_calculo_abc_xyz, stock.quant
├─ Calcula:
│   - Stock físico por sucursal (suma locations)
│   - Safety stock (Z × sigma × sqrt(period_weeks))
│   - MOQ inteligente (SMART_MOQ_ROUNDING)
│   - Cobertura en semanas (stock / demanda_weekly)
│   - Estado (sin_stock, critico, bajo, ok, alto, muy_alto)
│   - buy_action: compra_sala, compra_cd, transfer, retorno
│   - Routing CD (cobertura_caja vs exclusiones_categ)
│   - Reserva stock CD entre sucursales (prioridad: sin_stock > critico > etc)
│
└─ PERSISTE: x_analisis_de_stock
            Ej: 62,892 registros/semana

SCRIPT 5: OH Generacion de Documentos v1.5
├─ Entrada: x_analisis_de_stock
├─ Crea:
│   - purchase.order (compra a proveedor) [modo Borrador]
│   - stock.picking (traslados CD <-> sala) [modo Borrador]
│
├─ Idempotencia por origin_key contra no-cancelados
└─ OUTPUT: Documentos en estado Borrador esperando confirmación

    ↓ CONSUMO Y VISIBILIDAD ↓

SALIDA A ODOO
├─ x_hm_si_forecast → consumida por stock analysis (script 4)
├─ x_analisis_de_stock → Fuente compra, reorden
├─ purchase.order + stock.picking → Odoo workflow
├─ Confirmar OC → stock.move, stock.quant actualiza
│
└─ x_stock_balance_daily [Cron diario]
    (refrescado incremental para quiebre detection v3.48)

ANALÍTICA [PARALELO A PIPELINE]
├─ Team analytics (ventas, margen, cover por sucursal)
├─ Categoría analytics (GMROI, elasticidad)
├─ SKU analytics (performance, lifecycle)
├─ Cobertura ABCXYZ por sala
└─ Competencia pricing (Trébol)

FINANZAS [PARALELO A PIPELINE]
├─ Presupuesto Ventas (forecast descontaminado + evento)
├─ Flujo de Caja (proyección 90d)
└─ Insumos: x_hm_si_forecast + eventos x_promo_plan (futura)

BACKTEST [VALIDACION OFFLINE]
├─ Input: x_hm_si_forecast (últimas 3 sem cerradas)
├─ Input: pos.order real (same 3 sem)
├─ Calcula: WAPE, BIAS por team, regimen, categ
├─ Output: CSV para análisis + diagnóstico
└─ Gestiona: pivoteo, análisis Pareto, anomalías
```

---

## V. LÓGICA DE DECISIÓN CENTRAL (Script 3: HM SI Forecast)

### 5.1 Heurística Base

**SMA Blend:**
```
short_sma = promedio ultimas 6 semanas
long_sma = promedio ultimas 16 semanas

ratio = short_sma / long_sma

if ratio >= ratio_up (1.15):          → tendencia al alza, usa short
    mu_base = short_sma
elif ratio >= ratio_hold (0.90):      → estable, usa long (inercia)
    mu_base = long_sma
elif raw_ratio < ratio_collapse (0.30):  → colapso real, usa short
    mu_base = short_sma
else:                                 → decline suave, blend down
    mu_base = 0.70 * short_sma + 0.30 * long_sma
```

**Deflactación SI:**
```
q_base = q_raw / SI_w   (si SI_ENABLED)
base_vals = [q_base_w1, ..., q_base_w26]
```

### 5.2 Auto-Model Selection (v3.39 — SAP IBP Bake-Off)

**Candidatos:**
1. Heurístico (SMA blend arriba)
2. SBA(α=0.15) — Syntetos-Boylan, corrección para intermitentes
3. Croston(α=0.10) — clásico intermitente
4. Seasonal Naive lag-52 (si n >= 56 sem)

**Entrenamiento:** holdout 4 semanas cerradas, train=resto.
**Evaluador:** MAE en holdout.
**Ganador:** heur_bias=0.90 protege core → heur gana a menos que otro sea ≥10% mejor.

**Resultado:** REG-1 (smooth A) intacto (53.69% WAPE vs 53.68% baseline). REG-5/6 mejora -2.6pp a -10.9pp (lumpy).

### 5.3 Estacionalidad SI Multi-Nivel

**Jerarquía:**
```
w = iso_week (1-52)

SI_main = SI_local_categ(team, categ)[w]
if SI_main is None:
    SI_main = SI_categ_global(categ)[w]
if SI_main is None:
    SI_main = SI_global[w]
```

**Ajuste SKU (si n_years >= 3):**
```
SI_sku_raw / SI_categ_global → desviación
si_factor = 1.0 + alpha * (desviacion - 1.0)   [alpha ∈ {0.15, 0.30}]
SI_final = clamp(SI_main * si_factor, 0.05, 5.0)
```

### 5.4 Fair Share Canonical (v3.42)

**Trigger:** ABC ∈ {A, B} + mu_week=0 + lifecycle ∈ {mature, ramp_up}

**Gating:** Clase B solo si gap_count <= 2 (TERMINAR COBERTURA pequeño).

**Fórmula:**
```
factor_norm = promedio share SKU en otras salas

conf_n = {1→0.30, 2→0.50, 3→0.75, 4→0.75, 5+→1.00}
       (confianza estadística, SAP IBP canon)

growth_cap = {X: 3.0, Y: 2.0, Z: 1.5}   (Blue Yonder)

mu_fs = factor_norm × conf_n × mu_categ_target × growth_cap / gap_count

if active_weeks_target > 0:     # sala ya probó y falló
    mu_fs = mu_fs × 0.15        # tried_penalty
```

**Diagnóstico validado:** 60 SKUs A con <3 salas → 97% "probó y falló" → regla correcta.

### 5.5 Router Forecast (Z1-Z4)

**Entradas:** ABCXYZ, series_type, lifecycle, mu_week

**Outputs:** forecast_zone, forecast_scope, forecast_model_code

| Zone | Trigger | Scope | Ejemplo |
|------|---------|-------|---------|
| **Z1** | AX/AY/BX smooth + mu≥2 O AZ/AX/AY no-terminal | core_hm_si | Heineken Lata, Sprite |
| **Z2** | AX/AY erratic/lumpy + mu≥2 | controlled_hm_si | Vino Premium intermitente |
| **Z3** | BY/BZ, seasonal, fallback | secondary_model | Sidra, Queques estacionales |
| **Z4** | CX/CY/CZ, no_signal, dead, declining | no_forecast | Fast-movers bajo margen |

**v3.45 cambio clave:** removido threshold mu<2.0 del router. Croston/SBA ya calibrados para slow-movers; el threshold post-forecast descartaba su output. Ahora Z3 rescata SKUs B/C con mu<2.0.

### 5.6 Capas de Corrección (Aplicadas en Secuencia)

#### P1: Declinantes → Cero
```
if lifecycle in ('declining', 'dead'):
    mu_week = 0.0
```

#### P3: Zero-Gate Z4
```
if forecast_zone == 'Z4' and lifecycle != 'ramp_up' and regimen != 'REG-8':
    if nz_recent_8w == 0:     # sin ventas últimas 8 sem (SMA-style)
        mu_week = 0.0
```

#### P6: Caps Anti-Spike
```
if mu_week > 0 and base_vals:
    max_obs = max(base_vals)
    if abcxyz == 'BZ':
        mu_week = min(mu_week, max_obs * 0.8)      # lumpy extremo
    elif abcxyz in ('AZ', 'CZ') or (AY smooth en Z2) or (CY en Z4):
        mu_week = min(mu_week, max_obs * 1.2)      # anti-spike
```

#### Corrección Precio (v3.29)
```
factor = x_price_coreccion[product_id].factor  (si existe)

if factor < 0.90 and weeks_since >= 3:         # validación empírica
    empirical_factor = real_post_avg / real_pre_avg
    if (empirical_factor - factor) > 0.15:
        factor = (factor + empirical_factor) / 2.0   # blend atenúa over-corr

mu_week = mu_week * factor
```

#### Categ Calibration (v3.47)
```
factor = x_categ_calib_factor[(categ_id, abc_letter)]

if factor is not None and (regimen in regimenes_aplicables o regimenes_aplicables is None):
    mu_week = mu_week * factor    # [0.70, 1.30]
```

#### Trend Correction (v3.43) — ASIMETRICO
```
Para cada team:
    yoy_i = units[week_i] / units[week_i-52w] - 1    (últimas 8 sem)
    trend_factor[team] = clamp(1 + mean(yoy_i), 0.70, 1.00)
    
En el loop:
    mu_week = mu_week × trend_factor[team]

Resultado validado: Mar-16 BIAS -15.0% → -9.9% (+5.1pp mejora)
Trade-off: Feb-16 empeora +2.65pp (compresión uniforme afecta sub-forecast en algunas categs)
```

#### Bias-Outlier Correction (v3.48) — POST-WRITE
```
1. Lee mu ensamblado (post-trend) + real reciente limpio de quiebre.
2. Acumula por SKU en unidades (no %).
3. Toma Pareto-80% del |error|.
4. Guard persistencia: >= 2 de 3 sem en dirección del delta.
5. Aplica factor multiplicativo GLOBAL por SKU.
6. Clamp asimétrico [0.65, 4.0]:
   - Piso: cortar suave lo largo (over-forecast).
   - Techo: corregir lo corto (sub-forecast cuesta más).

Costo: despreciable. Safety: try/except, nunca rompe forecast.
```

---

## VI. MÉTRICAS DE VALIDACIÓN Y RENDIMIENTO

### 6.1 Benchmark Productivo (Backtest W17-W19)

| Métrica | v3.31 Baseline | Actual (v3.48) | Cambio |
|---------|---|---|---|
| **WAPE Global** | 70.85% | 70.85%* | Línea base |
| **BIAS Global** | -3.16% | Variable | ±2pp |
| **Forecast=0 + Real>0** | 3,870 filas (5.41%) | Similar | Trade-off |
| **WAPE BZ** | 154.5% | 154.5% | Intacto |
| **WAPE CZ** | 136.9% | 136.9% | Intacto |

*Mejoras por capa:
- v3.39 auto-model: -0.42pp (REG-5/6 beneficiados)
- v3.43 trend: -0.36pp localizado (Mar-16, Los Lagos, etc.)
- v3.47 categ_calib: <0.1pp (en prueba)
- v3.48 bias-outlier: <0.05pp (1-2% de SKUs corregidos)

### 6.2 Validación por Régimen

| Régimen | Type | WAPE | BIAS | Notas |
|---------|------|------|------|-------|
| REG-1 | Smooth A | 53.69% | -2.1% | **Control.** Auto-model intacto. |
| REG-2 | Smooth B | 62.4% | -1.8% | Estable. |
| REG-3 | Smooth C | 89.2% | +2.5% | Sub-representado. |
| REG-4 | Erratic | 75.2% | -4.5% | Riesgo amplificación trend. |
| REG-5 | Lumpy A/B | 101.86% | -8.2% | Croston/SBA aportan. |
| REG-6 | Lumpy C | 171.33% | -15.3% | Ultra-esporádico. |
| REG-7 | Intermittent | 89.27% | -5.8% | SMA suficiente. |
| REG-8 | Seasonal | 73.88% | -2.2% | PLC + feriados. |

### 6.3 Validación Fair Share

**SKUs A sin historia local (<3 salas):**
- Total: 60 pares (A-class) en 12 salas.
- Gap: 97% son "probó y falló" (active_weeks_local>0, mu_local=0).
- **Conclusión:** regla fair_share_min_salas=1 correcta.
- **Tried_penalty 0.15:** bien calibrada (evita insistencia en flacos).

---

## VII. ARQUITECTURA TÉCNICA

### 7.1 Stack

| Componente | Detalles |
|------------|----------|
| **Hosting** | AWS, Odoo 17 EE |
| **BD** | PostgreSQL (advisory locks, SAVEPOINT defensivos) |
| **Lenguaje** | Python 3 (Odoo Server Action sandbox) |
| **Dependencias** | CERO (no numpy/scipy, solo built-ins) |
| **Lock** | PostgreSQL advisory lock LOCK_KEY=99009438 (HM-SI v3.48) |
| **Batch Size** | 500 registros por insert batch |
| **Testing** | Backtest CSV + análisis per-régimen (offline) |
| **CI/CD** | Manual (usuario confirma git post-validación) |

### 7.2 Sandboxes y Defensas

- **SAVEPOINT en lectura contexto:** si fail router/correccion/categ_calib → rollback, insumo vacío, forecast no rompe.
- **Try/Except bias-outlier:** última capa nunca bloquea pipeline.
- **Advisory locks:** evita ejecuciones concurrentes (LOCK_KEY único por script).
- **Combo explosion SQL:** maneja kits phantom + padre/hijo.
- **Timezone-aware queries:** POS timestamps converted a Santiago (TZ_NAME).

### 7.3 Parámetros Expuestos (Context Override)

Scripts aceptan context dict para cambiar comportamiento sin codear:

```python
# Script 3 (HM SI Forecast)
context = {
    'fwd_model': 'x_hm_si_forecast',
    'hard_reset': True,
    'team_ids': [5,6,7,8,9,10,11,12,13,16,17,18],
    'demand_history_months': 24,
    'demand_window_weeks': 26,
    'si_enabled': True,
    'apply_trend_correction': True,
    'apply_categ_calib': True,
    'apply_bias_outlier': True,
    'use_demand_normalization': True,
}

# Ejemplo desactivar capas:
context['apply_trend_correction'] = False  # sin trend_factor
context['apply_bias_outlier'] = False      # sin v3.48
```

---

## VIII. PROYECTOS EN CURSO Y PENDIENTES

### 8.1 Normalizacion de Demanda (2026-05-25)

**Estado:** En prueba (USE_DEMAND_NORMALIZATION_DEFAULT = True).

**Propósito:** Corregir demanda censurada por quiebre (x_stock_balance_daily).

**Mecanica:** Overlay x_demanda_normalizada reemplaza q_raw en script 3 cuando hay stockout.

**Próximo paso:** Post-validación backtest → default permanente.

---

### 8.2 Detector Aprende Factores (2026-05-13+)

**Pendiente:** Refactor detector v5.8 → factores empíricos por SKU.

**Hoy:** Tabla hardcoded (elasticidad ABC=1.3/1.0/0.7).

**Futuro:** Calibración dinámica desde demanda real post-cambio.

---

### 8.3 Fair Share Extendido

**Potencial:** Granularidad categ_L2 en lugar de categ global.

**Diagnóstico:** Regla actual correcta, pero marginal gain potencial.

**Estado:** No prioridad (regla v3.42 ya robusto).

---

### 8.4 April-6 Motor Cutoff Bug (Diagnosticar)

**Síntoma:** Cuando cutoff < 8 sem de hoy, ~99% SKUs → forecast=0.

**Causa probable:** Presencia trimestral u_q0=0 genera lifecycle "declining" falso.

**v3.44 parcial fix:** Added check nz_recent_8w, pero requiere diagnóstico profundo.

---

### 8.5 Presupuesto Integración

**Estado:** Script 5 (OH Presupuesto Ventas) consume backtest y calibra baseline.

**Patrón:** "baseline + evento" idéntico a correcciones (precio, trend).

**Coordinación:** Armonizar source of truth (forecast motor vs presupuesto).

---

## IX. GUÍA OPERATIVA

### 9.1 Ejecutar Pipeline Completo

```
1. Script 1: OH Calculo ABCXYZ (cron semanal, lunes 6am)
   └─ Actualiza x_calculo_abc_xyz (5,241 SKUs)

2A. Detector Precio v5.8 (cron diario)
    └─ Actualiza x_price_coreccion (47 eventos aprox)

2B. Margen SA 1435 (cron diario)
    └─ Actualiza x_margen_por_producto_

3. Script 3: HM SI Forecast v3.48 (cron semanal, lunes 8am)
   └─ Cálculo: ~45 seg (12 teams × 5,241 SKUs)
   └─ Salida: x_hm_si_forecast (62,892 registros/semana)
   └─ Auditoria: Full trail de transformaciones

4. Script 4: OH Analisis de Stock v9.1.86 (cron semanal, lunes 9am)
   └─ Cálculo: ~30 seg (12 teams × 5,241 SKUs)
   └─ Salida: x_analisis_de_stock (decisiones compra)

5. Script 5: OH Generacion de Documentos (manual, lunes 10am)
   └─ Crea: purchase.order + stock.picking (Borrador)
   └─ Revisión humana Compras + Operaciones
   └─ Confirmación → stock.quant actualiza
```

### 9.2 Validar Resultados

```
1. Backtest: Ejecutar "4- OH Forecast Backtest.py"
   - Input: x_hm_si_forecast (últimas 3 sem cerradas)
   - Output: CSV con WAPE/BIAS por team/regimen/categ
   - Comparar vs snapshot anterior (memory proyecto-motor)

2. Dashboard analítica:
   - x_hm_si_forecast: revisar forecast_zone, demanda_method, correcciones
   - x_analisis_de_stock: buy_action, qty_a_comprar, estado
   - Anomalías: búsquedas por BIAS extreme, WAPE > 200%

3. Campos auditoria:
   - x_studio_mu_week (final)
   - x_studio_mu_week_pre_bias (pre-trend)
   - x_studio_correccion_factor (precio)
   - x_studio_categ_calib_factor (sesgo cat)
   - x_studio_bias_outlier (si v3.48 aplicó)
```

### 9.3 Troubleshooting

| Síntoma | Causa Probable | Solución |
|---------|---|---|
| WAPE sube sin cambios visibles | Contaminación quiebre | Validar x_stock_balance_daily |
| Forecast=0 masivo | Lifecycle "declining" falso | Revisar nz_recent_8w check |
| Trend empeora REG-8 | Compresión uniforme por team | Reducir TREND_CLAMP_LOW o granularidad |
| Fair share NO aplica | Gating abc_letter, gap_count | Revisar allowed_abc, b_max_gap |
| Auto-model no gana | Heuristic-bias=0.90 protege | Bajar a 0.80 o revisar MAE holdout |

---

## X. REFERENCIAS Y DOCUMENTACIÓN

### Scripts Productivos
- [01_segmentacion/OH Calculo ABCXYZ.py](01_segmentacion/OH Calculo ABCXYZ.py) — v19.4
- [02_forecast/HM SI Forecast.py](02_forecast/HM SI Forecast.py) — v3.48
- [02_forecast/OH Price Correccion.py](02_forecast/OH Price Correccion.py) — v5.8
- [03_stock/OH Analisis de Stock.py](03_stock/OH Analisis de Stock.py) — v9.1.86
- [03_stock/OH Generacion de Documentos.py](03_stock/OH Generacion de Documentos.py) — v1.5

### Backtests & Analítica
- [02_forecast/OH Forecast Backtest.py](02_forecast/OH Forecast Backtest.py) — validación
- [proyectos/2026-05-26-backtest-3-no-consecutivas/](proyectos/2026-05-26-backtest-3-no-consecutivas/) — laboratorio v3.43+

### Memoria Distribuida (Auto-memory)
- [[project-motor-productivo-2026-05-12]] — snapshot v3.31
- [[hm-si-v3-43-trend-correction]] — trend correction
- [[auto-model-per-sku-funciona]] — bake-off SAP IBP
- [[forecast-backtest-context]] — CSV schema
- [[modelo-separacion-responsabilidades]] — arquitectura tables
- [[feedback-objetivo-declarado]] — preferencias macro

### Decisiones Arquitecturales
- [[si-deflation-enmascara-colapso]] — por qué v3.36 usa raw_vals para ratio
- [[sma-short-calibration]] — SMA(6) es sweet spot
- [[fair-share-flacos]] — diagnóstico 60 SKUs A
- [[hm-si-no-seasonal-band]] — por qué SI no usa SEASONAL_BAND legacy

---

## XI. CONCLUSIÓN

El sistema OH Market integra 5 scripts productivos + capas paralelas en un pipeline robusto y auditable. El motor HM SI Forecast (script 3, v3.48) es el corazón: 7 capas de transformación determinísticas (demanda base → SI → correcciones → precio → categ → trend → bias-outlier) que generan pronósticos de demanda semanal consumidos por stock analysis para reorden.

**Principios clave:**
- Canon SAP IBP / Blue Yonder (fair share, bake-off, SI multi-nivel).
- Separación de responsabilidades (ABCXYZ ≠ análisis stock operativo).
- Auditoria completa (9+ campos trail por (team, SKU, semana)).
- Asimetría en correcciones (sub-forecast cuesta más que over).
- Defensa en profundidad (try/except, SAVEPOINT, locks advisory).

**Próximos pasos:** Validar normalización demanda post-rollout, diagnosticar April-6 cutoff bug, refactor detector a factores empíricos.

---

**Documento compilado 2026-05-29 por Claude Code**  
**Preguntas: consultar memory, CLAUDE.md, o scripts CHANGELOG.md**
