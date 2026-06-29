# Informe gerencial de quiebres — Clase A

## Qué / por qué
Informe de evolución de quiebres de stock por sala desde ene-2025, restringido al
**universo clase A** (el 80% del margen acumulado de la segmentación ABCXYZ). El
resto (B/C) se analiza por separado.

Decisión comercial: ver dónde y cuánto se está quebrando lo que más margen aporta,
y si la situación mejora o empeora en el tiempo por sala.

## Universo
`x_stock_balance_daily` con `x_studio_abcxyz LIKE 'A%'` (AX+AY+AZ).
Rango: `x_studio_date >= 2025-01-01`.

## Métricas por sala × mes
- **SKUs distintos en quiebre**: `COUNT(DISTINCT product_id)` con ≥1 día de quiebre
  TOTAL en el mes.
- **Días-quiebre total**: `COUNT(*)` de días en quiebre total.
- **Nº episodios**: rachas de días consecutivos en quiebre total (gaps-and-islands),
  asignadas al mes de inicio.
- **Duración promedio de episodio**: `AVG` del largo de la racha, en días.
- **Incidencias parciales** (aparte): días con venta-y-quedó-en-0 intradía
  (`x_studio_stockout_partial = TRUE`). No cuentan como episodio.

## Motor (Fase 0 — server-side, sin matar el server)
Server Action **read-only** (SELECT puro, no escribe en datos de negocio; solo crea
un `ir.attachment` con el CSV). Tres queries SQL agregadas server-side:
1. Gaps-and-islands → episodios por (team, pid) → agregado a (team, mes).
2. SKU-distinct + días total por (team, mes).
3. Incidencias parciales por (team, mes).

Canon: gaps-and-islands (window functions) es el método SQL estándar para rachas
consecutivas; `read_group` no puede. Devuelve ~12 salas × 18 meses ≈ 200 filas.
Nunca extrae filas crudas → no repite el incidente del "API completo del modelo".

## Entregable
- CSV Excel-CL (`;`, `,`, utf-8-sig) como `ir.attachment` descargable + volcado al log.
- Mapeo `team_id` → nombre real de sala vía `pos.config.name`.
- Resumen ejecutivo (markdown) lo arma el asistente con el CSV: tendencia, salas
  peores, dirección del quiebre A desde ene-2025.

## Fuera de alcance (ahora)
Clase B y C → análisis separado posterior.
