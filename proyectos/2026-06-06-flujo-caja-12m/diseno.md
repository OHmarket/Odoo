# Diseño — Flujo de Caja detallado 12 meses (jun 2026 → may 2027)

**Fecha:** 2026-06-06
**Tipo:** Análisis one-off (proyectos/), no productivo. Reproducible (pull Odoo + inputs manuales).
**Contexto de negocio:** escenario de quiebres y problemas de liquidez; país con poca
liquidez. El flujo NO es un plan de crecimiento, es una **herramienta de supervivencia
de caja**: detectar meses valle (saldo negativo) y calzar el pago de pasivos sin quebrar.

## Fase 0 — Decisiones cerradas

| Tema | Decisión |
|---|---|
| Entregable | Análisis one-off (Excel es-CL / reporte), itera escenarios. No cron Odoo. |
| Método | Flujo de caja **directo** (cobros − pagos), estándar de tesorería. |
| Granularidad | Mensual, 12 meses: jun-2026 → may-2027. |
| Ventas | Presupuesto Odoo (jun–dic 2026, ya existe hasta 12-2026) + 2027 = mismo mes 2026 ±5%. Vista base + conservadora. |
| Costos fijos | Reconstruir de Odoo contable (baseline histórico por cuenta). |
| Saldo inicial caja, deuda bancaria, convenio TGR | Los entrega Marco (manual). |
| Proveedores (CxP) e IVA | Desde Odoo. |

## Módulo IVA — diagnóstico y modelo (validado 2026-06-06)

Diagnóstico read-only sobre Odoo (`explore_iva.py`, `explore_iva2.py`), ventana
mar–may 2026. **Casos canónicos confirmados con dato duro:**

1. **Mix 80/20 validado.** Venta afecta (IVA 19%) = $984,8M (80,7%); venta exenta
   (sin impuesto) = $235,9M (19,3%) en 3 meses. Débito cuadra: 19%×984,8M = $187,1M.
2. **Exento = cigarrillos confirmado.** El top de venta sin impuesto son marcas de
   cigarro (Pall Mall, Lucky Strike, Kent Neo) + "servicio pago tarjeta". Régimen
   correcto: OH no es distribuidor de tabaco → vende cigarros exentos (impuesto pagado
   aguas arriba). NO es misclasificación.
3. **La proporcionalidad ya está resuelta por contabilidad, a nivel mercadería.**
   El tax `IVA Compra 19% No Recup.` (id 17, $29,6M/3m) cae **100% en cuenta 210230
   Facturas por Recibir** (mercadería reventa), **0% en overhead**. Es decir: la compra
   de cigarros trae IVA del distribuidor y, al venderse exento, ese IVA se castiga como
   **costo** (no-recup). El IVA de overhead (arriendo, luz, sistemas, internet) se
   recupera al **100%**.

**Implicancia de diseño:** NO se aplica proporcionalidad sobre uso común en el modelo
de flujo — la atribución al exento ya ocurre en los libros. Prorratear overhead además
sobre-estimaría el IVA a pagar vs. lo realmente declarado. El script productivo
`OH Flujo de Caja.py` ya calcula el IVA correcto para este método (excluye no-recup
por nombre).

**Modelo de la línea IVA (forecast 12m) — paramétrico en restock%:**
```
IVA_a_pagar(mes) = 0,19 × venta_afecta × (1 − restock%) − 0,0144 × venta_afecta
   venta_afecta = venta_total − venta_cigarros (exento)
   restock%     = compras_reventa_afecta / venta_afecta  (palanca maestra)
   overhead_credit ≈ 1,44% de venta_afecta (medido)
   pago = día 20 del mes siguiente
```
La línea IVA se ancla al `restock%` (mismo driver que compras y recuperación de venta).
Clave contra-intuitiva: a MENOR compra, MAYOR IVA a pagar (menos crédito).

**Margen y restock% validados (fuente: `x_margen_por_producto_`, modelo de Marco):**

| Segmento | Margen | restock% reposición |
|---|---|---|
| Blended | 24,4% (= su 25%) | 75,6% |
| Cigarros (exento, ~23% venta) | 8–10% | — |
| **Afecto (resto)** | **29,1%** | **70,9%** |

- restock% reposición afecto = **70,9%** → IVA ≈ 4,1% de venta afecta.
- restock% actual (sangrando) = **56,6%** → IVA ≈ 6,8% de venta afecta (lo que paga hoy).

## 🚨 HALLAZGO CENTRAL — sangrado de inventario (reordena el proyecto)

Vía `stock.valuation.layer` (COGS real al costo), mar–may 2026:

| Mes | COGS real | Entradas a stock | Δ Inventario |
|---|---|---|---|
| Mar | $358M | $302M | −56M |
| Abr | $260M | $207M | −53M |
| May | $234M | $181M | −53M |

