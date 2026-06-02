# Auto-modelo por segmento — diseño

**Fecha:** 2026-06-02
**Estado:** Fase 1 (harness local read-only)

## Qué medimos
El mejor modelo de forecast POR SEGMENTO (no uno global). El SMA(4) gana en smooth
pero sub-pronostica intermitentes (REG-7/REG-8). ¿Un selector por segmento — SMA en
smooth, Croston/SBA en intermitente — le gana al SMA(4) plano?

## Qué decisión
Si el ensemble por segmento le gana al SMA(4) plano (sobre todo en la cola
intermitente sin perder REG-1), se evalúa llevar el auto-modelo a producción.

## Cómo lo hacen los grandes
SAP IBP / Blue Yonder: best-fit / pick-best por SKU-segmento. Clasificación
Syntetos-Boylan (ADI/CV2) → modelo apropiado por tipo de serie.

## Base de confianza (Fase 0)
Antes de probar nada se REPLICA EXACTO el SMA(4) del server (paridad diff≈0,
corr 1.0). Si la base local no reproduce el server, no se confía en el resto.

## Decisiones
- Segmento: series_type (LOCAL, Syntetos-Boylan) + regimen (del export del motor).
- Ganador: menor WAPE entre los candidatos con |BIAS| ≤ 10%; fallback menor |BIAS|.
- Candidatos: Naive, SMA(3/4/6), Mediana(4), WMA(4), SES(0.3/0.5), Croston(0.1), SBA(0.15).
- Walk-forward 1 paso, shift(1) (sin look-ahead). Excluye San José (medición).

## Fuente
ventas_semanal.csv (venta combo-expandida, 21 sem). Paridad: export SMA4 P.
Regimen/ABC: export SMA4 M (join por combo).

---

## RESOLUCIÓN (2026-06-02) — MODELO BASE

Validado en 15 sem evaluables (284.479 obs, sin San José), walk-forward shift(1).
Gate de paridad SMA(4) local vs server: PASÓ (diff 0.000000, corr 1.000000).

### Modelo base elegido: por régimen LOCAL, SES con 3 niveles de α

```
clasificación: RÉGIMEN LOCAL por combo (producto × sala) — Script 1 / x_studio_regimen
modelo:
   REG-0                 → HalfNaive (0.5 × última venta)   [coletazo de muertos]
   REG-1                 → SES(α=0.5)   [el grueso, 53% del volumen, prefiere 0.5]
   REG-4, sin_regimen    → SES(α=0.7)   [más reactivos]
   REG-2, REG-3          → SES(α=0.6)   [default; poca data, no forzar α de filo]
   REG-5, REG-6, REG-7, REG-8 → Mediana(4)   [lumpy / intermittent / seasonal]
```

### Por qué 3 niveles de α (no 1 único, no 5 distintos)

El α óptimo SÍ varía por régimen (sweep: REG-1→0.5, REG-4/sin→0.7, REG-2→0.6).
- **SES(0.6) único:** WAPE 61.87% / BIAS +8.3% / FVA +7.82%.
- **3 niveles (0.5/0.6/0.7):** WAPE 61.70% / BIAS +8.7% / FVA +8.08%.
- **α completo por régimen:** WAPE 61.70% / +8.7% / FVA +8.09% (idéntico a 3 niveles).

Los 3 niveles capturan TODO el valor del α-por-régimen con solo 3 valores. Los α que
mueven la aguja son 2 (REG-1→0.5 grueso, REG-4/sin→0.7); REG-2/3 quedan en 0.6 por
defecto porque su "óptimo" (0.4/0.6) es ruido sobre poca data. No es el overfit que mató
al HM-SI (allí se tuneaba por celda SKU×sala); acá es 1 parámetro sobre 3 segmentos
gruesos con curva de α plana → estable y defendible.

### Resultado vs incumbente
SMA(4) plano: WAPE 67.12% / BIAS +18.9%  →  MODELO BASE: WAPE 61.70% / BIAS +8.7%
**FVA +8.08%** (−5.4pp WAPE; bias menos de la mitad).

### Pendiente Fase 2 (producción)
Validar dónde vive el régimen LOCAL por combo (Script 1 escribe x_studio_regimen con
bucket=GLOBAL, pero el export trae régimen por producto×sala). Alternativa: clasificar
series_type localmente en el script de forecast (ADI/CV2 sobre las 26 sem que ya carga).
Detalle y artefactos en CIERRE.md.
