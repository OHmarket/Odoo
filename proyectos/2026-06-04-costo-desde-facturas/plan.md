# Plan — Costo desde Facturas

## Tareas

- [x] Fase 0: diseño cerrado (ver diseno.md). Decisiones: costo neto+ILA sin IVA;
      factura manda / tarifa distribuye; llave cc=volume, pack=uom.ratio.
- [x] Inspeccionar `x_vendor_freight_rule` + tarifas (6 reglas, 3 rule_type).
- [x] Inspeccionar campos reales de `x_vendor_bill_cost_lin` (escribir solo los
      que existen; reusar `x_studio_unit_gross_with_freight` = "Precio Compra").
- [ ] `OH Costo desde Facturas.py`: Server Action generalizado.
- [ ] `validar_reconciliacion.py`: read-only, cuadre flete y costo creíble.
- [ ] Correr en `dry_run` rango chico → revisar conteos.
- [ ] Validar reconciliación contra facturas reales.
- [ ] Promover: mover a `04_analitica/` o dominio correspondiente + commit.

## Generalización v2 (2026-06-04): todos los proveedores

El Server Action ahora procesa **todos** los proveedores, no solo los de flete:

- Solo captura productos **almacenables** (`type='product'`); excluye servicios/
  consumibles genéricos (RETENCION, Artículos de Oficina, recargas).
- Proveedor **sin** regla de flete → costo = `neto × (1+ILA) / unidades` (sin flete).
- Proveedor **con** regla → landed cost con reparto por tarifa (lógica v1).
- `vendor_bill_mode`: `all` (def) | `simple` (solo sin flete) | `freight` (solo con flete).
- `vendor_bill_partner_ids`: lista opcional para acotar. `dte_code='all'` quita el filtro DTE.

**Partir por lo simple (no-ILA / no-flete):** correr con `vendor_bill_mode='simple'`.
Validado con `preview_no_ila.py`: ~50% líneas costeables (resto = sin product_id o
no almacenable), costos creíbles (pan, helados, cigarros, snacks).

## Cambios del script vs. CCU viejo

1. Borrar línea huérfana `tt` (NameError).
2. Iterar `move.invoice_line_ids` (no `line_ids`) → solo líneas producto/flete,
   sin ruido de asientos. Skip `qty <= 0`.
3. Multi-proveedor: dominio sobre partners con regla activa (no hard 315).
4. Flete detectado por `freight_patterns` del proveedor (no label fijo).
5. IVA/ILA por clasificación de nombre (no por sequence).
6. Peso de tarifa por `rule_type`; lookup exacto → nearest-cc → fallback unidades
   (`flag_tariff_miss`).
7. Reparto del flete de la factura ∝ peso, residual en última línea (cuadra exacto).
8. **Precio Compra = costo cash landed** = (neto×(1+ILA) + flete_neto_asig)/unidades.
   Sin IVA. (Antes guardaba bruto con IVA.)
9. Escribir solo campos existentes del modelo.

## Casos canónicos

1. **CCU 1 línea** (FAC 178421273): flete completo a la única línea;
   `costo_cash = (3711×1.18 + 1967)/6 ≈ 1057,9`.
2. **CCU multi-línea**: Σ flete_asignado == flete_factura (tol 0); reparto ∝
   tarifa_caja × n_cajas.
3. **CC Botella** (La Vinoteca 464 / Premium Brands 271): reparto ∝ tarifa_botella × unidades.
4. **Tarifa Fija** (Las Pataguas 1408): peso plano por caja.
5. **Sin flete**: costo = neto×(1+ILA), sin componente flete.
6. **Sin tarifa** (Dist. y Excelencia 307): peso=unidades, `flag_tariff_miss`.

## Verificación end-to-end

1. Server Action con `{'dry_run': True, 'vendor_bill_purge_all': False}`, rango
   chico → conteos (moves / líneas / moves_with_freight) sin escribir.
2. `validar_reconciliacion.py` → Σ flete asignado == flete factura; costo creíble.
3. En firme (purge según corresponda) → spot-check 3 SKUs en Stock.
4. Commit solo tras confirmación verbal explícita (flujo AGENTS.md).
