# Diseño: Stock Analysis y Balance

**Fecha:** 2026-05-30  
**Objetivo:** Diagnosticar anomalías en cálculo de stock diario y balance de inventario

## Problema

Necesidad de validar:
1. **Stock real** reportado vs esperado (auditoría)
2. **Stock balance diario** (Script: Stock Balance Daily.py) — reconstrucción de historial
3. **Impacto en qty_a_pedir** cuando stock está corrupto o inconsistente

## Solución Propuesta

Dos líneas de investigación:

### Línea 1: Stock May 2026
- **debug_stock_may2026.py** — auditoría de stock en mayo 2026
- Validar: saldos diarios, movimientos, consistencia
- **Output:** reporte de anomalías por local/SKU

### Línea 2: Stock Balance Product
- **debug_stock_balance_product_id.py** — detalle por product_id
- Validar: reconstrucción histórica del balance daily
- **Output:** dataset de inconsistencias

## Decisiones Pendientes

1. ¿Hay corrupción de datos en stock real?
2. ¿Stock Balance Daily está calculando bien?
3. ¿Afecta a qty_a_pedir (lo cual afectaría OC en Script 4)?

---

**Siguiente:** ver plan.md para tareas.
