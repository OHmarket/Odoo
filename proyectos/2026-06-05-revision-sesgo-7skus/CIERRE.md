# CIERRE — Revisión de sesgo de 7 SKUs (2026-06-05)

## Objetivo
Operaciones reportó 7 SKUs con problema: 4 "cortos" (0154 CocaCola 3L, 2233 Vital
gas 1.6L, 1963 Monster, 1966 Monster Ultra) y 3 "pasados" (vinos Gran120: 6242
Cab, 6243 Merlot, 6244 Carmenère). Pregunta: ¿es un problema de forecast del motor
(Forecast Base) o de otra capa? Validar el análisis inicial con más información.

## Qué se hizo (read-only, sin tocar producción)
- `analisis.py` — bias inicial + safety activo de los 7.
- `diag5_persistencia_sesgo.py` — bias por segmento (ABC×series_type) sobre 8
  orígenes rolling; tracking signal de Trigg.
- `diag6_clean_vs_dirty.py` — bias en combos siempre disponibles vs combos con
  quiebre (experimento natural para aislar el doble conteo).
- `diag7_revalida_7skus.py` — re-mide los 7 SKUs en limpio + semana a semana.
- `diag8_wape_bias_global.py` — WAPE y BIAS globales del motor, 8 periodos.

Fuente: `x_forecast_backtest` (8 sem rolling, 2026-04-06 a 2026-05-25; cada semana
cutoff = semana−1 → walk-forward genuino). Quiebre cruzado con
`x_stock_balance_daily`. Excluido siempre: Ventas San José (crm_team 11) y la
semana 04-06 (bug de cutoff <8 sem).

## Hallazgo metodológico central (el más importante)
**Doble conteo de-censura.** El motor pronostica demanda **de-censurada** (cleansing
de entrada, correcto para comprar), pero el backtest la mide contra **venta real
censurada** por quiebre → **bias positivo artificial**. Excluir solo la semana
medida con stockout NO alcanza (la censura es más ancha que el flag). Medido
apples-to-apples (combos siempre disponibles):

| | BIAS | qué es |
|---|---|---|
| TODO (excl San José) | +16.8% | contaminado |
| LIMPIO (combos disponibles, excl bug 04-06) | **~+7%** | número real |

→ ~10pp de los 17 eran artefacto de medición. Guardado en memoria
`feedback_doble_conteo_decensura`. La de-censura **se queda ON en producción**.

## Resultado sobre los 7 SKUs (bias LIMPIO)

| SKU | grupo | inicial (contaminado) | LIMPIO | veredicto |
|---|---|---|---|---|
| CocaCola 3L | CORTO | +8.8% | +4.0% | forecast OK |
| Vital | CORTO | +21.2% | +16.7% | sobre real (leve) |
| Monster | CORTO | −2.6% | +10.8% | sobre, no neutro |
| Monster Ultra | CORTO | −8.8% (sub) | +5.5% | **sobre, NO sub** |
| Cab | PASADO | +33.6% | n/d (0/13 salas limpias) | quiebra en las 13 |
| Merlot | PASADO | +16.0% | +1.8% | forecast OK |
| Carmen | PASADO | +25.1% | +9.5% | sobre leve |

- **CORTO: análisis inicial CONFIRMADO y reforzado.** El motor no está corto en
  ninguno; el único sub aparente (Monster Ultra) era artefacto → en limpio es +5.5%
  over. El quiebre **no es del forecast** → es cobertura/lead (los 7 están bajo su
  propio target, con z safety ya en ~1.68).
- **PASADO (vinos): análisis inicial REFUTADO.** El "+16 a +34% over" era casi todo
  doble conteo. En limpio: Merlot ~OK, Carmen leve, Cab no medible — y **si Cab
  quiebra en las 13 salas, no está sobre-stockeado**. La percepción "pasado" no la
  respalda un sesgo de forecast.

## Estado del motor (8 periodos)
- **BIAS real ≈ +7%** (limpio, sin bug, sin semanas-evento 04-27/05-18). Sobre-
  forecast modesto y sistemático, **concentrado en segmentos smooth** (AX +7.5%,
  AY +12%); en erráticos/intermitentes el sesgo real es **~0** (lo que parecía
  +100/+300% era todo censura).
- **WAPE ≈ 67%** (limpio). En línea con la validación del motor (62.5%, otoño es
  más volátil).
- **El error es casi todo varianza, no sesgo** (+7% bias vs 67% WAPE). Corregir el
  sesgo **libera caja** (no sobre-comprar), **no mejora el acierto**.

## Decisión
- **No se toca el motor ni la de-censura.** El problema de los 7 SKUs **no es de
  forecast**: es **cobertura/abastecimiento/lead** (cortos) y percepción no
  respaldada (vinos).
- **No se corrige el bias por SKU.** A nivel SKU el bias es ruido (alta varianza
  semanal, pocas salas limpias). La única señal corregible está en el **agregado
  por segmento smooth**, y es modesta (~+7%).

## Pendiente / siguiente hilo
1. **Cobertura/lead de los 7** (donde sí está el problema): por qué stock < target
   con z ya lean; revisar lead_weeks y abastecimiento.
2. **Capa de corrección de sesgo** (proyecto aparte, si se decide): solo segmentos
   smooth, calibrada en combos limpios, capada y asimétrica (K_UNDER=2), gobernada
   por tracking signal Trigg, validada walk-forward. Antes: confirmar si el +7% es
   nivel estable o arranque estacional de invierno (el bias semanal limpio sugiere
   ruido + un par de spikes, no nivel claro → probablemente NO amerita capa todavía).

## Conclusión de una línea
El forecast de los 7 SKUs está bien (sesgo real ~0 a +12%, antes inflado por doble
conteo). El problema vive en cobertura/lead, no en el motor. El motor tiene un
sesgo agregado de ~+7% (smooth) que es lever de caja, no de acierto, y a nivel SKU
es ruido — no se corrige individualmente.
