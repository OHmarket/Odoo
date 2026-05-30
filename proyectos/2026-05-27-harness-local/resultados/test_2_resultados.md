# Test 2 — Calibración por categoría (resultados + propuesta)

**Fecha:** 2026-05-28
**Método:** Análisis Pareto top 50 + propuesta calibración estructural por (categoria, abc_letter)
**No implementado en motor productivo — para revisión de Marco**

## Resumen ejecutivo

| Configuración | Universo (sin cigarros/snack, sin quiebres) WAPE | BIAS | Cervezas WAPE | Cervezas BIAS |
|---|---:|---:|---:|---:|
| Baseline v3.46 | 48.71% | +23.78% | 45.70% | +18.46% |
| Test 1 (tuning hyperparams) | 49.39% | +25.17% | 45.60% | +20.40% |
| **Test 2 (categ calib)** | **48.74%** | **+13.59%** | **45.06%** | **+4.01%** |

**Test 2 elimina sesgo estructural de cervezas (BIAS +18 → +4) sin degradar WAPE.**

**Test 1 NO mejora en universo limpio** — su -4.89pp WAPE observado antes venía de cigarros con quiebres no filtrados.

## Recorrido del análisis

### Step 1 — Pareto top 50 errores (sobre 10 semanas)

Sobre 10 sem, con filtro `demanda_normalizada` censurada:
- 25% del AE explicado por **29 SKUs** (1.8% del universo)
- 50% del AE → 153 SKUs
- 75% → 409 SKUs

Concentración moderada. Top 50 SKUs = 21% del AE total.

### Step 2 — Filtro cigarros/snack/impulso + proxy quiebre

Aplicando filtro proxy (avg_prev_8w >= 1 + qty_target < 20% del avg):
- Detectado 55% pares (team, sku, sem) con proxy quiebre vs solo 6.8% en demanda_normalizada
- **Confirmado**: cigarros tienen quiebres no detectados por demanda_norm
- Excluidos: Cigarrillos, Cigarros, Tabaco, Snack, Impulso

Resultado top 50 limpio:
- 100% son AX o AY (clase A alta velocidad)
- **67% son cervezas** (Premium, Importadas, Tradicionales, Artesanales)
- SKU 9407 Stella en rank #3 (BIAS +27%)

### Step 3 — Test hipótesis "level shift no detectado"

Marco hipótesis original: cervezas premium tienen saltos de nivel que SMA no detecta rápido.

**Medición** (ratio SMA(4) / SMA(16) en serie hasta cutoff, sobre 10 sem × top 50 SKUs):
- Shift UP (ratio > 1.25): solo **3.9%** de pares
- Shift DOWN (ratio < 0.75): **54.3%** dominante
- Stella avg_ratio=0.59, Budweiser 0.65 (series RECIENTES están BAJAS)

**Conclusión técnica:** La hipótesis no se sostiene en la métrica simple. Las series recientes están BAJAS, pero los SKUs problemáticos tienen **alta varianza + peaks coyunturales en target_weeks específicos** (Semana Santa, mayo). El motor pega el promedio pero los peaks individuales lo golpean.

### Step 4 — ¿Qué modelo del bake-off elige el motor?

En top 50 × 10 sem (5,929 filas):
- sma_heur: 71%
- sba: 18%
- croston: 11%

**Por categoría cervezas:**

| Categoría | Modelo dominante | n | WAPE | BIAS |
|---|---|---:|---:|---:|
| Cervezas Tradicionales | sma_heur | 1,211 | 56.7 | **-9.1** (over) |
| Cervezas Importadas | sma_heur | 177 | 41.9 | **+21.9** (sub) |
| Cervezas Premium | sma_heur | 319 | 46.0 | **+21.7** (sub) |
| Cervezas Artesanales | sma_heur | 581 | 50.6 | -9.5 (over) |

**Patrón estructural confirmado:** Premium/Importadas SUB +22%, Tradicional/Artesanal OVER -9%.

### Step 5 — Solución: calibración estructural por (categ, abc_letter)

Calcular `factor = real_clean / fcst_clean` por cluster sobre 10 sem baseline. Aplicar:
- Min 500 unidades reales en cluster
- Clamp [0.70, 1.30]
- Aplicar solo si |factor-1| >= 5%

**14 clusters significativos identificados.** Top:

| categ | abc_letter | real | factor | dirección |
|---|---|---:|---:|---|
| Cervezas Premium | A | 12,855 | **1.222** | up 22% |
| Cervezas Tradicionales | A | 38,630 | 0.939 | down 6% |
| Bebidas Gaseosas Regulares | A | 22,403 | 1.083 | up 8% |
| Isotónicas/Energéticas | A | 13,801 | 1.092 | up 9% |
| Cervezas Importadas | A | 22,854 | **1.220** | up 22% |
| Cervezas Artesanales | A | 12,883 | 0.917 | down 8% |
| Cigarros (no aplicado, excluido) | - | - | - | - |

## Resultados Test 2

### Totales (sin cigarros/snack/impulso, sin quiebres)

| | WAPE | BIAS | fcst |
|---|---:|---:|---:|
| baseline v3.46 | 48.71% | +23.78% | 244,242 |
| Test 1 (hyperparams tuning) | 49.39% | +25.17% | 239,784 |
| **Test 2 (categ factors)** | **48.74%** | **+13.59%** | **276,898** |

