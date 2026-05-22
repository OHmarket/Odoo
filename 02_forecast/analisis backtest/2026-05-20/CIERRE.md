# Cierre del día 2026-05-20 — HM-SI Forecast

## Estado al cierre

**Productivo: `FWD_v3_39_AUTO_MODEL`** (snapshot: `HM_SI_v3_39_productivo.py`).

Camino productivo del día: v3.35 → **v3.36** → **v3.37** → **v3.39**.

| Versión | Estado | Cambio |
|---|---|---|
| v3.36 COLLAPSE | activa | Detector de colapso en `_calc_base_demand` (ratio sobre raw_vals, branch nuevo cuando ratio < 0.30) |
| v3.37 CORR_VALIDATION | activa | Validación empírica del factor de corrección externo (atenúa over-correcciones cuando empírico > teórico) |
| v3.38 SMA8 | DESCARTADA | SMA(8) en vez de SMA(6) → colas devastadas (AZ -49%, CZ -48%) |
| v3.38 SBA REG7 | DESCARTADA | SBA(0.05) dogmático en REG-7 → BIAS -4.5pp peor |
| **v3.39 AUTO_MODEL** | **activa** | Bake-off per-SKU (heur + SBA(0.15) + Croston(0.10) + seasonal_naive_52) con heuristic-bias 10% |

## Métricas de cierre (backtest 3 semanas W18-W20/2026)

| Métrica | v3.37 baseline | v3.39 productivo final | Δ |
|---|---|---|---|
| **WAPE global** | 67.36% | **66.94%** | **-0.42pp ✓** |
| BIAS global | -3.27% | -4.50% | -1.2pp (en rango [-15,+5]) |
| **REG-1 WAPE (control)** | 53.68% | **53.69%** | **✓ intacto** |
| REG-5 WAPE | 104.48% | 101.86% | -2.6pp |
| REG-6 WAPE | 182.22% | 171.33% | **-10.9pp** |
| REG-7 WAPE | 90.02% | 89.27% | -0.75pp |
| REG-8 WAPE | 75.91% | 73.88% | -2.0pp |

## Archivos del día

| Archivo | Contenido |
|---|---|
| `HM_SI_v3_39_productivo.py` | Snapshot del runner productivo al cierre |
| `bt_v3_37_baseline.csv` | Backtest de la versión previa (referencia) |
| `bt_v3_38_sma8_DESCARTADO.csv` | Backtest del experimento SMA(8) (descartado) |
| `bt_v3_38_sba_reg7_DESCARTADO.csv` | Backtest del experimento SBA dogmático REG-7 (descartado) |
| `bt_v3_39_auto_model.csv` | Backtest del productivo final |

## Aprendizajes del día (memoria)

1. **SI deflation enmascara colapso**: el ratio short/long sobre `base_vals` SI-deflated no detecta caídas reales cuando coinciden con baja estacionalidad. Solución: evaluar el ratio para detección de colapso sobre `raw_vals` (v3.36 ajustado).
2. **Sub-forecast cuesta más que over-forecast**: confirmado en SMA(8) descartado (colas Z devastadas con BIAS -48%) y SBA REG-7 descartado (-4.5pp BIAS).
3. **Cambios per-regimen dogmáticos fallan, cambios per-SKU con bias funcionan**: el patrón SAP IBP (bake-off + heuristic-bias 10%) mejoró WAPE sin tocar REG-1. Es el patrón a seguir.
4. **SI no captura día de la semana del feriado**: W18/2026 tuvo Día del Trabajador en viernes (long weekend); el motor sub-forecasteó -16.5%. La SI promedia años sin distinguir día. Solución prevista: capa `x_promo_plan` (Fase 3+).
5. **`_forecast_models.py` portado al runner principal**: `_croston` y `_sba` son helpers disponibles. SBA(0.05) dogmático no funciona, pero SBA(0.15) y Croston(0.10) ganan en algunos SKUs vía bake-off.

## Casos testigo registrados

- **SKU 451500 ROYAL GUARD GOLDEN LAGER, Futrono** — colapso 330→6 u/sem en 6 semanas. Forecast bajó de 43 a ~6 u con v3.36 (detector activa, ratio_raw=0.026 < 0.30).
- **SKU 0154 COCA COLA DES 3L, Paillaco** — sobre-corrección por precio. Factor teórico 0.814 → atenuado a ~0.9 por validación empírica v3.37; forecast 13 → 15.

## Pendientes priorizados (próximas sesiones)

1. **Capa `x_promo_plan`** (Fase 3+): multiplicador post-forecast con calendario de feriados para resolver W18-tipo BIAS -16.5%. Es el siguiente cambio de mayor impacto.
2. **Persistir `x_studio_regimen` en `x_forecast_backtest`**: hoy reconstruimos manualmente desde abcxyz/series_type/lifecycle. Si se persiste, los análisis por regimen son directos.
3. **Hampel filter** sobre `base_vals` antes de `_calc_base_demand`: limpiar outliers (cervezas con peaks navideños). Riesgo controlado si se aplica selectivamente.
4. **Elasticidad por SKU con shrinkage** en `7- OH Price Correccion.py`: hoy `ELASTICIDAD_ABC = {'A':1.30, 'B':1.00, 'C':0.70}` es por clase. Calibrar por SKU con regresión.
5. **Subir `DEMAND_WINDOW_WEEKS` a 56**: habilitaría `seasonal_naive_52` ampliamente en el bake-off v3.39 (hoy con ventana 26 prácticamente no participa).
6. **Sigma por modelo ganador en v3.39**: hoy reusa sigma del heurístico. Si SBA/Croston ganan en muchos SKUs, calcular sigma específico para mejorar safety stock.

## Referencias

- Plan completo de la sesión: `C:\Users\sanhu\.claude\plans\es-clave-detectar-estos-joyful-shore.md`
- Header del runner con changelog completo: `5- HM SI Forecast.py:1-220`
- Roadmap original: `HM_SI_v4_proceso.md:395-454`
