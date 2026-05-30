# Plan: Análisis de Quiebre en Categoría Cigarrillos

**Estado:** En investigación  
**Scripts:** diagnosticar_quiebre_cigarrillos.py, debug_cigarro_quiebre.py

## Tareas

- [ ] **Fase 1: Diagnóstico**
  - [ ] diagnosticar_quiebre_cigarrillos.py — mapear quiebres por local y SKU
  - [ ] debug_cigarro_quiebre.py — análisis detallado de casos específicos
  - [ ] Generar reports: frecuencia, duración, distribución
  - **Output esperado:** CSV de quiebres identificados

- [ ] **Fase 2: Análisis de Causa**
  - [ ] Correlacionar con promotions (x_loyalty_promo_event)
  - [ ] Correlacionar con cambios de precio (Script 2 input)
  - [ ] Revisar stock real vs forecast en esos períodos
  - **Output esperado:** documento de patrones identificados

- [ ] **Fase 3: Decisión**
  - [ ] ¿Filtrar del backtest (quiebres = no válido para validar forecast)?
  - [ ] ¿O mejorar capacidad del motor para predecir quiebres?
  - [ ] Marco decide scope
  - **Output esperado:** criterio de exclusión documentado

- [ ] **Fase 4: Implementación (si aplica)**
  - [ ] Actualizar `governance/VALIDATION_CHECKLIST.md` con exclusión
  - [ ] Integrar en Script 5 (Backtest) si decide filtrar
  - [ ] Actualizar governance/CHANGELOG.md

## Progress

| Tarea | Estado | Notas |
|-------|--------|-------|
| Diagnóstico | 🧪 En curso | Scripts ejecutando |
| Análisis de causa | ⏳ Pendiente | Espera diagnóstico |
| Decisión | ⏳ Pendiente | Requiere input Marco |
| Implementación | ⏳ Pendiente | Espera decisión |

---

**Próximo paso:** Revisar resultados de diagnóstico, presentar opciones a Marco.
