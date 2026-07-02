# CD reposición solo_bodega → installation stock (no pooling)

**Fecha:** 2026-07-02
**Script:** `03_stock/OH Analisis de Stock.py` (v9.6.1 → v9.7.0)
**Estado:** aplicado en repo, pendiente correr en Odoo + validar + subir.

## Problema

El bloque de reposición del CD para SKU `solo_bodega` calculaba el target con
**echelon pooling**:

```
target_red = mu_red * period_weeks + z * sqrt(Σσᵢ²) * sqrt(period_weeks) + piso_red
```

El safety pooleado `sqrt(Σσᵢ²)` es ~√N más chico que la suma de los safety de
las salas `Σσᵢ`. Resultado: el target del CD queda por debajo de la suma de los
target de las salas.

Caso 1756 (BEBIDA PEPSI DES 3 L, tmpl 11555):
- Σ target de las 12 salas = **138.5**
- target CD pooleado = **117.4** (mu 35.56×2.14 + safety 20.2 + piso 21)
- diferencia = 21.1 = safety no pooleado que se borró.

## Por qué es incorrecto para esta operación

El pooling **solo es válido si el nodo central retiene físicamente el colchón**
y despacha reactivo a la sala que pica (postergación de asignación). El CD de
OH Market es **pass-through**: `stock_real ≈ 0`, entrega todo a las salas. El
colchón pooleado entonces no vive en ninguna parte → las salas quedan
crónicamente bajo su propio target. Incongruencia de piso: salas marcadas
`bajo`/`sin_stock` mientras el CD compra casi nada.

Decisión del dueño: "la idea es entregar todo" → si el CD entrega todo, el
safety tiene que sentarse en cada sala, y el target del CD debe ser el
**installation stock** = Σ target de las salas.

## Cambio

```
target_red  = Σ rec['target_units']       # cada uno ya trae safety+vitrina+cola_larga+cap
safety_red  = Σ rec['safety_stock_units'] # solo para reporte (decision_reason)
```

`disponible_red` y el neteo NO cambian:
```
disponible_red = stock_CD_fisico + Σ stock_salas_fisico + POs_inbound
compra_CD      = max(0, target_red - disponible_red)   # MOQ 1 vez en build CD
```

`piso_red` ya no se re-suma (viene dentro de cada `target_sala`). `sigma_red` se
conserva solo para el `decision_reason`.

## Validación a mano (canónica, es el objetivo del cambio)

> Suma los target de las salas, resta lo que hay físico y lo que viene en OC.

1756 con la data del 2026-07-02:
```
Σ target salas           = 138.5
menos disponible:
  físico salas           =  39
  físico CD              =   0
  tránsito (OC pend.)    =  72
─────────────────────────────────
comprar                  = 27.5  → 5 cajas (MOQ 6) = 30
```

## Riesgo / impacto

- Sube la compra de **toda** la cola larga solo_bodega por la diferencia
  `Σσᵢ − sqrt(Σσᵢ²)`. Mientras más salas tenga el SKU, mayor el salto.
- En contexto de caja apretada, correr el **delta de capital total** sobre todos
  los solo_bodega antes de promover (Σ nueva compra vs Σ compra vieja).
- Reversible: `git revert` del commit; el bloque pooled queda en el historial.

## Casos canónicos de validación

| SKU | Σtarget salas | disponible | compra esperada |
|-----|---------------|------------|-----------------|
| 1756 | 138.5 | 111 | 30 (5 cajas) |

Correr en Odoo, revisar `decision_reason` del CD: `cd_target_units` debe ser
= Σ target de las salas, y `cd_qty_neta` = target − disponible.
