# Cola larga: lote de traslado por caja autofinanciada (CD→sala)

**Fecha:** 2026-06-30
**Rama:** stock-cd-passthrough
**Script afectado:** `03_stock/OH Analisis de Stock.py` (v9.5.0)
**Relacionado:** `proyectos/2026-06-22-cola-larga-minmax/` (diagnóstico de SKUs muertos; sin diseño escrito)

---

## Fase 0 — Diseño

### 1. Qué problema se quiere resolver

En la cola larga (baja rotación, `mu_week ≤ 3 u/sem`) el motor repone el traslado
CD→sala con horizonte ~semanal. Resultado: a un slow-mover se le manda **1 botella
por semana**. Operativamente no tiene sentido (picking, manipuleo, viaje por 1
unidad). Marco quiere **consolidar en envíos más espaciados**, pensando en stock
mensual promedio por SKU.

Hoy además ese segmento queda en un hueco: la regla de **presentación / piso de
exhibición** (`_calc_display_stock_units`, `PRESENTATION_UMBRAL_SEM = 3.0`) solo
aplica a `mu_week > 3/sem`. Bajo 3/sem no hay piso de presencia **ni** lote sensato:
el target colapsa a ~0–1u (rama CZ: `min(2,H)·max(mu, 0.23)`, safety=0). Hay que
**completar la curva de mínimos hacia abajo**.

### 2. Qué decisión se toma con el resultado

Cuánto y cada cuánto trasladar un SKU de cola larga desde el CD a la sala. La
política fija el **lote de traslado** (order-up-to) y, vía el lote, la **frecuencia**
(emerge ~mensual). NO toca la compra al proveedor (el CD sigue comprando normal).

### 3. Qué pasa si el modelo se equivoca

- **Lote muy chico** → vuelve el goteo semanal (no resuelve nada).
- **Lote muy grande / cap flojo** → stock muerto inmovilizado en sala, financiado
  de bolsillo (el SKU rinde más allá del plazo de pago al proveedor).
- Mitigación: cap anclado al **plazo de pago** (efecto caja medible), no a un número
  arbitrario.

### 4. Cómo lo resuelve la teoría / ERPs grandes

- **Revisión periódica (R, S)** — SAP MRP "periodic lot-sizing" / Oracle "Periods of
  Supply": para slow-movers se revisa cada R (aquí ~30 días) y se sube a un
  order-up-to S. Reduce frecuencia de pedido a costa de mayor stock promedio (trade-off
  aceptado explícitamente).
- **Fixed lot size / "lot-for-lot por caja"** — SAP `EX`/`FX` lot-sizing: pedir en
  múltiplos de la caja del proveedor. Aquí: enviar **1 caja entera** cuando la caja
  rinde dentro del horizonte.
- **Cap por cashflow** — análogo a *cash conversion cycle*: si el stock rota antes de
  pagar la factura, es autofinanciado. Anclar el cap al plazo de pago es práctica
  estándar de gestión de capital de trabajo (no es fórmula nueva).

No se inventa modelo: es (R,S) periódico + redondeo a caja + cap por días de pago.

### 5. Enfoques considerados

| # | Enfoque | Por qué NO |
|---|---|---|
| A | EOQ Wilson por SKU (T*=√(2S/(D·h))) | requiere estimar costo de picking S y holding h; data no disponible, sobre-ingeniería para la cola |
| B | Lote fijo en unidades (ej. ≥6u global) | no escala con rotación ni con la caja real del SKU; sobre-stockea el fondo de la cola |
| C | Intervalo fijo mensual puro (R,S, S=mu·30d) | ignora la caja: fracciona siempre, pierde el "enviar caja limpia" y el efecto cashflow |
| **D** | **(R,S) con lote por caja autofinanciada + cap por plazo de pago** | **elegido** |

### 6. Enfoque elegido (D) y qué se decide NO hacer

> **mu es por local.** `mu_week` no es un escalar del SKU: es un vector por
> (sala, SKU). El script ya corre por (team, SKU), así que el gate, `cobertura_caja`
> y el lote se evalúan con el mu de **cada sala**. No hay variable global de demanda.

**Lote para SKU de cola larga (`mu_week ≤ 3/sem`), traslado CD→sala — por (sala, SKU):**

```
cobertura_caja_dias = (moq / mu_week) * 7         # moq = caja real (product_supplierinfo.min_qty × UoM)
q30 = floor(mu_week * COLA_OBJETIVO_DIAS / 7) + COLA_PISO_UNIDADES   # order-up-to mensual: ciclo SOBRE el piso (ROP)

# --- CUÁNTO (lote), 3 vías ---
SI OBJETIVO_DIAS (30) <= cobertura_caja_dias <= PLAZO_PAGO_DIAS (45):
    lote = moq                                     # caja rinde ~1 mes y autofinanciada -> CAJA LIMPIA
SINO SI cobertura_caja_dias < 30:                  # CAJA CHICA
    lote = q30                                     # caja + unidades sueltas hasta ~30d (traslado interno fracciona)
SINO:                                              # cobertura_caja > 45  -> COLA PROFUNDA
    lote = q30                                     # fracción a ~30d (caja rendiría > plazo de pago)

# Nota (s,S): el ciclo mensual va SOBRE el piso de presencia (ROP), NO incluyéndolo.
# ciclo real = (S − ROP)/mu ≈ 30d. Con S = max(floor,piso) (sin +piso) el piso se comía
# medio ciclo -> cadencia 17d (medido 1ª corrida). Con q30 (+piso) -> 94% target en 4-6 sem.
```

