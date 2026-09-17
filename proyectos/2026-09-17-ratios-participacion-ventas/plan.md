# Plan — ratios de participacion sobre ventas (ene-jul 2026)

## Estado

| # | Tarea | Estado |
|---|-------|--------|
| 1 | Diseno (7 preguntas de Fase 0) | HECHO — `diseno.md` |
| 2 | DIAG read-only para safe_eval | HECHO — `DIAG_ratios_participacion.py` |
| 3 | Lint safe_eval | HECHO — `lint_safe_eval.py`, pasa |
| 4 | Corrida en seco con env falso | HECHO — `test_diag_offline.py`, 4 escenarios |
| 5 | Correr contra produccion | HECHO — via `consulta_ratios_jsonrpc.py` (read-only, desde fuera) |
| 6 | Auditar el mapeo PROXY contra el plan de cuentas real | HECHO — 3 correcciones, ver abajo |
| 7 | Decidir si se promueve a `04_analitica/` o queda como consulta | PENDIENTE — decision del usuario |

## Mapeo PROXY: correcciones hechas tras ver el plan de cuentas real

1. `410182 Mercado Pago` caia en OTROS GASTOS -> COMISIONES MEDIOS DE PAGO.
2. `410197 Gastos Bancarios` caia en OTROS GASTOS -> GASTOS FINANCIEROS
   (la palabra clave era 'banco' y la cuenta dice 'bancarios').
3. `410161 Mantencion Electrica` caia en ELECTRICIDAD -> MANTENCION. El grupo
   MANTENCION ahora se evalua ANTES que ELECTRICIDAD. Sin esto, la luz salia
   2,4% en vez de 2,2%.

Queda sin naturaleza clara `410115 Gastos Menores no tributables`: el nombre
no dice que gasto es y pesa lo suficiente para importar. Vive en OTROS GASTOS
hasta que alguien lo abra.

## Hallazgo que cambia como se lee el resultado

La venta del periodo cae fuerte entre enero y julio. NO es un problema
contable: el conteo de tickets POS cae en la misma proporcion y la venta
contable calza con el POS neteado dentro de 0-6% todos los meses (correr
`DIAG_venta_mensual.py` para ver el contraste). Es el negocio que se achico.
Consecuencia para el analisis: el ratio acumulado ene-jul mezcla dos tamanos
de negocio distintos, asi que hay que mirar tambien el corte de los ultimos
meses aparte. Los gastos fijos -arriendo, remuneraciones- no bajan con la
venta, y ahi es donde se ve.

## Como correrlo

1. Odoo > Ajustes > Tecnico > Acciones de servidor > Crear.
2. Modelo: `account.move.line`. Tipo: `Ejecutar codigo Python`.
3. Pegar `DIAG_ratios_participacion.py` completo en `python_code`.
4. Guardar y darle a "Ejecutar".
5. El reporte sale en el dialogo de error (es a proposito: `raise UserError`
   revierte la transaccion y garantiza que no se escribio nada). Copiar el
   texto completo.

Ajustes arriba del archivo si hace falta: `YEAR`, `MONTH_FROM`, `MONTH_TO`
(hoy 1..7: agosto queda fuera porque no esta cerrado), `TOP_N`.

## Validacion (los casos de diseno.md s8)

El propio reporte los evalua e imprime en la seccion 6. Lo que hay que mirar
al leerlo, en este orden:

1. **Denominador.** Venta neta contable vs venta POS neteada /1,19. Si el
   reporte marca separacion > 3%, PARAR: el ratio no es publicable hasta
   entender la diferencia (venta por factura no-POS, exento, ILA, o
   contabilidad incompleta).
2. **Costo de venta.** Si sale 0 o el margen bruto queda fuera de 15%-40%, el
   inventario no se esta valorizando en el mayor y el COGS hay que sacarlo del
   POS (`04_analitica/OH Calculo de Margen.py`), no de la contabilidad.
3. **Borradores.** Facturas de compra del periodo en draft: ese gasto todavia
   no esta en el mayor, asi que todos los % salen cortos. Si pesa > 2% de la
   venta, cerrar las facturas (motor de Cuadre Fiscal DTE) y volver a correr.
4. **Mapeo PROXY.** Leer la seccion 4 (detalle cuenta por cuenta con su grupo)
   y confirmar que cada cuenta cayo donde corresponde. Todo lo que quede en
   OTROS GASTOS y pese mas que una partida nombrada hay que reclasificar a
   mano en la lista `GRUPOS` del script.
5. **Multi-company.** El reporte es de `env.company`. Si hay mas de una
   compania operativa, correrlo una vez por cada una.

## Que falta para promover

- Dos corridas consistentes (misma cifra de venta neta) y el mapeo PROXY
  auditado en el punto 4.
- Si se promueve: mover el .py a `04_analitica/`, subirle version, entrada en
  `governance/CHANGELOG.md` (sin excepcion) y decidir si el output pasa de
  `UserError` a un modelo Studio `x_*` o a un CSV descargable.

## Fuera de alcance (decidido, no olvidado)

- Corte por sala / team: exige validar la analitica de arriendo y luz por
  local. Es otro proyecto.
- Proyeccion agosto-diciembre.
- Comparacion contra 2025 (YoY). Se puede agregar cambiando `YEAR`, pero el
  reporte comparativo es otra version.
