# Plan de implementación — Diagnóstico de des-censura por quiebre (Fase 1)

> **Para workers agénticos:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development
> (recomendado) o superpowers:executing-plans para implementar tarea por tarea. Los pasos usan
> checkbox (`- [ ]`) para tracking.

**Goal:** Construir un script de diagnóstico **read-only** que mida cuánto sesgo a la baja introduce
el quiebre en la demanda y calibre los parámetros (`AVAIL_FLOOR`, `CAP`) antes de tocar HM-SI.

**Architecture:** Odoo Server Action (safe_eval) que cruza días de quiebre (`x_stock_balance_daily`)
con ventas POS diarias, construye el perfil weekday (sala base, refinable a categoría/SKU), calcula
la disponibilidad ponderada por (sala, SKU, semana) y reporta distribuciones de calibración. **No
escribe nada productivo** — solo devuelve un `result` dict y loguea.

**Tech Stack:** Odoo 17 EE Server Action (safe_eval: sin `import`, sin `class`, sin `getattr`;
`datetime` y `log()` disponibles), PostgreSQL vía `env.cr.execute`.

---

## Contexto del toolset (leer antes de empezar)

- **No hay pytest.** La "prueba" de cada sección es: ejecutar el Server Action en Odoo e inspeccionar
  el `result` dict (y los `log()` intermedios). Los **invariantes** se computan dentro del script y
  se reportan en `result['invariantes']`.
- **safe_eval:** prohibido `import`, `class`, `getattr`. `datetime` ya está en scope. `log(msg, level=)`
  es función. Usar `env.cr.execute(...)` para SQL y `env['modelo'].sudo()` para ORM.
- **Git:** los comandos se entregan al final; el dueño los corre tras confirmar que el script funcionó.
- **Fuente de verdad del diseño:** `diseno.md` (co-ubicado en esta carpeta de proyecto).

## Estructura de archivos

- Carpeta de proyecto: `proyectos/2026-05-25-normalizacion-demanda/`
  - `diseno.md` — diseño aprobado del cambio.
  - `plan.md` — este plan de implementación.
  - `OH Normalizacion Demanda.py` — script DIAG (Fase 1, read-only).

Cuando la Fase 2 (escritura productiva) esté validada, el script productivo se mueve a
`02_forecast/` y esta carpeta de proyecto queda como historial del cambio.

---

## Task 1: Esqueleto + parámetros + ventana temporal

**Files:**
- Create: `OH Normalizacion Demanda.py`

- [ ] **Step 1: Escribir el bloque de constantes y setup**

```python
# ============================================================
# DIAG des-censura por quiebre (read-only) — Fase 1
# Mide el sesgo a la baja que el stockout introduce en la demanda
# y calibra AVAIL_FLOOR / CAP. NO escribe nada productivo.
# Ver diseno.md (co-ubicado en la carpeta del proyecto)
# ============================================================

VERSION_ID = "DIAG_DESCENSURA_v0_1"
TZ_NAME    = 'America/Santiago'

# Salas (mismas que el resto del pipeline)
FILTERED_TEAM_IDS = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

# Cobertura de x_stock_balance_daily: arranca 2025-01-01
COVERAGE_FLOOR = (2025, 1, 1)
WINDOW_WEEKS   = 52          # ventana de análisis (semanas hacia atrás)

# Parámetros que el diagnóstico ayuda a calibrar (se prueban varios floors)
MIN_CLEAN_DAYS_LEVEL = 20    # días limpios para refinar perfil weekday sala->categ/sku
AVAIL_FLOORS_TO_TEST = [0.20, 0.30, 0.40]
CAP                  = 2.5   # tope al multiplicador de corrección

# SKU de control para spot-check (que el dueño sepa que NO quiebra). 0 = omitir.
CONTROL_SKU_NEVER_STOCKOUT = 0

CTX = (env.context or {})

def _log(msg, *a):
    log((msg % a) if a else msg, level='info')

# HOY local Chile y ventana
env.cr.execute("SELECT (now() AT TIME ZONE %s)::date", (TZ_NAME,))
today_local = env.cr.fetchone()[0]
date_to   = today_local - datetime.timedelta(days=1)          # día cerrado = ayer
floor_d   = datetime.date(*COVERAGE_FLOOR)
date_from = date_to - datetime.timedelta(weeks=WINDOW_WEEKS) + datetime.timedelta(days=1)
if date_from < floor_d:
    date_from = floor_d

result = {'version': VERSION_ID, 'date_from': str(date_from), 'date_to': str(date_to)}
_log('%s: ventana [%s .. %s] teams=%s', VERSION_ID, date_from, date_to, FILTERED_TEAM_IDS)
```

