# Necesidad de productos pedida a bodega (pull sala → CD visible)

**Fecha:** 2026-07-02
**Estado:** Diseño (Fase 0) — aprobado enfoque A
**Script afectado:** `03_stock/OH Analisis de Stock.py` (Script 4)
**Origen:** auditoría de stock cero (2026-07-02). De 5.538 quiebres con demanda,
77% quedaron sin acción visible; la necesidad que las salas ejercen sobre el CD
no se persiste cuando el CD está vacío → los CD-idle son invisibles.

---

## 1. Qué problema se resuelve

Hoy el modelo calcula la necesidad de cada sala hacia el CD
(`qty_neta_pre_central`) pero **solo la persiste cuando el CD tiene stock para
repartir** (`x_studio_qty_transferir`). Cuando el CD está vacío, la necesidad
cruda se pierde: la sala en quiebre muestra `no_comprar` y no queda rastro
auditable de que *pidió* producto a bodega.

Queremos **reflejar (ver) la necesidad pedida a bodega**, exista o no stock en el
CD, sin crear documentos.

## 2. Qué decisión se toma con el resultado

- El comprador/analista ve el **pull consolidado** que las salas ejercen sobre el
  CD por SKU.
- Se **caza el CD-idle**: SKUs con salas en quiebre donde el CD ni tiene stock ni
  compró (los 87 del top-500 / $939K de la auditoría).
- Insumo para calibrar el piso de reorden del CD y para priorizar compra.

## 3. Qué pasa si el modelo se equivoca

Campos informativos (Float), read-only para el resto del pipeline. **No** disparan
compra ni traslado (no tocan `qty_a_pedir` ni `qty_transferir`). Un valor mal
calculado desinforma pero no genera ni bloquea documentos. Riesgo operativo bajo.

## 4. Cómo lo resuelve la industria

Patrón canónico **DRP / distribution requirements planning** (SAP IBP, Oracle
Demantra, Manhattan): la demanda dependiente de cada nodo hijo (sala) se agrega
como *requirement* sobre el nodo padre (CD), y el *net requirement* del CD =
`Σ requerimientos_hijos − stock_disponible_padre` (incluye in-transit). Es
exactamente lo que exponemos, sin inventar fórmula: bottom-up dependent demand +
net requirement. No creamos el documento DRP formal (fuera de alcance), solo el
indicador.

## 5. Enfoques evaluados

- **A (elegido):** campo por sala + agregado en CD. Ver el pull por sala y
  consolidado, con la alarma de no-cubierta.
- **B:** solo agregado en CD. Más simple, pierde la distribución por sala.
- **C (descartado):** reusar `x_studio_qty_transferir` cargando la necesidad
  cruda aunque el CD esté vacío. Rompe la semántica del campo → Script 5 generaría
  **traslados fantasma**. Descartado.

## 6. Enfoque elegido y qué NO se hace

**Enfoque A reducido al mínimo (1 campo).** Definición de necesidad = **target
forward completo** (`target_units − stock_proyectado`, ≥0), consistente con lo que
el CD usa para comprar.

Solo se persiste el **átomo** (necesidad por sala). El pull consolidado y la
alarma de CD-idle se **derivan** en reportería (group-by / pivote), no se
materializan como campos:
- **Pull total por SKV** = `Σ x_studio_necesidad_bodega` agrupando por producto
  (Odoo lo suma solo en un pivote).
- **Alarma CD-idle** = filtro sobre la fila CD: `pull_total > stock_proyectado_CD
  AND x_studio_qty_a_pedir = 0` (o vista con la resta). El CD ya expone
  `x_studio_stock_proyectado` (físico + pipeline) y `x_studio_qty_a_pedir`.

### Campo nuevo (Studio, tipo Float, creado manualmente en Studio)

| Campo | Fila donde aplica | Fórmula |
|---|---|---|
| `x_studio_necesidad_bodega` | sala **solo_bodega** | `max(target_units − stock_proyectado, 0)`. 0 en salas no-solo_bodega y en la fila CD. |

### Punto de inserción en `OH Analisis de Stock.py`

- **Sala** (dict `vals` de la fila-sala, ~L3356-3381): agregar
  `'x_studio_necesidad_bodega': _safe_float(rec.get('qty_neta_pre_central'), 0.0)
  if meta.get('solo_bodega') else 0.0`. El flag es `meta.get('solo_bodega')`
  (proviene de `x_studio_comprar_solo_en_bodega`, seteado en `meta` en ~L1077 y
  ya usado así en ~L3130). `qty_neta_pre_central` se almacena en el `rec` en
  ~L2428. **Único punto de cambio**: la pseudo-fila del CD no se toca.

### Qué NO se hace
- No se crea documento (requisición/traslado interno) en Odoo.
- No se materializan `total` ni `no_cubierta` como campos (derivables por pivote/
  filtro; ver arriba).
- No se modifica `qty_a_pedir` ni `qty_transferir` ni la lógica de compra/traslado.
- No se cambia la definición de necesidad a "gap hasta reorden" (usamos target
  completo).
- No se agregan queries nuevas (reusa lo ya calculado en memoria).

## 7. Casos canónicos de validación

**Alcance del campo:** refleja SOLO el pull de salas `solo_bodega` (las únicas que
tiran del CD). Un SKU `no_disponible_de_compra` (p.ej. Escudo 450299) es
`not solo_bodega` por definición → `necesidad_bodega = 0`. Eso es correcto: ese es
un problema de catálogo (`purchase_ok=False`), no de pull a bodega, y se atiende
por otra vía.

| Caso | `necesidad_bodega` (sala) | Pull Σ (derivado) | Alarma idle (derivada) | Esperado |
|---|---|---|---|---|
| **Fernet 470017** solo_bodega (OC34298, 48u en tránsito) | >0 en salas quiebre | ≈ Σ salas | Σ ≤ stock_proy_CD(48) → no marca | ✅ no falsea |
| **solo_bodega en quiebre, CD vacío** (caso CD-idle) | >0 | ≈ Σ salas | Σ > stock_CD(0) y qty_a_pedir 0 → **marca** | ✅ caza idle |
| **Escudo 450299** no_disponible (not solo_bodega) | 0 | no aporta al Σ | — | ✅ excluido (es catálogo) |
| **solo_bodega con traslado sano** | = qty_transferir | Σ | CD con stock/pedido → no marca | ✅ |
| **solo_bodega sobrestock / cola-larga sobre ROP** | 0 (política (s,S)) | — | — | ✅ no pide de más |

Validación operativa: correr Script 4 y comprobar que el pivote
`Σ x_studio_necesidad_bodega` por SKU, filtrado por la fila CD con
`Σ > x_studio_stock_proyectado AND x_studio_qty_a_pedir = 0`, lista los CD-idle
**solo_bodega** (subconjunto de los 87 del top-500 que sí tiran del CD).
