SNAPSHOT DIARIO — 2026-06-01  (MODELO: SMA(4) puro)
═════════════════════════════════════════════════════════════

GLOBAL (Resumen Ejecutivo):
  Modelo:         SMA(4) puro (SA 1576) — reemplaza HM-SI v3.49 tras FVA
  WAPE core:      54.28%      (universo core, comparable al motor)
  BIAS core:      +5.87%
  WAPE catalogo:  64.9%       (TODO lo que el SMA4 pronostica, +cola intermitente)
  BIAS catalogo:  +4.0%
  Forecast NaN:   0 ✓
  Status:         ✓ SMA(4) validado = idéntico al cálculo local (corr 1.0000)

NOTA DE UNIVERSO:
  El SMA(4) pronostica TODO el catálogo (51K SKUxsala). El motor solo pronosticaba
  ~17K (core) y mandaba el resto a min_stock_or_manual. Para comparar contra el
  motor, usar el bloque CORE (54.3%). El catálogo completo (64.9%) sube por la
  cola intermitente que el motor nunca pronosticó.

POR REGIMEN (core, sin San José, W21-W23 = May 11/18/25):
═══════════════════════════════════════════════════════════════════

Regimen | WAPE   | BIAS   | Unid/sem | SKUs  | Unid/SKU | Dist       | Error Real
────────┼────────┼────────┼──────────┼───────┼──────────┼────────────┼───────────
REG-1   |  48.9% |  +9.2% | 18,238   | 2,933 |   18.7   | 🔴 Conc    | 8,919 unid
REG-8   |  72.9% |  +0.2% |  4,963   | 2,535 |    5.9   | 🟡 Mixta   | 3,619 unid
REG-4   |  48.2% |  +9.8% |  2,627   |   487 |   16.2   | 🔴 Conc    | 1,267 unid
REG-7   |  77.7% | -45.5% |    790   |   422 |    5.6   | 🟡 Mixta   |   614 unid
REG-2   | 131.3% | -29.1% |     46   |    75 |    1.9   | 🔵 Cola    |    61 unid
REG-5   |  26.9% |  +2.6% |     26   |     5 |   15.6   | 🔴 Conc    |     7 unid

LEYENDA DISTRIBUCIÓN:
  🔴 Concentrada: >15 unid/SKU (demanda concentrada → fácil pronóstico)
  🟡 Mixta: 5-15 unid/SKU (algunos altos, otros bajos)
  🔵 Cola Larga: <5 unid/SKU (muchos SKUs esporádicos → difícil pronóstico)

PRIORIZACIÓN (Error Real = WAPE × Unid/sem):
─────────────────────────────────────────────

Prioridad | Regimen | Error Real | Unid/sem | Comentario
──────────┼─────────┼────────────┼──────────┼────────────────────────
🔴 CRÍTICO| REG-1   | 8,919      | 18,238   | Volumen alto, WAPE controlado (48.9%)
🟡 ALTO   | REG-8   | 3,619      |  4,963   | Erratic: SMA4 sufre (72.9%)
🟡 ALTO   | REG-4   | 1,267      |  2,627   | Smooth variable, WAPE OK
🟢 MEDIO  | REG-7   |   614      |    790   | Intermitente: SMA4 SUB-forecastea (-45.5%)
🟢 BAJO   | REG-2   |    61      |     46   | Cola, ruido
🟢 BAJO   | REG-5   |     7      |     26   | Cola, insignificante

ANÁLISIS POR REGIMEN:
─────────────────────

REG-1 (Control / Smooth A) — el grueso:
  • WAPE 48.9% / BIAS +9.2% sobre 18,238 unid/sem (68% del volumen core).
  • Donde el SMA(4) gana: demanda estable, promedio-4 sigue bien el nivel.
  • +9.2% de over-forecast (limpio de quiebre sería mayor; ver abajo).

REG-8 (Erratic) y REG-7 (Intermitente) — la debilidad del SMA(4):
  • REG-8: WAPE 72.9%; REG-7: WAPE 77.7% con BIAS -45.5% (SUB-pronostica fuerte).
  • Causa: el SMA(4) sobre series con muchos ceros se va a la baja. El motor
    manejaba esto con el bake-off (Croston/SBA), que el SMA4 no tiene.
  • Es el trade-off conocido y aceptado: "SMA4 y listo" gana en el grueso (REG-1),
    pierde en la cola intermitente (3% del volumen core).

REG-4 (Smooth Variable):
  • WAPE 48.2% / BIAS +9.8%, 10% del volumen. Comportamiento sano.

EFECTO QUIEBRE (medido sobre stockout_full.json, W21-W23):
─────────────────────────────────────────────────────────
  • 6.5% de las filas tienen quiebre en la semana target.
  • Limpio de quiebre el BIAS catálogo SUBE +4.0% → +8.7%: los quiebres ocurren en
    SKUs de alta demanda donde el SMA4 sub-pronostica (bias negativo que enmascara
    el over-forecast). Limpio, el sesgo real del SMA(4) es ~+8.7%.

VALIDACIÓN DE PARIDAD:
──────────────────────
  • forecast_qty del servidor (SA 1576) == SMA(4) local: diff máx 0.0000, corr
    1.000000, 0 pares con diff>0.01. El servidor calcula SMA(4) exacto.

NOTAS OPERATIVAS:
─────────────────
  • CSV: x_forecast_backtest "2026-06-01 SMA4 P" (SA 1576), 3 sem cerradas.
  • Modelo nuevo OH SMA4 Forecast v1.0 — NO desplegado a producción aún (solo medición).
  • Universo CORE para comparar contra el motor; catálogo completo para magnitud real.
  • San José excluida de la medición (ruido); SÍ se pronostica en producción.

RECOMENDACIÓN PARA HOY:
───────────────────────
  1️⃣ REG-1 (68% del volumen): el SMA(4) lo controla (48.9%). Es el caso de éxito.
  2️⃣ REG-7/REG-8 (intermitente/erratic): el SMA(4) sub-pronostica. Si el quiebre
     en estos sube, evaluar reintroducir Croston SOLO para series intermitentes
     (híbrido: SMA4 en smooth, Croston en intermitente) — pero recién si duele.
  3️⃣ Decidir deploy: repuntar el cron del forecast a SA 1576 cuando se confirme.

PREGUNTAS PARA MARCO:
────────────────────
  1. ¿El sub-forecast en REG-7/REG-8 (intermitentes) es tolerable, o querés un
     híbrido SMA4+Croston para esa cola?
  2. ¿Desplegamos SMA(4) a producción (repuntar cron a 1576) o seguimos midiendo?

═════════════════════════════════════════════════════════════════════
Generado: 2026-06-01 | Período: W21-W23 (May 11/18/25)
Modelo: OH SMA4 Forecast v1.0 (SA 1576) | Validado = SMA(4) exacto (corr 1.0)
