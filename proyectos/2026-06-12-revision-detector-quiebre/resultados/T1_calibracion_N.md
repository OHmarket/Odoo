# T1 — Calibración ventana de surtido activo N

Fuente: report.pos.order, 3 salas (Panguipulli790 alto, Paillaco medio, Mehuin
bajo), desde 2025-04-01. Gaps inter-venta por (sala, SKU), semanal → días.
6.072 pares medibles, 140.999 gaps.

| Clase | p50 | p75 | p90 | p95 | >30d | >45d | >60d |
|---|---|---|---|---|---|---|---|
| X | 7 | 7 | 14 | 14 | 1,0% | 0,5% | 0,2% |
| Y | 7 | 7 | 21 | 35 | 5,8% | 3,2% | 1,9% |
| Z | 7 | 21 | 49 | 84 | 16,1% | 11,6% | 8,5% |
| TODOS | 7 | 7 | 21 | 35 | 5,4% | 3,3% | 2,2% |

## Decisión: **N = 45 días** (PROXY)

- Cubre X (99,5%) e Y (96,8%): rotación regular no cae en falso-inactivo.
- Z >45d (11,6%) es correcto NO marcarlo: en intermitentes no se distingue
  góndola vacía de no-demanda; canon OOS = surtido con velocidad reciente.
- Corta perpetuación: deslistado inactivo a los 45 d, no 400.
- Error en dirección segura (sub-censura → leve over-forecast, lever de caja).
- N=30 muy agresivo (16% Z); N=60 no gana en X/Y.

Documentar en header del detector como PROXY; recalibrable.
