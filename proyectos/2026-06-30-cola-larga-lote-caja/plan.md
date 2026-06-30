# Cola larga: lote por caja autofinanciada — Plan de implementación

> **Para workers:** SUB-SKILL REQUERIDA: usar superpowers:subagent-driven-development o
> superpowers:executing-plans para ejecutar tarea por tarea. Los pasos usan checkbox `- [ ]`.

**Goal:** Reemplazar el goteo semanal de traslado CD→sala en la cola larga (mu ≤ 3/sem)
por una política (s, S) de lote mínimo: caja entera autofinanciada o fracción mensual,
con disparo por ROP bajo. Cadencia ~mensual emergente por local.

**Architecture:** Una función pura nueva (`_calc_cola_larga_lote`) calcula el order-up-to
S y el ROP por (sala, SKU). En la rama `solo_bodega` del loop principal se sobrescribe
`target_units` con S para SKUs gated; un gate por ROP sobre `qty_neta_pre` suprime el
traslado hasta que el stock drena al ROP (evita goteo). Resto del pipeline (fair-share,
cover_label, compra CD) intacto.

**Tech Stack:** Python en `ir.actions.server` bajo safe_eval (Odoo 17). Sin pytest/CI:
el helper es PURO → test local con asserts (`python`); la integración se valida con
diagnóstico read-only XML-RPC (`shared/odoo_xmlrpc.py`) y corrida en Odoo por Marco.

## Global Constraints

- **safe_eval:** no `import`, no `fields`, no `getattr`, no `obj.attr=x`. Usar `.write()`,
  `datetime.date.today`, `def`/`lambda` permitidos. (skill `odoo-server-action-safe-eval`).
- **Una versión, un cambio.** Esta versión SOLO toca el traslado CD→sala de la cola larga.
- **No tocar la compra al proveedor** ni el fair-share (Rule C) ni la compra consolidada CD.
- **PROXY documentado:** plazo de pago global (45d), no por proveedor → marcar en header.
- **mu es por (sala, SKU):** el gate y el lote se evalúan con `mu_for_target` de cada fila.
- Mantener el archivo productivo `03_stock/OH Analisis de Stock.py` como única fuente;
  los scripts de test/diagnóstico viven en `proyectos/2026-06-30-cola-larga-lote-caja/`.

**Parámetros (defaults, tuneables vía CTX):**

| Param | Default | Rol |
|---|---|---|
| `COLA_UMBRAL_WEEK` | 3.0 | gate: `mu_for_target ≤ umbral` entra a la política |
| `COLA_OBJETIVO_DIAS` | 30.0 | cobertura objetivo del lote (dimensiona la fracción) |
| `COLA_PLAZO_PAGO_DIAS` | 45.0 | techo: caja entera si rinde ≤ esto; si no, fracciona |
| `COLA_PISO_UNIDADES` | 1.0 | presencia mínima / piso del ROP |

---

### Task 1: Helper puro `_calc_cola_larga_lote` + test local

**Files:**
- Modify: `03_stock/OH Analisis de Stock.py` (constantes ~134-195; CTX ~780-790; helper tras `_calc_target_units` ~línea 370)
- Test: `proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py` (standalone, copia el helper)

**Interfaces:**
- Produces: `_calc_cola_larga_lote(mu_week, moq, lead_weeks, objetivo_dias, plazo_pago_dias, piso_units) -> (S_units: float, rop_units: float)`
- Consumes: `_safe_float` (ya existe en el script).

- [ ] **Step 1: Escribir el test local que falla**

Crear `proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py`:

```python
# Test standalone del helper de lote de cola larga. Pure-Python, sin Odoo.
# Correr: python proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py

def _safe_float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d

# >>> PEGAR AQUI la version vigente de _calc_cola_larga_lote (Step 3) <<<

def _aprox(a, b, tol=1e-6):
    return abs(a - b) < tol

def run():
    OBJ, PAGO, PISO = 30.0, 45.0, 1.0
    # Caso A: mu=1/sem, caja=6 -> caja rinde 42d (<=45) -> S=caja=6 ; ROP=1 (lead 0)
    S, rop = _calc_cola_larga_lote(1.0, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 6.0), ('A.S', S); assert _aprox(rop, 1.0), ('A.rop', rop)
    # Caso B: mu=2/sem, caja=6 -> caja rinde 21d (<=45) -> S=caja=6
    S, _ = _calc_cola_larga_lote(2.0, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 6.0), ('B.S', S)
    # Caso C: mu=0.5/sem, caja=6 -> caja rinde 84d (>45) -> fraccion floor(0.5*30/7)=2
    S, _ = _calc_cola_larga_lote(0.5, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 2.0), ('C.S', S)
    # Caso D: mu=0.2/sem, caja=6 -> caja rinde 210d (>45) -> floor(0.857)=0 -> piso 1
    S, _ = _calc_cola_larga_lote(0.2, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 1.0), ('D.S', S)
    # Caso E: mu=0 -> sin demanda -> S=0, ROP=0
    S, rop = _calc_cola_larga_lote(0.0, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 0.0) and _aprox(rop, 0.0), ('E', S, rop)
    # Caso F: ROP con lead real 1 semana, mu=2 -> rop = 2*1 + 1 = 3
    _, rop = _calc_cola_larga_lote(2.0, 6.0, 1.0, OBJ, PAGO, PISO)
    assert _aprox(rop, 3.0), ('F.rop', rop)
    print('OK: 6 casos canonicos')

if __name__ == '__main__':
    run()
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py`
Expected: FAIL — `NameError: name '_calc_cola_larga_lote' is not defined`

- [ ] **Step 3: Implementar el helper y pegar en el test**

En `03_stock/OH Analisis de Stock.py`, añadir las constantes junto a las de presentación
(después de `PRESENTATION_PACK = 6`, ~línea 190):

```python
# Politica de cola larga (CD->sala): lote minimo (s,S) por caja autofinanciada.
# Completa hacia abajo la curva de minimos (presentacion solo cubre mu>3/sem).
# Ver proyectos/2026-06-30-cola-larga-lote-caja/diseno.md
COLA_UMBRAL_WEEK_DEFAULT     = 3.0     # gate: mu_for_target <= umbral entra a la politica
COLA_OBJETIVO_DIAS_DEFAULT   = 30.0    # cobertura objetivo del lote (1 mes); dimensiona la fraccion
COLA_PLAZO_PAGO_DIAS_DEFAULT = 45.0    # techo: caja entera si rinde <= esto; sino fracciona. PROXY: global, no por proveedor
COLA_PISO_UNIDADES_DEFAULT   = 1.0     # presencia minima / piso del ROP
```

Añadir las lecturas de CTX junto a las demás (después de `MAX_COVER_WEEKS = ...`, ~línea 785):

```python
COLA_UMBRAL_WEEK     = _safe_float(CTX.get('cola_umbral_week',     COLA_UMBRAL_WEEK_DEFAULT),     COLA_UMBRAL_WEEK_DEFAULT)
COLA_OBJETIVO_DIAS   = _safe_float(CTX.get('cola_objetivo_dias',   COLA_OBJETIVO_DIAS_DEFAULT),   COLA_OBJETIVO_DIAS_DEFAULT)
COLA_PLAZO_PAGO_DIAS = _safe_float(CTX.get('cola_plazo_pago_dias', COLA_PLAZO_PAGO_DIAS_DEFAULT), COLA_PLAZO_PAGO_DIAS_DEFAULT)
COLA_PISO_UNIDADES   = _safe_float(CTX.get('cola_piso_unidades',   COLA_PISO_UNIDADES_DEFAULT),   COLA_PISO_UNIDADES_DEFAULT)
```

Añadir el helper justo después de `_calc_target_units` (después de la línea 370):

```python
def _calc_cola_larga_lote(mu_week, moq, lead_weeks, objetivo_dias, plazo_pago_dias, piso_units):
    # Politica (s,S) de lote minimo para la cola larga, traslado CD->sala.
    # Devuelve (S_units, rop_units).
    #   S (order-up-to): 1 caja entera si la caja rinde <= plazo_pago (autofinanciada,
    #     limpia); si no, fraccion dimensionada al objetivo mensual (~30d). El traslado
    #     interno fracciona caja: el pack/MOQ solo ata la compra al proveedor.
    #   ROP (s): mu*lead + presencia. Lead CD->sala ~0-1d -> ROP ~= piso (dispara casi vacio).
    # PROXY: plazo de pago global (no por proveedor).
    mu   = max(_safe_float(mu_week,    0.0), 0.0)
    moq  = max(_safe_float(moq,        1.0), 1.0)
    piso = max(_safe_float(piso_units, 1.0), 1.0)
    if mu <= 0.0:
        return 0.0, 0.0
    cobertura_caja_dias = (moq / mu) * 7.0
    if cobertura_caja_dias <= max(_safe_float(plazo_pago_dias, 45.0), 1.0):
        S = moq                                                       # 1 caja entera, autofinanciada
    else:
        frac_units = mu * (max(_safe_float(objetivo_dias, 30.0), 1.0) / 7.0)  # ~30d de demanda
        S = max(float(int(frac_units)), piso)                         # floor + piso de presencia
    lead = max(_safe_float(lead_weeks, 0.0), 0.0)
    rop  = mu * lead + piso                                           # ROP = demanda en lead + presencia
    return S, rop
```

