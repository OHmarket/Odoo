# Propuesta de integración: capa `categ_calib_factor` al motor productivo HM-SI

**Estado:** Diseño para revisión. **NO implementado.**
**Versión motor propuesta:** v3.47 (`FWD_v3_47_CATEG_CALIB`)
**Patrón seguido:** análogo a `correccion_factor` (precio) y `trend_factor` (team) — capas multiplicativas existentes.

## 1. Resumen ejecutivo

Test 2 demostró que existe **sesgo estructural por categoría** (Cervezas Premium +22%, Tradicionales -6%) que ninguna de las 2 capas actuales captura. Esta propuesta agrega una **3ra capa multiplicativa** por `(categ_id, abc_letter)`, calculada mensualmente desde backtest histórico, refrescada vía SA y aplicada en el motor entre `correccion_factor` y `trend_factor`.

**Mejora esperada en cervezas:** BIAS +13% → -2% (centrado), WAPE neutro.
**Impacto en universo total:** BIAS +13% → 0%.

## 2. Modelo Studio nuevo: `x_categ_calib_factor`

Crear en Studio (no requiere migración SQL).

| Campo técnico | Tipo | Required | Descripción |
|---|---|---|---|
| `x_name` | Char | sí | Display: "categ=<id>\|abc=<X>\|2026-05-28" |
| `x_studio_categ_id` | M2O `product.category` | sí | Categoría target |
| `x_studio_abc_letter` | Selection `A`/`B`/`C` | sí | Letra ABC del SKU |
| `x_studio_factor_corr` | Float (4 dec) | sí | Factor multiplicativo (clamped) |
| `x_studio_raw_factor` | Float (4 dec) | no | Factor antes del clamp (auditoría) |
| `x_studio_n_real_units` | Float | no | Unidades reales en cluster |
| `x_studio_n_sample_pairs` | Integer | no | n filas en cluster |
| `x_studio_bias_pct_pre` | Float | no | BIAS observado pre-corrección |
| `x_studio_target_week_start` | Date | sí | Lunes del cálculo (alineado backtest) |
| `x_studio_calc_run_id` | Char | no | run_id del SA que calculó |
| `x_studio_active` | Boolean | sí | Default true |

**Constraint lógica** (no Studio constraint):
- Único por `(categ_id, abc_letter, target_week_start)` — un solo factor por cluster por mes.

**Filtros típicos** (motor lee con domain):
- `x_studio_active = True`
- `x_studio_target_week_start <= target_date`
- Tomar el más reciente por (categ_id, abc_letter)

## 3. SA refresh mensual: `OH Calc Categ Calib Factors`

**Script nuevo:** `04_analitica/OH Calc Categ Calib Factors.py`

**Trigger:** cron mensual día 1 a las 02:00. Manual on-demand también.

**Algoritmo (replica `auto_calib_categ.py` del harness):**

```python
1. Determinar ventana 10 sem cerradas previas (hoy - 70 días → hoy - 1 día)
2. Para cada cutoff target_week:
   a. Pull forecast histórico de x_hm_si_forecast con week_start=target
   b. Pull real qty_sold de pos.order.line (mismo SQL que motor productivo)
   c. Detectar quiebres via x_demanda_normalizada + proxy 8w
3. Excluir categorías noise (cigarros, snack, impulso, tabaco) - configurable via constante
4. Agrupar por (categ_id, abc_letter):
   - Filtrar filas con quiebre
   - sum_real, sum_fcst por cluster
5. Para cada cluster con sum_real >= 500:
   - raw_factor = sum_real / sum_fcst
   - clamped = clamp(raw_factor, 0.70, 1.30)
   - Si |clamped - 1.0| >= 0.05 → persistir como factor activo
   - Sino: persistir con factor=1.0 (para auditoría) o no persistir
6. Marcar registros previos del mismo (categ, abc) como active=False
7. Notify con cantidad de factores nuevos
```

**Constantes configurables (header):**
```python
WINDOW_WEEKS = 10
MIN_REAL_UNITS = 500
FACTOR_CLAMP_LOW = 0.70
FACTOR_CLAMP_HIGH = 1.30
APPLY_THRESHOLD = 0.05
EXCLUDE_CATEG_KEYWORDS = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']
```

