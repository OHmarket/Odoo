# Sobre-asignación del CD: traslados > stock físico (combo/echelon keying)

Fecha: 2026-06-29
Estado: **Fase 0 — diagnóstico abierto, NO resuelto**
Detectado validando: `proyectos/2026-06-29-fair-share-cd-salas/` (Fair Share v9.4.0)

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
