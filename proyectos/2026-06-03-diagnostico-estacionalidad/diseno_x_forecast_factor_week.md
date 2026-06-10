# x_forecast_factor_week — Diseño del modelo de factores semanales

**Fecha:** 2026-06-10 · **Estado:** diseño cerrado, script v1.0 escrito y
validado en local; **pendiente: crear el modelo en Studio y primera corrida.**
Documento de handoff autocontenido (la conversación de diseño completa está
resumida aquí).

---

## 1. Qué es y qué decisión habilita

Matriz de **factores de corrección por categoría × semana futura** (52 semanas),
sobre la *semana base* (nivel destendenciado, factor centrado en 1). Corrige el
forecast operativo para estacionalidad (verano) y eventos (feriados/comerciales),
habilitando compra multi-semana con anticipación automática de eventos.

```
demanda(sala, sku, semana_w) =
  mu_week(sala, sku)                      ← Forecast Base (SES), NIVEL local. No se toca.
  × factor_total(categ, w) / factor_verano(categ, semana_actual)
                                          ← este modelo. División por el SI de HOY:
                                            el SES ya trae la estacionalidad actual
                                            adentro (evita doble conteo).
  × damping_rank                          ← CZ 0.65 / AY 1.14 / resto 1.0, SOLO verano.
compra = Σ demanda(w) para w ∈ [hoy+lead, hoy+lead+period_weeks]   (DRP fechado)
```

Excepción L3 (manda sobre todo): SKU con evento vinculado
(`product.template.x_studio_eventos`, pendiente Fase C) y semana en ventana →
**ancla LY** escalada por nivel local (`venta_LY × nivel_actual/nivel_LY`,
same-store cae ~−11%/año), SIN factor de categoría encima.

## 2. El modelo Studio (crear con estos campos exactos)

Nombre sugerido: "Forecast Factor Semanal" → `x_forecast_factor_week`.

| Campo | Técnico | Tipo |
|---|---|---|
| Descripción | `x_name` | (Studio lo crea, required; lo llena el script: `categ_id:week_start`) |
| Categoría | `x_studio_categ_id` | Many2one → product.category |
| Inicio Semana | `x_studio_week_start` | Date (lunes, fecha real del calendario) |
| Semana ISO | `x_studio_iso_week` | Integer |
| Factor Estacional | `x_studio_factor_verano` | Float |
| Factor Evento | `x_studio_factor_evento` | Float |
| Evento | `x_studio_evento` | Char |
| Factor Total | `x_studio_factor_total` | Float (= verano × evento; lo que consume Stock) |
| Versión Cálculo | `x_studio_source_version` | Char |

Vistas: lista + pivot (categoría × semana, medida factor_total).
~63 categorías × 52 semanas ≈ 3,300 filas. Fecha real (no solo iso_week):
el evento viaja con el calendario de cada año.

## 3. El script: `OH Factor Semanal.py` (v1.0, en esta carpeta)

Server Action (safe_eval). LOCK_KEY **99009614** (libre, verificado).
- **Factor verano:** regresión armónica Fourier K=3 sobre log-venta semanal de
  `x_pos_week_sku_sale` (pooled salas, toda la historia), destendenciada, con
  dummy de semana-evento que absorbe los spikes. Gates: amplitud ≥1.3
  (categ estacional) y zona muerta |SI−1|<0.10 → 1.0.
- **Factor evento:** uplift medido = semana objetivo / mediana semanas limpias
  ±6 (excluye todas las semanas-evento → sin estacionalidad ni doble conteo).
  Arquetipo A feriado → semana de la VÍSPERA; B comercial (San Valentín,
  Halloween, generados internos) → semana del DÍA. Eventos en la misma semana
  → máximo, no producto (bloques: 18+19 sep; Halloween+Todos los Santos).
  Madre/Padre excluidos (uplift flojo medido). Calendario: `x_holiday_occurrence`
  (`x_studio_holiday_id`, `x_studio_holiday_date`) + master `x_studio_code`.
- **Stateless hacia adelante:** cada corrida (semanal, antes de Análisis de
  Stock) recalcula TODO desde la historia y regenera solo las semanas FUTURAS;
  las pasadas quedan congeladas con su factor vigente → historial para el
  monitor de sesgo. NO ajuste incremental por venta reciente (el nivel lo
  persigue el SES; el factor solo es forma).
