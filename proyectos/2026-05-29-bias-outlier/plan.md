# Plan: Bias-Outlier Correction Layer

**Estado:** En investigación  
**Scripts:** check_bias_outlier_marks.py, diag_bias_outlier.py, test_bias_outlier_core.py, revisar_*.py, validar_*.py

## Tareas

- [ ] **Fase 1: Diagnóstico**
  - [ ] diag_bias_outlier.py — identifica regímenes con bias alto
  - [ ] revisar_outliers_correcto.py — valida detección de outliers
  - [ ] revisar_outliers_ultima_semana.py — analiza tendencia reciente
  - **Output esperado:** lista de SKUs/regímenes problemáticos

- [ ] **Fase 2: Implementación**
  - [ ] check_bias_outlier_marks.py — marca outliers en demanda histórica
  - [ ] test_bias_outlier_core.py — valida lógica del detector
  - [ ] Agregar `anomaly_flag` a x_hm_si_forecast (Studio o script)
  - **Output esperado:** gate funcional en Script 2

- [ ] **Fase 3: Validación**
  - [ ] revisar_bias_outlier_api.py — valida API de detección
  - [ ] validar_bias_outlier.py — backtest REG-1 vs REG-8
  - [ ] Comparar WAPE antes/después
  - **Criterio de éxito:** REG-1 no empeora >0.5pp, REG-8 mejora ≥1pp

- [ ] **Fase 4: Promoción**
  - [ ] Integrar gate en `02_forecast/HM SI Forecast.py` (versión v3.49+)
  - [ ] Actualizar governance/CHANGELOG.md
  - [ ] Mover script productivo a 02_forecast/, carpeta queda como historial

## Progress

| Tarea | Responsable | Estado | Notas |
|-------|-------------|--------|-------|
| Diagnóstico | Claude | 🧪 En curso | revisar_*.py ejecutando |
| Implementación | Claude | ⏳ Pendiente | Espera resultados diagnóstico |
| Validación | Claude + Marco | ⏳ Pendiente | Requiere aprobación WAPE |
| Promoción | Claude | ⏳ Pendiente | Post-validación |

---

**Dependencias:** Script 2 (HM-SI v3.48), governance/VALIDATION_CHECKLIST.md (Fase 4)

**Próximo paso:** Revisar resultados de diagnóstico en resultados/
