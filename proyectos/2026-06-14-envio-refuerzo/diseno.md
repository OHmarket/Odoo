# Envío Sala Refuerzo — segundo viaje de mitad de semana

## Fase 0 — Diseño

### 1. Qué problema resuelve
El reparto normal CD→sala sale el **lunes** según plan de cobertura semanal. El
**viernes** operaciones hace un segundo viaje ("refuerzo") para puentear el fin de
semana hasta el próximo lunes: vie–sáb–dom–lun = 4 días (5 si hay feriado). Hoy ese
segundo viaje se arma a mano, sin método: operaciones decide a ojo qué mandar.

El objetivo es **calcular el refuerzo**: enviar cobertura para esos N días, pero
**solo para los SKU cuyo stock proyectado no alcanza a cubrir N días** de demanda.

### 2. Qué decisión se toma con el resultado
Qué SKU y cuánto despachar desde el CD a cada sala en el viaje del viernes. El
resultado son traslados internos CD→sala en **borrador** que operaciones revisa y
confirma (mismo modo adopción que el ciclo del lunes).

### 3. Qué pasa si el modelo se equivoca
Riesgo acotado:
- **Sobre-envía** → sala queda con algo más de stock de finde; el ciclo del lunes lo
  compensa (no compra lo ya cubierto). Costo: capital de trabajo de 3 días.
- **Sub-envía** → quiebre de finde (el problema que ya existe hoy). El método solo
  puede mejorarlo, no empeorarlo, porque parte del mismo gap.
- Nunca auto-confirma: todo queda en borrador para revisión humana.

### 4. Cómo lo resuelven los grandes (modelo canónico)
Es **revisión periódica diferenciada por criticidad** (ABC-driven review intervals)
+ **expedite replenishment**: bajar el review period solo para el subconjunto que no
cubre el horizonte corto, en vez de esperar al próximo ciclo. SAP/Oracle modelan
exactamente esto: un segundo `(R,S)` con horizonte = días hasta el próximo reparto,
restringido a `stock proyectado < demanda(horizonte)`. No es modelo nuevo: es el
mismo target del ciclo normal con horizonte = N días en vez de la semana, y filtro
gap>0. La demanda del horizonte se pondera por **día de semana** (DOW) porque el
finde es pesado; ponderar es lo correcto cuando el horizonte no es múltiplo de semana.

### 5. Enfoques considerados (dónde vive el cálculo)
- **A) Server Action nueva "OH Envío Refuerzo"** que re-corre el análisis (snapshot
  fresco del viernes), lee `x_analisis_de_stock` y genera los traslados. Autocontenido,
  no toca la matemática del ciclo semanal, reusa los stock maps ya resueltos.
- B) "Modo refuerzo" dentro de OH Análisis de Stock (recalcula target a N días).
  Descartado: invasivo al script pesado; mezcla dos horizontes en un mismo modelo.
- C) Standalone con queries live a `stock.quant`/pickings. Descartado: re-implementa
  mapas de stock ya resueltos; más código y más superficie de error.

### 6. Enfoque elegido y qué NO se hace
**A — Server Action "OH Envío Refuerzo", propose-only (borrador), por ruta de salas.**

Lo que NO hace v1 (YAGNI):
- Sin prioridad ni fair-share entre salas: es trabajo manual por sala, en orden de la
  ruta seleccionada. Cada sala consume del CD lo que va quedando (secuencial).
- Sin rebalanceo sala→sala: el refuerzo sale solo del CD. Si el CD no tiene, no se
  despacha ese SKU (queda en el log).
- Sin MOQ/cajas: traslados internos en **unidades** (igual que `envio_a_sala`).
- Sin descontar reserva de exhibición: el refuerzo cubre venta de finde, no góndola.
- Sin auto-confirmar: todo en borrador.