**Output esperado:** ~10-20 factores activos por mes (14 vimos en Test 2).

## 4. Loader en motor: `_load_categ_calib_context`

**Agregar a `02_forecast/HM SI Forecast.py`** después de `_load_correccion_context` (~línea 1037).

**Patrón idéntico** al loader de precio. Devuelve dict `(categ_id, abc_letter) -> {factor, target_week_start, n_real_units}`.

```python
def _load_categ_calib_context(target_date):
    """v3.47: Lee factores de calibración por (categ_id, abc_letter) desde
    x_categ_calib_factor. Refrescado mensualmente por SA OH Calc Categ Calib.

    Devuelve dict (categ_id, abc_letter) -> {factor, target_week_start}.
    Si modelo no existe (initial deploy), retorna {} silenciosamente.
    """
    out = {}
    model_name = 'x_categ_calib_factor'
    if not target_date:
        return out
    if not _model_exists(model_name):
        return out

    M = env[model_name].sudo()
    cf = M._fields or {}
    catf = _first_m2o_field(M, ['x_studio_categ_id'], 'product.category')
    abcf = _first_field(M, ['x_studio_abc_letter'])
    facf = _first_field(M, ['x_studio_factor_corr'])
    twf = _first_field(M, ['x_studio_target_week_start'])
    activef = _first_field(M, ['x_studio_active', 'active'])
    nrf = _first_field(M, ['x_studio_n_real_units'])

    if not (catf and abcf and facf and twf):
        return out

    domain = [(twf, '<=', target_date)]
    if activef:
        domain.append((activef, '=', True))

    rfields = [catf, abcf, facf, twf]
    if nrf: rfields.append(nrf)

    env.cr.execute('SAVEPOINT categ_calib_lookup')
    try:
        rows = M.search(domain, order='%s desc' % twf).read(rfields)
        env.cr.execute('RELEASE SAVEPOINT categ_calib_lookup')
    except Exception:
        env.cr.execute('ROLLBACK TO SAVEPOINT categ_calib_lookup')
        return out

    for r in rows:
        cv = r.get(catf)
        cid = cv[0] if isinstance(cv, (list, tuple)) else _safe_int(cv, 0)
        letter = _safe_text(r.get(abcf), 1).upper()
        if not cid or letter not in ('A', 'B', 'C'):
            continue
        key = (cid, letter)
        if key in out:
            continue  # ya tenemos el más reciente
        out[key] = {
            'factor': _safe_float(r.get(facf), 1.0),
            'target_week_start': r.get(twf),
            'n_real_units': _safe_float(r.get(nrf), 0.0) if nrf else 0.0,
        }
    return out
```

## 5. Pre-loop init: cargar contexto

En el main loop, **agregar después** del bloque que carga `correccion_ctx` (~línea 1810):

```python
# v3.47: Cargar calibración por categoria × abc_letter
categ_calib_ctx = _load_categ_calib_context(target_date)
categ_calib_applied_count = 0
```

## 6. Aplicación en main loop

**Localización:** entre el bloque `correccion_factor` (termina línea 2315) y la captura `mu_week_pre_bias = mu_week` (línea 2325). Insertar antes de línea 2325 para preservar la semántica de `mu_week_pre_bias` (pre-trend, post-calib).

**Variable ABCXYZ correcta:** el motor productivo expone `abcxyz_local` (línea 2074), NO `abcxyz_eff` (esa variable solo existe en el mirror local del harness). Usar `abcxyz_local`.

```python
# ============================================================
# v3.47 — Categ calibration multiplicativo por (categ, abc_letter)
# Se aplica DESPUES de correccion_factor (precio) y ANTES de
# trend_factor (team) para que:
#  - El factor de categoría amplifique/recorte sobre el forecast
#    ya ajustado por evento de precio
#  - Trend correction (team) ajuste DESPUÉS el resultado por la
#    dinámica YoY del local específico
# Captura sesgo estructural del motor por segmento (categ × abc)
# detectado vía backtest mensual. Clamp simétrico [0.70, 1.30]
# (a diferencia de trend_factor que es asimétrico solo recorta).
# ============================================================
mu_week_pre_calib = mu_week
categ_calib_factor = 1.0
categ_calib_meta = ''
if APPLY_CATEG_CALIB and categ_calib_ctx:
    abc_letter = (abcxyz_local or '')[:1].upper() if abcxyz_local else ''
    if abc_letter in ('A', 'B', 'C') and categ_id:
        cc = categ_calib_ctx.get((int(categ_id), abc_letter))
        if cc and mu_week > 0:
            categ_calib_factor = _safe_float(cc.get('factor'), 1.0)
            if categ_calib_factor != 1.0:
                mu_week = mu_week * categ_calib_factor
                sigma_week = sigma_week * categ_calib_factor
                categ_calib_applied_count += 1
                categ_calib_meta = 'categ=%s|abc=%s|f=%.3f' % (
                    int(categ_id), abc_letter, categ_calib_factor)
```

