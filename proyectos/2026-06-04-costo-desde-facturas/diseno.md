# Diseño — Costo desde Facturas (landed cost multi-proveedor)

## ⭐ ACTUALIZACIÓN 2026-06-04 — Objetivo real: mantener el costo al día

El objetivo de fondo es **mantener `raw_product_price` al día** para que el
**margen** tenga sentido. Hoy `raw_product_price` es **manual** (proceso de
registro que se desactualiza) y está **CON IVA**. `standard_price` es el AVCO de
Odoo pero **se calcula desde las órdenes de compra**, no desde la factura final
→ no confiable como costo real.

**Decisión:** calcular **WAC (promedio ponderado) desde las FACTURAS** (precio
real pagado) y **escribirlo de vuelta en `raw_product_price`** (con IVA),
reemplazando el ingreso manual.

```
raw_nuevo = Σ(price_total de las líneas) / Σ(unidades_base)     (ventana 90 días)
```

**Trampa de UoM (clave):** la `qty` de la factura a veces viene en unidades base
(GALLETA "x 40" trae qty=40 = 40 piezas) y a veces en packs (CHICLE en display).
`qty × uom_ratio` rompe en el primer caso, `qty` solo rompe en el segundo. Se
resuelve **anclando a `standard_price`**: se elige la base (qty o qty×ratio) cuyo
costo unitario neto quede más cerca de `standard_price` (el std fija la UNIDAD; la
factura pone el VALOR). Si ninguna cuadra (>15%), la línea es DUDOSA → el producto
se excluye, no se pisa.

**Resguardos del write-back (conservador):** dry-run primero; excluye productos con
líneas UoM dudosas; no pisa si el cambio vs raw actual es >30%; excluye templates
con >1 variante comprada.

**Validación (90d, no-ILA):** 127/143 SKU quedan ±5% del raw actual (consistente);
7 cambios de precio reales; 9 marcados UoM dudosa (excluidos).

**Scripts:** `OH Actualiza Raw Costo.py` (write-back WAC, camino simple/sin flete),
`wac_preview.py` (preview read-only). El landed-cost con flete (CCU) queda como
capa posterior. Lo de abajo (§1-9) es el diseño del capture landed original.

---

## 1. Problema

Calcular el **costo unitario real de compra** de cada producto a partir de las
facturas de proveedor (account.move / account.move.line), incluyendo el flete,
para alimentar valuación de inventario y GMROI en `OH Analisis de Stock.py`.

## 2. Decisión que se toma con el resultado

El costo landed por unidad es el `purchase_price_cash_unit` que Stock usa para:
- valorizar el stock,
- calcular GMROI de reposición,
- decidir compras/transferencias.

Un costo inflado o mal repartido distorsiona qué se compra y a quién.

## 3. Qué pasa si se equivoca

Sub-costo → margen aparente alto → se sobre-compra producto poco rentable.
Sobre-costo → margen aparente bajo → se deja de comprar producto bueno.
Por eso el costo debe quedar en la **base tributaria correcta** y el flete
**cuadrado contra la factura**, no estimado.

## 4. Cómo lo resuelven los grandes (teoría / ERP)

Modelo canónico: **Landed Cost** (SAP MM "Delivery Costs / Conditions",
Oracle/NetSuite "Landed Cost", Odoo `stock.landed.cost`). El flete y los
impuestos no recuperables se **capitalizan** al costo de inventario; los
impuestos recuperables (IVA crédito fiscal) **no** entran al costo.

Aplicado a Chile / OH Market:
- **IVA 19% compra**: crédito fiscal recuperable → NO entra al costo.
- **ILA / Específico / Beb. Analcohólicas / Vinos / IVA No Recuperable**:
  impuestos de costo → SÍ se capitalizan.
- **Flete**: se capitaliza (neto; su IVA es recuperable).

Asignación del flete: método **por valor/medida** (landed cost allocation).
Aquí el flete real lo da la factura y se distribuye con pesos del **tarifario
del proveedor** (`x_vendor_freight_rule`).

## 5. Enfoques considerados

