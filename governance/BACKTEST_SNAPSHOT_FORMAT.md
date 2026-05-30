# Backtest Snapshot Format — Estándar Diario

**Uso:** Cuando Marco pide "analiza backtest", genero este formato exacto. Cada día, mismo análisis.

---

## TEMPLATE (Copiar siempre)

```
SNAPSHOT DIARIO — YYYY-MM-DD
═════════════════════════════════════════════════════════════

GLOBAL (Resumen Ejecutivo):
  WAPE Global:    XX.X%
  BIAS:           X.X%
  Forecast NaN:   0 ✅
  Status:         ✅/⚠️/❌

POR REGIMEN (Operativo — Qué Mejorar Hoy):
═══════════════════════════════════════════════════════════════════

Regimen | WAPE  | Unid/Día | SKUs Act | Unid/SKU | Dist       | Vs Ayer
────────┼───────┼──────────┼──────────┼──────────┼────────────┼─────────
REG-1   | XX.X% | X,XXX    | XX       | XX.X     | 🔴 Conc    | ↗/↘/→
REG-2   | XX.X% | XXX      | XX       | XX.X     | 🟡 Mixta   | ↗/↘/→
REG-3   | XX.X% | XXX      | XX       | X.X      | 🟡 Mixta   | ↗/↘/→
REG-4   | XX.X% | XXX      | XXX      | X.X      | 🟡 Mixta   | ↗/↘/→
REG-5   | XX.X% | XXX      | XXX      | X.XX     | 🔵 Cola    | ↗/↘/→
REG-6   | XX.X% | XX       | XXX      | X.XX     | 🔵 Cola    | ↗/↘/→
REG-7   | XX.X% | XX       | XXX      | X.XX     | 🔵 Cola    | ↗/↘/→
REG-8   | XX.X% | XX       | XXX      | X.XX     | 🔵 Cola    | ↗/↘/→

LEYENDA DISTRIBUCIÓN:
  🔴 Concentrada: <5 unid/SKU (demanda concentrada → fácil pronóstico)
  🟡 Mixta: 1-5 unid/SKU (algunos altos, otros bajos)
  🔵 Cola Larga: <1 unid/SKU (muchos SKUs esporádicos → difícil pronóstico)

PRIORIZACIÓN (Error Real = WAPE × Unid/Día):
─────────────────────────────────────────────

Prioridad | Regimen | Error Real | Motivo
──────────┼─────────┼────────────┼────────────────────────────
🔴 Alto   | REG-X   | XXX unid   | Alto volumen + WAPE malo
🔴 Alto   | REG-X   | XXX unid   | Alto volumen + WAPE malo
🟡 Medio  | REG-X   | XX unid    | Volumen medio
🟢 Bajo   | REG-X   | X unid     | Bajo volumen (cola larga)

INSIGHTS:
─────────

✅ ESTABLE:
  • REG-X: dentro de rango esperado

⚠️ CAMBIOS:
  • REG-X: ↗ XX.X% vs ayer (investigar)
  • REG-X: ↘ XX.X% vs ayer (mejorando)

🔴 ALERTAS:
  • REG-1 (Control): ↗ XX% (debe mantenerse <54%)
  • REG-X: outlier nuevo detectado

RECOMENDACION PARA HOY:
──────────────────────

1️⃣ Mejorar REG-X (concentrado, alto volumen, WAPE mejorable)
2️⃣ Mejorar REG-X (mixto, volumen medio)
3️⃣ Monitorear REG-X (cola larga = mejora marginal posible)
4️⃣ Mantener REG-1 (control, no romper)

NOTAS OPERATIVAS:
─────────────────
• [Eventos conocidos: promos, quiebres, reabastecimiento, cambios de datos]
• [SKUs anómalos del día si aplica]
• [Recomendación: seguir, investigar, cambio urgente]

═════════════════════════════════════════════════════════════════════
Generado: YYYY-MM-DD HH:MM | Período: W17-W19 (3 semanas cerradas)
```

