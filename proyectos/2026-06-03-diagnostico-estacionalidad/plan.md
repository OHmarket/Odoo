# Plan — Factores de estacionalidad y eventos

Ver `diseno.md` para el qué/por qué. Este plan es el cómo, en ciclos chicos
(una hipótesis, un cambio, medir, promover). Read-only hasta tener FVA que gane.

## Estado

- [x] Paso 1 — eventos con aumento real (`eventos_uplift.py`): 15 medidos, 2
      arquetipos, regla de apertura. **Cerrado.**
- [x] Paso 2 — verano (`verano_curva.py`): swing 2.04×, peak Feb, same-store −5%.
      **Cerrado.**
- [x] Paso 2c — ¿granularidad `categ × rank ABCXYZ` para los factores?
      (`rank_sparsity.py`, `rank_uplift_eventos.py`, `rank_uplift_verano.py`).
      **Cerrado: NO se agrega la dimensión rank.** Eventos suben proporcional
      entre ranks (lift relativo 0.93–1.04); en verano el gradiente es "la cola
      C/Z es menos estacional" (C 0.79, Z 0.70), no "AX es más" (0.97), y el
      gate FVA por SKU del Paso 3 ya recorta esas colas. Ver diseno.md §6.
- [ ] Paso 3 — modelo de factores (overlay disperso sobre SES(0.5)).

## Calendario que manda

| Hito | Fecha objetivo | Por qué esa fecha |
|---|---|---|
| L1 verano validado (read-only, FVA+) | ~04-jul | antes de pedir backfill / promover |
| Backfill fact table a 2023 (Marco corre) | ~mediados jul | verano por categoría a 3 años |
| L1 verano productivo + backtest | ~31-jul | listo para compra de verano |
| L2 eventos validado | ~ago | 18-sep lo cubre presupuesto interino |
| Mini-calendario aperturas por sala | antes de cada irrenunciable | factor condicional |
| **Factor verano sólido vivo** | **~30-sep** | **deadline duro: ramp de verano** |

## Paso 3 — plan de implementación (cerrado 2026-06-10 con evidencia 2c)

### Modelos (Studio, los crea/edita Marco)

| Modelo / campo | Tipo | Para qué |
|---|---|---|
| `x_forecast_factor_week` (NUEVO, chico) | categ × week_start futuro | factor_verano, factor_evento, evento, factor_total, versión. `x_name` = `'%s:%s' % (categ_id, week_start)` (required). El fact existente queda como HISTORIA (hechos); este modelo es el PLAN (semanas futuras). Resuelve el flag "¿v14 fact o capa nueva?" → capa nueva. |
| `product.template.x_studio_eventos` (NUEVO campo) | many2many → `x_holiday_master` | marca SKU evento-only (pipeño, granadina, cola de mono). Un SKU puede tener 2+ eventos. |
| `x_holiday_master` (filas nuevas) | — | agregar eventos comerciales: San Valentín, Halloween (tipo "comercial"). |
| `x_sala_apertura_evento` (NUEVO, chico, Fase D) | team × occurrence | apertura en irrenunciables; histórico autopoblado venta>0, futuro lo edita Marco. |

`x_x_pos_week_sku_fact.season_factor_units` NO se toca: queda como piso (b)
del FVA y medición histórica.

### Script nuevo: `02_forecast/OH Factor Semanal.py` (Server Action)

Escribe `x_forecast_factor_week` para las próximas ~26 semanas:

1. Curva verano por categoría (Fourier K3 destendenciada, dummy evento —
   método ya validado en `real_categoria_diag.py`).
2. Zona-factor: hombros donde el índice se aleja de 1; fuera → factor 1.
3. Factor evento × categoría (mismo método de `rank_uplift_eventos.py`,
   semanas-evento vs baseline limpio) con arquetipo 🅰️ víspera / 🅱️ día.
4. Modulación calendario desde `x_holiday_occurrence`: día-semana (S/D ×0.4),
   bloques (18+19; Halloween+Todos los Santos = misma semana, deduplicar),
   largo del finde.
5. LOCK_KEY nuevo (consultar tabla en memoria antes de asignar).

### Cambio en consumidor: `03_stock/OH Analisis de Stock.py`

