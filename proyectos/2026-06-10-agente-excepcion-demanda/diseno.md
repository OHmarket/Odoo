# Agente Analista de Excepción de Demanda

## Fase 0 — Diseño

### 1. Qué problema resuelve
El Demand Review canónico (SAP IBP / IBF) tiene un planner que: trabaja una lista de
excepción, mira la venta del SKU marcado, diagnostica la causa del error (promo, quiebre,
dato malo, ruido) y corrige la **historia/evento** (no el número), con cada toque medido
por FVA. Hoy ese rol no existe en OH Market: el motor corre solo y nadie trabaja la
excepción. El monitor de impacto-$ (`2026-06-09`) ya entrega la lista; falta el **analista**
que la procese: junte evidencia, diagnostique y proponga acción medida, dejando la decisión
al humano.

### 2. Qué decisión se toma con el resultado
Cada ciclo, el dueño (Marco) recibe propuestas accionables ("este SKU rompió por X, propongo
Y, el backtest da +Zpp, ¿apruebas?") en Odoo y aprueba/rechaza. El forecast del motor se
ajusta solo con overrides **aprobados**. Decisión = qué SKU-sala corregir esta semana y cómo.

### 3. Qué pasa si el modelo se equivoca
Riesgo acotado por diseño:
- El agente **nunca aplica** — solo propone (estado `pendiente`). Humano aprueba.
- Toda propuesta lleva FVA backtesteado > 0; sin eso → `no_action`.
- El motor consume solo `aprobado`. Un mal diagnóstico cuesta el tiempo de revisión, no el
  forecast. Auto-medición posterior (¿el override aprobado mejoró de verdad?) cierra el loop.

### 4. Cómo lo resuelven los grandes (modelo canónico)
- **Demand Review / S&OP** (IBF, APICS, SAP IBP): gestión por excepción + history cleansing
  + judgmental override con reason code + **FVA governance** (Gilliland): el toque que empeora
  se elimina. Principio: corregir causa (historia/evento), no el output, y medir cada capa.
- **Agentes LLM de orquestación** (JD.com 2025, arXiv 2509.03811): ganancias medidas cuando el
  agente orquesta intent→tareas→plan-correction con humano; el forecast/optimización por debajo
  sigue siendo estadístico. NO usar LLM para producir el número (NeurIPS 2024, arXiv 2406.16964:
  ablar el LLM no empeora el forecast). → El agente razona y orquesta; el número se mide.

### 5. Enfoques considerados
- A) Reporte determinista sin LLM → descartado: no "mira y diagnostica", solo taxonomía fija.
- B) Agente LLM autónomo que aplica correcciones → descartado: viola FVA governance (override
  sin aprobación) y la evidencia de FVA negativo del override de juicio.
- C) **Agente LLM propose-only, human-in-the-loop, herramientas deterministas** → elegido.
  El LLM orquesta (decide qué evidencia mirar, diagnostica, redacta); monitor/sensing/gate son
  deterministas y validados. Propone a Odoo; humano aprueba; motor consume aprobados.

### 6. Enfoque elegido y qué NO se hace
**Agente Claude (Agent SDK), propose-only, semanal post-pipeline.**
- NO pronostica ni corrige a ciegas. NO aplica nada. NO reemplaza el motor.
- NO inventa la magnitud: el número viene de demand sensing (medición) + gate FVA.
- Alcance inicial: **solo bucket evento (cervezas)** con corrección validada. Otras causas →
  diagnostica y reporta `no_action` con razón, sin actuar, hasta tener gate propio.

#### Arquitectura
```
[OH Forecast Base] → mu_week (base)
   │
[Agente Analista de Excepción]  (Claude Agent SDK, Python, semanal)
   tools (deterministas) que el LLM invoca:
     list_exceptions(weeks, top_n)  → monitor impacto-$ + causa
     get_evidence(product_id)       → venta diaria, eventos precio (x_price_coreccion),
                                       quiebres (x_stock_balance_daily), ABC/series_type,
                                       list_price, historia forecast-vs-real, calendario
     run_sensing_gate(product_id)   → demand sensing + backtest FVA → pp esperado
     propose_override(...)          → crea fila en x_forecast_override (pendiente)
   │
[x_forecast_override]  ← Marco aprueba/rechaza en Odoo
   │
[Capa demand sensing (OH Demand Sensing)]  consume SOLO status=aprobado → mu_week_adjusted
   │
[OH Analisis de Stock]  COALESCE(mu_week_adjusted, mu_week)   (patch ya en repo)
```

