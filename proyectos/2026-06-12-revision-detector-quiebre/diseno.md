# Revisión detector de quiebres (OH Quiebre de Stock.py, STOCKOUT_v2_0)

## Síntoma reportado
Productos que llegan a 0 por quiebre se perpetúan marcados `stockout=True`
los días posteriores.

## Evidencia (read-only, vía XML-RPC)

- 179.918 filas en `x_stock_balance_daily`, 17.478 pares (team, producto).
- Racha de quiebre por par: mediana 3 días, **708 pares con 30+ días, máx 413 días**.
- **376 pares (2,2%) terminan con balance < 0**, y aportan **19,9% de TODAS las
  filas de quiebre**. El balance negativo arrastra toda la serie del par.
- 27 pares están en negativo plano sin ningún movimiento por 400+ días.

## Causa raíz (confirmada, no inferida)

El balance negativo es **100% artefacto de reconstrucción**, no realidad:

| Producto | balance reconstruido (último quiebre) | stock.quant REAL hoy |
|---|---|---|
| AUSTRAL CALAFATE (MEHEX) | −6 | **+17** |
| LAYS STAX (FU120) | −1 | **+13** |
| LAYS JAMON SERRANO (CO899) | −1 | **+15** |
| BON O BON GALLETA (PA763) | −1 | **+1** |

**En todo Odoo hay 0 stock.quant internos negativos (0 de 12.823).** Las
cantidades físicas nunca son negativas; el negativo nace del roll-backward.

Mecanismo: el roll-backward ancla en `stock.quant` de hoy y resta/suma
`stock_move`. Cuando el neto de movimientos del rango NO reconcilia con el quant
actual (ajustes de inventario sin move, drift histórico, doble conteo de
recepciones internas), la serie reconstruida acumula un offset → cruza a
negativo en el pasado. El header ya lo admite a medias: *"balance reconstruido
es inferencia matemática desde quant actual, NO un snapshot real"*.

Sobre ese balance contaminado, el detector aplica:
```
is_stockout = bal_end <= 0.0001
```
→ marca quiebre todos los días que el artefacto está ≤ 0, sin pisar el negativo
ni exigir evidencia de demanda. De ahí la perpetuación (hasta 413 días).

## Dos defectos, no uno

1. **Sin piso en 0:** un balance físicamente imposible (negativo) cuenta como
   "más quebrado". Hay que `max(0, balance)`. Industria: el on-hand nunca es < 0.
2. **Sin gate de demanda / sin tope de perpetuación:** un ítem en 0 sin ventas
   por meses NO está "en quiebre", está deslistado / no surtido. SAP / Oracle
   Retail definen día OOS = *assortment activo* (vendió hace poco) **AND**
   disponibilidad 0. Eso corta la cola perpetua automáticamente.

## Propuesta (pendiente de aprobación — Fase 0)

- **Fix A (piso):** clamp `bal_end`/`bal_start` a `max(0, .)` en la
  reconstrucción. Bajo riesgo, mata el 20% de filas-fantasma negativas.
- **Fix B (gate demanda):** `is_stockout` solo si hubo `qty_out > 0` en una
  ventana móvil (p.ej. 30–45 días) → patrón "assortment activo + disponibilidad 0".
  Corta la perpetuación que reportó Marco.
- **Fix C (reconciliación, más profundo):** si el neto de moves no reconcilia con
  el quant actual, marcar la serie como no-confiable en vez de emitir quiebres.
  Ataca la causa raíz del drift; requiere tracing a stock_move.

Recomendación: A + B juntos como una versión ("detección robusta de quiebre").
C como proyecto aparte.