Pegar la MISMA función (sin el contexto Odoo) en el bloque marcado del test.

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py`
Expected: PASS — `OK: 6 casos canonicos`

- [ ] **Step 5: Commit**

```bash
git add "03_stock/OH Analisis de Stock.py" proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py
git commit -m "stock: helper de lote de cola larga (s,S) por caja autofinanciada"
```

---

### Task 2: Diagnóstico read-only de impacto (antes de integrar)

Sizea el cambio en producción SIN tocar el pipeline: cuántos (sala, SKU) gated hoy
gotean y cuánto cambiaría el lote/cadencia. Read-only (XML-RPC con whitelist).

**Files:**
- Create: `proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py`

**Interfaces:**
- Consumes: `shared/odoo_xmlrpc.py` (cliente read-only), `_calc_cola_larga_lote` (Task 1, copiado).

- [ ] **Step 1: Escribir el diagnóstico**

Crear `proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py`:

```python
# Read-only: estima impacto del lote de cola larga sobre las filas SALA solo_bodega.
# Lee x_analisis_de_stock vigente (mu, moq, stock, target actual) y proyecta el nuevo
# lote/cadencia. NO escribe. Correr: python proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.odoo_xmlrpc import get_client  # cliente read-only del repo

UMBRAL, OBJ, PAGO, PISO = 3.0, 30.0, 45.0, 1.0

