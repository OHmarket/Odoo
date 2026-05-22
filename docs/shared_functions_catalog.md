# Shared Functions Catalog — OH Market

Funciones que aparecen implementadas en múltiples scripts. Candidatas a centralizar en
`shared/` cuando los scripts migren a módulos Odoo instalables (hoy corren bajo `safe_eval`
que bloquea imports externos).

Para cada función se indica: firma canónica, qué hace, y en qué scripts está implementada hoy.

---

## Módulo: `calendar_rules`

Reglas del calendario OH Market: semana lunes-domingo, LY-364, bandas estacionales.

### `oh_week_start(d: date) -> date`
Retorna el lunes de la semana de `d`. Estándar OH: semana = lunes a domingo.
Implementado en: SKU v12, Categ v10, Team v13, ABCXYZ v19.4, Price Correccion v5.8, Presupuesto v13.

### `oh_week_end(d: date) -> date`
Retorna el domingo de la semana de `d`.
Implementado en: SKU v12, Categ v10.

### `ly_364(d: date) -> date`
Retorna `d - 364 días` (52 semanas exactas, mismo weekday). Estándar OH para comparar
periodos equivalentes sin desplazamiento de día de la semana.
Implementado en: SKU v12, Presupuesto v13.

### `oh_iso_week(week_start: date) -> int`
Retorna el número de semana ISO (1–53) a partir del lunes de semana.
Implementado en: SKU v12, Categ v10.

### `iter_week_starts(d1: date, d2: date) -> Iterator[date]`
Genera todos los lunes en el rango `[d1, d2]`.
Implementado en: SKU v12, Categ v10.

### `month_start(d: date) -> date` / `month_end(d: date) -> date`
Inicio y fin del mes de `d`.
Implementado en: Team v13, Flujo de Caja v1.3.

### `iter_month_starts(d1: date, d2: date) -> Iterator[date]`
Genera todos los primeros días de mes en el rango `[d1, d2]`.
Implementado en: Team v13.

### Bandas estacionales (ISO week)

Clasificación por número de semana ISO:

| Banda | Semanas ISO | Contexto |
|-------|-------------|----------|
| `VERANO_ALTO` | 1–3, 52–53 | Fin de año / inicio enero |
| `VERANO_MEDIO` | 4–8 | Enero medio / febrero |
| `VERANO_BAJO` | 9–12 | Marzo |
| `FIESTAS_PATRIAS` | 37–38 | Septiembre |
| `HALLOWEEN` | 43–44 | Octubre |
| `FIN_ANIO` | 49–51 | Noviembre–diciembre |
| `BASE` | resto | Semanas estándar |

Implementado en: SKU v12. Referencia en: Presupuesto v13 (usa enfoque diferente de offsets).

---

## Módulo: `sales_reader`

Lectura de ventas POS con detección dinámica de campos según versión Odoo.

### `detect_team_field(env) -> str`
Detecta si `pos.config` usa `crm_team_id` (v14+) o `team_id` (v13). Retorna nombre del campo.
Implementado en: SKU v12, Categ v10, Team v13, Margen, Presupuesto v13 (como `_first_existing_field`).

### `detect_type_field(env) -> str`
Detecta si `product.template` usa `detailed_type` (v16+) o `type` (v13-v15).
Implementado en: SKU v12, Categ v10, Team v13, Margen.

### `fetch_pos_agg(cr, team_ids, date_from, date_to, team_field, type_field) -> list[dict]`
SQL agregado de ventas POS por (team, product, semana). Maneja combos internamente.
Retorna filas con: team_id, product_id, week_start, qty_sold, sales_gross.
Implementado en: SKU v12 (función `fetch_rows`), Categ v10, Team v13.

---

## Módulo: `combo_explosion`

Separación de productos combo en sus componentes reales para análisis de SKU.

### `explode_combo_sql(cr, team_ids, date_from, date_to, ...) -> list[dict]`
SQL que retorna dos conjuntos de líneas:
1. **Standalone:** líneas sin `combo_parent_id` que no sean tipo 'service'/'combo'
2. **Children:** líneas hijo con `combo_parent_id`, con prorrateo de venta bruta
   según peso del hijo dentro del combo

Sin combo explosion, los análisis SKU sobreestiman los productos combo y subestiman los
componentes.

Implementado en: SKU v12 (`fetch_rows`), Categ v10, Team v13, Margen.

**Detección de disponibilidad:** `combo_parent_id` solo existe en Odoo v16+. Los scripts
verifican la columna via `information_schema.columns` antes de usarla.

---

## Módulo: `cost_reader`

Lectura de costo real del producto con manejo de impuestos anidados.

