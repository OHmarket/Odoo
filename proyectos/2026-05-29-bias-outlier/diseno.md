# Diseño: Bias-Outlier Correction Layer

**Fecha:** 2026-05-29  
**Objetivo:** Detectar y corregir outliers en la capa de corrección de sesgo del motor HM-SI Forecast

## Problema

El forecast presenta BIAS sistemático en ciertos regímenes (particularmente REG-8, regímenes con demanda errática). Sospecha: outliers en demanda histórica están influyendo desproporcionadamente en el cálculo de sesgo.

**Ejemplo:** Un SKU con pico anómalo en semana 15 causa que el sesgo se calcule sobre valores extremos, sesgando la corrección para semanas futuras.

## Solución Propuesta

Implementar una capa de detección y gate de outliers **antes** de aplicar la corrección de sesgo:

1. **Detectar outliers** en demanda histórica (método: IQR, Z-score, o Tukey)
2. **Marcar** filas con outlier (`anomaly_flag = True`)
3. **Gate**: No aplicar sesgo si porcentaje de outliers > threshold
4. **Validar** que REG-1 (control) no regresa >0.5pp WAPE

## Enfoques Evaluados

| Enfoque | Ventaja | Desventaja | Status |
|---------|---------|-----------|--------|
| **IQR (Tukey)** | Simple, estándar | No adapta a nivel de SKU | 🧪 En prueba |
| **Z-score dinámico** | Adapta por SKU | Sensible a distribución | 🧪 En prueba |
| **Media móvil + sigma** | Detecta cambios recientes | Requiere ventana | ❌ Descartado |

## Casos de Validación

Cuando se implemente, validar contra:
- REG-1 (smooth demand): WAPE no cambia >0.5pp
- REG-8 (erratic demand): WAPE mejora 1-2pp
- SKU con picos estacionales: sesgo se estabiliza

---

**Siguiente:** ver plan.md para tareas y progress.
