# Ratios de participacion sobre ventas — ene-jul 2026

Fecha: 2026-09-17
Estado: DISENO + DIAG (read-only). NO promovido.

## 1. Que problema se quiere resolver o medir

Cuanto pesa cada partida de gasto sobre la venta del ano en curso. En concreto
arriendo, electricidad (luz) y costo de venta, mas el resto de las partidas
principales. Periodo 2026-01-01 a 2026-07-31: agosto NO esta cerrado y meterlo
mezclaria un mes incompleto con meses cerrados (sesga a la baja todo gasto que
se devenga a fin de mes).

## 2. Que decision se tomara con el resultado

- Benchmark de estructura de costos: que % de la venta se va en ocupacion
  (arriendo), energia y mercaderia, y cuanto queda de margen operacional.
- Detectar partidas fuera de rango contra el retail de conveniencia
  (referencias tipicas: margen bruto 22-30%, arriendo 4-8%, energia 1,5-3%).
- Insumo para presupuesto 2027 y para negociar contratos (arriendo, energia).

## 3. Que pasa si el modelo se equivoca

Riesgo medio-alto: se negocia o se corta gasto sobre un % falso. Los dos modos
de falla reales son (a) denominador equivocado —venta bruta con IVA vs venta
neta— que corre TODOS los ratios ~16% hacia abajo, y (b) numerador incompleto
—facturas de compra en borrador que aun no llegan al mayor— que subestima el
gasto. El DIAG mide y reporta ambos explicitamente en vez de suponerlos.

## 4. Modelo canonico

**Analisis vertical / common-size income statement.** Cada linea del estado de
resultados dividida por la venta neta del mismo periodo. Es el estandar de
facto (SAP FI-CO "common size", Oracle EPM "vertical analysis", NRF / FMI para
retail) y esta en cualquier manual de analisis financiero (Penman, "Financial
Statement Analysis and Security Valuation", cap. 9; Brigham, "Financial
Management", cap. 3).

Reglas del canon que aplican aca:
- Denominador = **venta neta** (sin IVA, neta de devoluciones/NC), del MISMO
  periodo y la MISMA fuente que el numerador. No mezclar POS bruto con
  contabilidad.
- Devengado, no caja: fecha del asiento, no fecha de pago.
- Solo asientos posted.
- COGS separado del opex: margen bruto primero, luego gastos.

## 5. Enfoques posibles

- **A. Mayor contable (account.move.line por cuenta).** Numerador y denominador
  de la misma fuente, incluye TODO el gasto (POS + facturas + provisiones).
  Limite: depende de que la contabilidad este al dia y bien imputada.
- **B. POS + facturas de compra sueltas.** Venta desde pos_order, gasto desde
  account.move de proveedor. Rapido, pero mezcla bases (POS trae IVA e ILA) y
  se pierde todo gasto que no venga de factura (remuneraciones, provisiones,
  depreciacion). Descartado como fuente primaria.
- **C. Modelo Studio de analitica (x_*).** No existe uno de P&L; habria que
  crearlo. Fuera de alcance para una pregunta de diagnostico.

## 6. Enfoque elegido

**A, con B como control cruzado.** El reporte sale del mayor (account.move.line
agrupado por cuenta, solo posted, company de env.company) y ademas imprime la
venta POS bruta del periodo y su neteo /1.19 para contrastar contra la venta
neta contable. Si esos dos numeros se separan mas de ~3% el reporte lo marca:
significa que la contabilidad no esta capturando toda la venta (o que hay ILA /
exento / venta no-POS moviendo la diferencia) y el ratio no es publicable.

Se decide NO hacer:
- No se toca ningun dato: el DIAG es read-only y devuelve el reporte por
  UserError. No crea modelos, no escribe campos.
- No se reparte por sala/team en esta version. El gasto de arriendo y luz esta
  imputado por cuenta, no necesariamente con analitica por local; pretender el
  corte por sala sin validar la analitica seria inventar precision.
- No se anualiza ni se proyecta agosto-diciembre.

## 7. Clasificacion de partidas — que es canon y que es PROXY

Canon (viene del plan de cuentas, no de nosotros):
- Venta neta = suma de cuentas `account_type in ('income','income_other')`,
  con el signo dado vuelta (en Odoo el ingreso vive en el haber: balance < 0).
- Costo de venta = cuentas `account_type = 'expense_direct_cost'`.
- Gasto operacional = `expense` + `expense_depreciation`.

**PROXY** — el agrupado de arriendo / luz / agua / remuneraciones se arma por
**palabra clave sobre el nombre de la cuenta** (`arriend`, `electric`, `energ`,
` luz `, etc). Odoo no tiene un campo que diga "esto es ocupacion". El reporte
imprime SIEMPRE el detalle cuenta por cuenta junto al agrupado, justamente para
que el agrupado se pueda auditar y corregir a mano. Mientras no se confirme el
mapeo contra el plan de cuentas real, los subtotales de arriendo y luz son
estimacion, no verdad dura.

## 8. Casos canonicos de validacion

1. `venta_neta_contable` vs `POS bruto / 1.19`: separacion < 3%.
2. `suma de meses == total del periodo` (el script suma por mes y compara).
3. Margen bruto (1 - COGS/venta) dentro de 15%-40%. Fuera de ese rango casi
   siempre significa COGS mal imputado o inventario sin valorizar.
4. Facturas de compra en `draft` del periodo: si su neto supera el 2% de la
   venta, el gasto esta subestimado y el reporte lo marca como contaminacion.
   (Antecedente real: el motor de Cuadre Fiscal DTE llego a tener 118 facturas
   en draft simultaneas — no es un caso hipotetico.)
5. Cuentas de gasto sin clasificar en ningun grupo: se listan aparte; si pesan
   mas que cualquier grupo nombrado, el agrupado no sirve todavia.