- **Gotchas safe_eval resueltos:** sin `math` → sin/cos desde Postgres
  (`generate_series`+`sin()`), `ln` por serie atanh y `exp` por `E**x`
  (validados vs numpy, error <1e-9); Gauss-Jordan puro Python; dummy de evento
  solo si tiene variación (todo-cero = matriz singular, bug cazado en test).

## 4. Evidencia que cierra el diseño (paso 2c, scripts `rank_*` y `sim_*`)

- **Eventos suben proporcional entre ranks ABCXYZ y tipos de serie** → factor
  por categoría parejo; sin dimensión rank (lift relativo 0.93–1.04).
- **Verano:** solo CZ (0.65) y AY (1.14) se desvían con CI fuera de 1 →
  matriz damping de 3 valores (`resultados/matriz_damping_verano_rank.csv`).
- **Elasticidad genérica a eventos R²=0.36** → el par evento×categ es
  idiosincrático; factor directo (253 pares con señal en
  `resultados/factor_evento_categ.csv`), fórmula intensidad×sensibilidad solo
  como fallback.
- **Sim FVA out-of-sample** (`sim_fva_overlay.py`, 15 cortes, verano 2025-26):
  overlay vs SES solo: **+1.3pp (h=1), +2.3 (h=2), +6.4 (h=4)** WAPE; aplasta
  al season_factor v13 crudo (que valida por qué HM-SI falló). 40/60 categs
  FVA+ (75% volumen) → gate por categoría necesario (Cervezas Importadas −15.7,
  Tradicionales −3.0 quedan apagadas).
- **SKUs evento-only detectables por concentración** (share ventana ≥50%):
  pipeño 88%, granadina 84%, helado piña 83%, cola de mono 81%
  (`rank_sku_evento_detector.py`; "pan de pascua" no existe en el maestro).

## 5. Calibraciones pendientes ANTES del FVA gate / promoción

1. **BIAS overlay +11.5% a h=4 (rampa):** causa probable = curva sobre data
   pooled con salas que abrieron en la ventana (la tendencia pooled da +12%/año
   por aperturas; el same-store real cae −11%). Fix: estimar curva sobre
   **cohorte estable de salas** (patrón `verano_curva.py`); si no basta, shrink
   del factor hacia 1. **NO agregar tendencia al factor** (brazo probado:
   empeora FVA 6.4→3.5).
2. **Eventos a h=2 dan FVA −4.2** → modulación de calendario (día-semana ×0.4
   si cae S/D; finde largo amplifica) es Fase B, no opcional.
3. Backfill fact a 2023 (Marco) → 3 veranos en vez de 1.

## 6. Operación y monitoreo

- **Monitor de sesgo** (diseñado, no construido): BIAS móvil 8 sem por
  categ × horizonte sobre factor_vigente congelado + `x_hm_si_forecast.mu`;
  alarma tracking signal |TS|>4-6; corrección automática suave
  (`factor/(1+bias)^0.5`, tope ±15%) recién v1.2 si la alarma persiste.
- ⚠️ **Coordinación con z:** hoy z AY/BY ya bajados (1.28/1.04, commit 02f2403);
  el sesgo del motor (~+7%) actúa como z escondido. Al des-sesgar el overlay,
  revisar z EN EL MISMO cambio.
- Colchones vigentes y su riesgo (no traslapar): período H (demanda esperada) +
  z·σ·√H (ruido demanda) + 2 días solo_bodega (lead camión, NO eliminar: riesgo
  logístico distinto) + display stock (comercial; hoy DISPLAY_ENABLED=False
  default) + sesgo motor +7% (a eliminar, no a compensar).

## 7. Secuencia de implementación

1. ☐ Marco crea `x_forecast_factor_week` en Studio (tabla §2).
2. ☐ Pegar `OH Factor Semanal.py` en Server Action nueva y correr.
3. ☐ Validación visual: cervezas 1.5-1.9 ene-feb / 1.0 invierno; espumantes
   semana 29-dic alto; abarrotes plano 1.0; semana 14-sep-2026 con evento.
4. ☐ Calibración v1.1 (cohorte estable) + FVA gate vs 2 pisos.
5. ☐ Integración Análisis de Stock (suma fechada por ventana + división SI hoy
   + damping). Recién aquí toca compras.
6. ☐ Fases B (modulación + resaca post-evento en Forecast Base), C (SKU-evento
   + ancla LY), D (aperturas irrenunciables). Detalle en `plan.md`.

**Git:** commits 02f2403 (z) y 6aae567 (proyecto) en rama `stock-cd-passthrough`;
**push pendiente**. Plan maestro: `plan.md`; diseño del proyecto madre: `diseno.md`.
