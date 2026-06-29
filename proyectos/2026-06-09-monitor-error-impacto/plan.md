# Plan — Monitor de error por impacto-$ (Fase 1)

## Tareas
1. [ ] `monitor_error.py` — pull read-only desde Odoo:
   - `x_forecast_backtest` (N semanas más recientes; default últimas 4: W20-W23).
   - `product.product` → `list_price` por id (un read batched).
   - `x_price_change_event` (is_real_change) y `x_loyalty_promo_event` → set (producto, iso_week) con evento.
   - `x_stock_balance_daily` (stockout / stockout_partial) → set (producto, sala, iso_week) con quiebre.
2. [ ] Métrica: pinball asimétrica (K_UNDER=2, K_OVER=1) × list_price.
3. [ ] Clasificar causa por fila (orden: quiebre → fantasma → evento → cola → smooth_real).
4. [ ] Excluir sala Ventas San José; marcar quiebre como no-accionable.
5. [ ] Salida en `resultados/`:
   - `ranking_impacto.csv` (Excel-CL: sep=';', decimal=',', utf-8-sig) — top filas por impacto-$.
   - `resumen_por_causa.csv` — impacto-$ y % por bucket de causa.
   - log a stdout con los hallazgos clave.

## Validación (casos canónicos)
- [ ] Top del ranking trae SKUs de evento (cervezas conocidas del 2026-05-31).
- [ ] Bucket `smooth_real` accionable es chico en $ (consistente con "no hay top SKUs que arreglar").
- [ ] Si el grueso del impacto cae en `evento` → Fase 2 justificada para ese subconjunto.

## Gate de decisión
- smooth_real chico + evento dominante → seguir a Fase 2 SOLO sobre evento (demand sensing).
- evento sin $ relevante → Fase 2 no vale la pena; cerrar.

## Notas técnicas
- product_id / team_id en backtest son m2o (id, name). Resolver id para cruces.
- iso_week: alinear target_week_start (lunes) con iso_week de los modelos de evento.
- Pull defensivo y por lotes; si una semana no cruza, log y seguir.