| # | Enfoque | Límite |
|---|---|---|
| A | Prorrateo del flete por unidades (script CCU viejo) | Penaliza productos chicos; ignora que el flete es por volumen/caja. Solo CCU. |
| B | Tarifa pura del tarifario como flete | No cuadra contra el monto real facturado; si el tarifario está desactualizado, el costo se desvía. |
| C (elegido) | **Factura manda, tarifa distribuye** | El total del flete = línea de flete de la factura (verdad dura); la tarifa solo da los pesos relativos de reparto. Cuadra exacto y es multi-proveedor. |

## 6. Enfoque elegido y qué NO se hace

**C.** Costo landed cash por unidad:

```
costo_landed_cash_unit = ( neto_producto × (1 + ILA_factor) + flete_neto_asignado ) / unidades_equiv
unidades_equiv = qty_factura × uom.ratio          (cajas × pack)
flete_neto_asignado = flete_neto_factura × (peso_linea / Σ pesos)
```

**Peso por línea = litros × tarifa-por-litro del tipo de caja** (escala única,
consistente entre líneas matcheadas y no matcheadas):

```
litros_linea = unidades_equiv × cc_producto / 1000
rate_$/L     = tarifa_caja / (volumen_caja / 1000)     (por tipo de caja)
peso         = litros_linea × rate_$/L
```

Llave del tarifario (descubierta en diagnóstico, ver §7):
- **Tipo de Caja** (CCU): match por **volumen de caja** = `product.volume × uom_ratio`
  ≈ `cc × pack` del tarifario. (No por (cc,pack) separados: `volume` guarda el
  volumen del multipack, no la botella → matchear (cc,pack) fallaba en ~90%.)
- **CC Botella**: match por `cc` de la botella.
- **Tarifa Fija Caja**: flat, `peso = tarifa_fija × n_cajas`.

Robustez:
- No-match exacto → `rate = $/L promedio del proveedor` (mismo eje de litros).
- `product.volume = 0` → litros imputados con la densidad `L/$` de la factura.
- Como **la factura manda**, el peso solo reparte: el total SIEMPRE cuadra
  (normalización por Σ pesos). Validado: 13/13 facturas con diff=0.0000.

Se escribe en `x_vendor_bill_cost_lin.x_studio_unit_gross_with_freight`
(label **"Precio Compra"**, el campo que Stock ya lee). **No** se crea campo
nuevo ni se toca `OH Analisis de Stock.py`.

NO se hace:
- No se toca `OH Calculo de Margen.py` (sigue con `raw_product_price` + ILA).
- No se reemplaza `raw_product_price` como fuente primaria (la factura sigue
  siendo fallback en `_purchase_price_for_tmpl`).
- No se inventa tarifa para proveedores sin líneas (Dist. y Excelencia 307):
  caen a peso = unidades y quedan con `flag_tariff_miss`.

## 7. Supuestos y PROXY

- **PROXY cc**: `cc_unit = product.template.volume` (el negocio guarda CC en
  el campo volume, no m³). Validar por producto.
- **PROXY pack**: `pack_qty = product_uom_id.ratio` (validado: "x 6 Unidades"→6).
- **ILA por nombre/clasificación, no por sequence**: recuperable = name contiene
  "iva" y no "no recup"; todo otro % positivo es costo (Específico, Beb. Analc,
  Vinos, ILA, IVA No Recup.). Retenciones (monto negativo) se ignoran.
- **PROXY tariff-miss**: si (cc,pack) no está en el tarifario, se usa nearest-cc;
  si no hay tarifario, peso = unidades_equiv. Como la factura manda, el miss solo
  desplaza el reparto, nunca el total.

## 8. Casos canónicos de validación

Ver `plan.md`. Caso ancla: FAC 178421273 (2026-06-04), AGUA CACHANTUN 1.6L,
caja x6, neto 3711, flete factura 1967, tarifa (cc1600,pack6)=1978.
Esperado: todo el flete a esa línea; `costo_cash = (3711×1.18 + 1967)/6`.

## 9. Modelo de flete del usuario (`x_vendor_freight_rule`)

6 reglas activas (una por proveedor). Padre: `x_studio_partner_id`,
`x_studio_rule_type`, `x_studio_freight_patterns` (CSV keywords para detectar la
línea de flete), `x_studio_active`. Hijo `x_vendor_freight_rule_`
(o2m `x_studio_tariff_line_ids`): `x_studio_cc_unit`, `x_studio_pack_qty`,
`x_studio_tariff_case`.