- [ ] **Step 2: Verificar en Odoo (run parcial)**

Ejecutar el Server Action con solo este bloque (cerrar con `result` como valor final o
`raise ValueError(str(result))`).
Esperado: `result` muestra `date_from`/`date_to` coherentes (date_from ≥ 2025-01-01, date_to = ayer).

---

## Task 2: Cargar días de quiebre desde `x_stock_balance_daily`

**Files:**
- Modify: `OH Normalizacion Demanda.py`

- [ ] **Step 1: Query de días de quiebre (full + partial tratados como quiebre, v1)**

```python
# stockout_days[(team_id, product_id)] = set(fechas en quiebre)
# Recordatorio: x_stock_balance_daily SOLO persiste días de quiebre.
env.cr.execute("""
    SELECT x_studio_team_id, x_studio_product_id, x_studio_date
    FROM x_stock_balance_daily
    WHERE x_studio_team_id = ANY(%s)
      AND x_studio_date >= %s AND x_studio_date <= %s
      AND (x_studio_stockout = TRUE OR x_studio_stockout_partial = TRUE)
""", (list(FILTERED_TEAM_IDS), date_from, date_to))

stockout_days = {}
for tid, pid, d0 in env.cr.fetchall():
    if tid is None or pid is None or d0 is None:
        continue
    stockout_days.setdefault((int(tid), int(pid)), set()).add(d0)

result['pairs_con_quiebre'] = len(stockout_days)
result['dias_quiebre_total'] = sum(len(s) for s in stockout_days.values())
_log('%s: pares (sala,SKU) con quiebre=%s | dias-quiebre=%s',
     VERSION_ID, result['pairs_con_quiebre'], result['dias_quiebre_total'])
```

- [ ] **Step 2: Verificar en Odoo**

Esperado: `pairs_con_quiebre` > 0 y `dias_quiebre_total` ≥ `pairs_con_quiebre`. Si es 0, revisar que
`x_stock_balance_daily` tenga datos en la ventana (correr antes `OH Quiebre de Stock.py`).

---

## Task 3: Cargar ventas POS diarias (con combo explosion) y mapa producto→categoría

**Files:**
- Modify: `OH Normalizacion Demanda.py`

- [ ] **Step 1: Detectar combo_parent_id y armar SQL diario**

```python
# ¿existe combo_parent_id? (Odoo v16+). Mismo criterio que sales_reader.
env.cr.execute("""
    SELECT 1 FROM information_schema.columns
    WHERE table_name='pos_order_line' AND column_name='combo_parent_id' LIMIT 1
""")
use_combo = bool(env.cr.fetchone())

date_to_excl = date_to + datetime.timedelta(days=1)
combo_union = ""
if use_combo:
    combo_union = """
        UNION ALL
        SELECT pc.crm_team_id AS team_id, pol.product_id,
               (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS d,
               pol.qty AS qty
        FROM pos_order_line pol
        JOIN pos_order po ON po.id = pol.order_id
        JOIN pos_session ps ON ps.id = po.session_id
        JOIN pos_config pc ON pc.id = ps.config_id
        WHERE po.state IN ('paid','invoiced','done')
          AND po.date_order >= %(dfrom)s AND po.date_order < %(dto)s
          AND pc.crm_team_id = ANY(%(teams)s)
          AND pol.combo_parent_id IS NOT NULL
    """
    standalone_filter = "AND pol.combo_parent_id IS NULL AND pt.type NOT IN ('service','combo')"
else:
    standalone_filter = "AND pt.type NOT IN ('service','combo')"

sql_pos = """
    SELECT team_id, product_id, d, SUM(qty) AS qty FROM (
        SELECT pc.crm_team_id AS team_id, pol.product_id,
               (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS d,
               pol.qty AS qty
        FROM pos_order_line pol
        JOIN pos_order po ON po.id = pol.order_id
        JOIN pos_session ps ON ps.id = po.session_id
        JOIN pos_config pc ON pc.id = ps.config_id
        JOIN product_product pp ON pp.id = pol.product_id
        JOIN product_template pt ON pt.id = pp.product_tmpl_id
        WHERE po.state IN ('paid','invoiced','done')
          AND po.date_order >= %(dfrom)s AND po.date_order < %(dto)s
          AND pc.crm_team_id = ANY(%(teams)s)
          AND pp.active = TRUE AND pt.sale_ok = TRUE
          {standalone_filter}
        {combo_union}
    ) s
    GROUP BY team_id, product_id, d
""".format(standalone_filter=standalone_filter, combo_union=combo_union)

env.cr.execute(sql_pos, {
    'tz': TZ_NAME, 'dfrom': datetime.datetime.combine(date_from, datetime.time.min),
    'dto': datetime.datetime.combine(date_to_excl, datetime.time.min),
    'teams': list(FILTERED_TEAM_IDS),
})

# pos_daily[(team, product)] = { fecha: qty }
pos_daily = {}
for tid, pid, d0, qty in env.cr.fetchall():
    if tid is None or pid is None or d0 is None:
        continue
    pos_daily.setdefault((int(tid), int(pid)), {})[d0] = float(qty or 0.0)

result['pares_pos'] = len(pos_daily)
_log('%s: pares (sala,SKU) con venta POS=%s | use_combo=%s', VERSION_ID, len(pos_daily), use_combo)
```

