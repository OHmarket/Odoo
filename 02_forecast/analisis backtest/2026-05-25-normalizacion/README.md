# Backtest comparativo — normalización de demanda

Objetivo: medir el impacto de la normalización de demanda (overlay
`x_demanda_normalizada`) sobre WAPE/BIAS de HM-SI.

## Resumen del setup

- HM-SI productivo tiene flag `USE_DEMAND_NORMALIZATION` (default `False`,
  comportamiento idem actual).
- Cuando flag está activo, HM-SI hace lookup a `x_demanda_normalizada` y
  reemplaza `q_raw[wk]` por `qty_norm` si la celda fue corregida por censura.
- OH Forecast Backtest propaga el flag al HM-SI que invoca.

## Workflow paso a paso

### Setup previo (una sola vez)

1. **Crear Server Action wrapper** "OH Forecast Backtest NORMALIZADO":
   - Settings → Technical → Server Actions → New
   - Model: cualquiera (ej: `res.users`)
   - Type: Execute Python Code
   - Pegar el contenido de `wrapper_normalizado.py`.
   - Confirmar que `BACKTEST_ACTION_ID` (línea ~12) coincide con el ID real
     del SA `OH Forecast Backtest`. Si no, ajustarlo.

### Corrida pareada

2. **Run A (PRE — sin normalización)**:
   - Action → Run sobre `OH Forecast Backtest` (el original, sin context).
   - Esperar a que termine (5-15 min según la ventana).
   - La notificación final mostrará `norm_overlay=OFF (hits=0)`.

3. **Exportar resultado PRE**:
   ```bash
   cd "c:/Users/sanhu/Odoo"
   python "02_forecast/analisis backtest/2026-05-25-normalizacion/export_backtest.py" pre
   ```
   Genera `resultados/pre_YYYYMMDD-HHMMSS.csv`.

4. **Run B (POST — con normalización)**:
   - Action → Run sobre `OH Forecast Backtest NORMALIZADO` (el wrapper).
   - Esperar a que termine.
   - La notificación final mostrará `norm_overlay=ON (hits=N)`.

5. **Exportar resultado POST**:
   ```bash
   python "02_forecast/analisis backtest/2026-05-25-normalizacion/export_backtest.py" post
   ```
   Genera `resultados/post_YYYYMMDD-HHMMSS.csv`.

6. **Comparar**:
   ```bash
   python "02_forecast/analisis backtest/2026-05-25-normalizacion/comparar_backtest.py" \
       "02_forecast/analisis backtest/2026-05-25-normalizacion/resultados/pre_YYYYMMDD-HHMMSS.csv" \
       "02_forecast/analisis backtest/2026-05-25-normalizacion/resultados/post_YYYYMMDD-HHMMSS.csv"
   ```
   Output: tabla por consola + `resultados/comparativo.csv`.

## Métricas a vigilar

| Métrica | Mejora esperada |
|---|---|
| WAPE global | ↓ (sub-forecast por quiebres se corrige) |
| BIAS global | acercarse a 0 desde negativo |
| MAE global | ↓ |
| WAPE por régimen REG-1 | **NO debe regresarse** (control intacto, regla del repo) |
| WAPE en SKUs con quiebre frecuente | ↓ significativo |
| WAPE en SKUs sin quiebre | sin cambio (overlay no aplica) |

## Decisión

- Si WAPE baja y REG-1 no se regresa → cambiar
  `USE_DEMAND_NORMALIZATION_DEFAULT = True` en HM-SI productivo.
- Si WAPE sube o REG-1 se regresa → revisar AVAIL_FLOOR / CAP del
  productivo de normalización y volver a iterar.
