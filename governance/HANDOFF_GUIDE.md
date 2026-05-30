# Handoff Guide — OH Market

**Para otros desarrolladores:** cómo funciona el pipeline, dónde está cada cosa, cómo cambiar sin romper.

---

## Pipeline en 30 segundos

```
Script 1: OH Calculo ABCXYZ.py       ← Clasifica SKUs (A/B/C × X/Y/Z)
         ↓ output: x_calculo_abc_xyz
Script 2: HM SI Forecast.py         ← Pronostica demanda (Croston, Holt-Winters, etc.)
         ↓ output: x_hm_si_forecast
Script 3: OH Analisis de Stock.py   ← Calcula qty a pedir basado en forecast
         ↓ output: x_analisis_de_stock
Script 4: OH Generacion de Docs.py  ← Crea OC, transferencias
         ↓ output: purchase.order, stock.picking
Script 5: OH Forecast Backtest.py   ← Valida Script 2 (compara vs venta real)
```

**Cron diario (paralelo):**
- `Stock Balance Daily.py` — reconstruye stock histórico
- `OH Presupuesto Ventas.py` — proyecta ingresos

---

## Dónde está qué

### Scripts productivos
- `01_segmentacion/` → Script 1 (ABCXYZ)
- `02_forecast/` → Scripts 2 (HM-SI), 5 (Backtest), + helpers (Price Corr, Cambio de Precio)
- `03_stock/` → Scripts 3, 4
- `04_analitica/` → Análisis (Team, Categoría, SKU, Margen) — no bloquea pipeline
- `05_finanzas/` → Flujo de Caja, Presupuesto — paralelo
- `_legacy/` → Scripts reemplazados (referencia)

### Configuración y documentación
- `governance/` ← **AQUÍ ESTÁS** — Cambios, validación, impacto
  - `CHANGELOG.md` — historial de versiones, qué funcionó/no
  - `IMPACT_MATRIX.md` — si cambio X, afecta Y, Z, W
  - `VALIDATION_CHECKLIST.md` — cómo validar antes de commit
  - `contracts/` — especificación de modelos Studio (campos, tipos, relaciones)
  - `CHANGE_CONTROL_LOG.md` — registro de cambios (opcional, para auditoría)
- `CLAUDE.md` — reglas no-negociables (canon SAP IBP, REG-1 control, etc.)
- `SISTEMA_REABASTECIMIENTO_COMPLETO.md` — arquitectura 30k pies
- `AGENTE_DESARROLLO_FLUJO.md` — cómo Claude opera (5 fases)

### Laboratorio (REGLA: TODO experimento aquí, NUNCA en raíz)
- `proyectos/<YYYY-MM-DD>-<slug>/` — experimentos en desarrollo
  - **OBLIGATORIO**: cada proyecto tiene `diseno.md` (qué problema, solución) y `plan.md` (tareas, validación)
  - **OBLIGATORIO**: `*.py` (scripts) y `resultados/` (output/logs) dentro del proyecto
  - **PROHIBIDO**: scripts sueltos en raíz (`/debug_*.py`, `/revisar_*.py`, etc.)
  - Cuando se promueve a productivo: mover script a `02_forecast/` (o dominio), carpeta queda como historial
  - **Sin excepciones**: esta es la única forma de mantener el repo limpio y rastreable

### Data
- `02_forecast/analisis backtest/` — ~60 snapshots históricos de backtest
  - `YYYY-MM-DD/HM_SI_vX_Y_productivo.py` — espejo del motor en esa fecha
  - `YYYY-MM-DD/CIERRE.md` — métricas detalladas, análisis, pendientes

---

## Cómo leer el código productivo

### Script 1: ABCXYZ
- **Input**: pos.config, pos_weekly_sku (ventas POS)
- **Output**: x_calculo_abc_xyz (ABC class, XYZ class, ciclo_de_vida, series_type)
- **Key fields**: x_studio_abcxyz, x_studio_ciclo_de_vida (gate declining)
- **Cambio típico**: ajustar ventanas (52 sem, 12 sem), thresholds de CV²