- [ ] **Step 2: Mapa producto → categoría**

```python
all_pids = list({pid for (_, pid) in pos_daily.keys()} | {pid for (_, pid) in stockout_days.keys()})
product_categ = {}
if all_pids:
    env.cr.execute("""
        SELECT pp.id, pt.categ_id FROM product_product pp
        JOIN product_template pt ON pt.id = pp.product_tmpl_id
        WHERE pp.id = ANY(%s)
    """, (all_pids,))
    for pid, cid in env.cr.fetchall():
        product_categ[int(pid)] = int(cid) if cid else 0
```

- [ ] **Step 3: Verificar en Odoo**

Esperado: `pares_pos` > 0 y del orden de cientos/miles (200 SKU × hasta 12 salas). `use_combo` debe
ser `True` en este Odoo (v17).

---

## Task 4: Perfil weekday (sala base, refinar a categoría/SKU si hay data)

**Files:**
- Modify: `OH Normalizacion Demanda.py`

- [ ] **Step 1: Acumular qty limpia por weekday en los 3 niveles**

```python
# "Día limpio" = día SIN quiebre para ese (team, product).
# wd_* acumulan: clave -> [qty por weekday 0..6], y contar días limpios distintos.
wd_sala       = {}   # team -> [7]
wd_sala_categ = {}   # (team, categ) -> [7]
wd_sala_sku   = {}   # (team, product) -> [7]
cleandays_sala_categ = {}  # (team, categ) -> set(fechas limpias)
cleandays_sala_sku   = {}  # (team, product) -> set(fechas limpias)

def _add7(dct, key, wd, qty):
    arr = dct.get(key)
    if arr is None:
        arr = [0.0]*7
        dct[key] = arr
    arr[wd] += qty

for (tid, pid), day_map in pos_daily.items():
    so = stockout_days.get((tid, pid), set())
    categ = product_categ.get(pid, 0)
    for d0, qty in day_map.items():
        if d0 in so:
            continue  # día contaminado: fuera del perfil limpio
        wd = d0.weekday()
        _add7(wd_sala, tid, wd, qty)
        _add7(wd_sala_categ, (tid, categ), wd, qty)
        _add7(wd_sala_sku, (tid, pid), wd, qty)
        cleandays_sala_categ.setdefault((tid, categ), set()).add(d0)
        cleandays_sala_sku.setdefault((tid, pid), set()).add(d0)
```

- [ ] **Step 2: Normalizar a share (suma=1) y función de selección sala-base-refinar**

