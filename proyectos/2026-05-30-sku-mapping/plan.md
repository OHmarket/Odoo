# Plan: SKU Mapping y Outlier Detection

**Estado:** En investigación  
**Scripts:** verificar_mapeo_sku.py, debug_outlier_product_id.py

## Tareas

- [ ] **Fase 1: Auditoría de Mapeo**
  - [ ] verificar_mapeo_sku.py — validar relaciones product
  - [ ] Detectar: duplicados, huérfanos, inconsistencias de tipo
  - [ ] Comparar vs x_studio_product_id en modelos Studio
  - **Output esperado:** reporte de issues de mapeo

- [ ] **Fase 2: Detección de Outliers**
  - [ ] debug_outlier_product_id.py — identificar product_ids anómalo
  - [ ] Clasificar: discontinuados, pocas semanas de venta, cambios recientes
  - [ ] Marcar para revisión manual
  - **Output esperado:** lista de candidates para exclusión

- [ ] **Fase 3: Decisión de Scope**
  - [ ] ¿Excluir product_ids descontinuados de análisis?
  - [ ] ¿Afecta WAPE si excluyo estos SKUs del backtest?
  - [ ] Marco decide criterio
  - **Output esperado:** documento de política de exclusión

- [ ] **Fase 4: Implementación (si aplica)**
  - [ ] Crear lista blanca/negra de product_ids en Script 1 o Script 5
  - [ ] Actualizar governance/VALIDATION_CHECKLIST.md
  - [ ] Integrar en pipeline productivo si hay cambios

## Progress

| Tarea | Estado | Notas |
|-------|--------|-------|
| Auditoría Mapeo | 🧪 En curso | verificar_mapeo_sku.py |
| Detección Outliers | 🧪 En curso | debug_outlier_product_id.py |
| Decisión de Scope | ⏳ Pendiente | Requiere input Marco |
| Implementación | ⏳ Pendiente | Espera decisión |

---

**Riesgo:** Si hay muchos product_ids con problemas, puede afectar universo de análisis.

**Próximo paso:** Revisar reportes de auditoría y mapeo.
