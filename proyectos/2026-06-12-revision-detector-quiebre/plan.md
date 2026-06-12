# Plan — detector de quiebres por evidencia

Diseño: [diseno_fase0.md](diseno_fase0.md). Diagnóstico: [diseno.md](diseno.md).
Regla: una versión = un cambio. Validar en casos canónicos antes de promover.

## Fase 1 — calibración previa (read-only, sin tocar productivo)

- [x] **T1. Distribución de gaps entre ventas por SKU/sala** → **N = 45 días**
  (PROXY). Cubre X 99,5% / Y 96,8%; Z >45d es correcto no marcar. Ver
  [resultados/T1_calibracion_N.md](resultados/T1_calibracion_N.md).
- [ ] **T2. Snapshot de validación:** congelar un set de (sala, SKU, día) con su
  quant real, venta y movimientos, para comparar v2.0 vs método nuevo en los 6
  casos canónicos del diseño.

## Fase 2 — núcleo (enfoque C), una versión

- [x] **T3. Reescribir detección:** [OH Quiebre de Stock v3.py](OH%20Quiebre%20de%20Stock%20v3.py)
  (STOCKOUT_v3_1). Evidencia (stock-primero + venta=prueba) + piso 0 + gate
  N=45 + `reliable[]` que corta el tail de drift. Lógica verificada local con
  [test_deteccion.py](test_deteccion.py) (9 casos canónicos + episodio onset + reliable + gate, todos OK).
- [x] **T3b (v3.2). Marca continua mientras falte:** decisión de Marco
  2026-06-12 — "que siga marcando cuando no está". El bound de onset W=14
  (v3.1, cortaba el episodio a 2 semanas) fue retirado; el episodio queda
  acotado solo por el gate de actividad (45d sin venta → deslistado). Volumen
  ~1M filas en backfill aceptado explícitamente (modelo Studio propio; el
  costo a cuidar es de queries, no de datos).
  **Pendiente:** correr v3.2 dentro de Odoo — validar SOLO con el dict del log
  (cero queries externas; servidor es productivo).
- [ ] **T3c. Filtro `available_in_pos`:** hoy se usa `sale_ok` (5 productos de
  diferencia, inmaterial). Cambiar en versión aparte (una versión, un cambio).
- [ ] **T4. Backfill controlado:** re-derivar el histórico con la detección por
  evidencia (robusta al drift). Marcar parciales de historia profunda como
  best-effort si hace falta flag de confianza.
- [ ] **T5. Medir:** % días-quiebre con venta (esperado ~0, hoy 44,6%), %
  negativos (esperado 0, hoy 59,5%), conteo total (debe caer el tail perpetuo),
  parciales conservados (~41%). Validar los 6 casos canónicos.

## Fase 3 — censura semanal (consumo del backtest)

- [ ] **T6. Agregar a (sala, SKU, semana):** total censura si ≥1 día quiebre
  total; parcial censura parcial. Confirmar cómo lo consume OH Forecast Backtest.

## Fase 4 — opcional, diferible

- [ ] **T7. Lost-sales sizing intradía** con timestamps `pos.order.line` sobre el
  41% parcial. Solo si T5 muestra que el peso lo justifica.

## Promoción

- [x] **Promovido a productivo 2026-06-12:** v3.2 movido a
  `03_stock/OH Quiebre de Stock.py` (reemplaza STOCKOUT_v2_0). Carpeta del
  proyecto queda como historial.
- [ ] Commit a GitHub: pendiente confirmación explícita de Marco ("subir"/"dale").
