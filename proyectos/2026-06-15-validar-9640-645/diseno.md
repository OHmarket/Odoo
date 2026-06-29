# Sensibilidad de la de-censura (cleanse_min_days) — efecto sobre μ, σ y orden

Fecha: 2026-06-15
Origen: validación del transfer 95u para SKU 9640 → Panguipulli 645 (team 8).

## Fase 0 — Diseño

### 1. Qué problema medir
El motor (OH Forecast Base) calcula μ y σ sobre la serie **des-censurada** (cleansing
etapa 2, `cleanse_min_days=1`). La de-censura entra DOBLE en la orden: sube μ
(base) y sube σ (safety). Para 9640/645 levantó μ ~39→56 y σ ~14→26, llevando el
target a 107u y el transfer a 95u. Queremos medir cuánto cambian μ, σ, target y
transfer si la de-censura es menos agresiva (`cleanse_min_days` 1→2→3→4) o se apaga.

### 2. Qué decisión se toma
Si subir `cleanse_min_days` baja el sobre-forecast sin generar sub-forecast en las
semanas realmente quebradas, es candidato a calibración productiva del context del
motor. Es un parámetro de context, no un cambio de código.

### 3. Qué pasa si se equivoca
- Subir min_days de más → sub-censura → forecast cae bajo la demanda real en SKUs
  con quiebre crónico → sub-stock. (Caro: memoria `feedback_objetivo_declarado`,
  sub-forecast cuesta más que over.)
- Bajar de más → over-forecast → stock muerto (caja).
Por eso se MIDE antes de tocar; no se promueve en este proyecto.

### 4. Teoría / ERP
Demand unconstraining (Manhattan / SAP IBP / Oracle Demantra): reconstruir demanda
no satisfecha por quiebre antes de estimar. El canon NO prescribe un umbral de días
fijo; min_days es un PROXY de "¿cuánto quiebre amerita corregir?". Medimos su
sensibilidad, no inventamos fórmula.

### 5. Enfoques posibles
- (A) Replicación offline read-only del motor (cleanse + SES + sigma) variando
  min_days. Sin tocar producción. ELEGIDO.
- (B) Correr el motor en Odoo con distinto context y hard_reset=False a un modelo
  scratch. Descartado: riesgo de pisar x_hm_si_forecast productivo.
- (C) Backtest WAPE por min_days. Descartado como métrica primaria: medir forecast
  des-censurado vs venta censurada infla el error artificialmente
  (`feedback_doble_conteo_decensura`, `quiebre_no_medir_por_wape`).

### 6. Enfoque elegido y qué NO se hace
(A). Read-only. NO se promueve cambio. NO se mide por WAPE como veredicto. La
métrica es el delta de μ/σ/target/transfer y cuántas semanas-quiebre se dejan de
corregir. Combos quedan fuera del cohorte v0 (9640 es standalone).

### 7. Casos canónicos de validación
GATE: reproducir offline el μ=56.4 / σ=26.2 del motor para 9640/team8 a min_days=1.
Si no reproduce (±5%), la replicación no es fiable y el experimento se detiene.

## Datos (read-only, XML-RPC)
- Venta cruda semanal por (team, sem): `x_forecast_backtest.x_studio_real_qty`
  (ya combo-expandida por el motor; ventana corta basta, SES(0.5) converge).
- Días de quiebre/sem: `x_stock_balance_daily` (stockout/partial/balance<=0).
- Perfil DOW global: `read_group` de pos.order.line por día (~56 filas).

## Parámetros del motor a replicar (defaults productivos)
window=26, MEDIAN_K=4, ALPHA_SMOOTH_A=0.5 (clase A smooth), severe=0.5,
base_k=6, lookback=16, dow_profile=12 sem.
