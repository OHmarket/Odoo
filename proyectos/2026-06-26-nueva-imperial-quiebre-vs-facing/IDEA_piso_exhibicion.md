# La idea: piso de exhibición en góndola

## El problema

Las heladeras de algunas salas (Nueva Imperial el caso testigo) se ven con
**caras vacías**. No siempre es quiebre de abastecimiento: muchas veces el
sistema **dimensiona el stock justo al ras de la demanda**, y un producto que
rota poco queda en cero en la góndola aunque "técnicamente" no falte stock.

> Cara vacía ≠ quiebre. El cliente igual ve la heladera pelada.

El motor hoy calcula cuánto mandar como `demanda + seguridad`. Para un producto
de baja rotación eso da casi cero → cara vacía. Y peor: si no está en la cara no
se vende, el sistema lo lee como "no hay demanda", pide menos, y nunca se llena.

## La idea

Agregar un **piso de exhibición** (en la industria: *presentation stock*): un
mínimo de unidades que el sistema siempre intenta tener en la sala para que la
cara no quede en cero. Es exactamente lo que hacen los ERP grandes de retail
(SAP "minimum target stock", Oracle "stock para llenar una cara").

## Cómo funciona

El envío se calcula así:

```
       lo que mando = MAX( demanda + seguridad ,  piso de exhibición )
```

Es un **piso, no un extra que se suma**: si la demanda ya pide más que el piso,
no se agrega nada (no se paga stock de más). El piso solo actúa cuando el
producto rota tan poco que quedaría vacío.

El **piso** combina dos criterios, y gana el mayor:

```
  piso de exhibición = MAX( 2 días de venta ,  1 pack por formato )
                            (lata 6 · vidrio 4 · pet 3)
```

- **2 días de venta** → manda en los productos de alto volumen (Coca Cola,
  Quilmes): mantiene una cara digna sin sobre-stockear.
- **1 pack por formato** → manda en los lentos: garantiza que ni una cerveza
  que vende poco quede en cero.

> No necesita conocer el tamaño de cada sala: la demanda local ya hace que una
> sala grande reciba más piso y una chica menos, automáticamente.

## Por qué "piso" y no "sumar"

Probamos las dos formas con datos reales:

| Forma | Qué hace | Costo (AX bebidas) |
|---|---|---|
| **Piso (elegido)** | Solo agrega donde el producto quedaría vacío | **+$155 mil** |
| Sumar siempre | Encaja el mínimo a todos, también a los que ya tienen | +$2,74 millones |

**Misma cara llena, 18 veces menos capital.** Sumar solo se justificaría si la
cara fuera intocable (el cliente saca de atrás), y en una heladera de
autoservicio eso no pasa.

## Alcance inicial

- **Productos:** los importantes (clase AX) de **bebidas frías** (cervezas y
  gaseosas). Después se evalúa ampliar a energéticas, aguas, etc.
- **Salas:** solo las salas de venta (la Bodega Central y la Web no exhiben).
- **Tabaco y licores quedan fuera:** no van en heladera; meterlos inflaba el
  costo 4 veces sin resolver nada visible.

## Qué se necesita

1. Un campo nuevo en el análisis de stock — **"Stock Mínimo Exhibición"** — que
   guarda el piso por producto y sala. Auditable y **editable por Operaciones**
   (se puede forzar a mano un producto puntual).
2. Un ajuste en el cálculo de envío para aplicar el `MAX`.

## Qué resuelve y qué no

- ✅ Que los productos importantes y los lentos **no queden en cero en la cara**.
- ✅ Capital acotado y medible (+$155 mil en toda la cadena, corte AX bebidas).
- ⚠️ NO evita que la cara se vacíe **entre reposiciones** si la venta la drena
  antes del próximo relleno: eso depende de **cada cuánto se repone la sala**,
  que es otra palanca (frecuencia de reposición).
