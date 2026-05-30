# Diseño: SKU Mapping y Outlier Detection

**Fecha:** 2026-05-30  
**Objetivo:** Validar mapeos de SKUs entre sistemas y detectar outliers en product_id

## Problema

Necesidad de asegurar:
1. **Mapeo consistente** de product.product ↔ product.template
2. **Detección de outliers** — SKUs con comportamiento anómalo
3. **Integridad** de product_id en modelos Studio (x_analisis_de_stock, x_hm_si_forecast)

**Síntoma:** Posibles desajustes entre Studio (product.template) y POS (product.product) afectando análisis.

## Solución Propuesta

### Línea 1: Mapeo SKU
- **verificar_mapeo_sku.py** — auditar relaciones product.product → product.template
- Validar: sin duplicados, sin huérfanos, tipos correctos
- **Output:** reporte de inconsistencias

### Línea 2: Outlier Product
- **debug_outlier_product_id.py** — detectar product_ids anómalo
- SKUs con pocas semanas de venta, cambios de template, discontinuados
- **Output:** lista de candidates para revisión manual

## Decisión Pendiente

¿Hay product_ids que deberían excluirse de análisis (p. ej., productos descontinuados)?

---

**Siguiente:** ver plan.md para tareas.
