# Impact Matrix — OH Market

**Matriz de impacto:** si cambio X en el script/modelo Y, ¿qué procesos/scripts se ven afectados?

Usada en Fase 3 (Validación de Integración) para evaluar impacto de cambios antes de implementar.

---

## Scripts del Pipeline

```
Script 1: ABCXYZ        ┐
Script 2: HM-SI         ├─ Upstream (generan datos)
Script 3: Stock         ├─ Consumer (consumen datos)
Script 4: Documentos    ┘
Script 5: Backtest      (validación)
```

---

## Cambios en x_calculo_abc_xyz (Script 1 output)

| Campo afectado | Scripts que leen | Impacto | Validación |
|---|---|---|---|
| `x_studio_abcxyz` | Script 2 (filter), Script 3 (filter) | Forecast, Stock | Backtest REG-1, REG-8 |
| `x_studio_regimen` | Script 5 (agrupación WAPE) | Segmentación backtest | Todos los regímenes |
| `x_studio_ciclo_de_vida` | Script 2 (gate declining/dead) | Forecast = 0 para declining SKUs | Verificar trending SKUs no se maten |
| `x_studio_series_type_active` | Script 2 (detector modelo) | Elige Croston vs Holt-Winters | Backtest WAPE, sin regresión REG-1 |
| `x_studio_cv2` | Script 2 (diagnóstico) | Información de variabilidad | Verificar no afecta lógica core |

---

## Cambios en x_hm_si_forecast (Script 2 output)

| Campo afectado | Scripts que leen | Impacto | Validación |
|---|---|---|---|
| `mu_week` (forecast) | Script 3 (qty_a_pedir), Script 5 (backtest WAPE) | Stock qty, forecast accuracy | Backtest W17-W19, WAPE total |
| `mu_week_pre_bias` | Script 5 (diagnóstico) | Análisis de bias layer | Verificar bias no sea negativa |
| `anomaly_flag` | Script 3 (validación) | Marca forecast con baja confianza | Stock no debe sobre-confiar |
| Cualquier campo | Script 5 (backtest) | Comparación vs venta real | Backtest REG-1 control |

---

## Cambios en x_analisis_de_stock (Script 3 output)

| Campo afectado | Scripts que leen | Impacto | Validación |
|---|---|---|---|
| `qty_a_pedir` | Script 4 (genera OC) | Orden de compra creada | Verificar qty > 0, no NaN |
| `buy_action` | Script 4 (tipo documento) | RFQ vs picking vs nada | Revisar cada buy_action enum |
| Cualquier campo | Reportes/analytics | Decisiones comerciales | Comparar vs estado actual |

---

## Cambios en Script 5 (Backtest)

| Cambio | Afecta | Impacto | Validación |
|---|---|---|---|
| Rango de semanas (W17-W19) | Baseline de comparación | Resultados no comparables | Mantener W17-W19 fijo |
| Métricas (WAPE, BIAS) | Target control | Diferentes benchmarks | Documentar new baseline |
| Exclusiones (quiebre, SJ) | Universo de comparación | Sesgo en selección | Documentar qué se excluye y por qué |

---

## Cross-Process Validations

Antes de cualquier cambio en Fase 3, verificar:

1. **Script 1 → Script 2**: Si cambio ABC/XYZ, ¿Script 2 puede leerlo? ¿Tipos de campo coinciden?
2. **Script 2 → Script 3**: Si cambio forecast, ¿Stock quantity puede procesar NaN/Inf? ¿Hay test cases?
3. **Script 2 → Script 5**: Cambio en forecast debe backtestear y mostrar delta WAPE.
4. **Script 3 → Script 4**: Cambio en `qty_a_pedir` debe validar OC generadas (cantidad, tipo documento).

---

## Template para Nuevos Cambios

Cuando propongo un cambio en Fase 3, lleno esto:

```
Cambio:        [descripción]
Script:        [Script X, modelo Y]
Campo(s):      [lista de campos]
Scripts afectados:
  - [Script A] (lee [campo], impacto [X])
  - [Script B] (lee [campo], impacto [X])
  
Validación requerida:
  [ ] Backtest W17-W19, REG-1 no regresa >0.5pp
  [ ] [otro test específico]
  
Risk: [LOW / MEDIUM / HIGH]
```

---

**Última actualización:** 2026-05-30
**Relacionado:** `CHANGELOG.md`, `VALIDATION_CHECKLIST.md`, `AGENTE_DESARROLLO_FLUJO.md`