### Script 2: HM-SI Forecast
- **Input**: x_calculo_abc_xyz, POS histórico (72 semanas)
- **Output**: x_hm_si_forecast (mu_week = forecast)
- **Modelo**: Syntetos-Boylan (detector) + SAP IBP (auto-select Croston vs Holt-Winters per SKU)
- **Layers**: SI correction, trend factor, bias outlier gate, price factor
- **Key rule**: REG-1 es control — no puede empeorar >0.5pp WAPE
- **Cambio típico**: ajustar SI bands, trend decay, outlier gate

### Script 3: Stock
- **Input**: x_calculo_abc_xyz, x_hm_si_forecast, stock actual
- **Output**: x_analisis_de_stock (qty_a_pedir, buy_action)
- **Key fields**: qty_a_pedir (quanto comprar), buy_action (enum: RFQ/picking/nada)
- **Cambio típico**: ajustar cover_weeks, safety_stock, supplier logic

### Script 4: Documentos
- **Input**: x_analisis_de_stock
- **Output**: purchase.order, stock.picking (transferencias internas)
- **Cambio típico**: raramente — es ejecución de Script 3

### Script 5: Backtest
- **Input**: x_hm_si_forecast, pos real (POS actual)
- **Output**: CSV con WAPE por regimen, BIAS, error por SKU
- **Control**: REG-1 debe mantener WAPE <54%
- **Cambio típico**: ajustar rango de semanas, exclusiones (quiebre, SJ)

---

## Cómo cambiar sin romper

### Regla 1: Lee IMPACT_MATRIX primero
Si cambio Script 2 (forecast), ¿afecta Script 3 (stock)? Sí → valida qty_a_pedir.

### Regla 2: Backtest es obligatorio
Cambio significativo = correr Script 5 (Backtest) y comparar WAPE.

### Regla 3: REG-1 es REG-1
Si empeora >0.5pp, el cambio NO va a producción.

### Regla 4: CHANGELOG primero
Antes de hacer `git commit`, actualiza `governance/CHANGELOG.md` con nueva versión.

### Regla 5: Prueba en "cases canónicos"
Antes de confiar en métricas globales, valida contra 5-10 SKUs manuales:
- Un clase A estable (smooth)
- Un clase B variable (erratic)
- Un clase C lumpy (largo periodo sin venta)
- Un trending up (ramp_up)
- Un trending down (declining)

---

## Common Pitfalls

| Error | Síntoma | Fix |
|---|---|---|
| Cambio en Script 2, no backtest | WAPE global baja pero REG-1 sube 3pp | **VETO** — revert, backtest obligatorio |
| NaN en forecast | Stock Script 3 falla (division by NaN) | Validar: no hay Inf, división por 0, missing values |
| qty_a_pedir negativo | OC generada con qty < 0 | Validar: forecast >0, stock logic >0, safety_stock ≥0 |
| Studio campo desaparecido | Script lee x_field pero no existe | Verificar contracts/*.yml, confirmar field en modelo |
| CHANGELOG desactualizado | Otros devs no saben qué cambió | **OBLIGATORIO** — actualizar antes de commit |

---

## Cuando quieres hacer un cambio

1. **Lee:**
   - `governance/IMPACT_MATRIX.md` — qué afecta
   - `governance/VALIDATION_CHECKLIST.md` — qué validar
   - `governance/CHANGELOG.md` — qué versión es baseline

2. **Propone:**
   - ¿Qué problema resuelves?
   - ¿Qué script cambias?
   - ¿Cómo validas sin romper REG-1?

3. **Implementa:**
   - Código mínimo (no "ya que estoy")
   - Backtest
   - Actualiza `governance/CHANGELOG.md`

4. **Commit:**
   - Mensaje describe "POR QUÉ", no "QUÉ"
   - Ej: "forecast: agrega bias-outlier gate para REG-8" (no "actualiza línea 450")

---

## Contactos / Contexto

- **Marco Sanhueza** — Dueño, experto en negocio
- **Claude (agent)** — Implementación, validación técnica
- **Este handoff** — Para cuando nuevo dev toque el código

---

**Última actualización:** 2026-05-30
**Documentación:** governance/*.md
**Reglas:** CLAUDE.md
