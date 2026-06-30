# Sobre-asignación del CD: traslados > stock físico (combo/echelon keying)

Fecha: 2026-06-29
Estado: **Fase 0 — CERRADO 2026-06-30: NO hay bug, fue artefacto de medición**
Detectado validando: `proyectos/2026-06-29-fair-share-cd-salas/` (Fair Share v9.4.0)

## CIERRE (2026-06-30) — el síntoma es un artefacto de medición

El reparto CD→sala **no sobre-asigna**. Evidencia (DIAG read-only en esta carpeta):

- `DIAG_remed_universo.py`: re-medido el universo separando por `buy_action`.
  **`transferir_desde_cd` (CD→sala): 335 templates, 0 con Σtransfer > stock_central.**
  El cap del fair-share (`_runout_level_alloc`, Σ ≤ available) funciona correcto.
- Causa del falso síntoma: `x_studio_qty_transferir` es un campo operativo
  **sobrecargado** que carga 3 cosas, y el conteo original las sumó todas
  comparándolas contra `stock_central` (que solo acota la dirección CD→sala):
  | flujo en qty_transferir | unidades | acota contra |
  |---|---|---|
  | `transferir_desde_cd` (CD→sala) | 10.766 | stock_central CD ✓ (0 exceden) |
  | `retorno_a_cd` (sala→CD) | 2.197 | stock de la SALA, no del CD |
  | `compra_cd` / `no_comprar` (residual inerte) | ~10.800 | nada — Generación lo ignora |

### Hipótesis del síntoma — todas descartadas
- **H1 combo/kit**: ❌ caso testigo VINO PIPEÑO (tmpl 24185) NO tiene BoM, es
  producto simple de 1 variante. `DIAG_vino_pipeno.py`.
- **H2 echelon keying**: ❌ `stock_central=0` es correcto, el CD genuinamente no
  tiene stock (cero quants en ubicación CD; todo el stock vive en salas).
  Los 60 "de exceso" son 4 salas (teams 7/8/9/18) devolviendo al CD vía
  `retorno_a_cd`, cada una capada a su propio stock (45≤48, 6≤10, 5≤10, 4≤8).
  `DIAG_vino_pipeno2.py`.
- **H3 filas stale**: ❌ todas las filas con write_date = run actual.

### Riesgo (impossible pickings) — NO se materializa
`OH Generacion de Documentos.py` filtra **estricto por `buy_action`**
(`transferir_desde_cd` → picking CD→sala; `retorno_a_cd` → sala→CD) y lee
`qty_transferir`. El `qty_transferir` residual en filas `compra_cd`/`no_comprar`
**nunca se consume** (esas filas solo originan OC). Y como Σ`transferir_desde_cd`
≤ stock_central en los 335 templates, **ningún picking imposible se genera**.

### Deuda residual (cosmética) — RESUELTA 2026-06-30
Filas `compra_cd`/`no_comprar_esta_semana` retenían un `qty_transferir`
heredado que nunca se documenta pero ensuciaba el campo. Resultó ser **100% la
pseudo-fila CD (team 26)**: 200 `compra_cd` + 135 `no_comprar` = 335 = exactamente
los templates con `transferir_desde_cd`. Esa fila escribía
`qty_transferir = Σ despacho a salas` (agregado redundante que ya vive, desglosado,
en las filas `transferir_desde_cd` de cada sala) → al sumar el campo crudo se
doble-contaba.

**Fix aplicado** en `03_stock/OH Analisis de Stock.py` (1 invariante, 2 puntos):
`x_studio_qty_transferir` queda en 0 salvo que `buy_action ∈
{transferir_desde_cd, retorno_a_cd}`.
- Path sala (~L2972): cubre además la rama latente `compra_cd` que preservaba transfer.
- Path pseudo-fila CD (~L3343): pone en 0 el agregado redundante.

Document-neutral (Generación ya filtra por `buy_action`) y no toca el reparto.
**Validación:** tras correr la SA, re-correr `DIAG_remed_universo.py`: el desglose
por acción no debe mostrar unidades de transfer en `compra_cd`/`no_comprar`, y
`transferir_desde_cd` debe quedar idéntico (335 tmpl, 0 exceden).

---
## (Histórico) Diagnóstico original — superado por el cierre de arriba

## Síntoma
En `x_analisis_de_stock` (run 2026-06-29), **168 de 461 templates** con traslado
escriben `Σ x_studio_qty_transferir` > `x_studio_stock_central` (stock físico del
CD). Muchos con **pool = 0**:

| Exceso | SKU | Pool CD | Σtransfer | salas |
|---|---|---|---|---|
| +60 | VINO PIPEÑO (9780801379628) | 0 | 60 | 4 |
| +53 | CERVEZA CUSQUEÑA (9958) | 8 | 61 | 4 |
| +48 | ENERGÉTICA (798190181738) | 31 | 79 | 7 |
| +29 | VASO COCA-COLA 350 (8005) | 635 | 664 | 10 |

## Por qué NO es el fair-share (v9.4.0)
`_runout_level_alloc` capea `Σ transfer ≤ available` (= `central_stock_real_map
[tmpl_id]` = lo que se muestra en `x_studio_stock_central`). Con pool=0 devuelve
ceros. Por lo tanto esos traslados los genera **otra ruta**, no el reparto central.
v9.3.1 (cascada) producía el mismo exceso: la cascada también capea al pool.
→ Anomalía estructural **previa**, ortogonal al cambio de reparto.

## Hipótesis a confirmar (Fase 0)
1. **Explosión combo/kit**: un template componente recibe demanda de traslado de
   varios combos padres; el stock del componente en el CD se cuenta una vez pero
   se promete a cada combo. (Ver `shared/combo_explosion.py`, `_apply_kit_stock`.)
2. **Echelon keying**: el stock del CD vive bajo un `tmpl_id` (variante/padre)
   distinto al de la fila escrita → `central_stock_real_map.get(tmpl_id)=0` para
   la fila aunque físicamente exista stock bajo otra clave.
3. **Filas stale**: `HARD_RESET` no reescribió todas las filas y quedaron
   traslados de un run anterior con más stock CD. (Verificable: comparar
   write_date de las filas excedidas vs el run.)

## Riesgo / decisión
`OH Generacion de Documentos.py` podría crear pickings internos por stock que el
CD no tiene. PENDIENTE verificar si el documento recapea contra disponible real
al crearse (si recapea, el exceso es solo cosmético en el análisis; si no, genera
traslados imposibles).

## Próximos pasos
- [ ] Dump de 1 caso pool=0 (VINO PIPEÑO 24185): ver si es combo, y bajo qué
      tmpl_id vive el stock CD real.
- [ ] Confirmar/descartar las 3 hipótesis.
- [ ] Revisar si Generación de Documentos recapea Σtransfer ≤ stock CD disponible.
- [ ] Si es combo/echelon: la asignación central debe agrupar por la MISMA clave
      en que se contabiliza el stock del CD.