**Inventario actual = solo $148M (~3 meses de pista).** Compran ~57% afecto cuando
deberían ~71% para reponer → drenan ~$53M/mes de stock → quiebres → menos venta →
menos caja (doom loop). El flujo a 12m NO es de crecimiento: es **salir del sangrado
de inventario sin quebrar la caja**. Para frenar el sangrado hay que subir compras a
~$330M/mes a costo (~$390M con IVA) justo con la caja apretada. Ese es el nudo.

El `restock%` es el **driver maestro** del modelo: liga (a) recuperación de venta,
(b) caja a proveedor, (c) crédito IVA, (d) nivel de inventario. Una sola palanca,
escenarios survival (restock bajo, preserva caja, acepta quiebre) vs recovery
(restock alto, rebuild stock, exige caja).

**IVA realmente pagado (egreso día 20), histórico:**

| Mes | Débito | Créd recup | IVA a pagar | créd/déb |
|---|---|---|---|---|
| Mar-26 | $64,7M | $39,3M | $25,4M | 61% |
| Abr-26 | $62,4M | $26,1M | $36,3M | 42% |
| May-26 | $60,1M | $33,2M | $26,9M | 55% |

Promedio ≈ $29,5M/mes (~7% venta total). **Volátil**: el crédito sigue a las compras,
no a la venta. La línea IVA hay que proyectarla desde compras, no como % fijo de venta.

### Riesgo marcado (no se actúa, decisión de Marco/contador)
IVA de overhead (uso común) recuperado al 100% sin prorratear. Por SII el uso común
debería ir a ~80% (proporción afecta/total). Exposición ≈ $0,8M/mes si hay fiscalización.
Es un **punto de mejora / riesgo tributario**, no un error del flujo.

### Pendiente de validación
- Cuadrar débito/crédito/total contra el **F29 real** de 1-2 meses (Marco aporta).
- Revisar `Retención Total IVA` (cambio de sujeto) si aplica a compras relevantes.

## Módulo flete/ILA — medición split producto/flete (2026-06-06)

Marco: `raw_product_price` = precio a pagar, YA incluye flete; el total se reparta
~83/17 producto/flete y el flete no lleva ILA → sospecha que el modelo de margen
(`OH Calculo de Margen.py`: `costo_neto = raw/(1+ila+iva)`) distorsiona costo_neto+ILA
al aplicar ILA sobre la porción de flete. Medido en `split_flete_ila.py` (read-only,
1974 facturas mono-producto, 12 meses).

**Resultado: la distorsión es DESPRECIABLE.**
- Split real flete = **mediana 13% (con flete), p25-p75 9-19%** (no 17%; 83/17 es el p75).
  Aguas/gaseosas suben a 20-39%.
- **`err_oh` (sobre-costo del modelo) = mediana 0,29%, p75 0,39%.** Caso extremo (agua,
  split 31,5%) = 0,77%. El IVA recuperable se cancela; solo queda el ILA-sobre-flete, de
  segundo orden. Efecto exacto: `dif_costo = neto_flete × ila × iva / (1+ila+iva)`.
- En **puntos de margen** (sobre precio de venta) ≈ **0,4pp** (NO 0,2pp; un 0,6% de costo
  se traduce en `0,6% × costo/precio ≈ 0,6%×0,72 = 0,43pp`). Validado a mano por Marco en
  Stella: RAW costo 730,8 vs Factura 726,4 → −0,6% costo / +0,43pp margen (margen real
  MAYOR, porque RAW sobre-aplica ILA al flete y sub-recupera IVA).
- **Conclusión: el margen afecto 29% NO está materialmente mal por esto. No corregir el
  modelo de margen por este efecto** (no vale la complejidad para 0,6% costo).

**Sobre staleness de raw (corregido):** el "Stella raw stale 6,5pp" inicial salió de UNA
factura atípica (RECARGO de $174k = 31,7% del neto). Promediando las **42 facturas** de
Stella, valor a pagar ≈ 753 vs raw 770 → **raw OK (~2%)**. Igual Pisco (~2%). El único con
desvío real es **Coca: raw 1.442 vs valor a pagar ~1.613 (~11% bajo)**, pero su flete es
prorrateo PROXY (multi-producto), así que parte puede ser el reparto, no staleness pura.
Lección: un solo caso engaña; el promedio sobre N facturas es el dato. Para validar
frescura de raw a escala, usar la machinery WAC de `costo-desde-facturas` (maneja UoM).

Scripts: `split_flete_ila.py`, `ejemplo_3_productos.py`, `tabla_costo_facturas.py`
(CSV es-CL en resultados/). Caso ancla validado: FAC 178421273 (AGUA CACHANTUN 1.6L)
neto 3711 / flete 1967, f=31,5%.

## Pendiente de diseño (siguientes módulos)
- Línea ventas (presupuesto + YoY 2027, base/conservador).
- Línea compras / proveedores (CxP Odoo + proyección por COGS).
- Costos fijos (baseline por cuenta: arriendos, remuneraciones, luz, sistemas…).
- Pasivos: deuda bancaria + convenio TGR (inputs de Marco) + saldo inicial caja.
- Capa "puntos de mejora": ranking de gasto, meses valle, capacidad de pago de pasivos.