def _safe_float(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d

def _calc_cola_larga_lote(mu_week, moq, lead_weeks, objetivo_dias, plazo_pago_dias, piso_units):
    mu  = max(_safe_float(mu_week, 0.0), 0.0); moq = max(_safe_float(moq, 1.0), 1.0)
    piso = max(_safe_float(piso_units, 1.0), 1.0)
    if mu <= 0.0: return 0.0, 0.0
    if (moq / mu) * 7.0 <= max(_safe_float(plazo_pago_dias, 45.0), 1.0):
        S = moq
    else:
        S = max(float(int(mu * (max(_safe_float(objetivo_dias, 30.0), 1.0) / 7.0))), piso)
    return S, mu * max(_safe_float(lead_weeks, 0.0), 0.0) + piso

def run():
    cli = get_client()
    # Campos minimos; ajustar nombres x_studio_* si difieren (verificar via ir.model.fields).
    fields = ['x_studio_mu_week', 'x_studio_moq', 'x_studio_stock_proyectado',
              'x_studio_target_units', 'x_studio_solo_bodega', 'x_studio_lead_weeks']
    rows = cli.search_read('x_analisis_de_stock',
                           [['x_studio_solo_bodega', '=', True]], fields, limit=20000)
    gated = caja = frac = 0
    for r in rows:
        mu = _safe_float(r.get('x_studio_mu_week'))
        if not (0.0 < mu <= UMBRAL):
            continue
        gated += 1
        moq = _safe_float(r.get('x_studio_moq'), 1.0)
        S, rop = _calc_cola_larga_lote(mu, moq, 0.0, OBJ, PAGO, PISO)
        es_caja = ((moq / mu) * 7.0) <= PAGO
        caja += 1 if es_caja else 0
        frac += 0 if es_caja else 1
        cadencia_dias = (S / mu) * 7.0 if mu > 0 else 0.0
        if gated <= 25:
            print('mu=%.2f moq=%.0f | S=%.1f rop=%.1f | %s | cad~%.0fd | target_hoy=%.1f'
                  % (mu, moq, S, rop, 'CAJA' if es_caja else 'FRAC',
                     cadencia_dias, _safe_float(r.get('x_studio_target_units'))))
    print('\n--- gated=%d | caja_entera=%d | fraccion=%d ---' % (gated, caja, frac))

if __name__ == '__main__':
    run()
```

- [ ] **Step 2: Correr el diagnóstico**

Run: `python proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py`
Expected: imprime ~25 filas de muestra + totales `gated / caja_entera / fraccion`.
Verificar a ojo: SKUs ~1u/sem hoy → CAJA con cadencia ~30-45d; SKUs <0.5/sem → FRAC ~1-2u.
Confirmar que los nombres de campo `x_studio_*` existen (si falla, inspeccionar
`ir.model.fields` de `x_analisis_de_stock` y corregir `fields`).

- [ ] **Step 3: Commit**

```bash
git add proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py
git commit -m "stock: diagnostico read-only de impacto del lote de cola larga"
```

---

### Task 3: Integrar en la rama solo_bodega (target = S) + gate por ROP

**Files:**
- Modify: `03_stock/OH Analisis de Stock.py` — rama `solo_bodega` (~2140-2149), `qty_neta_pre` (~2205), header de versión (~línea 4-6).

**Interfaces:**
- Consumes: `_calc_cola_larga_lote` (Task 1), `COLA_*` (Task 1), variables del loop
  `mu_for_target`, `moq`, `lead_weeks`, `stock_proyectado`, `solo_bodega`, `target_units`,
  `safety_stock_units`, `reorder_target_weeks`.

- [ ] **Step 1: Override del target para SKUs gated (rama solo_bodega)**

> ⚠️ ANCLAR POR CONTENIDO, no por número de línea (Task 1 corrió las líneas). El override
> va DESPUÉS de que termina TODA la cadena `if solo_bodega: / elif / else:` de cálculo de
> target — NO entre el `if` y el `elif` (eso sería SyntaxError). Punto de inserción exacto:
> inmediatamente DESPUÉS de la línea `reorder_target_weeks = _clamp(reorder_target_weeks,
> 0.0, financial_ceiling_sku)` (último renglón del bloque `else:` de fallback) y ANTES del
> comentario `# Piso de exhibicion (presentation stock) -- ADITIVO.`. Ahí `target_units`,
> `safety_stock_units` y `reorder_target_weeks` ya están definidos en todas las ramas.

Insertar (respetar la sangría de 24 espacios del loop por (team, SKU)):

```python
                        # v9.6.0: cola larga -> lote minimo (s,S) por caja autofinanciada.
                        # Solo solo_bodega y mu <= umbral. Order-up-to = caja/fraccion ~mensual;
                        # el gate por ROP (mas abajo) evita el goteo semanal. Ver
                        # proyectos/2026-06-30-cola-larga-lote-caja/diseno.md
                        cola_larga_rop = None
                        if solo_bodega and DEMAND_FLOOR_WEEK < mu_for_target <= COLA_UMBRAL_WEEK:
                            _cl_S, _cl_rop = _calc_cola_larga_lote(
                                mu_for_target, moq, lead_weeks,
                                COLA_OBJETIVO_DIAS, COLA_PLAZO_PAGO_DIAS, COLA_PISO_UNIDADES)
                            if _cl_S > 0.0:
                                target_units         = _cl_S
                                safety_stock_units   = 0.0
                                reorder_target_weeks = _cl_S / mu_for_target
                                cola_larga_rop       = _cl_rop
```

> Nota: `cola_larga_rop` debe quedar inicializado a `None` también cuando NO es gated,
> porque se referencia más abajo. La línea `cola_larga_rop = None` arriba lo cubre
> (se ejecuta en cada iteración antes del `if`). El bloque va dentro del nivel de
> indentación del loop por (team, SKU) — respetar las 24 espacios de sangría existentes.

- [ ] **Step 2: Gate por ROP sobre qty_neta_pre (suprime el goteo)**

Localizar por contenido la línea `qty_neta_pre = max(target_units - stock_proyectado, 0.0)`
(hay una sola; actualmente ~línea 2241). Insertar INMEDIATAMENTE DESPUÉS (antes de la
línea siguiente `qty_buy_pre = (_smart_moq_box_or_wait(...`):

```python
                        # v9.6.0: cola larga (s,S) -> solo transferir cuando el stock cae
                        # al ROP; si esta por encima, dejar drenar el lote (cadencia ~mensual,
                        # no goteo semanal). Al disparar, refilla al lote completo S.
                        if cola_larga_rop is not None and stock_proyectado > cola_larga_rop:
                            qty_neta_pre = 0.0
```

- [ ] **Step 3: Actualizar header de versión**

En el header del archivo (~línea 4-6), añadir el bloque v9.6.0 arriba del v9.5.0:

```python
# v9.6.0 (2026-06-30): cola larga -> lote minimo (s,S) por caja autofinanciada en el
#   traslado CD->sala. Para SKU solo_bodega con mu_for_target <= COLA_UMBRAL_WEEK (3/sem):
#   order-up-to S = 1 caja entera si la caja rinde <= COLA_PLAZO_PAGO_DIAS (45d,
#   autofinanciada), si no fraccion ~COLA_OBJETIVO_DIAS (30d). ROP = mu*lead + presencia
#   (~1u); el traslado se suprime mientras stock > ROP -> drena el lote antes de reponer
#   (cadencia ~mensual emergente por local, elimina el goteo de 1u/sem). El pack solo ata
#   la compra; el traslado interno fracciona. No toca compra a proveedor ni fair-share.
#   PROXY: plazo de pago global. Tuneable: cola_umbral_week, cola_objetivo_dias,
#   cola_plazo_pago_dias, cola_piso_unidades. Ver proyectos/2026-06-30-cola-larga-lote-caja/
```

- [ ] **Step 4: Re-correr el diagnóstico de impacto (sanity, sigue read-only)**

Run: `python proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py`
Expected: mismos totales que en Task 2 (el diag no depende del script productivo; sirve
de checklist de que las cifras proyectadas siguen sanas). Confirmar que ningún SKU gated
proyecta `S` mayor a 1 caja ni cadencia > 45d en la rama CAJA.

- [ ] **Step 5: Verificación en Odoo (manual, la corre Marco)**

Marco pega la v9.6.0 en el Server Action y la ejecuta en Odoo. Inspeccionar en
`x_analisis_de_stock` 3-5 SKUs gated conocidos (los ~1u/sem de la queja original):
- `x_studio_qty_transferir` = 0 cuando `stock > ROP` (no gotea), y = lote (~caja/fracción)
  cuando cayó al ROP.
- `x_studio_target_units` ≈ S (caja o ~30d), no el ~2 sem viejo.
- `cover_label` = `normal` justo tras un traslado (no `exceso` falso).
Sin confirmación explícita de Marco ("corrió", "ok", "subir"), NO commitear el cambio
productivo de este Step.

- [ ] **Step 6: Commit (tras confirmación de Marco)**

```bash
git add "03_stock/OH Analisis de Stock.py"
git commit -m "stock: lote minimo de cola larga (s,S) por caja autofinanciada en traslado CD->sala"
```

---

## Self-Review

**Cobertura del spec (diseño.md):**
- Gate `mu ≤ 3/sem` → Task 3 Step 1 (`DEMAND_FLOOR_WEEK < mu_for_target <= COLA_UMBRAL_WEEK`). ✓
- Lote: caja ≤45d / fracción ~30d → Task 1 helper + Task 1 tests A–D. ✓
- Disparo ROP por local emergente → Task 3 Step 2 (gate `stock_proyectado > cola_larga_rop`). ✓
- mu por (sala, SKU) → se usa `mu_for_target` de cada fila. ✓
- Coherencia cover_label (C = lote) → Task 3 Step 1 (`reorder_target_weeks = S/mu`). ✓
- No tocar compra/fair-share → la lógica solo altera `target_units` y `qty_neta_pre` de
  filas SALA solo_bodega; el fair-share consume `qty_neta_pre_central` aguas abajo. ✓
- Plazo de pago global (PROXY) → header + comentario helper. ✓

**Placeholder scan:** sin TBD/TODO; todo el código está completo. El único "PEGAR AQUI"
es una instrucción explícita de copiar el helper del Step 3 al test (función idéntica). ✓

**Type consistency:** `_calc_cola_larga_lote(mu_week, moq, lead_weeks, objetivo_dias,
plazo_pago_dias, piso_units) -> (float, float)` — misma firma en helper, test y diag. La
variable `cola_larga_rop` se define en Step 1 y se consume en Step 2. ✓

**Bordes pendientes de vigilar en la corrida:** (a) si `demanda_semanal > 3` pero
`mu_for_target ≤ 3` (caso raro share-based), el gate usa `mu_for_target` y el display
(gate sobre `demanda_semanal`) podría sumar — improbable en la cola; revisar en Step 5.
(b) Sala en sin_stock con demanda real: `stock_proyectado ≤ ROP` → transfiere el lote
completo (no difiere), correcto.
