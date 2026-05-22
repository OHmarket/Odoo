# Análisis de Stock - Proceso del código

Documento de proceso del runner `3- OH Analisis de Stock.py` y el modelo `x_analisis_de_stock`.

---

## Pendiente — revisar stock por transferencias internas (2026-05-14)

**Problema**: cuando una transferencia interna sale de un local origen pero aún no llega al destino, esas unidades **no aparecen en `x_studio_stock_real` de ninguno de los dos locales**. El motor las trata como inexistentes y puede:

- Disparar `qty_a_pedir` en el destino (creyendo que está más bajo de lo que estará una vez llegue la transferencia).
- No reflejar la baja real en el origen para efectos de cobertura proyectada.

**Por qué importa**: el stock disponible operativo no es solo el stock físico actual sino `stock físico + stock en tránsito hacia el local`. Ignorar el tránsito sobre-estima necesidades de compra en el destino.

**A definir antes de implementar**:

1. **Qué estados de picking cuentan como "en tránsito"**: probablemente `assigned`, `waiting`, `confirmed` de `stock.picking` con `picking_type_id.code = 'internal'` y `state != 'done'/'cancel'`.
2. **Si se descuenta o no del origen**: depende de si `x_studio_stock_real` ya refleja la salida o no (verificar contra Odoo: ¿el stock físico se decrementa al confirmar el picking o al validarlo?).
3. **Horizonte temporal**: solo transferencias con `scheduled_date` dentro de la ventana de cobertura (ej. ≤ `cover_weeks` × 7 días).
4. **Campo nuevo en `x_analisis_de_stock`**: `x_studio_stock_en_transito` (Float) — unidades pendientes de recibir por SKU × team. Útil para auditar.
5. **Cómo entra al cálculo**: `stock_disponible = stock_real + stock_en_transito`; `qty_a_pedir` se calcula sobre `stock_disponible`, no sobre `stock_real` puro.

**No tocar**: `x_calculo_abc_xyz` no se modifica — esto es 100% operativo y pertenece a `x_analisis_de_stock` (ver separación de responsabilidades del proyecto).

**Para revisar mañana (2026-05-15)**:
- Leer `3- OH Analisis de Stock.py` y ubicar dónde se calcula `qty_a_pedir`.
- Validar contra Odoo qué estados de `stock.picking` interno conviven con stock físico ya descontado.
- Decidir si arrancar con un campo de auditoría (`x_studio_stock_en_transito`) antes de integrarlo al cálculo, para medir el impacto sin riesgo.
