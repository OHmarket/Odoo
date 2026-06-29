# Diseño — Cap de cobertura máxima = frecuencia de pedido + 3 días

Fecha: 2026-06-04
Estado: Fase 0 (diseño), sin codear productivo.

## 1. Qué problema se resuelve
El target de cobertura de `x_analisis_de_stock` sube muy por encima de la
cobertura deseada para productos de compra frecuente. Hoy, para un SKU de
compra semanal (frecuencia ≈ 7 d), el target mediano es **2.32 semanas** y
muchos topan en **4.29 sem** (techo de crédito). El dueño quiere que esos
productos no pasen de **~1.5 semanas** de cobertura.

## 2. Qué decide el negocio con el resultado
La cobertura máxima fija el **inventario tope** por SKU → define cuánto se
compra (`compra = target − stock`). Bajar el cap baja el capital inmovilizado
en góndola y bodega para los productos de alta rotación, que se reponen seguido
y no necesitan colchón grande.

## 3. Qué pasa si el modelo se equivoca
- Cap **muy bajo** → quiebres en SKU de alta varianza (el safety queda recortado).
- Cap **muy alto** → sobrestock (situación actual).
El cambio sube el riesgo de quiebre en colas erráticas; se mide en backtest
antes de promover. Se reporta como recorte, no como verdad dura.

## 4. Cómo lo resuelve la teoría / ERPs
Modelo canónico: **periodic-review order-up-to (S)**.
`S = μ·(R+L) + z·σ·√(R+L)`, con techo financiero opcional.
- R = review period (frecuencia de pedido), L = lead time de entrega.
- El **cap** sobre S es práctica estándar (SAP "max stock level / target stock
  max"). Acá el cap se define como **R + buffer fijo**, con buffer = 3 días.
- El buffer fijo de 3 días es un **PROXY** del safety: reemplaza el término
  `z·σ·√(R+L)` por un colchón plano. Se documenta como PROXY: simple, sin
  sensibilidad a σ por SKU, elegido por control y transparencia operativa
  sobre precisión estadística.

## 5. Enfoques posibles
- **A. Buffer = medio ciclo con tope (min(½·freq, 6d)).** Calza puntos
  7→1.5 / 15→21 / 30→36 exactos, pero es por tramos.
- **B. Buffer media semana fija (3.5 d).** Solo calza el caso semanal.
- **C. Buffer fijo 3 días, general.** Una sola constante para todos.
  7→10d / 15→18d / 30→33d. ← **ELEGIDO**.

## 6. Enfoque elegido y por qué
**C: cap = frecuencia_pedido + 3 días, como techo (cap), general.**
- Una sola constante, sin tramos ni `min`. Trivial de explicar y auditar.
- Reemplaza `max(_fcw_sku, period_weeks * 2.0)` (línea ~1947) por
  `period_weeks + 3/7`. Se elimina el ×2 y el crédito como limitadores
  superiores.
- Es un **cap**: el motor sigue calculando `cobertura + safety(z·σ)`, pero el
  resultado nunca supera `freq + 3d`. Los SKU de alta varianza que hoy llegan a
  2–3 sem quedan recortados.
- Se decide **NO** volver el target 100% determinístico (mantener el safety
  estadístico por debajo del cap) para no perder priorización fina entre SKU.

En semanas: `cap_w = freq_w + 3/7` (3/7 ≈ 0.4286).

| Frecuencia | + 3 d | cap |
|---|---|---|
| 7 d  | 10 d | 1.43 sem |
| 15 d | 18 d | 2.57 sem |
| 30 d | 33 d | 4.71 sem |

## 7. Casos canónicos de validación
- SKU semanal de alta varianza (ej. CERVEZA STELLA, Mehuín): target debe caer
  de ~2.15 → 1.43 sem.
- SKU semanal de baja varianza con target ya < 1.43: **no debe cambiar**.
- SKU de proveedor a 30 d crédito: ya no debe inflar a 4.29; cap por su
  frecuencia real.
- Cigarros (hoy capado en 2.0 por ×2): nuevo cap por su frecuencia + 3d.

## Riesgos / decisiones abiertas
- `period_weeks` viene de `product.supplierinfo.delay` (campo "Delivery Lead
  Time" de Odoo, usado como frecuencia de pedido). **Validar que el delay
  cargado representa la frecuencia real de pedido** antes de promover.
- El campo persistido `x_studio_periodo_repos_weeks` está **stale** (guarda 1.0
  cuando la H real usada es 1.29). Revisar la persistencia por separado.
