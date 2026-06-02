# CIERRE — Auto-modelo por segmento → MODELO BASE por régimen local

**Fecha:** 2026-06-02
**Estado:** Fase 1 cerrada (harness local validado). Fase 2 (producción) con 1 validación pendiente.
**Aprobado por:** Marco Sanhueza

---

## OBJETIVO

Tras reemplazar el motor HM-SI por SMA(4) puro, medir si un **modelo por segmento**
(no uno global) le gana al SMA(4) plano, partiendo de **replicar exacto** el cálculo
del server (gate de confianza) antes de probar candidatos.

## GATE DE CONFIANZA (Fase 0) — PASÓ

SMA(4) local vs `forecast_qty` del server (export SMA4 P): **40.107 pares, diff máx
0.000000, corr 1.000000, 100% < 0.001**. La base local reproduce el server al bit.

## RESULTADO — MODELO BASE

Medido sobre **15 semanas evaluables (284.479 obs, ~664K u), sin San José**, walk-forward
1 paso con `shift(1)` (sin look-ahead):

| modelo | WAPE | BIAS | FVA vs SMA(4) |
|--------|------|------|---------------|
| SMA(4) plano (incumbente) | 67.12% | +18.9% | — |
| **MODELO BASE (régimen local, α en 3 niveles)** | **61.70%** | **+8.7%** | **+8.08%** |

**−5.4pp de WAPE y el bias cae de +18.9% a +8.7%** (menos de la mitad del over-forecast).

### Estructura del modelo base

```
clasificación:  RÉGIMEN LOCAL por combo (producto × sala)
modelo por régimen (SES con 3 niveles de α):
   REG-0                       → HalfNaive (0.5 × última venta)   [coletazo de muertos]
   REG-1                       → SES(α=0.5)   [el grueso, 53% del volumen]
   REG-4, sin_regimen          → SES(α=0.7)   [más reactivos]
   REG-2, REG-3                → SES(α=0.6)   [default; poca data]
   REG-5, REG-6, REG-7, REG-8  → Mediana(4)   [lumpy / interm / seasonal]
```

Detalle por régimen en `resultados/modelo_base_regimen.csv`.

## DECISIONES Y POR QUÉ (lo que se probó y descartó)

1. **Segmentar LOCAL, no global.** Régimen-local (62.6%) y series_type-local (62.8%)
   empatan y le ganan al **ABCXYZ global (63.8%)**. El ABCXYZ es un valor por producto
   (100% un solo valor/SKU); el régimen varía por sala (87.7% de los SKU tienen ≥2).
   La forma de la serie se captura por combo, no por producto.

2. **Más granularidad NO suma.** ABCXYZ (10 seg) < ABC (4) ≈ series_type (5); cruzar
   dimensiones (series_type×XYZ, 20 seg) tampoco mejora. Todo cae en una meseta ~63%;
   las diferencias son ruido. La palanca es **elegir el modelo correcto por forma de
   serie**, no partir más fino.

3. **2 modelos + 1 caso, no un campeón libre por segmento.** El "campeón libre por
   régimen" (cada uno su mejor modelo+α) da FVA +7.2% pero **pierde** contra el base
   (+7.8%) porque (a) en REG-0 elige SES → over-forecast +46% de stock muerto, y (b) en
   segmentos flacos (REG-3/5/6, <1.500 u) sobreajusta a ruido. El base manda esos por
   **regla teórica** (Syntetos-Boylan), no por campeón medido.

4. **REG-0 = HalfNaive.** En muertos/declive todos los modelos normales sobre-pronostican
   (+30% a +84% → recompra de muerto). HalfNaive es el menos malo (WAPE 93.5%, bias −35%,
   le gana incluso a forecast=0). Marco confirma: tiene **dummy de control para muertos**,
   así que HalfNaive cubre el coletazo sin riesgo.

