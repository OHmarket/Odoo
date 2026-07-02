# Plan de implementación — Techo de cobertura 30/15 por rotación

> **Para el que ejecuta:** este repo NO tiene pytest/CI. La "prueba" es (a) el diagnóstico
> read-only que ya existe y (b) el BACKTEST de servicio. El código productivo es un
> Server Action (safe_eval): no se corre local, lo pega Marco en Odoo. Promover solo tras
> backtest OK + confirmación explícita de Marco (CLAUDE.md "Sincronización con GitHub").

**Goal:** Poner un techo de días de cobertura (15d si ≥2 cajas/sem, si no 30d) sobre el
order-up-to de sala, para liberar ~$16M de caja inmovilizada sin subir el ROP.

**Arquitectura:** Un solo punto de cambio en `03_stock/OH Analisis de Stock.py`: tras
computar `target_units` (ya con vitrina sumada), aplicar `S = min(target_units, d·cap)`
con piso en `display + safety` para no cortar vitrina ni safety. El ROP y el resto del
pipeline (cola larga, pass-through CD, Fair Share) NO se tocan.

**Tech Stack:** Python safe_eval (Odoo 17 Server Action). Sin imports, sin `fields`,
`.write()` no aplica (esto es cálculo en memoria, no persistencia nueva).

## Global Constraints (verbatim del diseño)

- `K_FAST = 2.0` cajas/sem (tunable por CTX). ≥K → cap 15d; si no → cap 30d.
- Cap SOLO recorta: `S ≤ target_units` siempre. Nunca levanta stock.
- Piso del cap: `display_stock_units + safety_stock_units` (no cortar vitrina ni safety).
- NO tocar: gate `mu≤3` de cola larga, `cola_larga_rop`, ROP, pass-through CD. (Cambios
  separados, versiones futuras — "una versión, un cambio").
- Una sola hipótesis: capar cobertura baja caja con impacto acotado en servicio.

---

### Task 1: Constantes y helper del cap

**Files:**
- Modify: `03_stock/OH Analisis de Stock.py` (bloque de constantes ~215; bloque CTX ~792;
  helpers ~371 junto a `_calc_cola_larga_lote`)

**Interfaces:**
- Produce: `COVER_CAP_FAST_DAYS`, `COVER_CAP_SLOW_DAYS`, `COVER_CAP_K_BOXES_WEEK` (floats)
  y `_cover_cap_days(mu_week, moq)` → float (días de cobertura techo para ese SKU×sala).

- [ ] **Step 1: Agregar constantes DEFAULT** tras la línea 215 (`COLA_PISO_UNIDADES_DEFAULT`):

```python
# Techo de cobertura por rotacion (proyectos/2026-07-01-cobertura-30-15-por-rotacion).
# Cap SOLO recorta el order-up-to; no sube stock. Libera caja del sobrestock de cola.
COVER_CAP_FAST_DAYS_DEFAULT   = 15.0   # >= K cajas/sem -> techo 15d (donde el cash se concentra)
COVER_CAP_SLOW_DAYS_DEFAULT   = 30.0   # resto -> techo 30d
COVER_CAP_K_BOXES_WEEK_DEFAULT = 2.0   # umbral "varias cajas semanales" (PROXY, tunable)
```

- [ ] **Step 2: Agregar overrides CTX** junto a los otros `_safe_float(CTX.get(...))` (~792):

```python
COVER_CAP_FAST_DAYS    = _safe_float(CTX.get('cover_cap_fast_days',    COVER_CAP_FAST_DAYS_DEFAULT),    COVER_CAP_FAST_DAYS_DEFAULT)
COVER_CAP_SLOW_DAYS    = _safe_float(CTX.get('cover_cap_slow_days',    COVER_CAP_SLOW_DAYS_DEFAULT),    COVER_CAP_SLOW_DAYS_DEFAULT)
COVER_CAP_K_BOXES_WEEK = _safe_float(CTX.get('cover_cap_k_boxes_week', COVER_CAP_K_BOXES_WEEK_DEFAULT), COVER_CAP_K_BOXES_WEEK_DEFAULT)
```

- [ ] **Step 3: Agregar helper** junto a `_calc_cola_larga_lote` (~371):

```python
def _cover_cap_days(mu_week, moq):
    # Techo de dias de cobertura por rotacion. >= K cajas/sem -> 15d (rapido, cash
    # concentrado); si no -> 30d. Ver proyectos/2026-07-01-cobertura-30-15-.../diseno.md
    mu  = max(_safe_float(mu_week, 0.0), 0.0)
    moq = max(_safe_float(moq, 1.0), 1.0)
    cajas_semana = mu / moq
    if cajas_semana >= COVER_CAP_K_BOXES_WEEK:
        return COVER_CAP_FAST_DAYS
    return COVER_CAP_SLOW_DAYS
```

- [ ] **Step 4: Verificación de recompute** (sanity, fuera de Odoo). Correr:

Run: `PYTHONPATH="d:/Desarrollo/Odoo" python -c "K=2.0;F=15.0;S=30.0;
def cap(mu,moq):
 c=mu/max(moq,1.0)
 return F if c>=K else S
assert cap(7.8,24)==15.0  # Royal Guard: varias cajas -> 15d
assert cap(5.95,6)==30.0  # Jagermeister max sala ~1 caja -> 30d
assert cap(0.84,6)==30.0
print('cap OK')"`
Expected: `cap OK`

- [ ] **Step 5: Commit** (solo si Marco confirmó que corrió en Odoo — ver Task 3/4).

---

### Task 2: Aplicar el cap al target_units