#### Loop del agente (por excepción top)
1. `get_evidence` — junta lo que un planner miraría.
2. Diagnostica causa: evento / outlier_dato / quiebre / varianza_irreducible / estructural.
3. Acción según causa:
   - evento + `run_sensing_gate` FVA>0 → `propose_override(reset_level, value=nivel_medido)`.
   - outlier_dato → `propose_override(cleanse_history)`.
   - varianza/cola/quiebre → `no_action` con razón (no toca).
   - estructural recurrente → `no_action` + flag "volver estructural".
4. Crea propuesta solo si FVA backtesteado > 0; resto = `no_action` explicado.
5. Marco aprueba en Odoo; motor consume solo `aprobado`.
6. Auto-medición: semana siguiente mide si los aprobados mejoraron (FVA del agente).

#### Modelo `x_forecast_override` (Studio, lo crea Marco)
`x_name` (req), `x_studio_product_id` (m2o product.product), `x_studio_team_id` (m2o crm.team,
vacío=todas), `x_studio_week_start` (date), `x_studio_action` (selection: reset_level /
cleanse_history / no_action), `x_studio_value` (float), `x_studio_reason` (text),
`x_studio_evidence` (text), `x_studio_expected_fva` (float), `x_studio_status` (selection:
pendiente / aprobado / rechazado, default pendiente), `x_studio_source` (char, 'agent_v1').

#### Decisiones de implementación
- **Autonomía:** propose-only. Master switch + alcance `Cerveza`.
- **Modelo LLM:** Sonnet 4.x (barato, diagnóstico estructurado); Opus si se queda corto.
- **Runtime:** script Python con Claude Agent SDK, corre en el PC/servidor de Marco semanal,
  después del pipeline. Lectura vía `shared/odoo_xmlrpc` (read-only).
- **Escritura de propuestas:** `OdooReader` es read-only por diseño. Resolver en el plan entre
  (a) cliente de escritura mínimo acotado a `x_forecast_override` (bajo volumen, recomendado),
  o (b) agente emite JSON + Server Action importadora (preserva read-only externo).
- **Consumo de aprobados:** extender `OH Demand Sensing` para leer `x_forecast_override`
  (status=aprobado, semana actual) y escribir `mu_week_adjusted` con el value aprobado.

### 7. Casos canónicos de validación
- El agente, sobre los SKU de evento conocidos (Stella, Budweiser, Royal Guard), debe proponer
  `reset_level` con FVA>0 y narrar la causa correcta (evento de precio).
- Sobre SKU smooth de alto impacto sin evento (Cristal, JW Red sin evento esa semana) debe
  decir `no_action` (varianza irreducible) — NO proponer corrección.
- Sobre SKU con quiebre debe reconocer el dato censurado y no proponer corrección de forecast.
- Los overrides aprobados, medidos la semana siguiente, deben mostrar FVA agregado ≥ 0.

### Dependencias / riesgos
- Reusa: monitor (`2026-06-09-monitor-error-impacto`), demand sensing + gate
  (`2026-06-01-demand-sensing`), patch Stock (ya en repo).
- Riesgo doble corrección: el motor NO consume `x_price_coreccion.factor_corr`; si se reactiva,
  coordinar (este agente y factor_corr corregirían lo mismo).
- Costo LLM por corrida: acotado por top_n excepciones y alcance cervezas.

### Fuera de alcance (v1)
- Causas distintas de evento (solo diagnóstico, sin acción).
- Aplicación automática sin aprobación humana.
- Consenso multi-área / colaboración (paso 5 del Demand Review).