**Orden resultante en main loop (líneas 2310-2332):**

```text
L2310-2315  correccion_factor (precio)         -> mu_week ajustado
L2316       <NUEVO bloque v3.47>               -> mu_week_pre_calib = mu_week
                                                  mu_week *= categ_calib_factor
L2325       mu_week_pre_bias = mu_week         (pre-trend, post-calib)
L2326-2332  trend_factor (team)                -> mu_week *= trend_factor
```

## 7. Campos persistidos en `x_hm_si_forecast`

**Nuevos campos a crear en Studio** (model `x_hm_si_forecast`):

| Campo | Tipo | Default |
|---|---|---|
| `x_studio_categ_calib_factor` | Float (4 dec) | 1.0 |
| `x_studio_categ_calib_meta` | Char | '' |
| `x_studio_mu_week_pre_calib` | Float | mu_week pre-calibración (auditoría) |

**Persistir en `_put_field` block** (~línea 2390):
```python
_put_field(vals, fwd_fields, 'x_studio_categ_calib_factor', categ_calib_factor)
_put_field(vals, fwd_fields, 'x_studio_categ_calib_meta', categ_calib_meta)
_put_field(vals, fwd_fields, 'x_studio_mu_week_pre_calib', mu_week_pre_calib)
```

## 8. Cambios header

**Línea 66** — bump VERSION_ID:
```python
VERSION_ID = "FWD_v3_47_CATEG_CALIB"
```

**Líneas 16-65** — agregar bullet en "Reglas vivas":
```
- Categ calibration (v3.47): factor multiplicativo por (categ_id, abc_letter)
  calculado mensualmente vía SA OH Calc Categ Calib desde backtest 10 sem.
  Captura sesgo estructural del motor por segmento (Cervezas Premium A
  sub +22%, Cervezas Tradicionales A over -6%, etc.). Clamp [0.70, 1.30].
  Aplicado entre correccion_factor (precio) y trend_factor (team).
  Modelo Studio: x_categ_calib_factor.
```

## 9. Configuración + constantes (header ~línea 130-150)

```python
# v3.47: categ calibration por (categ_id, abc_letter)
APPLY_CATEG_CALIB_DEFAULT = True
```

Lectura en CTX init (~línea 1290):
```python
APPLY_CATEG_CALIB = bool(CTX.get('apply_categ_calib', APPLY_CATEG_CALIB_DEFAULT))
```

Guard del bloque de aplicación:
```python
if APPLY_CATEG_CALIB and categ_calib_ctx:
    ...
```

## 10. Notification post-run

**Agregar al mensaje final** (~línea 2470):
```python
'categ_calib=ON,n=%d' % categ_calib_applied_count if APPLY_CATEG_CALIB else 'categ_calib=OFF',
```

## 11. Plan de rollout

### Fase A — Setup Studio (manual, ~30 min)

1. Crear modelo `x_categ_calib_factor` en Studio con los 11 campos listados arriba.
2. Crear los 3 campos nuevos en `x_hm_si_forecast`.
3. Validar con `fields_get` que se ven via XMLRPC.

### Fase B — SA Calc Factors (~2 hrs implementación + 30 min validación)

1. Implementar `04_analitica/OH Calc Categ Calib Factors.py`.
2. Crear SA en Odoo con el código.
3. Disparar manual una vez. Validar que crea ~10-20 registros.
4. Crear cron mensual día 1 02:00 que dispara la SA.

### Fase C — Motor productivo (~1 hr implementación + 30 min validación)

