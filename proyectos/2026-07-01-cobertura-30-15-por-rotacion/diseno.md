# Cobertura de sala 30/15 por rotación (order-up-to cash-bounded)

Fecha: 2026-07-01
Estado: Fase 0 (diseño) + diagnóstico read-only. NO promovido.

## 1. Problema

El gate de entrada a la política de cola larga es `mu_week <= 3` (COLA_UMBRAL_WEEK),
un umbral **plano y ciego al MOQ**: el mismo `mu=3` significa "la caja rinde 2 días"
(moq=1) o "la caja rinde 8 semanas" (moq=24). Deja entrar cajas que rotan a diario y
deja afuera cajas que rinden 6 semanas. Además convive con un segundo mundo (target
estadístico para `mu>3`), y el campo `x_studio_stock_minimo` cambia de significado en
el borde `mu=3` (caja S ↔ facing de vitrina), lo que hace que un mismo SKU muestre
mínimos incoherentes entre salas.

## 2. Decisión que se toma con el resultado

Cuánto stock (order-up-to `S`) mantener en cada sala, por SKU, para el reparto
CD→sala en cadencia fija. Fija el nivel de inmovilizado, la frecuencia de picking
(viajes) y el colchón contra quiebre.

## 3. Qué pasa si el modelo se equivoca

- S muy alto → caja inmovilizada (crítico: runway ~3 meses, sangrado ~$53M/mes).
- S muy bajo en rápido → quiebre → pérdida de tráfico (quiebre alto = −34% tráfico).
- Toques mal dimensionados → picking redundante (costo operativo, no de flete: el
  camión pasa igual en cadencia fija).

## 4. Prioridad declarada (dueño)

**Caja > Quiebre > Viajes.** Sobrevivencia de caja primero (minimizar inmovilizado),
tolerar algo de quiebre en la cola, viajes al final porque el camión ya pasa.

## 5. Cómo lo resuelven los grandes

Revisión periódica **(R, s, S)** (Silver-Pyke-Peterson; SAP IM/IBP "periodic review",
Oracle "Days of Cover"). En cadencia fija el camión ES la revisión `R`. El order-up-to
`S` se fija en días de cobertura; el reorder point `s` cubre `demanda·(lead+R) + safety`.
La novedad de negocio: el nivel `S` se ancla a **rotación** para concentrar el ahorro
de caja donde el capital se acumula (alta rotación = mucho inventario valorizado).

## 6. Enfoque elegido: TECHO de cobertura de dos niveles por rotación

> HALLAZGO del diagnóstico (2026-07-01) que reencuadró el diseño: hoy el sistema ya
> corre en la mediana 15d (fast) / 32d (slow). Aplicar 30/15 como **target/piso**
> SUBE la caja +16% ($28M) porque levanta los ~4.170 SKU×sala que están por debajo →
> contradice la prioridad #1. La regla correcta es **cap/techo**: solo recorta, nunca
> sube. Libera −$16M (−9.3%). El "30d" que el dueño tenía en la cabeza es el **techo**
> de los lentos, no su piso.

Clasificador por SKU × sala:

```
cajas_semana = mu_week / moq
si cajas_semana >= K_FAST  ->  T = 15 días   (rápido: donde el cash se concentra)
si no                      ->  T = 30 días   (lento/medio)
```

Política (R,s,S) periódica con TECHO de cobertura (R = cadencia del camión; lead L ~1d):

```
d = mu_week / 7                          # demanda diaria
S = min( target_estadístico , d * T )    # order-up-to CAPADO a 30d/15d (solo recorta)
```

Propiedades:
- **Solo recorta** (S nunca sube sobre el target actual) → cash a target ≤ actual,
  garantizado. Sirve Caja primero.
- Piso del cap: `vitrina + safety` → nunca corta por debajo del safety ni de la
  presentación.
- Elimina el gate arbitrario `mu<=3`. El pass-through de cola profunda (caja en CD que
  gotea fracciones) sigue: es *sourcing* del CD, no el target de la sala.

> ⚠️ CORRECCIÓN (revisión 2026-07-01): la versión previa afirmaba *"el ROP no cambia →
> quiebre protegido"*. **Es falso en esta base de código.** No existe un `s` separado: el
> gatillo de reorden se deriva de `reorder_target_weeks`, y el cap lo baja junto con el
> target (`_cover_label` usa ese valor como `C` y dispara `bajo` en `<50%·C`). Por lo
> tanto **el cap SÍ baja el punto de reorden**: un rápido capado 30d→15d pasa a marcar
> `bajo` recién con ~7d de cobertura en vez de ~15d → repone más tarde. El impacto en
> quiebre es MAYOR que el "−stock de ciclo": se mueve el trigger, no solo el nivel. Esto
> es consistente con Caja > Quiebre (más agresivo en caja), pero el backtest debe medir
> el *timing* de reorden, no solo el nivel de stock. Un (s,S) con `s` desacoplado del
> techo queda para una versión futura si el backtest muestra que el quiebre desborda.

En cada pasada: si stock_proyectado <= s, transferir hasta S. El CD consolida y compra
la caja (pass-through v9.2.0 sin cambios).

Por qué el techo del rápido en 15d rinde tanto: 440 filas fast = $30M (~$70k/fila) vs
$15k/fila en slow → el fast es 4.6× más denso en capital. Recortarlo es la palanca de
caja de mayor leverage (−14.6% en el bucket fast).

Por qué el rápido va a 15d (contraintuitivo pero correcto para Caja):
- 30d de un SKU de varias cajas/sem = montaña de cash (Royal Guard 187 u/sem × 30d
  ≈ 33 cajas en UNA sala). 15d lo parte al medio.