### `raw_to_cost_net(product, fallback_to_standard=True) -> float`
Lee `raw_product_price` del producto. Si es 0 o no existe, usa `standard_price` como fallback.
Retorna el costo neto por unidad antes de impuestos.
Implementado en: Margen (función `_ensure_cost`).

### `flatten_taxes(tax_record, env) -> list[dict]`
Descompone recursivamente un impuesto (incluye grupos de impuestos anidados) en una lista plana
con: `{amount: float, type_tax_use: str, name: str, price_include: bool}`.
Implementado en: Margen (función `_flatten_taxes`), Flujo de Caja.

### `iva_compra_factor(product, env) -> float`
Detecta IVA en `product.supplier_taxes_id` y retorna el multiplicador (ej: 1.19 para IVA 19%).
Implementado en: Margen (función `_iva_compra_factor`).

### `sum_ila_factor(product, env) -> float`
Suma todos los impuestos tipo ILA en `product.supplier_taxes_id`. Retorna factor acumulado.
Implementado en: Margen (función `_sum_ila_factor`).

### `is_no_recuperable(tax_record) -> bool`
Detecta si un impuesto es "no recuperable" (uso común) basado en keywords en nombre/grupo.
Implementado en: Margen, Flujo de Caja.

---

## Módulo: `stock_reader`

Mapeo entre equipos (sucursales) y almacenes Odoo.

### `build_team_warehouse_map(env) -> dict[int, int]`
Lee `pos.config` y construye el mapeo `{team_id: warehouse_id}` via `crm_team_id` o `team_id`.
Implementado en: Stock Analisis, Stock Balance Daily, Generacion Documentos (como lookup inline).

### `TEAM_WAREHOUSE_MAP_FALLBACK: dict[int, int]`
Dict hardcoded de fallback cuando `pos.config` no tiene el mapeo completo. Usado como
capa de seguridad.
Implementado en: Stock Analisis, Generacion Documentos.

### `get_stock_loc_from_wh(wh_id, env) -> int`
Retorna el `lot_stock_id` (ubicación interna principal) del warehouse dado.
Implementado en: Stock Analisis (`_get_stock_loc_from_wh`), Generacion Documentos.

### `get_in_type_from_wh(wh_id, env) -> int`
Retorna el `picking_type` de tipo 'incoming' del warehouse.
Implementado en: Stock Analisis (`_get_in_type_from_wh`), Generacion Documentos.

### `get_internal_type_from_wh(wh_id, env) -> int`
Retorna el `picking_type` de tipo 'internal' del warehouse.
Implementado en: Stock Analisis, Generacion Documentos.

---

## Módulo: `odoo_safe_eval_helpers`

Utilidades genéricas para scripts bajo `safe_eval`. Todas sin imports externos.

### Conversiones seguras

| Función | Firma | Descripción |
|---------|-------|-------------|
| `_safe_float` | `(v, default=0.0) -> float` | Convierte a float, retorna default si falla |
| `_safe_int` | `(v, default=0) -> int` | Convierte a int, retorna default si falla |
| `_safe_text` | `(v, maxlen=255) -> str` | Convierte a str y trunca |
| `_safe_bool` | `(v, default=False) -> bool` | Convierte a bool tolerante |
| `_ctx_bool` | `(ctx, key, default=False) -> bool` | Extrae bool del contexto de server action |
| `_to_int_list` | `(v) -> list[int]` | Convierte string/list a lista de enteros |
| `safe_div` | `(num, den, default=0.0) -> float` | División segura (den=0 → default) |

Implementado en: todos los scripts.

### `batch_create(env, model_name, vals, batch_size=500) -> int`
Crea registros en lotes para evitar memory bloat. Retorna total creado.
Implementado en: todos los scripts que escriben modelos Studio.

### `acquire_advisory_lock(cr, lock_key: int) -> bool`
Ejecuta `pg_try_advisory_lock(lock_key)`. Retorna True si se obtuvo el lock.
Implementado en: ABCXYZ, HM SI, Price Correccion, Cambio Precio, Generacion Docs, Stock Daily.

### `release_advisory_lock(cr, lock_key: int)`
Ejecuta `pg_advisory_unlock(lock_key)`. Llamar siempre en bloque `finally`.
Implementado en: mismos scripts.

### `delete_range_sql(cr, table_name, team_ids, date_field, d1, d2)`
DELETE SQL directo sin ORM para borrar rango de fechas por equipo. Evita overhead de
`search + unlink` en modelos Studio sin lógica de negocio.
Implementado en: SKU v12, Categ v10, Team v13, Presupuesto v13, Margen.

### `dry_run_guard(dry_run: bool, counts: dict) -> dict | None`
Si `dry_run=True`, retorna dict con conteos sin ejecutar escrituras. Patrón estándar.
Implementado en: SKU v12, Categ v10, Team v13, Presupuesto v13.

