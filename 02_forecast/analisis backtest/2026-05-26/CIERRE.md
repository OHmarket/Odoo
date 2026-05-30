# CIERRE — Backtest 2026-05-26

**Motor:** HM-SI v3.44 → v3.45 → v3.46  
**Período:** W17-W19/2026 (3 semanas cerradas)  
**Baseline:** v3.43 WAPE 71.20%, BIAS -1.8%  
**Fecha de ejecución:** 2026-05-26

---

## RESUMEN EJECUTIVO

| Métrica | v3.43 Baseline | v3.46 Final | Delta | Status |
|---------|---|---|---|---|
| **WAPE Global** | 71.20% | 70.85% | -0.35pp | ✅ |
| **BIAS** | -1.8% | -2.1% | -0.3pp | ✅ |
| **REG-1 (Control)** | 53.60% | 53.50% | -0.10pp | ✅ PASS |
| **REG-8 (Erratic)** | 73.88% | 73.52% | -0.36pp | ✅ |
| **Forecast NaN** | 0 | 0 | 0 | ✅ |

**Veredicto:** ✅ LISTO PARA PROMOCIÓN

---

## WAPE POR REGIMEN

| Regimen | Baseline | v3.46 | Delta | Comentario |
|---------|----------|-------|-------|-----------|
| REG-1 | 53.60% | 53.50% | -0.10pp | Control intacto ✅ |
| REG-2 | 62.15% | 61.95% | -0.20pp | Smooth steady |
| REG-3 | 68.44% | 68.10% | -0.34pp | Mejor cobertura |
| REG-4 | 69.87% | 69.55% | -0.32pp | Lifecycle fix ayuda |
| REG-5 | 71.22% | 70.88% | -0.34pp | En rango |
| REG-6 | 72.11% | 71.75% | -0.36pp | Promedio |
| REG-7 | 72.58% | 72.30% | -0.28pp | Mejoró |
| REG-8 | 73.88% | 73.52% | -0.36pp | Erratic stable |

---

## CAMBIOS POR VERSIÓN

### v3.44 — Lifecycle Declining Fix
- **Problema:** SKUs declining no detectados, forecast inflado
- **Fix:** Mayor agresividad en declining gate (P1 = 0 si trending down)
- **Impacto:** +0.15pp en REG-4, REG-5 (SKUs lifestyle churn)
- **Status:** ✅ Sin regression

### v3.45 — Remove mu<2 Threshold
- **Problema:** SKUs con <2 ventas/sem silenciados (forecast=0)
- **Fix:** Permitir forecast bajo (mu≥0.5)
- **Impacto:** +0.12pp en REG-6, REG-7 (SKUs lentos)
- **Status:** ✅ Marginal

### v3.46 — Remove Rounding
- **Problema:** Redondeo a 0 decimales pierde precision
- **Fix:** Mantener flotantes exactos (mu_week = 1.3, no 1)
- **Impacto:** +0.08pp precision acumulada
- **Status:** ✅ Limpio

---

## ISSUES Y OUTLIERS

### SKU 9407 (Cigarrillos Blend)
- **WAPE:** 95% (vs 73% baseline)
- **Causa:** Quiebre prolongado semanas 16-17, forecast vs 0 venta real
- **Decision:** Excluir de backtest (quiebre ≠ error forecast)
- **Status:** Documentado en resultados/outliers.csv

### Categoría SJ (San José)
- **WAPE:** +8pp vs regional
- **Causa:** Datos históricos incompletos (solo 12 sem vs 26)
- **Decision:** Validar contra 4-week cutoff
- **Status:** No afecta validación (ya documentado)

---

## ARCHIVOS GENERADOS

```
resultados/
├─ backtest_raw.csv           ← WAPE/BIAS por SKU × regimen
├─ regimen_summary.txt        ← Tabla regimen vs baseline
├─ outliers.csv               ← SKUs problemáticos (quiebre, low-data)
└─ comparacion_v343_vs_v346.txt ← Delta detallado
```

---

## RECOMENDACIÓN

✅ **PROMOCIÓN AUTORIZADA**

- REG-1 control: intacto
- WAPE: -0.35pp mejora
- BIAS: estable
- Cambios: 3 versiones, cada una validada

**Próximo paso:** Mover script productivo a `02_forecast/HM SI Forecast.py`, actualizar CHANGELOG.

---

**Ejecutado:** 2026-05-26  
**Aprobado por:** Marco Sanhueza  
**Producción:** v3.46 desde 2026-05-27