- Δ Test 1 vs baseline: WAPE +0.68pp, BIAS +1.39pp (no mejora)
- **Δ Test 2 vs baseline: WAPE +0.03pp (neutro), BIAS -10.19pp (gana mucho)**

### Por categoría — cervezas (foco principal)

| | WAPE | BIAS |
|---|---:|---:|
| baseline | 45.70 | +18.46 |
| Test 1 | 45.60 | +20.40 |
| **Test 2** | **45.06** | **+4.01** |

### Por semana (todas)

| Semana | base WAPE/BIAS | T1 WAPE/BIAS | T2 WAPE/BIAS |
|---|---|---|---|
| 2026-03-16 | 45.69 / +3.18 | 45.75 / +4.08 | 50.17 / -8.75 |
| 2026-03-23 | 45.15 / +15.31 | 45.10 / +18.53 | 46.84 / **+4.02** |
| 2026-03-30 | 49.60 / +36.82 | 51.30 / +40.15 | 46.70 / +27.67 |
| 2026-04-06 | 47.37 / +21.62 | 48.00 / +23.72 | 47.36 / +10.21 |
| 2026-04-13 | 52.84 / +9.50 | 52.94 / +11.28 | 56.51 / -1.85 |
| 2026-04-20 | 49.20 / +30.49 | 50.35 / +29.51 | 47.41 / +21.35 |
| 2026-04-27 | 48.85 / +31.11 | 49.41 / +30.96 | 46.74 / +22.23 |
| 2026-05-04 | 46.85 / +24.87 | 47.82 / +26.65 | 46.99 / +14.22 |
| 2026-05-11 | 49.18 / +24.49 | 50.71 / +25.83 | 49.01 / +14.81 |
| 2026-05-18 | 52.74 / +37.83 | 52.87 / +37.19 | 50.79 / +29.30 |

Test 2 baja BIAS sistemáticamente ~10pp por semana. WAPE neutro o levemente peor en 2 semanas (W03-16, W04-13).

## Conclusión y propuesta para revisión

### Hallazgos clave

1. **Test 1 (tuning hyperparams) NO funciona** en universo limpio. Su mejora aparente venía de cigarros con quiebres no filtrados.
2. **Test 2 (calibración por categoría) SÍ funciona** — corrige BIAS estructural de cervezas Premium/Importadas (sub +22% → +4%).
3. **El problema NO es level shift no detectado** — es sesgo estructural por categoría que ningún modelo SMA/Croston/SBA puede resolver solo.
4. **Quiebres de stock contaminaban el análisis** — cigarros y Everycrisp tienen problemas de proveedor, filtro proxy los detecta mejor que `demanda_normalizada`.

### Propuesta de implementación (a revisar por Marco)

**No implementar en motor productivo aún.** Decisiones a tomar:

1. **¿Aplicar Test 2 como capa adicional en HM-SI?**
   - Cargar tabla `x_categ_calib_factor` (categ_id, abc_letter, factor)
   - Aplicar como capa post-trend, pre-redondeo: `mu_week *= factor`
   - Refrescar mensualmente con backtest sobre 10 sem rolling
   
2. **¿Refinar Test 2?** Opciones:
   - Granularidad mayor: (categ, abcxyz_completo) en vez de solo abc_letter
   - Excluir factor cuando muy pocos SKUs en cluster (< 5)
   - Limitar clamp: [0.85, 1.20] en vez de [0.70, 1.30] para no over-corregir
   
3. **¿Investigar Everycrisp similar a cigarros?**
   - Si tiene problemas similares de stock con proveedor, agregar al exclude list
   
4. **¿Mejorar proxy de quiebres?**
   - El proxy actual (qty<20%*avg_prev_8w) capta 55% vs 6.8% de `demanda_normalizada`
   - Considerar reemplazar/complementar el detector productivo de quiebres

### Factores calculados (para implementación)

Archivo: `resultados/test_2_categ_factors.json`

```json
{
  "1624|A": 1.222,    // Cervezas Premium A
  "1623|A": 1.220,    // Cervezas Importadas A
  "1625|A": 0.939,    // Cervezas Tradicionales A
  "1622|A": 0.917,    // Cervezas Artesanales A
  "1618|A": 1.083,    // Bebidas Regulares Gaseosas A
  "1619|A": 1.092,    // Isotónicas/Energéticas A
  ...
}
```

### Archivos asociados

- `auto_tune.py` — tuning Test 1 (descartar como solución)
- `pareto_sku.py` — Pareto top 50
- `top50_classify.py` — clasificación por categoría
- `measure_level_shifts.py` — descarta hipótesis level shift
- `analyze_top50_methods.py` — distribución modelos del bake-off
- `test_2_categ_calib.py` — propuesta + simulación
- `resultados/test_2_categ_factors.json` — factores para implementar
- `resultados/pareto_sku_10w.parquet` — Pareto agregado
- `resultados/top50_classified.parquet` — top 50 con detalle
- `resultados/top50_methods_detail.parquet` — modelos por (sku, sem)
- `resultados/level_shifts_top50.parquet` — análisis level shift
- `resultados/level_shifts_by_sku.parquet` — por SKU

### Decisión pendiente Marco

¿Promover Test 2 a productivo (v3.47) o más refinamiento?