---

## Cómo Usar

1. **Marco pide:** "Analiza backtest 2026-05-30"
2. **Claude responde:** Genera este template con datos del CSV
3. **Resultado:** Tabla normalizada, siempre igual estructura

---

## Datos a Extraer del CSV

| Campo | Fuente | Cálculo |
|-------|--------|---------|
| WAPE Global | CSV | Promedio ponderado |
| BIAS | CSV | Media de (forecast - real) / real |
| Unid/Día | CSV | Suma de `real_qty` por regimen |
| SKUs Activ | CSV | COUNT(SKU) donde `venta > 0` |
| Unid/SKU | Calculado | Unid/Día ÷ SKUs Activ |
| Dist | Heurística | Categorizar por Unid/SKU |
| Vs Ayer | Comparación | Diferencia con snapshot anterior |

---

## Criterios Fijos

- **Período siempre:** W17-W19 (últimas 3 semanas cerradas)
- **REG-1 = Control:** nunca puede empeorar >0.5pp
- **Concentrada:** <5 unid/SKU
- **Mixta:** 1-5 unid/SKU
- **Cola:** <1 unid/SKU
- **Error Real:** WAPE × (Unid/Día) = unidades de error/día

---

## Ejemplo Completado

```
SNAPSHOT DIARIO — 2026-05-30
═════════════════════════════════════════════════════════════

GLOBAL:
  WAPE Global:    71.0%
  BIAS:           -1.9%
  Forecast NaN:   0 ✅
  Status:         ⚠️ REG-1 sube

POR REGIMEN:
Regimen | WAPE  | Unid/Día | SKUs Act | Unid/SKU | Dist       | Vs Ayer
────────┼───────┼──────────┼──────────┼──────────┼────────────┼─────────
REG-1   | 53.7% | 1,200    | 95       | 12.6     | 🔴 Conc    | ↗ +0.1%
REG-2   | 62.1% | 320      | 110      | 2.9      | 🟡 Mixta   | ↘ -0.2%
REG-3   | 68.2% | 210      | 95       | 2.2      | 🟡 Mixta   | → 0.0%
REG-4   | 70.5% | 850      | 280      | 3.0      | 🟡 Mixta   | ↗ +0.2%
REG-5   | 71.0% | 180      | 320      | 0.56     | 🔵 Cola    | ↗ +0.3%
REG-6   | 71.9% | 95       | 180      | 0.53     | 🔵 Cola    | → 0.0%
REG-7   | 72.4% | 30       | 250      | 0.12     | 🔵 Cola    | ↗ +0.1%
REG-8   | 73.8% | 45       | 540      | 0.08     | 🔵 Cola    | ↗ +0.2%

PRIORIZACIÓN:
🔴 REG-1: 644 unid error/día (concentrado, control subiendo ⚠️)
🔴 REG-4: 600 unid error/día (mixto, subió vs ayer)
🟡 REG-2: 198 unid error/día (mixto, mejorando)
🟡 REG-5: 128 unid error/día (cola larga)
🟢 REG-8: 33 unid error/día (cola larga = bajo impacto)

RECOMENDACION PARA HOY:
1️⃣ Mejorar REG-1 (644 unid/día error, concentrado → mejora tangible)
2️⃣ Mejorar REG-4 (600 unid/día error, subió → investigar)
3️⃣ Mantener REG-1 (control, +0.1% aún aceptable)
4️⃣ Monitorear REG-5, REG-8 (cola larga = esfuerzo bajo ROI)

NOTAS:
• Sin eventos conocidos el 30-05
• SKU 9407 (cigarrillos) aún rompiendo (quiebre, no forecast error)
```

---

**Este template se genera automáticamente cada vez que pidas "analiza backtest".**

**Última actualización:** 2026-05-30