5. **SES con 3 niveles de α (0.5/0.6/0.7), no 1 único ni 5 distintos.** El α óptimo
   varía (sweep: REG-1→0.5, REG-4/sin→0.7, REG-2→0.6); la curva es plana entre 0.5–0.7.
   - SES(0.6) único: WAPE 61.87% / BIAS +8.3% / FVA +7.82%.
   - **3 niveles: WAPE 61.70% / +8.7% / FVA +8.08%** ← elegido.
   - α completo por régimen: 61.70% / +8.7% / +8.09% (idéntico → no aporta más).
   Los 3 niveles capturan todo el valor con 3 valores: los α que mueven la aguja son 2
   (REG-1→0.5 el grueso, REG-4/sin→0.7 reactivos); REG-2/3 quedan en 0.6 por defecto
   porque su "óptimo" sobre poca data es ruido. NO es el overfit que mató al HM-SI (allí
   se tuneaba por celda SKU×sala); acá es 1 parámetro sobre 3 segmentos gruesos.

6. **Croston/SBA descartados:** no ganan ningún segmento; sobre-pronostican fuerte (+30%
   a +466%) incluso en intermitentes. La cola intermitente se ataca con **Mediana(4)**.

7. **Naive descartado:** "muy errático" (decisión de Marco) — nervioso para reabastecer.

8. **Cap de |BIAS| relajado a 15%** (era 10%): el de 10% excluía a SES/WMA (bias ~+11%)
   y metía Naive; con +bias aceptable (sub-forecast cuesta más que over-forecast) SES gana.

## RESUELTO — régimen es GLOBAL, se clasifica LOCAL en el script

Validado: Script 1 escribe `x_studio_regimen` con `team_id=False` (GLOBAL por producto).
El régimen local del export venía del motor que lo recalculaba al vuelo. → **El script
de forecast clasifica series_type LOCALMENTE** (ADI/CV2 sobre las 26 sem que ya carga) y
lee ABC global de `x_calculo_abc_xyz`. Mapeo AUTO:
smooth+A→SES(0.5) / smooth+B,C→SES(0.6) / erratic→SES(0.7) / lumpy,interm,no_signal→Mediana(4).

## ESTADO — etapa 1 PROMOVIDA

- **Script productivo:** `02_forecast/OH Forecast Base.py` (corre en SA 1576, reemplaza
  el SMA4). Validado: paridad OK, FVA +6.84% local, backtest real 3 sem WAPE 62.6% /
  bias +4.6% (sin quiebre +1.1%), sin errores de opcode.
- **Cron:** `hard_reset=True, demand_window_weeks=26`, SIN `date_to` (última sem cerrada),
  SIN `demand_history_months` (obsoleta).
- **OH SMA4 Forecast.py:** superseded por Base (queda como referencia/rollback).

## ETAPA 2 — pendiente (de-censura de entrada por quiebre, LOCF)

Limpiar el input de semanas con quiebre con **LOCF** (valor pre-quiebre) → forecast estima
demanda no restringida → reabastece lo que corresponde. El WAPE sube vs crudo (62.8→64.2)
y es ESPERADO (real censurado, no demanda perdida del modelo). Solo semanas de quiebre
real; la baja estacional queda intacta. Aplica a TODOS los productos, no solo cigarros.
Diseño completo en `etapa2_decensura.md`. Requiere cablear `x_stock_balance_daily` al script.

## ARTEFACTOS

- `harness.py` — Fases 0-3 (paridad, clasificación, candidatos, ganador).
- `base_model.py`, `cruce_xyz.py`, `cruce_smooth.py`, `cmp_segmentacion.py`,
  `cmp_dimensiones.py`, `medir_por_regimen.py`, `reg0_least_bad.py`,
  `sweep_ses_alpha.py`, `sweep_alpha_por_regimen.py`, `modelo_base_regimen.py`.
- `resultados/` — parity.txt, ranking_segmento.{csv,xlsx}, ranking_xyz.{csv,xlsx},
  ranking_smooth.{csv,xlsx}, champions_cap15.csv, modelo_base_regimen.csv.
