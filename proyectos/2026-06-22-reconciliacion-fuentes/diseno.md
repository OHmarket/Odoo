# Reconciliación de fuentes — definiciones únicas + detección de error

**Fecha:** 2026-06-22
**Problema:** distintos informes arman su propio universo de datos y los números
no cuadran entre sí. Esta sesión expuso 4 clases de error que producen totales
contradictorios (ej. "stock muerto" $70M que era $0.3M real; "mal ubicado" $61.7M
que era $13.5M; "stock parado" $105M vs $195M según el join).

## Clases de error detectadas (causa raíz)

| # | Error | Efecto | Ejemplo de la sesión |
|---|---|---|---|
| 1 | **Cache lossy/stale** | venta perdida → falsos "sin venta" | pos_weekly CSV+default_code perdía 219 SKU; 35d viejo. $20M "muerto" falso |
| 2 | **Kit phantom double-count** | stock contado 2 veces (kit + componente) | $18M inflados en x_analisis_de_stock |
| 3 | **CD tratado como sala** | pipeline del echelon contado como "parado"/"mal ubicado" | team 26 = 78% del "mal ubicado" ($48M) |
| 4 | **Universo inconsistente** | mismo concepto, distinto filtro → totales distintos | $105M (inner join demanda) vs $195M (todo) |

## Definiciones canónicas (única fuente de verdad)

- **Venta:** modelo VIVO `x_pos_week_sku_sale` por XML-RPC por IDs reales.
  NUNCA el CSV legacy (lossy). Cache local solo si fresco (<8 días) y completo.
- **Stock:** `x_analisis_de_stock.x_studio_stock_value_cash_physical`, EXCLUYENDO
  kits phantom (`mrp.bom type=phantom`) y combos (`product.template.type=combo`).
- **Nodos echelon (NO salas):** team **26 = Bodega Central (CD)**, team **2 = Website**.
  "Stock parado en salas" excluye estos. El CD se reporta aparte como pipeline.
- **Naming de salas:** vía `pos.config.name` (prefix-strip "Ventas "), NO por
  `pos.config.crm_team_id` (link roto: matchea solo 1 team).
- **Ventanas estándar:** 13 sem (demanda corriente / u_mes), 26 sem (6m), 52 sem (1a).
- **Grano:** product.product (variante) → product.template para decisiones de surtido;
  team_id (crm.team) para sala. `x_studio_product_id` de stock es **template**.

## Entregables

1. `definiciones.py` — constantes + loaders canónicos (importable por informes).
2. `reconciliacion.py` — chequeo re-ejecutable: corre los 4 detectores + tie-outs,
   emite PASS/WARN/FAIL. Se corre antes de cualquier informe.

## Qué NO se hace ahora

- No se refactoriza cada informe existente (eso es fase 2). Primero la capa y el
  chequeo; los informes migran a `definiciones.py` de a uno.
- No se arregla el double-count de kits en producción (eso es cambio al Script de
  Stock, proyecto aparte). Acá solo se DETECTA y se neutraliza en lectura.