### `notify_action(title: str, message: str, type='success', sticky=False) -> dict`
Retorna el dict de acción `display_notification` para notificaciones Odoo.
Implementado en: todos los scripts.

---

## Módulo: `field_map`

Introspección dinámica de campos para adaptarse a diferentes versiones de Odoo/Studio.

### `first_existing_field(model, candidates: list[str], env) -> str | None`
Retorna el primer nombre de campo de `candidates` que existe en `model`. Retorna None si
ninguno existe.
Implementado en: ABCXYZ, HM SI, Price Correccion, SKU, Categ, Presupuesto (como `_first_field`
o `_first_existing_field`).

### `first_m2o_field(model, candidates: list[str], comodel: str, env) -> str | None`
Como `first_existing_field` pero solo acepta campos Many2one que apunten a `comodel`.
Implementado en: ABCXYZ, HM SI, Price Correccion.

### `put_field(vals: dict, fields_map: dict, fname: str, value, maxlen=255)`
Escribe `value` en `vals[fname]` con type checking según `fields_map`. Si el campo es
`selection`, normaliza case-insensitive. Si no existe en `fields_map`, lo omite con log.
Implementado en: ABCXYZ, HM SI, Price Correccion.

### `detect_holiday_model(env) -> str`
Busca si existe `x_holiday_occurrence` en el entorno. Retorna nombre del modelo o None.
Implementado en: SKU v12 (`_detect_holiday_model`).

### `holiday_week_counts(env, week_starts: list[date], team_ids: list[int], ...) -> dict`
Retorna dict `{week_start: {has_holiday: bool, holiday_days: int, in_band_key: str}}`.
Lee de `x_holiday_occurrence` + `x_holiday_master` con offsets P (pre-feriado) y H (feriado).
Fallback: lista manual desde contexto.
Implementado en: SKU v12 (`_holiday_week_counts`), Presupuesto v13 (`_apply_holidays_from_model`).

### `is_active_record(record) -> bool`
Verifica si un registro tiene campo `active` y su valor es True. Tolerante a modelos sin `active`.
Implementado en: SKU v12, Categ v10 (como `_is_active_record`).

---

## Módulos adicionales de forecast (sin dependencias Odoo)

Estos modelos son matemáticamente puros y portables fuera de Odoo.

### `_forecast_models` — Modelos de demanda intermitente

| Función | Descripción | Referencia |
|---------|-------------|------------|
| `croston(base_vals, alpha=0.10)` | Croston 1972: estimación separada de magnitud e intervalo | Croston 1972 |
| `sba(base_vals, alpha=0.15)` | Syntetos-Boylan-Adebiyi: corrección de sesgo de Croston | Syntetos-Boylan 2005 |
| `mae_of_forecast(base_vals, forecast, holdout_weeks=4)` | Mean Absolute Error sobre holdout | Hyndman-Koehler 2006 |
| `max_observed(base_vals) -> float` | Máximo histórico en ventana de base_vals | — |

Implementado en: HM SI Forecast v3.39 (bake-off AUTO_MODEL).

### `_si_helpers` — Índice estacional multi-nivel

| Función | Descripción |
|---------|-------------|
| `get_si_from_weekly(weekly_dict) -> dict[int, float]` | Calcula SI normalizado por ISO week (promedio / media global) |
| `get_si_final(si_sku, si_local_categ, si_categ_global, si_global, alpha_sku) -> float` | Selecciona SI jerárquico con clamp [0.05, 5.00] |
| `calc_si_from_weekly(weekly_data, iso_week, min_n=1) -> float` | SI para una semana ISO específica |

Implementado en: HM SI Forecast v3.39.

---

## Resumen de duplicación por función

| Función | Veces implementada | Scripts |
|---------|-------------------|---------|
| `_safe_float` | 8 | todos |
| `_safe_int` | 6 | ABCXYZ, HM SI, Price Correccion, Cambio Precio, Stock |
| `oh_week_start` / `_week_start` | 7 | ABCXYZ, HM SI, Price Correccion, Cambio Precio, SKU, Categ, Presupuesto |
| `_first_existing_field` | 5 | ABCXYZ, HM SI, Price Correccion, SKU, Categ |
| `batch_create` (inline) | 8 | todos los que escriben Studio |
| `advisory_lock` (pattern inline) | 6 | ABCXYZ, HM SI, Price Correccion, Cambio Precio, Gen Docs, Stock Daily |
| `delete_range_sql` (inline) | 6 | SKU, Categ, Team, Presupuesto, Margen, Flujo Caja |
| combo explode SQL | 4 | SKU, Categ, Team, Margen |
| `notify_action` | 8 | todos |
