# Factores para semanas con estacionalidad y eventos significativos

**Fecha:** 2026-06-03
**Tipo:** Fase 0/1 — diagnóstico read-only validado; diseño de capa productiva.
**Estado:** diseño cerrado y validado con datos. Pendiente escribir plan y promover.

---

## 1. Problema y decisión

Definir **factores que ajusten el forecast solo en períodos con señal real**
(verano + eventos), dejando el resto al motor base. Hoy el `season_factor_units`
de `x_x_pos_week_sku_fact` es un ratio-to-mean crudo (ruidoso, no destendenciado,
sin separar eventos, sesgado en año parcial) y se aplica a todo por igual,
metiendo ruido a SKUs que no son estacionales.

**Decisión que habilita:** qué factor aplicar, a qué SKU, en qué semana —
gateado por FVA, para comprar/forecastear mejor en verano y eventos sin degradar
el resto del año.

## 2. Principio rector

**Factor solo donde hay señal real. El resto lo maneja el motor base SES(0.5).**
Menos parámetros = menos sobreajuste = menos ruido (parsimonia / bias-variance).
La estacionalidad es una hipótesis que cada SKU debe **ganarse por FVA**, no un
default.

## 3. Lo medido (evidencia, no supuesto)

### 3a. Eventos — 15 medidos sobre `pos.order` diario, 3 años, por sala
(`eventos_uplift.py`. Uplift vs baseline mismo día-semana, abierto/cerrado
empírico.)

- **La víspera ES el evento** en feriados (no el día): 18-sep víspera 4.39×,
  Navidad víspera 3.01× (>25-dic 2.01×), Día del Trabajo **día 0.53× CAE** /
  víspera 2.72×.
- **Dos arquetipos:** 🅰️ feriado/celebración → peak víspera; 🅱️ comercial de
  consumo → peak el día (Halloween 2.52× el 31, San Valentín 1.76× el 14).
- **Irrenunciables: solo 45-72% de salas abren**; las que abren spikean 2.6-4.4×.
  Factor condicional a apertura.
- **Madre (1.25×) y Padre (1.21×) flojos** para OH (negocio regalo, no
  conveniencia) → candidatos a no meter factor.
- Ranking peak: 18-sep 4.4× > 19-sep 4.2× > Año Nuevo 3.5× > Navidad 3.0× >
  Día Trabajo / Halloween / Todos los Santos / Viernes Santo 2.4-2.7× > resto
  1.5-2×.

### 3b. Verano — curva 3 años, cohorte estable, limpia de eventos
(`verano_curva.py`.)

- **Swing 2.04×**: Feb 158 (peak) vs May 78 (valle). Bloque dic-mar, no spike.
- **Peak en FEBRERO**, no enero. Compra de verano puesta para fin de enero.
- **Diciembre modesto (104)** a nivel total: Navidad es spike de evento, no
  "diciembre alto".
- **Same-store −4.9%/año** (cohorte estable cae; la cadena crece por nº tiendas).
  🚩 confirmar.
- A nivel total, limpiar eventos casi no cambia la curva (delta ≤6 pts) → el
  **event-cleaning importa a nivel categoría, no en el agregado**.

## 4. Modelo elegido: overlay disperso sobre el motor base

```
forecast = base_SES(0.5)        ← motor, en TODO el año (OH Forecast Base, existe)
         × factor_verano        ← L1: solo en los HOMBROS del verano, FVA-gated
         × damping_rank         ← L1b: CZ 0.65 / AY 1.14 / resto 1.0 (solo verano)
         × factor_evento        ← L2: solo semanas-evento, por arquetipo + apertura

excepción L3 (manda sobre todo lo anterior): SKU con evento vinculado
(x_studio_eventos) y semana dentro de la ventana → ancla LY (venta de la
ventana del año pasado, perfil semanal LY). SIN factor de categoría encima
(doble conteo). Para pipeño/granadina/cola de mono: baseline ≈ 0 fuera del
evento, el factor multiplicativo no los levanta.
```

