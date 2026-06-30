# Task 3 Report — Integración cola larga (s,S) en rama solo_bodega

**py_compile:** SYNTAX OK (sin errores ni output)

---

## Edit 1: Target override (Step 1)

**Anchor:** `reorder_target_weeks = _clamp(reorder_target_weeks, 0.0, financial_ceiling_sku)` (línea 2196, dentro del `else:` del chain if/elif/else de target)

**Before:**
```python
                            reorder_target_weeks = _clamp(reorder_target_weeks, 0.0, financial_ceiling_sku)

                        # Piso de exhibicion (presentation stock) -- ADITIVO.
```

**After:**
```python
                            reorder_target_weeks = _clamp(reorder_target_weeks, 0.0, financial_ceiling_sku)

                        # v9.6.0: cola larga -> lote minimo (s,S) por caja autofinanciada.
                        # Solo solo_bodega y mu <= umbral. Order-up-to = caja/fraccion ~mensual;
                        # el gate por ROP (mas abajo) evita el goteo semanal. Ver
                        # proyectos/2026-06-30-cola-larga-lote-caja/diseno.md
                        cola_larga_rop = None
                        if solo_bodega and DEMAND_FLOOR_WEEK < mu_for_target <= COLA_UMBRAL_WEEK:
                            _cl_S, _cl_rop = _calc_cola_larga_lote(
                                mu_for_target, moq, lead_weeks,
                                COLA_OBJETIVO_DIAS, COLA_PLAZO_PAGO_DIAS, COLA_PISO_UNIDADES)
                            if _cl_S > 0.0:
                                target_units         = _cl_S
                                safety_stock_units   = 0.0
                                reorder_target_weeks = _cl_S / mu_for_target
                                cola_larga_rop       = _cl_rop

                        # Piso de exhibicion (presentation stock) -- ADITIVO.
```

**Indentación:** bloque de 24 espacios (nivel loop por team/SKU), `if` anidado a 28. Correcto.

---

## Edit 2: ROP gate sobre qty_neta_pre (Step 2)

**Anchor:** `qty_neta_pre = max(target_units - stock_proyectado, 0.0)` (única ocurrencia, ~línea 2257 post-edit)

**Before:**
```python
                        qty_neta_pre = max(target_units - stock_proyectado, 0.0)
                        qty_buy_pre  = (_smart_moq_box_or_wait(
```

**After:**
```python
                        qty_neta_pre = max(target_units - stock_proyectado, 0.0)
                        # v9.6.0: cola larga (s,S) -> solo transferir cuando el stock cae
                        # al ROP; si esta por encima, dejar drenar el lote (cadencia ~mensual,
                        # no goteo semanal). Al disparar, refilla al lote completo S.
                        if cola_larga_rop is not None and stock_proyectado > cola_larga_rop:
                            qty_neta_pre = 0.0
                        qty_buy_pre  = (_smart_moq_box_or_wait(
```

**Indentación:** 24 espacios para el `if`, 28 para el cuerpo. Correcto.

---

## Edit 3: Header de versión (Step 3)

**Anchor:** `# v9.5.0 (2026-06-30): clasificacion de cobertura CANONICA (SAP Range of Coverage /` (línea 6 original)

**Before:**
```python
# Version activa: v9.5.0 (ver CHANGELOG.md para historial completo)
#
# v9.5.0 (2026-06-30): clasificacion de cobertura CANONICA (SAP Range of Coverage /
```

**After:**
```python
# Version activa: v9.6.0 (ver CHANGELOG.md para historial completo)
#
# v9.6.0 (2026-06-30): cola larga -> lote minimo (s,S) por caja autofinanciada en el
#   traslado CD->sala. Para SKU solo_bodega con mu_for_target <= COLA_UMBRAL_WEEK (3/sem):
#   order-up-to S = 1 caja entera si la caja rinde <= COLA_PLAZO_PAGO_DIAS (45d,
#   autofinanciada), si no fraccion ~COLA_OBJETIVO_DIAS (30d). ROP = mu*lead + presencia
#   (~1u); el traslado se suprime mientras stock > ROP -> drena el lote antes de reponer
#   (cadencia ~mensual emergente por local, elimina el goteo de 1u/sem). El pack solo ata
#   la compra; el traslado interno fracciona. No toca compra a proveedor ni fair-share.
#   PROXY: plazo de pago global. Tuneable: cola_umbral_week, cola_objetivo_dias,
#   cola_plazo_pago_dias, cola_piso_unidades. Ver proyectos/2026-06-30-cola-larga-lote-caja/
# v9.5.0 (2026-06-30): clasificacion de cobertura CANONICA (SAP Range of Coverage /
```

---

## Verificación

- `python -m py_compile "03_stock/OH Analisis de Stock.py"` → **SYNTAX OK** (sin output)
- `cola_larga_rop = None` inicializado en cada iteración antes del gate → no hay NameError posible
- El override solo aplica cuando `solo_bodega and DEMAND_FLOOR_WEEK < mu_for_target <= COLA_UMBRAL_WEEK` (condición exacta del spec)
- El gate en qty_neta_pre usa `cola_larga_rop is not None` → filas no gated no se tocan
- No se introdujo `import`, `fields`, `getattr` ni `obj.attr=x`