```python
def _normalize7(arr):
    tot = sum(arr)
    if tot <= 0.0:
        return None
    return [x / tot for x in arr]

share_sala       = {}
share_sala_categ = {}
share_sala_sku   = {}
for k, arr in wd_sala.items():
    sh = _normalize7(arr)
    if sh: share_sala[k] = sh
for k, arr in wd_sala_categ.items():
    if len(cleandays_sala_categ.get(k, set())) >= MIN_CLEAN_DAYS_LEVEL:
        sh = _normalize7(arr)
        if sh: share_sala_categ[k] = sh
for k, arr in wd_sala_sku.items():
    if len(cleandays_sala_sku.get(k, set())) >= MIN_CLEAN_DAYS_LEVEL:
        sh = _normalize7(arr)
        if sh: share_sala_sku[k] = sh

# Sala base, refinar: el nivel MÁS específico que califica.
def _weekday_share(tid, pid):
    sh = share_sala_sku.get((tid, pid))
    if sh: return sh, 'sku'
    sh = share_sala_categ.get((tid, product_categ.get(pid, 0)))
    if sh: return sh, 'categ'
    sh = share_sala.get(tid)
    if sh: return sh, 'sala'
    return None, 'none'

result['niveles_perfil'] = {'sala': len(share_sala),
                            'sala_categ': len(share_sala_categ),
                            'sala_sku': len(share_sala_sku)}
```

- [ ] **Step 3: Verificar en Odoo**

Esperado: `niveles_perfil['sala']` ≈ 12 (una por sala con venta). `sala_categ` y `sala_sku` > 0. Cada
share de `share_sala` debe sumar ≈ 1.0 (se chequea como invariante en Task 6).

---

## Task 5: Disponibilidad ponderada por (sala, SKU, semana con quiebre)

**Files:**
- Modify: `OH Normalizacion Demanda.py`

- [ ] **Step 1: Agrupar días de quiebre en semanas ISO y calcular `avail`**

```python
def _week_monday(d0):
    return d0 - datetime.timedelta(days=d0.weekday())

# Semana válida = lunes..domingo completamente dentro de [date_from, date_to].
# cells[(team, product, lunes)] = {'avail':x, 'obs':qty_semana, 'level':lvl, 'n_so':k}
cells = {}
for (tid, pid), so_set in stockout_days.items():
    sh, lvl = _weekday_share(tid, pid)
    if not sh:
        continue
    day_map = pos_daily.get((tid, pid), {})
    # agrupar fechas en quiebre por semana
    weeks = {}
    for d0 in so_set:
        weeks.setdefault(_week_monday(d0), set()).add(d0)
    for monday, so_week in weeks.items():
        sunday = monday + datetime.timedelta(days=6)
        if monday < date_from or sunday > date_to:
            continue  # semana parcial en el borde de cobertura -> excluir
        # disponibilidad = share de los días EN STOCK (los 7 menos los en quiebre)
        avail = 0.0
        obs = 0.0
        d = monday
        while d <= sunday:
            wd = d.weekday()
            if d not in so_week:
                avail += sh[wd]
            obs += day_map.get(d, 0.0)
            d += datetime.timedelta(days=1)
        cells[(tid, pid, monday)] = {'avail': avail, 'obs': obs, 'level': lvl,
                                     'n_so': len(so_week)}

result['celdas_semana_con_quiebre'] = len(cells)
_log('%s: celdas (sala,SKU,semana) con quiebre y perfil=%s', VERSION_ID, len(cells))
```

- [ ] **Step 2: Verificar en Odoo**

Esperado: `celdas_semana_con_quiebre` > 0. Todos los `avail` deben quedar en (0, 1] (se valida como
invariante en Task 6).

---

## Task 6: Métricas de calibración + invariantes + run final

**Files:**
- Modify: `OH Normalizacion Demanda.py`

- [ ] **Step 1: Histograma de `avail`, factor de corrección y demanda recuperada por floor**

```python
def _bucket(x):
    if x <= 0.10: return '0.00-0.10'
    if x <= 0.20: return '0.10-0.20'
    if x <= 0.30: return '0.20-0.30'
    if x <= 0.40: return '0.30-0.40'
    if x <= 0.60: return '0.40-0.60'
    if x <= 0.80: return '0.60-0.80'
    return '0.80-1.00'

hist_avail = {}
for c in cells.values():
    b = _bucket(c['avail'])
    hist_avail[b] = hist_avail.get(b, 0) + 1
result['hist_avail'] = hist_avail

# Para cada AVAIL_FLOOR candidato: cuántas celdas se inflan vs caen a fallback,
# y cuánta demanda extra se recupera (con CAP).
calib = {}
for floor in AVAIL_FLOORS_TO_TEST:
    n_inflate = 0; n_fallback = 0
    obs_tot = 0.0; corr_tot = 0.0
    for c in cells.values():
        obs = c['obs']
        obs_tot += obs
        if c['avail'] >= floor:
            n_inflate += 1
            mult = 1.0 / c['avail'] if c['avail'] > 0 else CAP
            if mult > CAP:
                mult = CAP
            corr_tot += obs * mult
        else:
            n_fallback += 1
            corr_tot += obs  # el fallback se mide en Fase 2; aquí no infla
    uplift = (corr_tot / obs_tot - 1.0) if obs_tot > 0 else 0.0
    calib[str(floor)] = {'n_inflate': n_inflate, 'n_fallback': n_fallback,
                         'uplift_demanda_pct': round(uplift * 100, 1)}
result['calibracion_por_floor'] = calib
```