**Evidencia del paso 2c (2026-06-09/10) que fija granularidades:**
- Eventos: proporcional entre ranks y tipos de serie → factor por categ parejo.
- Verano: solo CZ (0.65) y AY (1.14) se desvían con CI fuera de 1 → matriz
  damping de 3 valores (`matriz_damping_verano_rank.csv`).
- Elasticidad genérica a eventos: R²=0.36 → el par evento×categ es
  idiosincrático; factor DIRECTO por par (253 con señal), fórmula
  intensidad×sensibilidad solo como fallback de pares sin muestra.
- SKUs evento-only: detectables por concentración (share ventana ≥50%);
  detector validado con pipeño 88%, granadina 84%, helado piña 83%,
  cola de mono 81%.

**Por qué hombros y no todo el verano:** SES(0.5) sigue bien lo plano (trough
invierno y peak meseta) pero **laggea en los giros**. El factor de verano vale en
la **rampa de subida (nov→feb)** y de **bajada (feb→abr)**, donde SES llega tarde.
Fuera de esa zona, factor = 1.

**Zona-factor (cuándo prende):**
```
prende = (índice estacional de la categoría se aleja de 1)  OR  (semana-evento)
fuera  → solo SES(0.5)
```

### L1 — Verano (se construye primero)
- Curva estacional por **categoría** (regresión armónica Fourier K≈3,
  destendenciada, eventos absorbidos por dummy).
- Pooling a categoría (o padre del árbol si la hoja tiene poco volumen).
- **FVA por SKU:** el factor de su categoría se aplica solo si le baja el WAPE
  vs base. Categoría plana → base sin factor.
- Tendencia y nivel por SKU (no se heredan de la categoría).

### L2 — Eventos (después)
- ~13 eventos con factor (excluye Madre/Padre), keyed por calendario:
  `x_holiday_occurrence` + comerciales a mano (Halloween, San Valentín).
- Arquetipo 🅰️ feriado → factor en víspera; 🅱️ comercial → factor en el día.
- **Modulación por configuración de calendario (determinística, se calcula):**
  el efecto del feriado depende del día-semana en que cae. Dos levers medidos:
  - 🥇 **día-semana vs finde:** feriado en Sáb/Dom ≈ NO-evento (×~0.4); en día
    de semana ×1.0. (Virgen Carmen Dom 1.09× vs Mié 2.07×.)
  - 🥈 **sánguche / finde largo:** el bloque largo amplifica (5d 3.36× vs 3d
    2.13×). 18-sep lunes 5.74×.
- **Bloques de feriado (clusters):** feriados adyacentes = UN bloque-evento, no
  factores sumados día a día (18+19 = Fiestas Patrias). El largo del bloque es
  dinámico (finde + leyes ad-hoc que agregan feriados) → leer el span real de
  no-laborables de `x_holiday_occurrence`, no hardcodear. Anticipación en la
  víspera del bloque; magnitud escala con su largo.
- Irrenunciable → **condicional a apertura**: mini-calendario de aperturas por
  sala (histórico se detecta con venta>0; futuro lo define Marco).
- Factor por **evento × categoría** (qué sube en cada evento).
- **Reusa la maquinaria del presupuesto** (`x_presupuesto_de_venta`:
  `ly_calendar_date` + `tratamiento` NORMAL/FERIADO_ACTUAL/FERIADO_ANTERIOR/
  PROM_4_SEMANAS). No reinventar la des-contaminación de calendario.

## 5. Validación (no negociable)

FVA contra **dos pisos**: (a) base SES(0.5), (b) `season_factor_units` v13 actual.
Si el factor no le gana a ambos, no se promueve. Validación out-of-sample (holdout
temporal), no in-sample.

## 6. Enfoques descartados