1. Aplicar 7 cambios al `02_forecast/HM SI Forecast.py`:
   - VERSION_ID
   - Header reglas vivas
   - Constante `APPLY_CATEG_CALIB_DEFAULT`
   - Lectura CTX `APPLY_CATEG_CALIB`
   - Loader `_load_categ_calib_context`
   - Pre-loop carga `categ_calib_ctx`
   - Aplicación en main loop
   - Persistencia de campos nuevos
   - Notify message
2. Copy/paste al SA en Odoo.
3. Disparar SA productivo. Validar notificación: `OK | ... | categ_calib=ON,n=N`.
4. Validar `x_hm_si_forecast` tiene `x_studio_categ_calib_factor` poblado.

### Fase D — Backtest validatorio (~30 min)

1. Disparar `OH Forecast Backtest` con la nueva config motor.
2. Comparar WAPE/BIAS vs corrida previa.
3. Si BIAS baja en cervezas y WAPE no degrada → promover commit a repo.
4. Si degrada → desactivar via context `{"apply_categ_calib": False}` y diagnosticar.

## 12. Rollback

Si la capa rompe algo, **dos vías de rollback inmediato sin tocar código**:

1. **Context override** en el cron del motor:
   ```python
   {"apply_categ_calib": False}
   ```
   → Motor ignora la capa, comportamiento idéntico a v3.46.

2. **Desactivar registros** en `x_categ_calib_factor`:
   ```sql
   UPDATE x_categ_calib_factor SET x_studio_active = false;
   ```
   → Motor sigue cargando contexto vacío, factores=1.0 todos.

**Rollback completo del código:** revertir el VERSION_ID y los 9 cambios al motor. ~10 min.

## 13. Costos / dependencias

| Componente | Tiempo | Riesgo |
|---|---|---|
| Modelo Studio (Fase A) | 30 min | Bajo (additive) |
| SA Calc (Fase B) | 2.5 hrs | Bajo (cron mensual, lock no requerido) |
| Motor (Fase C) | 1.5 hrs | Medio (motor productivo, requires backtest validation) |
| Total | **~4.5 hrs** | |

**Dependencias externas:**
- Ninguna nueva. Reutiliza `x_demanda_normalizada` para filtro de quiebres.
- El SA puede correr en paralelo con el motor (advisory lock no requerido — modelos disjuntos).

## 14. Métricas esperadas post-implementación

| Métrica | Pre v3.46 | Post v3.47 esperado |
|---|---:|---:|
| BIAS total (sin censura) | +13% | -1 a +3% |
| BIAS Cervezas Premium | +22% | -3 a +3% |
| BIAS Cervezas Tradicionales | -9% | -3 a +3% |
| WAPE total | 58% | 58% (neutro) |
| Cobertura factores activos | 0 | ~14 clusters |

## 15. Consideraciones de operación

- **Refresh frecuencia:** mensual es suficiente (cluster patterns son estables). Si quieres detectar shifts más rápido, semanal pero con cost de overhead.
- **Granularidad evolutiva:** si los 14 factores no son suficientes, considerar agregar `(categ_id, abcxyz_completo)` — 6x más granular (~84 factores potenciales). Requiere refresh más cuidadoso.
- **Auditoría:** los campos `raw_factor`, `n_real_units`, `bias_pct_pre` permiten ver POR QUÉ se decidió cada factor y auditar drift mes a mes.

## 16. Archivos asociados

Existentes (referencia):
- `02_forecast/HM SI Forecast.py:967-1037` — `_load_correccion_context` (patrón a copiar)
- `02_forecast/HM SI Forecast.py:2255-2315` — aplicación `correccion_factor` (patrón)
- `02_forecast/HM SI Forecast.py:2317-2332` — aplicación `trend_factor` (patrón)
- `proyectos/2026-05-27-harness-local/test_2_categ_calib.py` — Test 2 que validó la lógica
- `proyectos/2026-05-27-harness-local/resultados/test_2_categ_factors.json` — 14 factores iniciales

Nuevos:
- `04_analitica/OH Calc Categ Calib Factors.py` — SA refresh
- Modelo Studio `x_categ_calib_factor`
- Campos nuevos en `x_hm_si_forecast`

---

**Decisión pendiente:** revisar este diseño + decidir si implementar las 4 fases. Costo total ~4.5 hrs trabajo + 1 mes para acumular datos del primer refresh.
