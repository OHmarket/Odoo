# Harness local HM-SI

## Problema

El ciclo de tuning del motor productivo era lento y riesgoso:
1. Editar `02_forecast/HM SI Forecast.py` en PC
2. Copy/paste a la Server Action en Odoo
3. Disparar SA: corre 5-20 min, consume CPU del servidor
4. Esperar export CSV manual
5. Correr analisis local
6. Iterar

A veces el motor mataba el server. Cada iteracion: 30-60 min.

## Solucion

Mirror del motor en PC, sobre snapshot de datos (parquet). Iteracion: 3 seg. Cero riesgo al server.

Cuando un cambio cumple criterio en local, se promueve manualmente al motor productivo.

## Componentes

- `snapshot_cache.py` - pull one-shot de Odoo a parquet
- `process_pos_weekly_csv.py` - procesa CSV exportado a parquet (con mojibake fix)
- `HM_SI_local.py` - mirror del motor productivo, lee parquet (1136 lineas)
- `compare_parity.py` - valida que local da los mismos numeros que productivo
- `local_backtest.py` - corre N semanas x N configs, mide WAPE/BIAS

## Estado final 2026-05-27

### Cache local (~13 MB)

```
cache/
├── pos_weekly.parquet           1.4 MB   (581K filas POS weekly v12 COMBO_EXPLODE)
├── catalog_products.parquet      89 KB
├── catalog_categories.parquet     7 KB
├── catalog_teams.parquet          2 KB
├── catalog_pos_configs.parquet    3 KB
├── abcxyz.parquet                77 KB   (2,029 SKUs clasificados)
├── price_corr.parquet            28 KB   (786 productos con factor)
├── demanda_norm.parquet         1.0 MB
└── hmsi_prod.parquet            1.3 MB   (20,426 filas x_hm_si_forecast productivo)
```

### Motor productivo replicado: Bloques A-G

| Bloque | Componente | Estado |
|---|---|---|
| A | classify_series_type + infer_lifecycle + assign_regimen | OK (copia exacta) |
| B | Croston + SBA + select_best_model (bake-off 4 modelos) | OK |
| C | route_forecast_scope (Z1/Z2/Z3/Z4) v3.46 sin threshold mu<2 | OK |
| D | trend correction v3.43 (factor por team YoY 8sem asimetrico) | OK |
| E | detector precio (correccion_factor) | OK |
| F | SI local_categ (priority: local_categ > categ_global > global) | OK |
| G | fair share canonico v3.42 (rescate SKUs A/B sin venta local) | OK |

### Flujo replicado

```
serie_weekly (cache POS)
   |
   v
[bake-off Croston/SBA/heur/sn_52] -> mu_base
   |
   v
[SI factor] -> mu_week_post_si
   |
   v
[router by ABCXYZ + lifecycle + mu] -> forecast_zone, model_code
   |
   v
[fair_share si mu==0 y A/B] -> rescate mu_fs
   |
   v
[correccion_factor precio] -> mu_pre_trend
   |
   v
[trend_factor team] -> mu_week final
```

### Decision clave: ABCXYZ global desde archivo

En lugar de recalcular clasificacion local desde la serie (que daba divergencias),
el mirror **usa `x_calculo_abc_xyz` directamente** del archivo `abcxyz.parquet`:
- `abcxyz_eff` = global (AX, AY, AZ, etc)
- `series_type_eff` = global (smooth, erratic, lumpy, intermittent, no_signal)
- `lifecycle_eff` = global (mature, declining, seasonal, etc)
- `regimen_eff` = recalculado con los efectivos

La clasificacion local sigue computandose para auditoria (`series_type_local`,
`lifecycle_local`, `xyz_local`) pero NO entra al routing.

### Paridad con productivo (cutoff 2026-05-17, target W21)

- 15,494 SKUs matcheados entre local y productivo (de 20,426 prod / 15,747 local)
- diff < 0.01 mu_week: 17.6%
- diff < 0.10 mu_week: 37.9%
- **diff < 0.50 mu_week: 73.8%**
- diff > 1.00 mu_week: 15.0%
- median diff: 0.18 unidades

**Divergencia restante**: el bake-off elige distinto modelo en algunos SKUs (ej.
SKU 20907 Quilmes: local `seasonal_naive_52`, prod `sba_015`). Causa probable:
ventana de input al bake-off diferente entre productivo y local.

**Para A/B testing relativo** (caso de uso de Marco): paridad suficiente. Los
efectos relativos (config A vs config B en el mismo SKU) son consistentes.

**Para validacion absoluta**: re-correr en server al final.

## Uso

### Snapshot inicial (~5 min, hecho 2026-05-27)

```powershell
python "proyectos/2026-05-27-harness-local/snapshot_cache.py" --only catalog
python "proyectos/2026-05-27-harness-local/snapshot_cache.py" --only abcxyz
python "proyectos/2026-05-27-harness-local/snapshot_cache.py" --only price
python "proyectos/2026-05-27-harness-local/snapshot_cache.py" --only demanda
# pos_weekly: export CSV desde Odoo + process_pos_weekly_csv.py
```

### Correr mirror para 1 cutoff (~3 seg)

```powershell
python "proyectos/2026-05-27-harness-local/HM_SI_local.py" 2026-05-17
```

Output: `resultados/forecast_local_2026-05-17.parquet` con 15K forecasts.

### Compare con productivo (~2 seg)

```powershell
python "proyectos/2026-05-27-harness-local/compare_parity.py"
```

### Backtest multi-config (5 configs x 3 cutoffs, ~45 seg)

```powershell
python "proyectos/2026-05-27-harness-local/local_backtest.py"
```

Edit `configs` list in the file to test variants.

## Cron productivo

Ver `04_analitica/OH Analisis Ventas SKU.py` (limpio v12 COMBO_EXPLODE):
- Soporta `run_mode='backfill_chunked'` con cursor en `ir.config_parameter`
- Para mantener tabla al dia: `{"run_mode": "last_closed"}` interval 1 dia
- Backfill completo (~17 meses) corrido 2026-05-27, 607K filas v12

## Trabajos futuros

1. **Tuning SKU 9407 (Stella 660)**: usar el harness para probar variantes de
   SMA short/long, trend, SI que capturen el nivel reciente alto. Sin tocar server.
2. **Validacion paridad mas profunda**: investigar divergencias del bake-off en
   SKUs con seasonal_naive vs sba.
3. **Refresh semanal del cache**: re-export CSV de x_pos_week_sku_sale + re-pull
   abcxyz/price_corr cuando se quieran incluir semanas nuevas.

Detalles plan original: `~/.claude/plans/vamos-con-backtest-quiero-squishy-starlight.md`