**Files:**
- Modify: `03_stock/OH Analisis de Stock.py:2184-2191` (bloque tras sumar vitrina, antes
  de `over_target_units`)

**Interfaces:**
- Consume: `target_units`, `demanda_semanal`, `mu_for_target`, `moq`, `display_stock_units`,
  `safety_stock_units`, `reorder_target_weeks`, `financial_ceiling_sku` (todas en scope).
- Produce: `target_units` capado; `cover_cap_days_used` (float, para reporte/debug).

- [ ] **Step 1: Insertar el cap** inmediatamente ANTES de la línea 2191
  (`over_target_units = max(stock_proyectado - target_units, 0.0)`):

```python
# Techo de cobertura por rotacion: S = min(target, d*cap), piso en vitrina+safety.
# SOLO recorta (nunca sube). No toca ROP ni cola larga. Ver proyecto 2026-07-01.
cover_cap_days_used = _cover_cap_days(mu_for_target, moq)
if mu_for_target > DEMAND_FLOOR_WEEK and cover_cap_days_used > 0.0:
    d_daily     = mu_for_target / 7.0
    cap_units   = d_daily * cover_cap_days_used
    piso_cap    = _safe_float(display_stock_units, 0.0) + _safe_float(safety_stock_units, 0.0)
    target_capped = max(min(target_units, cap_units), piso_cap)
    if target_capped < target_units:
        target_units = target_capped
        if mu_for_target > DEMAND_FLOOR_WEEK:
            reorder_target_weeks = _clamp(target_units / mu_for_target, 0.0, financial_ceiling_sku)
```

- [ ] **Step 2: Exponer el cap en el rec** (para inspección). En el dict `rec = {...}`
  (~2329) agregar una clave:

```python
'cover_cap_days_used': cover_cap_days_used,
```

- [ ] **Step 3: Persistir a un campo de debug** en el `.write()`/create de salida
  (~3306, junto a `x_studio_reorder_target_weeks`). SOLO si el campo Studio
  `x_studio_cover_cap_days` existe; si no, saltear este paso (crear campo Studio es
  aparte, fuera de este cambio). Verificar con `ir.model.fields` antes:

```python
'x_studio_cover_cap_days': _safe_float(rec.get('cover_cap_days_used'), 0.0),
```

- [ ] **Step 4: Revisión safe_eval.** Confirmar que no se usó `fields`, `import`,
  `obj.attr=x`, `getattr`. Solo `def`, `min/max`, aritmética, `_clamp`, `_safe_float`
  (todos ya presentes). Usar la skill `odoo-server-action-safe-eval` como checklist.

- [ ] **Step 5: Commit** (condicionado a Task 4).

---

### Task 3: Validación (diagnóstico + backtest)

**Files:**
- Usa: `proyectos/2026-07-01-cobertura-30-15-por-rotacion/diag_impacto_30_15.py` (existe)
- Backtest: `02_forecast/OH Forecast Backtest.py` (motor de validación del repo)

- [ ] **Step 1: Re-correr el diagnóstico read-only** para reconfirmar el delta con K=2:

Run: `PYTHONPATH="d:/Desarrollo/Odoo" python "proyectos/2026-07-01-cobertura-30-15-por-rotacion/diag_impacto_30_15.py"`
Expected: `CAP (techo): ... (delta -9.3%)` total ≈ −$16,0M; Jagermeister 100% 30d.

- [ ] **Step 2: Marco pega el Server Action con el cap en Odoo y lo corre** sobre
  `x_analisis_de_stock`. Confirmar que corre sin error safe_eval y que
  `x_studio_target_units` bajó en los SKU sobrestockeados (spot-check: Cristal Lata,
  Johnnie Walker, hielo — top del ahorro).

- [ ] **Step 3: Backtest de servicio.** Correr el backtest y comparar, en casos
  canónicos (Royal Guard, Cristal Lata = fast→15d; Jagermeister = slow→30d), el nivel de
  servicio (quiebre) ANTES vs DESPUÉS del cap. Aceptar si el ahorro de caja no dispara
  quiebre por sobre el umbral de negocio (Caja > Quiebre, pero el quiebre no debe
  desbordar). Documentar WAPE/BIAS/servicio en `resultados/`.

- [ ] **Step 4: Escribir `resultados/validacion.md`** con: delta caja medido en Odoo
  (target antes/después), delta servicio del backtest, y veredicto promover sí/no.

---

### Task 4: Promoción

- [ ] **Step 1:** Marco confirma explícitamente ("subir"/"dale") tras ver Task 3.
- [ ] **Step 2:** Mostrar los comandos git (add del script productivo + carpeta del
  proyecto) y esperar confirmación verbal (CLAUDE.md).
- [ ] **Step 3:** Commit con mensaje funcional, ej:
  `stock: techo de cobertura 30/15 por rotacion (libera caja de sobrestock de cola)`.
- [ ] **Step 4:** Registrar en `governance/CHANGELOG.md` y actualizar la versión del
  header de `OH Analisis de Stock.py` (v9.6.1 → v9.7.0).

---

## Self-review (cobertura del spec)

- Clasificador rotación (K=2, 15/30): Task 1.
- Cap solo-recorta con piso vitrina+safety: Task 2 Step 1.
- No tocar gate mu≤3 / ROP / pass-through: Global Constraints + Task 2 (inserción aislada).
- Medición caja: Task 3 Step 1-2. Medición servicio/quiebre: Task 3 Step 3 (lo que el
  diagnóstico read-only NO puede ver, per diseño).
- Promoción con confirmación explícita: Task 4.