- [ ] **Step 2: SKU crónicamente quebrados + invariantes**

```python
# Crónico = >50% de sus semanas-con-quiebre quedaron bajo el floor medio (0.30)
chronic = 0
for c in cells.values():
    if c['avail'] < 0.30:
        chronic += 1
result['celdas_bajo_0_30'] = chronic

# Invariantes (sanity checks que reporta el propio script)
inv = {}
inv['share_sala_suma_1'] = all(abs(sum(v) - 1.0) < 1e-6 for v in share_sala.values())
inv['avail_en_rango'] = all(0.0 < c['avail'] <= 1.0 + 1e-9 for c in cells.values())
# Spot-check: SKU de control nunca debería aparecer en cells
if CONTROL_SKU_NEVER_STOCKOUT:
    inv['control_sku_sin_correccion'] = not any(
        pid == CONTROL_SKU_NEVER_STOCKOUT for (_, pid, _) in cells.keys())
result['invariantes'] = inv
_log('%s: invariantes=%s | calib=%s', VERSION_ID, inv, calib)
```

- [ ] **Step 3: Ejecutar el script completo en Odoo y validar**

Ejecutar el Server Action completo. Inspeccionar `result`:
- `invariantes.share_sala_suma_1` == True
- `invariantes.avail_en_rango` == True
- (si se fijó `CONTROL_SKU_NEVER_STOCKOUT`) `invariantes.control_sku_sin_correccion` == True
- `calibracion_por_floor` muestra, por cada floor, `uplift_demanda_pct` (cuánta demanda extra se
  recuperaría) y el split inflate/fallback. **Este es el output que calibra `AVAIL_FLOOR` y `CAP`.**
- `hist_avail` muestra dónde se concentra la disponibilidad.

Decisión esperada del dueño tras leer el output: fijar `AVAIL_FLOOR` y `CAP` definitivos para Fase 2.

- [ ] **Step 4: Commit (el dueño lo corre tras confirmar)**

```bash
git add "proyectos/2026-05-25-normalizacion-demanda/"
git commit -m "proyecto: diagnostico read-only de normalizacion de demanda (Fase 1)"
git push
```

---

## Fuera de este plan (planes posteriores)

- **Fase 2 — Implementación:** aplicar la corrección como pre-proceso del input de HM-SI
  (`raw_vals` antes de SMA/SI), con el fallback a semanas limpias vecinas. Se escribe **después** de
  que el diagnóstico fije `AVAIL_FLOOR` y `CAP`.
- **Fase 3 — Backtest comparativo:** medir BIAS/WAPE antes/después en SKU propensos a quiebre vs
  limpios (caso de validación #5 del spec).

---

## Self-review (cobertura vs spec)

- **Perfil weekday sala-base-refinar** → Task 4 (`_weekday_share`). ✓
- **Disponibilidad ponderada** → Task 5. ✓
- **Solo días con quiebre se corrigen; días limpios intactos** → Task 5 (solo itera `stockout_days`). ✓
- **CAP al multiplicador** → Task 6 Step 1. ✓
- **AVAIL_FLOOR calibrable** → Task 6 (prueba varios floors). ✓
- **Quiebre parcial tratado como quiebre (v1)** → Task 2 (incluye `stockout_partial`). ✓
- **Limitación de cobertura 2025-01-01** → Task 1 (`COVERAGE_FLOOR`). ✓
- **POS only (sin facturas)** → Task 3 (solo `pos_order_line`). ✓ (consistente con HM-SI)
- **Fallback vecino** → fuera de Fase 1 (se mide en Fase 2); el diagnóstico solo cuenta cuántas
  celdas lo necesitarían (`n_fallback`). Documentado en Task 6.
- **Marcar imputada** → aplica a Fase 2 (escritura); el diagnóstico no escribe. Documentado.
