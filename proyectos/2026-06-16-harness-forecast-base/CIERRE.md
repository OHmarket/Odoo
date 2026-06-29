# CIERRE — Harness Forecast Base + cap de la de-censura leve

Fecha: 2026-06-17. Estado: **cap PROMOVIDO a producción** (commit `bc12c7f`,
rama `stock-cd-passthrough`). Bake-off de no-smooth queda como próximo proyecto.

## Qué se hizo

1. **Mirror local de OH Forecast Base.py (= SA "OH SES Forecast")** en
   `forecast_base_local.py` — copia exacta del motor (clasificación SB,
   SES/SMA, de-censura por día con perfil dow). Paridad numérica verificada.
   Fuente de venta: cache `pos_weekly.parquet` (modelo Odoo `x_pos_week_sku_sale`,
   venta semanal por SKU; dic-2024 → 18-may-2026).

2. **Hallazgo: el modo LEVE de la de-censura sobre-inflaba.** Medido por dos vías:
   - **Salto vs vecinas sin-evento** (`salto_decensura.py`): el leve corregía
     semanas que YA habían vendido sobre su nivel local, dejándolas en **1,84×**
     la mediana de las vecinas (44% saltaban >2×). El severo, en cambio, caía
     justo al nivel local (mediana **1,00×**) — estaba bien.
   - Causa: la fórmula `venta/(1-peso_perdido)` extrapola la tasa de los días
     abiertos (que ya sobre-rindieron) a los días cerrados.

3. **Fix promovido: cap del leve al baseline in-stock** (mismo que usa el severo),
   solo-levanta: `val = max(y, min(y/(1-pw), base))`. Si la semana ya vendió ≥
   nivel similar → no infla. Severo intacto.

## Validación

- **Salto** post-cap: leve 1,84× → **0,95×** (>2× cae de 44% a 6%).
- **A/B limpio en producción** (mismo dato, capado vs previo): **−3,1%** de mu_sum
  (35.571 → 34.480), concentrado en smooth de alto volumen (artefacto). Calza con
  el mirror (−3,7%). El "−17,9%" que asustó era comparación sucia (datos/params
  distintos entre runs), NO el cap.
- **Backtest 10 sem (semanas sin quiebre)**: capado mejora vs previo en las tres
  métricas — WAPE −1,0pp, BIAS +16,2%→+14,2% (corta sobre-estimación, sin pasar
  a sub-forecast), FVA −6,2%→−4,7%.

## Lo que el backtest destapó (próximo lever, > que el cap)

El motor **pierde contra naive SMA(4)**, pero el gap NO es difuso:

| series_type | %venta | FVA vs naive | BIAS |
|---|---|---|---|
| smooth | 65,7% | **+1,1%** | +14,9% |
| erratic | 13,6% | **+7,4%** | +5,3% |
| intermittent | 13,6% | **−24,5%** | **+35,1%** |
| lumpy | 4,4% | **−18,4%** | +9,5% |

El motor le gana al naive en smooth+erratic (79% de venta). Pierde feo en
intermittent+lumpy (SMA6 arrastra spikes esporádicos → sobre-pronostica). Eso es
acierto **y** caja (sobre-comprar lentos = sangrado de inventario).

**Próximo proyecto: bake-off / best-fit por SKU (patrón SAP IBP) acotado a
no-smooth.** Candidatos SMA4/SMA6/Croston-SBA/SES; selección por rolling holdout
con guardrails (mín. historia, umbral ~10% para no bailar de modelo, fallback al
default por series_type). NO tocar smooth/erratic. Validar en mirror antes de
promover.

## Limitaciones honestas

- Backtest = **solo semanas sin quiebre** (venta censurada se excluye para no
  medir doble-conteo). Los productos en su semana de quiebre se evalúan aparte
  por **peer-stores** (no por WAPE).
- Cache hasta 18-may; 10 sem de evaluación. Para firmar el FVA de intermitentes
  conviene refrescar a junio.

## Scripts del proyecto

`forecast_base_local.py` (mirror), `salto_decensura.py`, `prototipo_cap.py`,
`backtest_cap.py` (+ FVA por series_type), `export_estimacion.py`,
`peer_stores.py` / `validar_reconstructor.py` / `prototipo_peer.py` (ground-truth
de quiebre por pares).
