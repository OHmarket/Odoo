# Resumen ejecutivo — Tests L1 + L2 completados

**Fecha:** 2026-05-28
**Ventana medida:** 10 sem cerradas (2026-03-16 → 2026-05-18)
**Universo limpio:** 60,878 filas (sin cigarros/snack/impulso, sin quiebres en target_week)
**BIAS baseline v3.46:** +21.87% (sub-forecast estructural)

---

## Ranking final — 7 configs evaluadas

Ordenado de menor a mayor |BIAS|:

| Rank | Config | WAPE | BIAS | \|BIAS\| | d_WAPE vs A | d_BIAS vs A | Observación |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | **F** = B + L2 cap residual | 49.02 | +4.79 | **4.79** | +1.10pp | -17.08pp | máx reducción BIAS |
| 2 | E cascada L2→abc sin gate | 48.88 | +7.79 | 7.79 | +0.96pp | -14.08pp | |
| 3 | C (L2, abc) familia | 48.86 | +7.84 | 7.84 | +0.94pp | -14.03pp | |
| 4 | D cascada L2→abc + gate REG | 48.84 | +7.98 | 7.98 | +0.92pp | -13.89pp | |
| 5 | B (L3, abc) Test 2 actual | 47.97 | +9.32 | 9.32 | +0.05pp | -12.55pp | |
| 6 | **B'** = (L3, abc) + gate REG | **47.92** | +9.52 | 9.52 | **+0.00pp** | -12.35pp | **WAPE neutro exacto** |
| 7 | A baseline v3.46 | 47.92 | +21.87 | 21.87 | — | — | referencia |

## Métricas por foco (cervezas, SKU 9407 Stella)

| Config | Cervezas WAPE | Cervezas BIAS | SKU 9407 WAPE | SKU 9407 BIAS |
|---|---:|---:|---:|---:|
| A baseline | 45.70 | +18.46 | 45.94 | +28.20 |
| **B'** | **44.99** | +4.35 | 44.84 | +6.65 |
| B | 45.06 | +4.01 | 44.84 | +6.65 |
| C/D/E | 46.91-46.95 | +1.69 a +1.94 | 44.09 | +13.62 |
| **F = B + L2 cap** | 46.20 | **-0.78** | 46.05 | **+1.99** |

---

## Conclusiones principales

### 1. Test 2 original (B) ya estaba bien afinado
Mejora WAPE neutro (+0.05pp) y BIAS -12.55pp. La granularidad `(L3, abc)` con 50 clusters era buena.

### 2. El régimen gate prácticamente no afecta el agregado
- B (sin gate) vs B' (con gate): solo 0.05pp WAPE / 0.2pp BIAS diferencia
- El gate evita que REG-7 y REG-5 sufran WAPE, pero el agregado los "lava" porque son <5% del volumen
- Conclusión: el gate es **higiene defensiva**, no aporta agregado. Vale agregarlo igual

### 3. (L2, abc) - cascada - degrada WAPE +0.9pp
C/D/E mejoran un poco más el BIAS pero el costo WAPE no se justifica. **No promover.**
- Razón: L2 promedia múltiples L3 con sesgos distintos → over-correge SKUs que estaban bien

### 4. F (cap residual L2 = 1.05) cierra el sub-forecast pero degrada WAPE +1.1pp
- BIAS total: +4.79% (vs +9.32% de B)
- Cervezas BIAS: -0.78% (casi perfecto)
- SKU 9407 Stella BIAS: +1.99% (excelente)
- **Costo:** WAPE +1.1pp porque el cap escala TODO por 1.05, incluyendo SKUs ya bien forecasteados (REG-1 pasa de +0.46% a -4.5%)

---

## Las 2 decisiones de promoción

### Camino 1 — Conservador: promover **B'** = `(L3, abc) + régimen gate`

**Qué hacer:**
- Mantener los 50 factores existentes (Test 2)
- Agregar régimen gate `{REG-1, REG-2, REG-4, REG-8}` al motor v3.47
- L2 cap residual: NO implementar (queda para v3.48 si decides después)

**Trade-off:**
- WAPE neutro (0.00pp)
- BIAS baja −12.35pp (de +21.87 a +9.52) ✅
- Cervezas BIAS de +18.46 a +4.35 ✅
- SKU 9407 BIAS de +28.20 a +6.65 ✅
- Queda residual sub-forecast +9.52%

**Por qué tiene sentido:**
- WAPE conservado al pixel
- 80% del beneficio sin costo en WAPE
- Reversible: si en producción algo sale mal, rollback completo en minutos

### Camino 2 — Agresivo: promover **F** = B + L2 cap residual

**Qué hacer:**
- Todo lo de Camino 1
- + implementar capa L2 cap global residual (más código + un nuevo modelo Studio)

**Trade-off:**
- WAPE degrada +1.10pp (47.92 → 49.02)
- BIAS baja −17.08pp (de +21.87 a +4.79) ✅✅
- Cervezas BIAS perfecto (-0.78%, casi cero)
- SKU 9407 BIAS perfecto (+1.99%)

