# Promoción a producción — capa demand sensing

Estado: **validado en backtest, NO promovido.** Sigue el flujo de sync de CLAUDE.md
(usuario crea/pega/corre, confirma "corrió", recién ahí git).

## Evidencia (read-only, reproducible)
- `gate_vs_base.py` — gate vs motor actual (Forecast Base): solo-evento limpio −1.86pp,
  ds-activo limpio −2.87pp. 72 cervezas evento, 8 semanas, 3% quiebre.
- `validar_layer_pcorr.py` — camino de datos LIVE de la SA (trigger x_price_coreccion):
  solo-evento limpio −1.43pp, ds-activo limpio −2.05pp. **Reproduce el gate.**
- `validar_layer.py` — control negativo: con trigger x_price_change_event el ds es
  net +1.9pp (peor). Confirma que el trigger correcto es x_price_coreccion.

## Pasos de promoción (en orden)
1. **Studio**: crear campo `x_studio_mu_week_adjusted` (Float) en `x_hm_si_forecast`.
   Hasta que exista, la SA no escribe y Stock cae a `mu_week` base (sin efecto).
2. **Server Action nueva** `OH Demand Sensing`: pegar `OH Demand Sensing.py`.
   - Encadenar en el cron del pipeline DESPUÉS de OH Forecast Base y ANTES de
     OH Analisis de Stock.
   - Revisar `ref_lock_keys` y asignar un LOCK_KEY nuevo si se agrega advisory lock.
3. **Patch Stock** (ya aplicado en repo, `03_stock/OH Analisis de Stock.py`):
   - `fwd_read_fields` incluye `x_studio_mu_week_adjusted`.
   - `mu_week` lee `COALESCE(adjusted, base)`.
   - Backward-compatible: si el campo no existe, se filtra y usa base.
4. **Correr 1 semana** y revisar el log de la SA:
   `ds_activos`, `filas_ajustadas`, `flag`, `quiebre`. Comparar compra de los SKU
   ajustados vs lo que habría comprado con base.
5. **Backtest** (opcional): leer `x_studio_mu_week_adjusted` en OH Forecast Backtest
   para medir la capa en el backtest live semana a semana.

## Parámetros de la SA (apagables)
- `DS_ENABLED=True` (master switch). `DS_CATEG_LIKE='Cerveza'` (solo cervezas).
- `CONF_DAYS=7`, `QB_SALAS=3`, `EVENT_LOOKBACK_DAYS=365`, factor acotado [0.2, 5.0].

## Caveats
- **PROXY** factor por producto repartido proporcional a cada team (señal diaria por
  team es rala). Re-suma exacto al nivel-producto validado.
- **Solo cervezas.** Ampliar a destilados/otros requiere nuevo gate (los destilados de
  evento aparecen en el monitor de Fase 1 pero no están validados).
- **Doble corrección**: el motor actual NO consume `x_price_coreccion.factor_corr`. Si se
  reactiva, esta capa lo duplicaría. Coordinar.
- La mejora es acotada: ~13% del impacto-$ del catálogo (bucket evento), −1.4/−2pp WAPE
  limpio en ese subconjunto. Alto valor por SKU, no mueve el WAPE global.
