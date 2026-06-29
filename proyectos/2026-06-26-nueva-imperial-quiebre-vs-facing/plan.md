# Plan de implementación — piso de exhibición (floor AX bebidas)

Ver `diseno.md`. Cambio único, controlado, en `03_stock/OH Analisis de Stock.py`.

## Tareas

1. **Crear campo en Studio (manual, fuera del script):**
   `x_analisis_de_stock.x_studio_stock_minimo` (Float, "Stock Mínimo Exhibición").

2. **Parámetros nuevos en el header del script** (reemplazan el bloque
   `DISPLAY_STOCK_*` apagado, líneas ~144-167):
   - `PRESENTATION_ENABLED_DEFAULT = True`
   - `PRESENTATION_DAYS_DEFAULT = 2`
   - `PRESENTATION_FLOOR_BY_FORMATO = {'lata':6,'vidrio':4,'pet':3,'sin_formato':3}`
   - `PRESENTATION_PACK_FLOOR = 1`  # packs: 1 pack (pendiente confirmar 1 vs 2)
   - `PRESENTATION_ABCXYZ_ALLOWED = ('AX',)`
   - `PRESENTATION_CATEG_IDS = [1621, 1614]`  # cervezas + gaseosas (corte inicial)

3. **Función `_calc_stock_minimo(...)`** (reemplaza `_calc_display_stock_units`,
   línea ~285): `stock_minimo = max(DAYS/7·demanda_semanal, floor_formato)`;
   floor_formato = pack-floor si es pack, si no el de formato. Devuelve 0 si:
   - no habilitado, o abcxyz ∉ AX, o categ ∉ bebidas frías, o team ∈ {26,2}.
   - Necesita: `x_studio_formato` y categ del template, y flag pack (regex `\dX\d`).

4. **Aplicar el FLOOR en `_calc_target_units` (línea ~296):**
   `target_units = max(target_units, stock_minimo)`. Es `max`, NO suma.
   Recalcular `target_weeks`/cover labels coherentes con el target final.

5. **Persistir** `stock_minimo` en el `.write()`/`create()` de
   `x_analisis_de_stock` (campo `x_studio_stock_minimo`).

6. **No romper packs phantom ni CD pass-through:** el floor es post-target, no
   toca routing solo_bodega ni la lógica de transferencia. El CD (team 26) recibe
   stock_minimo=0, así que el diferencial consolidado no cambia.

## Validación (dry-run antes de promover)

- Correr el script con el floor sobre Nueva Imperial + 2 salas.
- Confirmar casos canónicos (diseno.md §6): Cristal 0.0 sube a 6; Torobayo +0;
  CD/Web y no-bebida en 0.
- Medir Δ qty_a_pedir / qty_transferir y valorizar el incremental real (debe
  rondar +$155K en AX bebidas; si se dispara, revisar que sea `max` y no suma).
- Verificar que ningún AX bebida quede con stock_minimo > 1 pack salvo los de
  alto volumen (donde manda días·demanda).

## Pendientes (no bloquean el corte AX)

- Valor del piso de packs (1 vs 2).
- Ampliar universo a energéticas/aguas/lácteos fríos (otra fase).
- Exactitud del incremental corriendo el motor completo (con MOQ/redondeos).
