# Test 1 - Tuning automático v3.46 → v3.47 (propuesto)

**Fecha:** 2026-05-28
**Método:** Random search por fases sobre harness local, constraint REG-1 no degrada >0.5pp
**Datos:** 3 semanas (2026-05-04, 2026-05-11, 2026-05-18), sin filtro noise, excluyendo quiebres detectados

## Configuración ganadora (12 cambios sobre v3.46)

```python
# === SMA blend (Fase 1 + Fase 4) ===
SERVICE_BASE_SHORT_WEEKS_DEFAULT = 4     # era 6
SERVICE_BASE_LONG_WEEKS_DEFAULT  = 16    # igual
SERVICE_RATIO_UP_DEFAULT         = 1.15  # igual
SERVICE_RATIO_HOLD_DEFAULT       = 0.90  # igual
SERVICE_RATIO_COLLAPSE_DEFAULT   = 0.40  # era 0.30
SERVICE_DOWN_W_SHORT_DEFAULT     = 0.50  # era 0.70
SERVICE_DOWN_W_LONG_DEFAULT      = 0.50  # antes 0.30; ajustar a 1-DOWN_W_SHORT

# === Bake-off Croston/SBA (Fase 2) ===
HEUR_BIAS                        = 0.80  # era 0.90 (hardcoded en _select_best_model)
CROSTON_ALPHA                    = 0.25  # era 0.10 (hardcoded)
SBA_ALPHA                        = 0.20  # era 0.15 (hardcoded)

# === SI seasonal (Fase 3) ===
SI_CEIL_DEFAULT                  = 3.0   # era 5.0
SI_SKU_ADJ_ALPHA_HIGH_DEFAULT    = 0.20  # era 0.30
SI_MIN_YEARS_FOR_SKU_DEFAULT     = 2     # era 3

# === Fair share (Fase 4) ===
FAIR_SHARE_TRIED_PENALTY_DEFAULT = 0.05  # era 0.15
```

## Cambios al código

Archivo: `02_forecast/HM SI Forecast.py`

### Bloque 1: Header constantes (líneas ~110-163)

Cambiar 8 defaults listados arriba (SMA, SI, FAIR_SHARE).

### Bloque 2: `_select_best_model` (línea 705)

Modificar firma + hardcoded alphas:

```python
def _select_best_model(base_vals, raw_vals,
                       short_weeks, long_weeks,
                       ratio_up, ratio_hold, ratio_collapse,
                       down_w_short, down_w_long,
                       heur_bias=0.80,          # nuevo default
                       sba_alpha=0.20,          # nuevo param
                       croston_alpha=0.25):     # nuevo param
    ...
    # Reemplazar hardcoded 0.15, 0.10:
    sba_f = _sba(train_b, alpha=sba_alpha)
    crost_f = _croston(train_b, alpha=croston_alpha)
    ...
```

### Bloque 3: VERSION_ID (línea 66)

```python
VERSION_ID = "FWD_v3_47_AUTOTUNE_TEST1"
```

## Resultados comparativos

### Totales (3 sem, sin censura)

| Métrica | Baseline v3.46 | Tuned (test 1) | Δ |
|---|---:|---:|---:|
| Real | 85,806 | 85,806 | - |
| Fcst | 82,437 | 76,396 | -6,041 |
| **WAPE** | 74.37% | **69.48%** | **-4.89pp** |
| **BIAS** | +3.93% | +10.97% | +7.04pp |

### Por regimen

| Regimen | n | WAPE base | WAPE tuned | Δ WAPE | BIAS base | BIAS tuned |
|---|---:|---:|---:|---:|---:|---:|
| REG-1 smooth A (75% real) | 14,592 | 57.87 | **55.99** | -1.88 | +3.68 | +8.06 |
| REG-4 erratic | 2,423 | 196.86 | **149.75** | -47.11 | -81.56 | -12.32 |
| REG-7 intermitente | 7,584 | 149.95 | **125.64** | -24.31 | -17.40 | +5.93 |
| REG-5 lumpy A/B | 1,665 | 278.88 | **184.98** | -93.90 | -101.65 | -2.99 |
| REG-2 smooth B | 8,719 | 122.61 | 118.26 | -4.35 | -26.64 | -17.64 |
| REG-8 seasonal | 3,060 | 61.13 | 54.25 | -6.88 | +30.15 | +17.71 |

### Por semana

| Semana | WAPE base | WAPE tuned | Δ | BIAS base | BIAS tuned |
|---|---:|---:|---:|---:|---:|
| 2026-05-04 | 80.64 | 73.00 | -7.64 | -10.14 | +0.24 |
| 2026-05-11 | 75.19 | 70.51 | -4.68 | -3.59 | +4.79 |
| 2026-05-18 | 68.64 | 65.80 | -2.84 | +21.38 | +24.64 |

## Camino de tuning (4 fases secuenciales)

| Fase | Target | Hyperparams ganadores | WAPE |
|---|---|---|---:|
| Baseline | — | — | 74.37 |
| 1 | REG-2/4 SMA blend | SHORT=4, DW=0.5 | 72.27 |
| 2 | REG-7 Croston/SBA | HEUR=0.80, CROSTON=0.25, SBA=0.20 | 70.81 |
| 3 | REG-8 SI seasonal | SI_CEIL=3.0, ALPHA=0.20, MIN_Y=2 | 70.51 |
| 4 | REG-5 lumpy + collapse | TRIED=0.05, COLLAPSE=0.40 | **69.48** |

## Trade-offs a considerar

**Ganancias:**
- REG-5 (lumpy) y REG-4 (erratic): over-forecast brutal eliminado (BIAS -100% → ~0%). Menos stock muerto.
- REG-7 (intermitentes): WAPE -24pp, BIAS pasó de over a centrado.
- REG-1 (músculo, 75% del real): NO degradó.
- W04 mejora dramática: BIAS -10% → 0%.

**Riesgos:**
- Motor general más conservador: BIAS total +3.9% → +11% (sub-forecast).
- Si Marco tenía la regla "sub-forecast cuesta más que over", este tuning va en contra. PERO el over-forecast antes era en gran parte SOBRE stock muerto, no demanda real.
- W18 (peak Stella, etc.) sigue sub-forecast +25% (no se tocó esa parte del motor).

## Próximos pasos para promover a productivo

1. Aplicar los 12 cambios al `02_forecast/HM SI Forecast.py`.
2. Bump VERSION_ID a `FWD_v3_47_AUTOTUNE_TEST1`.
3. Copy/paste al SA en Odoo.
4. Correr backtest oficial en Odoo (1 semana cerrada, ej. W22 cuando se cierre).
5. Validar que el output coincida con la predicción local (±2pp WAPE).
6. Si OK → commit. Si no → diagnosticar diferencia.

## Validación pendiente

- **Test sobre 10 semanas extendido** (no solo 3): para confirmar que la mejora no es overfitting a W04-W18.
- **Test sobre los SKUs específicos problemáticos** (SKU 9407 Stella): ver si los cambios afectan ese caso.
- **Test BIAS-centered (Fase 5)**: agregar constraint BIAS en [-3%, +3%] y re-tunear si el +11% es inaceptable.

## Archivos asociados

- `cache/` — snapshot data usado en el tuning
- `HM_SI_local.py` — mirror del motor (overrides aplicados via auto_tune.py)
- `auto_tune.py` — script de tuning (con BASELINE_OVERRIDE acumulado)
- `resultados/tune_phase_{1..4}_*.parquet` — rankings completos de cada fase
- `resultados/compare_final.parquet` — comparativa baseline vs tuned por regimen