**Dos ejes distintos — no confundir cobertura objetivo con disparo:**

| Eje | Qué fija | Depende de |
|---|---|---|
| **ROP** (cuándo dispara) | gatillo: stock cruza el reorder point | **lead** → `mu_local × lead + presencia` |
| **Lote** (cuánto manda) | cobertura del envío (~30d / caja) → cadencia | **objetivo mensual / plazo pago**, NO el lead |

**Disparo = ROP por local (emergente).** NO hay período fijo (R) global. Cada sala
dispara cuando **su** stock cruza el ROP; se manda el lote calculado con **su** mu;
la cadencia emerge sola por local (≈ `lote / mu_local`). El objetivo del lote es
**~30 días (1 mes)**; los 45d son el **techo** (plazo de pago), no el target.

**ROP bajo, ligado al lead real.** `ROP = mu_local × lead + presencia`. El lead del
traslado **CD→sala es ~1 día** (interno; el `delay` grande es frecuencia de compra,
no lead). Entonces `ROP ≈ 1u` → la sala dispara **casi vacía** (piso de presencia 1u).
No ignora el lead: el lead es chico y el ROP queda en ~1u; si el lead fuera grande,
el ROP subiría y dispararía antes. Drenar el lote casi completo antes de reponer es
lo que da la cadencia ~mensual (con el trigger universal `cover < 50%·C` el ciclo se
cortaría a la mitad).

**Coherencia con `_cover_label`:** para SKU gated, `C` (coverage_target_weeks) = el
lote en semanas, no el target CZ de 2 sem → no marca "exceso" falso al llegar el lote.

**Parámetros (tuneables, CTX):**

| Param | Default | Rol |
|---|---|---|
| `COLA_UMBRAL_WEEK` | 3.0 u/sem | gate por (sala,SKU); calza con `PRESENTATION_UMBRAL_SEM` |
| `COLA_OBJETIVO_DIAS` | 30 | cobertura objetivo del lote (1 mes); dimensiona la fracción |
| `PLAZO_PAGO_DIAS` | 45 | techo (plazo de pago): decide caja-entera vs fraccionar |
| `COLA_PISO_UNIDADES` | 1 | presencia mínima / piso del ROP |

**Se decide NO hacer:**
- NO tocar la compra al proveedor (solo traslado interno).
- NO plazo de pago por proveedor (global único ~45d; refinamiento futuro).
- NO EOQ ni costos de picking/holding (no hay data; sobre-ingeniería).
- NO piso de presentación adicional bajo 3/sem (el piso 1u del lote cumple la presencia).
- NO romper la caja en la compra (el fraccionamiento es solo en el traslado interno).

### 7. Casos canónicos de validación

| SKU (pack=6) | cobertura caja | Hoy | Con política | Cadencia |
|---|---|---|---|---|
| mu=1/sem | 42 días (≤45) | ~1u/sem (goteo) | **1 caja** (autofinanciada) | ~6 sem |
| mu=2/sem | 21 días | ~2u/sem | **1 caja** (<1 mes, limpia) | ~3 sem |
| mu=0.5/sem | 84 días (>45) | goteo errático | fraccionar S=3u (floor2+piso1) | ciclo (3-1)/0.5=4 sem |
| mu=0.2/sem | 210 días (>45) | goteo errático | fraccionar S=1u (piso); dura 1/mu | ~5 sem |
| mu=3.1/sem | 14 días | regla actual | **sin cambio** (sobre el gate) | semanal |
| lento en sin_stock | — | 1u | **lote completo** (presencia) | — |

**Bordes:**
- Sala en 0 con demanda real → envía el lote igual (el gate evita goteo, no starvea).
- CD escaso → entra a fair-share (Rule C) como hoy; el lote es objetivo, no piso que
  rompe el reparto.

**Trade-off aceptado:** el slow-mover carga ~2u más de stock promedio que el SKU justo
sobre el gate. Es el precio de pasar de ~4 entregas/mes a ~1, elegido a conciencia.

### Integración técnica

- `_calc_target_units` — branch para gated: S = lote por caja/fracción (reemplaza el
  `min(2,H)` de la rama CZ para el segmento gated).
- Trigger / `qty_transferir` — ROP bajo para el segmento gated (cadencia real ~mensual).
- Usa `moq` ya disponible en el registro (`fwd['moq']`, líneas 1585/1656).
- `_cover_label` — `C` = lote para gated (evita alarma "exceso" falsa).