- **Granularidad `categ × rank ABCXYZ` para L1/L2 (evaluada 2026-06-09, paso
  2c)** — descartada con evidencia. La tesis era: en estacionalidad/eventos los
  AX/BX suben más que su categoría y las colas CZ menos → factor por
  `sucursal × categ × rank`. Lo medido (ratio-of-ratios, pooled 12 salas,
  73 semanas, CI bootstrap):
  - **Eventos: crecimiento proporcional entre ranks.** Lift relativo mediano
    0.93–1.04 en todos los ranks (letra A 1.01, C 0.94). El factor por categ
    captura ~todo; rank agrega ±5pp de ruido.
  - **Verano: gradiente real pero asimétrico.** AX NO es más estacional (0.97);
    la cola sí es MENOS estacional (C 0.79, Z 0.70). Y además es parcialmente
    **circular**: XYZ se define por CV, los SKUs estacionales caen en Y/Z por
    construcción (X es plano por definición; AY fue el único grupo amplificado,
    1.14).
  - **El gate FVA por SKU ya diseñado captura esto mejor** que una dimensión
    rank: el factor de categoría solo se aplica al SKU si le baja el WAPE, y
    eso recorta las colas CZ donde el factor sobra. No se agrega dimensión.
  - Sparsity confirmó el pooling: a nivel `team × categ × rank` solo 8% de
    celdas tiene muestra; pooled salas 29% de celdas (77.6% del volumen).
  - Scripts: `rank_sparsity.py`, `rank_uplift_eventos.py`,
    `rank_uplift_verano.py`, `rank_sanity_totales.py` (+ `resultados/rank_*`).
  - Caveats: clasificación ABCXYZ actual aplicada retro (PROXY, sin historia);
    un solo ciclo de verano en el fact; celdas SIN/CZ infladas por churn de
    surtido. 🚩 Hallazgo operativo colateral: 60-70% de los SKUs A tuvieron
    quiebre en alguna sala en semanas-evento (sesgo conservador del lift, y
    problema de cobertura en sí mismo).
- Mensual (smearea verano y eventos) — descartado, el negocio corre semanal.
- 52 dummies semanales (sobreajuste con span corto) — descartado, se usa Fourier.
- Factor a todo el año (lo actual) — descartado, mete ruido en el trough plano.
- Umbral absoluto de WAPE para gatear — descartado, arbitrario; se usa FVA.
- Heredar tendencia de la categoría al SKU — descartado, el PLC es propio del SKU.

## 7. Datos: activos y brechas

| Activo | Cobertura | Uso |
|---|---|---|
| `pos.order` | 2023-05 → hoy (3 años) | medición eventos/verano diaria |
| `x_x_pos_week_sku_fact` | dic-2024 → hoy (18m) | categoría×local×semana, combo-explode, LY, season_factor v13 (baseline) |
| `x_pos_week_sku_sale` | dic-2024 → hoy | venta semanal SKU explotada |
| `x_stock_balance_daily` | abr-2025 → hoy | de-censurar quiebres |
| `x_holiday_occurrence` | 2025-2027 | calendario feriados |
| `x_presupuesto_de_venta` | 2025-2026 diario | maquinaria de evento a reusar |

**Brecha:** verano **por categoría a 3 años** requiere backfillear el fact table
a 2023 (productivo, lo corre Marco). Mientras, se usa el mix de 18 meses.

## 8. Caveats marcados

- Same-store −5%/año: confirmar antes de fijar tratamiento de tendencia.
- Factor de irrenunciable inútil sin el mini-calendario de aperturas.
- Quiebres de-censurables solo desde abr-2025.

## 9. Artefactos del proyecto

```
proyectos/2026-06-03-diagnostico-estacionalidad/
├── diseno.md                  (este archivo)
├── plan.md                    (hitos y validación)
├── eventos_uplift.py          (paso 1, read-only) + resultados/
├── verano_curva.py            (paso 2, read-only) + resultados/
├── real_categoria_diag.py     (perfil estacional 62 categorías)
├── real_tabla_mensual.py      (tabla mensual por categoría)
└── sim_diagnostico.py         (validación del método con data sintética)
```
