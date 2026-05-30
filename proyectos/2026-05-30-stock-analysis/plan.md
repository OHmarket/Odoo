# Plan: Stock Analysis y Balance

**Estado:** En investigación  
**Scripts:** debug_stock_may2026.py, debug_stock_balance_product_id.py

## Tareas

- [ ] **Fase 1: Auditoría de Stock (May 2026)**
  - [ ] debug_stock_may2026.py — revisar saldos diarios
  - [ ] Validar contra datos de POS real
  - [ ] Identificar SKUs/locales con inconsistencias
  - **Output esperado:** reporte de anomalías

- [ ] **Fase 2: Auditoría de Balance Daily**
  - [ ] debug_stock_balance_product_id.py — validar reconstrucción histórica
  - [ ] Comparar vs stock real grabado en x_studio_stock_real
  - [ ] Detectar gaps o desajustes
  - **Output esperado:** timeline de inconsistencias por product

- [ ] **Fase 3: Impacto Analysis**
  - [ ] ¿Afecta a qty_a_pedir en Script 3?
  - [ ] ¿Hay OC generadas con qty incorrecto?
  - [ ] Scope del daño (cuántos SKUs, cuántos locales)
  - **Output esperado:** assessment de impacto

- [ ] **Fase 4: Decisión + Remediation**
  - [ ] Si hay corrupción: limpiar datos
  - [ ] Si hay bug en scripts: fix + re-ejecutar
  - [ ] Actualizar governance/CHANGELOG.md si se ejecuta remediation

## Progress

| Tarea | Estado | Notas |
|-------|--------|-------|
| Auditoría Stock May | 🧪 En curso | debug_stock_may2026.py |
| Auditoría Balance Daily | 🧪 En curso | debug_stock_balance_product_id.py |
| Impacto Analysis | ⏳ Pendiente | Espera auditorías |
| Remediation | ⏳ Pendiente | Espera decisión Marco |

---

**Crítico:** Si hay corrupción de stock, afecta decisiones de compra (Script 3 → Script 4).

**Próximo paso:** Revisar reportes de auditoría.
