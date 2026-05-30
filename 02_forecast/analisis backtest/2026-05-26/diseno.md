# Backtest 2026-05-26 — Evaluación de HM-SI v3.44 a v3.46

**Fecha:** 2026-05-26  
**Período:** W17-W19 (3 semanas cerradas)  
**Baseline:** HM-SI v3.43 (trend correction)

## Objetivo

Validar 3 versiones del motor:
- **v3.44** — Lifecycle declining fix (detecta declive más agresivo)
- **v3.45** — Remove mu<2 threshold (permite forecast bajo)
- **v3.46** — Remove rounding (usa flotantes exactos)

Medir impacto en WAPE, BIAS, y regímenes de control (especialmente REG-1).

## Hipótesis

- v3.44: mejora cobertura de SKUs declining sin regression
- v3.45: reduce bias-zero para SKUs lentos
- v3.46: precision flotante → WAPE marginal mejor

## Criterio de Éxito

✅ REG-1 WAPE ≤ 54% (control, no puede empeorar >0.5pp)  
✅ WAPE global < 71% (baseline 71.2%)  
✅ BIAS en rango [-15%, +5%]  
✅ Sin NaN/Inf en forecast

---

**Relacionado:** plan.md, CIERRE.md
