# Plan — Logística de Refuerzo

## Tareas

- [x] Fase 0: diseño (`diseno.md`) — modelo order-up-to a N días.
- [x] Implementar Server Action `OH Logistica de Refuerzo.py` (alcance
      `buy_action='transferir_desde_cd'`; cantidad = faltante a N días topado por CD).
- [ ] Studio (usuario): crear campo `x_studio_dias_cobertura_refuerzo` (selector
      de días) en el modelo del formulario y agregarlo a la vista.
- [ ] Validar en instancia Odoo (usuario): correr sobre una sala y revisar el
      picking borrador y las cantidades.
- [ ] Promover a `03_stock/` (o fusionar como gen_type `refuerzo_sala` en
      `OH Generacion de Documentos.py`) una vez confirmado.

## Cómo se valida (Fase 1 — medir)

1. Crear el campo selector y elegir, p. ej., N = 4 días.
2. Correr la acción sobre el registro-formulario con una sucursal.
3. Comprobar en el picking borrador, tomando 2-3 SKU a mano:
   - `qty ≈ round( demanda_semanal/7 * N − stock_real )`, nunca > `stock_central`.
   - SKU cuya sala ya cubre N días NO aparece (suma en `ya_cubiertos`).
   - SKU con faltante pero CD en 0 NO aparece (suma en `sin_cd`).
   - Origen = CD, destino = warehouse de la sala, `partner_id` con dirección.
   - Cada línea muestra "Cob. actual → refuerzo a N d".
4. Re-correr: no debe duplicar (idempotencia por `origin`).
5. Variar N (3 vs 7) y verificar que las cantidades escalan ~linealmente.

## Riesgos / supuestos a confirmar en la instancia

- Unidad de `x_studio_demanda_semanal`: se asume unidades/semana (daily = /7).
  Confirmar en datos contra un SKU de venta conocida.
- `x_studio_stock_real` = físico vendible en la sala (no incluye CD). Confirmado
  en código; validar en datos.
- `x_studio_stock_central` = stock del SKU en el CD. Si varias salas tiran del
  mismo CD el mismo día, el tope por CD se aplica por corrida/sucursal (no hay
  reserva global); se va descontando al confirmar pickings. Revisar en práctica.
- `stock.warehouse.partner_id` tiene la dirección de cada sala. Si está vacío,
  la dirección no imprime (no bloquea el traslado).
- El registro-formulario usa los mismos campos que `OH Generacion de
  Documentos.py` (`x_studio_team_id`, `x_name`, campos de resumen).