**Por qué tiene sentido:**
- Si tu filosofía es "sub-forecast cuesta más que over-forecast", el +1pp WAPE compensa
- Cierra el sesgo casi por completo
- L2 cap es 1 escalar simple (no es complejo de implementar)

**Por qué puede no tener sentido:**
- WAPE degrada notablemente (+1.1pp es palpable en el día a día de stock)
- El cap escala uniforme sin distinguir → SKUs ya bien calibrados se desbalancean
- Posible mejor diseño: cap residual SOLO en regímenes que aún sub-forecastean (REG-2 / REG-7 / REG-8) en vez de global

---

## Diagnóstico por régimen (config B mejor L1)

| Régimen | n_filas | real | WAPE base | BIAS base | WAPE post | BIAS post | Veredicto |
|---|---:|---:|---:|---:|---:|---:|---|
| REG-1 (76% vol) | 28,477 | 196,540 | 42.52 | +12.94 | 43.01 | **+0.46** | ✅ corrección casi perfecta |
| REG-2 | 11,755 | 22,002 | 58.03 | +32.31 | 58.88 | +16.17 | corrige mitad |
| REG-4 | 1,739 | 19,088 | 43.23 | +30.49 | 37.49 | +10.21 | ✅ WAPE −5.7pp + BIAS −20pp |
| REG-8 (lumpy) | 2,276 | 5,147 | 64.35 | +58.72 | 62.95 | +55.01 | marginal (sesgo del modelo Croston) |
| REG-7 (seasonal) | 6,731 | 3,428 | 80.03 | +52.95 | 82.97 | +39.81 | ⚠️ WAPE +2.94pp |
| REG-5 (lumpy raro) | 312 | 326 | 115.31 | +14.98 | 124.94 | -5.40 | ⚠️ WAPE +9.6pp (n=326, ruido) |
| REG-0/3/6 (no_signal) | 9,588 | 13,670 | 100.0 | +100 | 100.0 | +100 | neutro (mu=0 forzado) |

→ Esto justifica el régimen gate `{REG-1, REG-2, REG-4, REG-8}` para evitar empeorar REG-7 y REG-5.

---

## Mi recomendación al volver Marco

**Promover Camino 1 (B' = L3,abc + gate régimen) ahora.** Razones:

1. WAPE neutro exacto → riesgo bajo
2. Captura 80% del beneficio (BIAS −12pp)
3. Cervezas y Stella ya quedan bien (+4.35% y +6.65% respectivamente)
4. Reversible en minutos via context override
5. Si después de 2 semanas en producción quieres más, agregamos L2 cap residual (Camino 2) — pero como capa separada, medible y reversible

**No promover C/D/E** (cascada con L2 plano) — el costo WAPE +0.9pp no se justifica vs la ganancia marginal de BIAS.

---

## Estado del código motor v3.47

**YA escrito y validado sintaxis:**
- ✅ VERSION_ID, header
- ✅ Constantes + CTX
- ✅ Loader `_load_categ_calib_context`
- ✅ Pre-loop ctx
- ✅ Bloque aplicación con `(categ_id, abc)` plano + clamp + threshold
- ✅ Persistencia 3 campos
- ✅ Notify message

**Pendiente para Camino 1 (B'):**
- Agregar gate por régimen en el bloque de aplicación: ~5 líneas
- Persistir gate decision (opcional, para auditoría)

**Pendiente para Camino 2 (F = Camino 1 + L2 cap):**
- Todo lo anterior +
- Nuevo modelo Studio `x_global_bias_correction`
- Loader `_load_residual_bias_context`
- Aplicación post-trend_factor
- SA `OH Residual Bias Correction.py`

---

## Archivos para revisar

| Archivo | Contenido |
|---|---|
| [test_L1L2_consolidado.txt](test_L1L2_consolidado.txt) | Reporte detallado de los 7 configs + diagnóstico régimen |
| [test_L1L2_consolidado_summary.json](test_L1L2_consolidado_summary.json) | JSON con métricas y factores calculados |
| [simulacion_final_v347.txt](simulacion_final_v347.txt) | Backtest original A/B/C/D con tuning Test 1 (descartado) |
| [analisis_nivel_bias.txt](analisis_nivel_bias.txt) | Análisis de discriminación por nivel |
| [analisis_calib_x_regimen.txt](analisis_calib_x_regimen.txt) | Interacción factor × régimen |
| [plan_consolidado_v347.md](../plan_consolidado_v347.md) | Plan estructurado completo |
| [propuesta_integracion_categ_calib.md](../propuesta_integracion_categ_calib.md) | Diseño inicial de integración (ya validado) |

---

## Próximo paso al volver

Confirmar **Camino 1 (B') o Camino 2 (F)**. Luego ejecutar:

1. Agregar gate régimen al motor v3.47 (cambio pequeño)
2. (Si Camino 2) implementar L2 cap residual
3. Fase A en Odoo: crear modelo Studio
4. Fase B: copiar SA `OH Calib Factors.py` a Odoo, disparar manual, validar
5. Fase C: copiar motor v3.47 a SA productivo
6. Fase D: backtest validatorio

Tiempo estimado para llegar a producción: **3-5 hrs efectivas** desde tu OK.