Al proyectar demanda futura:
- **Proyección por ventana, semana a semana (time-phased / DRP), no mu plano:**
  `compra = Σ_{w ∈ [hoy+lead, hoy+lead+cobertura]} mu_week × factor_total(w) / factor_verano(hoy)`.
  Así la anticipación de eventos sale sola: la compra que cubre la semana del
  18-sep ve el factor 2-3 semanas antes (requisito explícito de Marco
  2026-06-10: él se abastece la semana ANTERIOR al 18, no la del 18).
- `demanda(w) = mu_week × factor_total(categ, w) × damping_rank`
  (damping: CZ 0.65, AY 1.14, resto 1.0 — `matriz_damping_verano_rank.csv`,
  solo cuando el factor activo es verano).
- SKU con `x_studio_eventos` y semana en ventana → **ancla LY** (venta de la
  ventana LY, perfil semanal LY), SIN factor de categoría encima (doble conteo).
- Motor base (Forecast Base) NO se toca: el overlay vive en el consumo,
  auditable y reversible.

### Fases (un ciclo, una medición)

- [ ] **A — L1 verano** (~jul): modelo factor + script (solo verano + damping)
      + **FVA gate** read-only contra 2 pisos (SES solo / season_factor v13),
      holdout temporal. Si no gana a ambos, no se promueve.
      Calibración pendiente (sim 2026-06-10, BIAS overlay +11.5% a h=4):
      (a) estimar curva sobre **cohorte estable de salas** (aperturas inflan
      amplitud en data pooled; patrón de `verano_curva.py`); (b) shrink del
      factor hacia 1 si (a) no basta. NO agregar tendencia al factor:
      brazo probado y descartado (empeora, FVA 6.4→3.5; la tendencia pooled
      es +12% por aperturas, el same-store −11% ya vive en el mu local).
- [ ] **B — L2 eventos** (~ago): factores evento + modulación + bloques. FVA
      del overlay completo. Incluye **resaca post-evento**: Forecast Base debe
      excluir/reemplazar semanas-evento en su entrada (hoy el spike del 18
      infla el SES 1-2 semanas después → sobre-compra post-evento). Mismo
      patrón que su cleansing de quiebres.
- [ ] **C — SKU-evento** (antes de FP, sep): filas comerciales en holiday
      master + campo Studio + curación de `sku_evento_candidatos.csv` (106
      candidatos; ojo falsos positivos de lanzamiento con 1 solo año) +
      ancla LY en Análisis de Stock. **El ancla LY se escala por deriva de
      nivel local**: `venta_LY × (nivel_actual / nivel_LY)` de la sala —
      same-store cae ~−11%/año (Marco, 2024 vs 2025); replicar LY crudo
      sobre-compra.
- [ ] **D — aperturas irrenunciables**: mini-calendario + factor condicional.
- [ ] **Monitor de sesgo del overlay** (pedido Marco 2026-06-10, evaluación
      constante): el Factor Semanal ya congela el factor vigente de cada
      semana pasada (wipe solo-futuro). Monitor semanal read-only:
      `BIAS_8sem(categ, h) = Σ(mu×factor_vigente − real)/Σ(real)` + tracking
      signal (alarma si |TS|>4-6 sostenido). Corrección automática suave
      (`factor/(1+bias)^0.5`, tope ±15%) recién en v1.2 y solo si la alarma
      persiste. ⚠️ Coordinar con z: al des-sesgar el overlay, el z=1.68
      actual pasa a ser real (hoy 1.68+sesgo ≈ 2.05 efectivo) — revisar z en
      el mismo cambio, no después.

### Validación canónica del overlay

- Cervezas verano FVA+ | Espumantes × Año Nuevo 6.3× (factor directo) |
  Pipeño FP por ancla LY (factor no lo levanta) | Abarrotes plano sin factor |
  CZ de categoría estacional: comprar MENOS que el factor pleno.

## Validación / casos canónicos

- Cervezas/hielo/aguas: verano FVA+ poolable.
- Dulces (chocolates/galletas): evento-Navidad domina, verano débil.
- Halloween: factor en el día (🅱️), categoría dulces.
- Categoría plana (abarrotes): base sin factor, FVA no justifica.
- Irrenunciable: factor solo en salas que abren; el resto sin spike.

## Flags a resolver

- [ ] Same-store −5%/año: ¿real o artefacto? Confirmar antes de fijar tendencia.
- [ ] Backfill fact table a 2023 (depende de Marco).
- [ ] Dónde vive el factor productivo (v14 fact vs capa nueva).