- Los viajes casi no suben: ese SKU se toca en cada pasada igual, y un pick de 15d
  sigue siendo >= 1 caja (eficiente).
- Quiebre: el trigger de reorden baja con el cap (ver ⚠️ arriba). En un rápido de alto
  volumen el riesgo es acotado (demanda predecible), pero NO es cero → lo mide el backtest.

Por qué el lento se queda en 30d:
- 30d = poca plata (1 caja o menos) → inmoviliza casi nada.
- 30d permite **saltear pasadas** → menos toques de picking (viajes).
- Bajarlo a 15d duplicaría toques para ahorrar centavos.

Parámetro FIJADO: **`K_FAST = 2` cajas/sem** (tunable por CTX). Con K=2: Jagermeister
(máx ~1 caja/sem) queda 100% en 30d; Royal Guard (~7.8 cajas/sem) cae a 15d.

Barrido de K (cap, 2026-07-01) — el cash es monótono decreciente en K; K=2 le gana a
K=3 por $1,4M y es la lectura fiel de "varias cajas" (≥2). K=1 estira la definición
(capa a 15d movedores de 1 caja/sem) y sube el riesgo de quiebre:

| K | n_fast | cash liberado (cap) |
|---|---|---|
| 1.0 | 862 | $20,2M |
| 1.5 | 580 | $17,2M |
| **2.0** | **440** | **$16,0M** |
| 3.0 | 289 | $14,6M |
| 4.0 | 204 | $14,1M |

Los viajes casi no dependen de K (~+13-16% en fast en todos los casos): el costo de
viajes lo pone el cap en sí, no dónde caiga K. K es un dial caja↔riesgo-de-quiebre;
bajar más de 2 solo lo valida el backtest de servicio.

Qué reemplaza: el cap actúa SOBRE el target estadístico y sobre el lote de cola larga
existentes (v1 NO elimina el gate `mu<=3` — es un cambio separado). El techo baja tanto
el nivel (S) como el gatillo de reorden (ver ⚠️ arriba), así que el ahorro de caja viene
con un costo de servicio que el backtest debe cuantificar.

### Enfoques descartados

- **B — arreglar solo el gate** (`box_days>=30` en vez de `mu<=3`): diff chico pero
  sigue con dos mundos y no ataca el inmovilizado del rápido. Fallback si A da mal
  backtest.
- **C — EOQ costo-total por SKU** (holding + quiebre + pick): lo más correcto pero
  necesita costo de pick y elasticidad de tráfico que no tenemos limpios. YAGNI v1.

## 7. Casos canónicos de validación

1. **Royal Guard 710** (varias cajas/sem, moq 24): debe caer a 15d y bajar cash vs hoy.
2. **Jagermeister** (moq 6, máx ~1 caja/sem): debe quedar 100% en 30d.
3. **Blue Label** (mu ~0.08/sem, moq 1): 30d < 1 caja → caja vive en CD, gotea; sala
   queda en piso vitrina.
4. **sin_salida** (mu <= 0.23): sin target, retorno a CD si sobra.

Métrica del diagnóstico read-only (antes de tocar el Server Action):

- # SKU×sala sobre el techo (recorte) vs bajo (sin cambio).
- Δ cash inmovilizado a target (Σ S·costo) actual vs cap.
- Δ toques/mes (proxy viajes) actual vs nuevo.
- Concentración del ahorro por SKU.

### Resultados medidos (diag_impacto_30_15.py, 2026-07-01, K_FAST=2)

Universo: 11.497 SKU×sala (mu>0.23, excl. CD/Web); 1.542 sin costo estimable.

| bucket | n | cobertura hoy (med) | sobre techo | cash actual | cap (techo) |
|---|---|---|---|---|---|
| FAST →15d | 440 | 15 d | 210 | $30,6M | **−14,6%** |
| SLOW →30d | 9.515 | 32 d | 5.575 | $141,6M | **−8,1%** |
| TOTAL | | | | $172,3M | **−9,3% (−$16,0M)** |

- Como **target/piso** la regla SUBE +16,2% ($28M) → descartado (viola Caja).
- Como **cap/techo**: libera **−$16,0M** a target. Toques/mes bajan (slow −27%),
  no suben → viajes ok.
- Ahorro poco concentrado: top-20 SKU = 28% ($4,4M). Lidera cerveza/whisky/commodities
  (Cristal Lata $1,09M, Johnnie Walker, Mistral, Royal Guard, hielo, carbón) = alto
  valor o alto volumen, justo donde 30/15 muerde.
- Caso canónico Jagermeister: 100% en 30d ✓ (todas las salas cap 30d), recorte modesto
  −$75k (salas de baja rotación que hoy quedaban levemente sobre 30d).

Pendiente de medir en backtest (no en este diagnóstico read-only): efecto en servicio
(quiebre) del recorte. Ojo: el cap baja el stock de ciclo Y el gatillo de reorden
(`reorder_target_weeks` alimenta `_cover_label`), así que el quiebre puede subir más de
lo que sugiere el −stock. El backtest debe mirar el *timing* de reorden, no solo el nivel.

## Supuestos / PROXY

- `K_FAST=2` cajas/sem: PROXY de negocio ("varias"), tunable.
- Plazo de pago no entra en v1 (el nivel se ancla a rotación, no a autofinanciamiento).
  Hook per-proveedor queda para v2.
- Costo unitario del diagnóstico = stock_value_cash_physical / stock_real (mediana por
  SKU entre salas con stock).
- Validación real = backtest / seguimiento de servicio+capital, no este diagnóstico.
