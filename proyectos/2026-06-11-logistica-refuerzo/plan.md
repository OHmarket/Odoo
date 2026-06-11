# Plan — Logística de Refuerzo

## Tareas

- [x] Fase 0: diseño (`diseno.md`) — criterio de inclusión y formato de guía.
- [x] Implementar Server Action `OH Logistica de Refuerzo.py` (patrón
      `envio_a_sala`, filtrado a `cover_label in ('sin_stock','critico')`).
- [ ] Validar en instancia Odoo (usuario): correr sobre una sala con quiebres
      conocidos y revisar el picking borrador.
- [ ] Promover a `03_stock/` (o fusionar como gen_type `refuerzo_sala` en
      `OH Generacion de Documentos.py`) una vez confirmado.

## Cómo se valida (Fase 1 — medir)

1. Elegir una sucursal con quiebres reales hoy (ej. revisar
   `x_analisis_de_stock` con `x_studio_cover_label = 'sin_stock'`).
2. Correr la acción sobre el registro-formulario con esa sucursal.
3. Comprobar en el picking borrador:
   - Solo aparecen SKUs con `cover_label` en (`sin_stock`, `critico`).
   - `qty` por línea = `x_studio_qty_transferir`.
   - Origen = CD, destino = warehouse de la sala, `partner_id` con dirección.
4. Re-correr: no debe duplicar (idempotencia por `origin`).
5. Contrastar el conteo de líneas contra el `envio_a_sala` normal del mismo
   snapshot: refuerzo ⊆ envío normal.

## Riesgos / supuestos a confirmar en la instancia

- `x_studio_cover_label` está poblado en filas de sala (lo escribe
  `OH Analisis de Stock.py`). Confirmado en código; validar en datos.
- `stock.warehouse.partner_id` tiene la dirección de cada sala. Si está vacío,
  la dirección no imprime (no bloquea el traslado). Revisar configuración.
- El registro-formulario usa los mismos campos que `OH Generacion de
  Documentos.py` (`x_studio_team_id`, `x_name`, campos de resumen).
