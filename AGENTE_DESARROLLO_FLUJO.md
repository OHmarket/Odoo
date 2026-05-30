---
name: agente-desarrollo-flujo
description: Cómo Claude propone y ejecuta cambios en OH Market — 5 fases estructuradas con validación de integración
metadata:
  type: instrucciones-operacionales
---

# Agente de Desarrollo — Modo de Operación

Cuando Marco solicita un cambio o mejora, Claude opero en esta secuencia. **Esto es automático — Se lee al inicio de cada sesión.**

## I. FLUJO DE 5 FASES

### Fase 1: Lectura de Contexto Completo
Antes de proponer nada, leo (en este orden):
1. `SISTEMA_REABASTECIMIENTO_COMPLETO.md` — arquitectura 30k pies (Scripts 1→5, cómo se conectan)
2. `governance/CHANGELOG.md` — historial de versiones y qué funcionó/qué no
3. `governance/IMPACT_MATRIX.md` — cómo cambios en X afectan Y, Z, W
4. `governance/contracts/` — especificación de modelos y campos Studio
5. `02_forecast/HM SI Forecast.py` header (líneas 1-100) — reglas vivas actuales
6. `memory/` — intentos pasados, lecciones, por qué fallaron
7. `CLAUDE.md` — constraints no-negociables (canon SAP/Oracle, REG-1 control)

**Output:** Entiendo arquitectura, integraciones, qué versión es baseline, qué cambios pueden romper, por qué intentos previos fallaron.

### Fase 2: Propuesta Estructurada
NO presento código. Presento TOP 3 opciones con:
- **Objetivo claro** (qué mejora, target numérico)
- **3 enfoques** ordenados por riesgo (LOW → MEDIUM → HIGH)
- Para cada uno: problema diagnosticado, solución, impacto estimado, riesgos
- **Recomendación** (cuál empezar primero)

**Marco elige una opción.**

### Fase 3: Validación de Integración
Antes de tocar código, verifico (usando `governance/IMPACT_MATRIX.md`):
- ¿Qué archivo(s) cambio?
- ¿Cómo afecta Scripts posteriores (1→3→4→5)? (ver IMPACT_MATRIX)
- ¿Hay cambios en Studio? ¿Nueva query? ¿Performance?
- ¿Hay impactos colaterales inesperados?

Si encuentro problema de integración (ej: necesito data que no existe), lo reporto ANTES de implementar.

Luego presento tabla de validación (paso a paso de `governance/VALIDATION_CHECKLIST.md`).

**Output:** Arquitectura del cambio, integración verificada, plan de validación claro.

### Fase 4: Implementación + Backtest
1. Muestro código ANTES/DESPUÉS (pequeño diff, comentado)
2. Corro backtest automático (W17-W19, 3 sem cerradas)
3. Presento resultados:
   - WAPE global, por regimen (REG-1 es control, no puede empeorar >0.5pp)
   - BIAS en rango
   - Sin NaN/Inf, runtime reasonable
4. Veredicto: ✅ LISTO PARA COMMIT o ⚠️ AJUSTAR

**Marco aprueba o pide ajustes.**

### Fase 5: Commit + Documentación
Si OK:
1. **ACTUALIZO `CHANGELOG.md`** con versión nueva (v3.48a)
   - Fecha
   - Qué problema resuelve
   - Cambios técnicos
   - Impacto (WAPE delta, safety checks)
   - Esto es **OBLIGATORIO antes de commitear** (no negociable)

2. Propongo mensaje commit (describe el POR QUÉ, no el QUÉ)

3. Actualizo `02_forecast/HM SI Forecast.py` header (reglas vivas)

4. Creo/actualizo memory con learnings

5. Espero confirmación explícita: **"Dale"**

**Recién entonces ejecuto git add/commit/push.**

**REGLA:** Cada commit debe tener su entrada en CHANGELOG. Sin excepción.

## II. GUARDRAILS (Lo Que NO Hago)

❌ NO commiteo sin aprobación explícita ("Dale")  
❌ NO cambio parámetros >10% sin backtest  
❌ NO propongo sin TOP 3 opciones (quiero que elijas)  
❌ NO ignoro REG-1 (es control, must-not-regress)  
❌ NO tomo decisiones de negocio (las pregunto)  
❌ NO implemento si encuentro problema de integración (primero reporto)  

## III. Información Que Necesito Para Empezar

Cuando Marco dice: "Mejora X", pregunto (si no está claro):

```
1. ¿Cuál es el objetivo? (WAPE target, BIAS range, etc.)
2. ¿Cuál es el constraint? (no romper REG-1, keep speed <60sec, etc.)
3. ¿Hay deadline? (para backtest, para producción)
4. ¿Riesgo tolerance? (auto-approve si <5%, else review)
5. ¿Hay contexto previo? (intentamos esto, memory dice por qué falló)
```

## IV. Ejemplo de Sesión Típica

```
MARCO: "REG-8 WAPE es 73.88%, demasiado alto. ¿Podemos bajar a <70%?"

YO (FASE 1-2):
├─ Leo memory → "bias-outlier over-corrige seasonal"
├─ Leo CHANGELOG → v3.48 agregó bias-outlier
├─ Propongo TOP 3:
│  A) Gate bias-outlier para REG-8 (low risk, -2.4pp estimado)
│  B) SI_CEIL diferencial por regimen (medium risk, -1.8pp estimado)
│  C) Holiday calendar layer (high risk, futuro, -3-5pp potencial)
└─ "¿Cuál prefieres?"

MARCO: "A"

YO (FASE 3-4):
├─ Valido integración → "afecta _bias_outlier_layer(), sin cambios Studio"
├─ Implemento + backtest → "REG-8: 73.88% → 71.2% (-2.68pp) ✅"
└─ "Listo para commit"

MARCO: "Dale"

YO (FASE 5):
├─ git add 02_forecast/HM SI Forecast.py
├─ git commit -m "fix: bias-outlier skip REG-8 seasonal..."
├─ git push
├─ Actualizo CHANGELOG/memory
└─ "Hecho. Versión v3.48a en main."
```

## V. Cómo se Ve en Práctica

Cada sesión, esto es automático:
- Leo `memory/` → conozco intentos pasados
- Leo `CHANGELOG.md` → sé qué versión es baseline
- Leo `HM SI Forecast.py` header → entiendo reglas vivas
- Si me pides un cambio → sigo el flujo de 5 fases
- Nunca cambio sin "Dale" explícito

**No necesitas hacer nada especial.** Solo di qué quieres mejorar.

---

**Versión:** 2026-05-30  
**Relacionado:** `CLAUDE.md`, `SISTEMA_REABASTECIMIENTO_COMPLETO.md`, `CHANGELOG.md`
