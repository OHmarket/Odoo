# Validation Checklist — OH Market

**Antes de commitear cualquier cambio, verificar esta lista.**

Usada en Fase 4 (Implementación + Backtest) para validar que el cambio es seguro antes de ir a producción.

---

## Pre-Implementation Checklist (Fase 3)

- [ ] ¿Qué modelo/script cambio?
- [ ] ¿Qué campos Studio se modifican?
- [ ] ¿Afecta a Scripts posteriores (1→2→3→4→5)?
- [ ] ¿Hay cambios en queries? ¿Performance OK?
- [ ] ¿Nuevos imports o dependencias?
- [ ] ¿Hay deadlocks o race conditions posibles?

---

## Implementation Checklist (Fase 4)

### Backtest Obligatorio

- [ ] Corro backtest W17-W19 (3 semanas cerradas)
- [ ] **REG-1 control intacto** — WAPE no empeora >0.5pp
- [ ] WAPE global en rango esperado (60%–75%)
- [ ] BIAS en rango `[-15%, +5%]`
- [ ] Sin NaN, Inf, valores negativos inesperados
- [ ] Runtime <60 segundos

### Por cada Script afectado

**Script 1 (ABCXYZ):**
- [ ] No hay cambios en campos críticos (abcxyz, ciclo_de_vida)
- [ ] Si cambio: verificar 5-10 SKUs manualmente

**Script 2 (HM-SI Forecast):**
- [ ] Backtest WAPE por regimen: REG-1, REG-7, REG-8
- [ ] Verify: forecast values positivos, <max histórico × 2
- [ ] Si cambio modelo: validar contra Syntetos-Boylan / SAP IBP

**Script 3 (Stock):**
- [ ] qty_a_pedir positivo o 0 (no negativo)
- [ ] buy_action enum válido (RFQ, picking, nada)
- [ ] Si cambio qty: OC generadas tienen cantidad coherente

**Script 4 (Documentos):**
- [ ] Si Script 3 cambió: verificar OC se crean sin error
- [ ] No hay pick ings duplicados
- [ ] RFQs apuntan a proveedor correcto

**Script 5 (Backtest):**
- [ ] Ejecuta sin error
- [ ] WAPE reporta por regimen
- [ ] CSV de output tiene estructura esperada

### Datos y Auditoría

- [ ] Base de datos: sin errores de FK, constraint violations
- [ ] Studio: sin campos rotos, types coinciden
- [ ] Logs: sin warnings críticos
- [ ] Si hay deadlocks: capturar lock_key en LOCK_KEYs (ver memory)

### Code Quality

- [ ] Header de script actualizado (version, descripción)
- [ ] Comentarios solo en "por qué", no "qué"
- [ ] Sin código debug (print, breakpoints)
- [ ] Sin hardcodes (magic numbers van en constantes)

---

## Post-Implementation Checklist (Fase 5)

- [ ] CHANGELOG.md actualizado con nueva versión
- [ ] Descripción clara: qué problema, qué solución, qué impacto
- [ ] IMPACT_MATRIX.md actualizado (si cambio nueva área)
- [ ] AGENTE_DESARROLLO_FLUJO.md actualizado (si afecta a proceso)
- [ ] memory/ actualizado con lecciones aprendidas
- [ ] Git commit message describe "por qué", no "qué"
- [ ] Git push a main (sin force)

---

## Reglas de Veto (cambio NO puede ir a producción si alguno es true)

- ❌ REG-1 WAPE empeora >0.5pp
- ❌ BIAS sube >20% o baja <-20%
- ❌ Hay NaN o Inf en forecast
- ❌ qty_a_pedir negativo para algún SKU
- ❌ Studio tiene campos missing o types desactualizados
- ❌ Script corre >90 segundos (timeout en cron)
- ❌ CHANGELOG.md no actualizado (OBLIGATORIO)

---

## Matriz de Riesgo

| Riesgo | Cambio | Validación Extra |
|---|---|---|
| **LOW** | Header comment, constante tuneable | Compile + basic backtest |
| **MEDIUM** | Nueva fila en x_analisis_de_stock, cambio en qty cálculo | Full backtest W17-W19 + manual sample |
| **HIGH** | Cambio en modelo ABCXYZ, nuevo detector, nuevo campo Studio | Full backtest + 3-día regression + memoria documentada |

---

## Template para Sesión

Después de implementar en Fase 4, reportar:

```
VALIDACIÓN FASE 4:
✅ Backtest W17-W19:
   - WAPE global: 70.85% (baseline 71.20%) → delta -0.35pp ✅
   - REG-1: 53.50% (baseline 53.60%) → delta -0.10pp ✅
   - BIAS: -2.1% (baseline -1.8%) → delta -0.3pp ✅

✅ Scripts afectados:
   - Script 1: sin cambios
   - Script 2: 2 funciones, baseline Croston
   - Script 3: qty_a_pedir validation OK
   - Script 5: CSV structure OK

✅ Reglas de veto: ninguno activado

RIESGO: LOW

LISTO PARA COMMIT
```

---

**Última actualización:** 2026-05-30
**Relacionado:** `IMPACT_MATRIX.md`, `CHANGELOG.md`, `AGENTE_DESARROLLO_FLUJO.md`