#### Arquitectura
```
[Form generación de documentos]
   multi-select salas (crm.team / ruta)  +  campo "días de refuerzo" (entero)
   botón "Envío Sala Refuerzo"
        │
[OH Envío Refuerzo]  (Server Action / nuevo gen_type = 'envio_refuerzo')
   1. Re-corre análisis (action 1502) → snapshot fresco del viernes
   2. Lee x_analisis_de_stock: mu_week, stock_real, stock_pedido_transfer, stock_central
   3. demanda_N = mu_week × (Σ pesos DOW de hoy..hoy+N) / 7      (generate_series)
   4. Por sala (orden de la ruta), por SKU:
        gap = max(demanda_N − (stock_real + stock_pedido_transfer), 0)
        qty = min(gap, CD_disponible[sku]);  CD_disponible[sku] −= qty
        si qty ≤ 0 → sin línea
   5. Crea stock.picking interno CD→sala (borrador, unidades)
        │
[Operaciones]  revisa y confirma el borrador
```

#### Demanda de N días (DOW-weighted)
Reusa los pesos DOW ya calibrados en OH Análisis de Stock (suma = 7.0, fuente
`x_presupuesto_de_venta` días NORMAL 2026; DOW PostgreSQL 0=dom..6=sáb):

| día | dom | lun | mar | mié | jue | vie | sáb |
|-----|-----|-----|-----|-----|-----|-----|-----|
| peso| 1.1039 | 0.6370 | 0.6845 | 0.7477 | 0.8104 | 1.3166 | 1.6998 |

`generate_series(hoy, hoy + N-1 días)` → suma pesos → `demanda_N = mu_week × Σ/7`.
Ej. viernes con N=4 (vie+sáb+dom+lun) = (1.3166+1.6998+1.1039+0.6370)/7 = **0.680 sem**
(vs 0.571 lineal: captura el peak de finde sin sub-enviar).

#### Stock de la sala (base del gap)
`stock_real + stock_pedido_transfer` = on-hand + en tránsito. En tránsito evita
re-enviar lo que viene llegando del lunes. NO se descuenta exhibición en v1.

#### Stock del CD (tope del envío)
`x_studio_stock_central` (on-hand libre del CD). Es el tope duro: "envía lo que tiene
en stock". Se descuenta secuencialmente a medida que se procesan las salas de la ruta,
para no prometer las mismas unidades a dos salas.

#### Documento
`stock.picking` interno CD→sala, mismo tipo que `envio_a_sala`, estado **borrador**,
cantidades en unidades. **Idempotente** por `origin_key` que incluye sala + fecha + N +
marcador `refuerzo` (re-correr el mismo viernes no duplica).

### 7. Casos canónicos de validación
- Sala con SKU en quiebre (stock 0) y mu_week > 0 → genera línea por demanda_N (capada
  a CD). Es el caso central.
- SKU con stock_real + en tránsito ≥ demanda_N → **sin línea** (ya cubre los N días).
- SKU con CD en 0 → sin línea, aparece en el log como "sin cobertura CD".
- Dos salas piden el mismo SKU y el CD no alcanza a ambas → la primera de la ruta se
  lleva lo disponible, la segunda recibe el remanente (orden secuencial).
- N=4 un viernes normal → demanda_N ≈ 0.68 × mu_week (verifica DOW vs lineal).
- Re-correr el mismo viernes con misma ruta/N → no duplica pickings (idempotencia).

### Dependencias / decisiones para el plan
- **Form host:** definir si el multi-select de salas + campo días se agregan al modelo
  del form de generación actual o a un wizard transient nuevo. (Pendiente confirmar en
  Fase 1 cómo está montado el botón actual de `envio_a_sala`.)
- Reusa: snapshot de `x_analisis_de_stock`, pesos DOW del análisis, infra de creación
  de `stock.picking` de OH Generación de Documentos, `TEAM_WAREHOUSE_MAP_FALLBACK`.
- Server Action safe_eval: aplican los gotchas conocidos (no `fields`, no import,
  `x_name` required al crear, etc.) — ver skill odoo-server-action-safe-eval.

### Fuera de alcance (v1)
- Prioridad / fair-share entre salas.
- Rebalanceo sala→sala cuando el CD no tiene.
- MOQ / redondeo a cajas.
- Cálculo automático de N desde el calendario de feriados.
- Auto-confirmación de traslados.
