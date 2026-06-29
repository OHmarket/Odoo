# Backlog de análisis — envío periodo / cadencia / fair-share

Lista viva. Se analiza **una por una**, con evidencia (sim o pull read-only), antes
de decidir el diseño final. No se promueve nada hasta cerrar las que afecten la
decisión.

## Items

1. **Efecto de eliminar la regla de 1 semana CD** (aislado).
   Cambiar SOLO `sala_H = 1.0 → period_weeks`, sin tocar el reorden. ¿Qué pasa con
   viajes, stock, fill? Hipótesis: sube stock, NO baja viajes (el reorden queda
   pegado al target). → **EN CURSO**

2. **Cadencia de envío** (el lever de viajes). Actual ~2-3d. Opciones 7d / otra.
   ¿Cuánto baja viajes por espaciar el camión, independiente del resto?

3. **Hueco de reorden (s,S) vs base-stock.** ¿El ahorro de viajes viene del hueco
   (drenar antes de recargar) o de la cadencia? Aislar los dos efectos.

4. **Horizonte del safety.** √periodo vs √cadencia (3d/7d). Incluye el doble conteo
   de σ por de-censura (σ inflada infla safety).

5. **Tabla de z por ABCXYZ.** Confirmar la productiva hoy. Calibrar fill↔stock.

6. **Working stock: periodo de compra vs cadencia de envío.** ¿El envío cubre el
   periodo (delay) o la semana logística? Desenredo de los 3 relojes.

7. **Fair-share cuando CD corto.** Igualar cobertura, alcance cadena. Con datos
   por sala reales (pull acotado).

8. **Realismo por sala.** El POC es agregado de cadena (pooling esconde varianza →
   fill real por sala más bajo). Pull por sala.

9. **Cola C/Z errática.** El ahorro y el servicio fuera de cervezas (movedores
   regulares).

10. **Económico: costo de un viaje CD→sala vs costo de capital.** El dato que
    decide si el trade-off viajes↔stock conviene, y dónde.

## Decisiones cerradas (no reabrir sin motivo)
- **La regla de 1 semana NO es la palanca de viajes.** Eliminarla sola sube stock
  +121% (period 15d), 0% menos viajes. No se toca de forma aislada.
- **El stock total de la cadena se CONSERVA.** El envío de 15d no crea capital;
  reubica del CD (−71%) a la sala (+38%), total plano (281 vs 281). El "+stock en
  sala" es capital que hoy está parado en bodega, movido a la góndola. Único costo
  neto posible = de-pooling del safety (√N salas), pendiente de medir por sala.

## Cambios aplicados al script productivo (OH Analisis de Stock.py)

- **v9.3.0 (en server)** — elimina el trato diferencial CD->sala. `sala_H=1sem`
  reemplazado por `sala_work_weeks = period_weeks` (delay); safety desacoplado
  sobre 7d (`sala_safety_weeks`). Efecto: la sala pasa de target 1 semana a su
  periodo. Confirmado con data real (reorder_target_weeks ~periodo, no ~1w).
- **v9.3.1 (pendiente aplicar)** — techo de cobertura 15d SOLO en CD->sala
  (opcion A: `sala_work_weeks = min(period_weeks, MAX_COVER_WEEKS)`). NO capa la
  compra del CD ni la directa-a-proveedor (esas necesitan el ciclo del proveedor;
  capar ahi = quiebre). Impacto medido: 3.804 lineas de delay 30d bajan ~43% su
  target; ~$31M deja de sobrecargar las salas (queda en CD). Productos delay<15d
  sin cambio (techo, no piso).

## Hallazgos por item

### Item 1 — eliminar regla 1 semana CD (CERRADO 2026-06-29)
- Aislado (z=1.28, period=15d, cadencia 3d, fiel al código donde `sala_H` gobierna
  target Y safety):
  - Viajes **+0%**, Stock **+121%**, Fill +0,14pp (ya estaba ~100%).
  - Escala con el periodo: 10d +46% / 15d +121% / 21d +209% / 30d +339% stock,
    siempre +0% viajes.
- **Causa raíz:** reorden pegado al target (base-stock). Subir el target sube la
  meseta de inventario; el camión topa a la misma frecuencia. Los viajes los fija
  la **cadencia de revisión**, no el nivel del target.
- **Implicancia:** la palanca de viajes está en cadencia (item 2) y hueco de
  reorden (item 3). El target solo mueve capital y servicio.
- Script: `item1_regla_1sem.py`.
