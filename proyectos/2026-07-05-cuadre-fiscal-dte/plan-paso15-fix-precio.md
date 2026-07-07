# PASO 1.5 — Fix de precio pisado en OH Cuadre Fiscal DTE — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que `OH Cuadre Fiscal DTE` (v0.5→v0.6), tras aplicar la posición fiscal, arregle el precio pisado de las líneas cuya cantidad coincide con el DTE (todo-o-nada, sin postear en la misma corrida) y deje una nota en el chatter cuando no puede cuadrar.

**Architecture:** Se agregan 3 helpers puros a `helpers.py` (parseo de líneas del DTE, cómputo del fix, clasificación del motivo), testeados con `python` sin Odoo. Se integran en el SA safe_eval como un PASO 1.5 entre fpos y posteo, con un savepoint SQL para el "todo-o-nada" y un `message_post` deduplicado para la nota. Todo lo que depende de `env` se valida con `DRY_RUN=True` en Odoo.

**Tech Stack:** Odoo 17 EE `ir.actions.server` (safe_eval), Python puro para los helpers y sus tests. Diseño: `proyectos/2026-07-05-cuadre-fiscal-dte/diseno-paso15-fix-precio.md`.

## Global Constraints

- **safe_eval:** sin `import` (`b64decode`/`datetime` inyectados); usar `.write()`/métodos, NO `obj.attr=x`; retorno en `action`; `x_name` required al `create` en modelos `x_*`. Ref skill `odoo-server-action-safe-eval`.
- **Odoo productivo, sin staging:** nada de `search_read` masivo; el SA arranca `DRY_RUN=True`.
- **No hay pytest/CI:** los tests de helpers son scripts `python` con `assert`, corridos con `python <archivo>`, sin librerías. La validación del SA (código con `env`) es correr `DRY_RUN=True` en Odoo y leer el log.
- **Nunca campo nuevo en `account.move`** (stored en tabla ~17M dispara backfill que satura el POS). La nota va a `mail.message` vía `message_post`.
- **El único write del cuadre sobre la factura**, además de la fpos: `price_unit` + `discount=0` en las líneas elegibles, y la nota interna (solo cuando no cuadra, deduplicada). NO tocar `product_id` ni `quantity`.
- **Fix solo si `qty_odoo == QtyItem`** (`abs(qty - QtyItem) <= 0.001`); redondeo de fracción de pack EXCLUIDO (trampa UoM).
- **Umbral de línea para gatillar fix:** `abs(price_subtotal - MontoItem) > 1.0`.
- **fpos-only se postea en su corrida**; solo las arregladas por precio (`fixed_now`) esperan a la corrida siguiente.
- **Tabaco** (`PROV_TABACO = {'885029000'}`) y **`falta_sku`** siguen fuera del fix y del posteo.
- **Perillas:** `DRY_RUN=True` de arranque, `TOL=2.0`, `BATCH=10`, `MAX_POST=20`, `LOCK_KEY=99123055`.
- **Git:** commits en `proyectos/2026-07-05-cuadre-fiscal-dte/`. La promoción del SA a `06_contabilidad/` y el push solo tras confirmación explícita de Marco de que corrió OK en Odoo (regla del repo).

---

### Task 1: Helper puro `parse_items` — parsear las líneas del DTE

Copia verbatim del detector (`OH Detector Error DTE.py`, ya probado allá) para tener la fuente de verdad local con test propio. Necesita los auxiliares `_seg` y `_num`.

**Files:**
- Modify: `proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py`
- Modify: `proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`

**Interfaces:**
- Produces:
  - `parse_items(xml: str) -> list[dict]` — cada dict: `{'nombre','codigo','ean','qty','monto','imp'}`, en el orden del XML. `qty`/`monto` son float; el resto str.
  - `_seg(s, o, c) -> str`, `_num(t) -> float` (auxiliares).

- [ ] **Step 1: Escribir el test que falla (agregar a `tests/test_helpers.py`)**

```python
from helpers import parse_items   # agregar al import existente

def test_parse_items():
    xml = (
        '<Detalle><NmbItem>GIN KANTAL</NmbItem>'
        '<CdgItem><TpoCodigo>INT1</TpoCodigo><VlrCodigo>12345</VlrCodigo></CdgItem>'
        '<QtyItem>24</QtyItem><MontoItem>506433</MontoItem><CodImpAdic>24</CodImpAdic></Detalle>'
        '<Detalle><NmbItem>COCA COLA X06</NmbItem>'
        '<CdgItem><TpoCodigo>EAN13</TpoCodigo><VlrCodigo>7801234567890</VlrCodigo></CdgItem>'
        '<QtyItem>0.166666</QtyItem><MontoItem>918</MontoItem></Detalle>'
    )
    items = parse_items(xml)
    assert len(items) == 2
    assert items[0]['codigo'] == '12345'
    assert items[0]['qty'] == 24.0
    assert items[0]['monto'] == 506433.0
    assert items[0]['imp'] == '24'
    assert items[1]['ean'] == '7801234567890'   # EAN va a 'ean', no a 'codigo'
    assert items[1]['codigo'] == ''
    assert items[1]['qty'] == 0.166666
    assert parse_items('') == []

# agregar al bloque __main__:  test_parse_items(); print('OK test_parse_items')
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`
Expected: `ImportError: cannot import name 'parse_items'`

- [ ] **Step 3: Implementar (copiar del detector) en `helpers.py`**

```python
def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def _num(t):
    try:
        return float(t)
    except Exception:
        return 0.0


def parse_items(xml):
    """DTE -> lista de items en orden: nombre/codigo/ean/qty/monto/imp."""
    items = []
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        cod = ''
        ean = ''
        j = 0
        while True:
            ca = blk.find('<CdgItem>', j)
            if ca == -1:
                break
            cb = blk.find('</CdgItem>', ca)
            cblk = blk[ca:cb]
            tpo = _seg(cblk, '<TpoCodigo>', '</TpoCodigo>')
            vlr = _seg(cblk, '<VlrCodigo>', '</VlrCodigo>')
            if vlr:
                if 'EAN' in tpo.upper():
                    ean = vlr
                elif not cod:
                    cod = vlr
            j = cb
        items.append({
            'nombre': _seg(blk, '<NmbItem>', '</NmbItem>'),
            'codigo': cod, 'ean': ean,
            'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
            'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>')),
            'imp': _seg(blk, '<CodImpAdic>', '</CodImpAdic>'),
        })
        i = b
    return items
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`
Expected: `OK test_parse_items` (y los tests previos siguen pasando)

- [ ] **Step 5: Commit**

```bash
git add "proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py" "proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py"
git commit -m "cuadre-fiscal: helper parse_items (lineas del DTE) + test"
```

---

### Task 2: Helper puro `price_fixes` — computar el fix de precio pisado

**Files:**
- Modify: `proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py`
- Modify: `proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`

**Interfaces:**
- Consumes: `_es_flete` (ya existe en `helpers.py`).
- Produces: `price_fixes(odoo_lines, items) -> list[tuple]` — lista de `(line_id, pu_target)`.
  - `odoo_lines`: list de dicts `{'id','name','quantity','price_subtotal','factor'}`, en el mismo orden que `items` (líneas de producto ordenadas por `(sequence, id)`).
  - `items`: salida de `parse_items`.
  - Regla: si conteos no alinean → `[]`. Por línea, incluye `(id, round(monto/qty*factor, 2))` solo si `abs(qty-QtyItem)<=0.001` y `abs(subtotal-monto)>1.0` y no flete y `qty!=0`.

- [ ] **Step 1: Escribir el test que falla (agregar a `tests/test_helpers.py`)**

```python
from helpers import price_fixes

def test_price_fixes():
    items = [{'qty': 24.0, 'monto': 506433.0}, {'qty': 8.0, 'monto': 168781.0}]
    # ambas pisadas (subtotal 0), qty coincide, factor 1.0 (no price_include)
    ol = [{'id': 1, 'name': 'GIN A', 'quantity': 24.0, 'price_subtotal': 0.0, 'factor': 1.0},
          {'id': 2, 'name': 'GIN B', 'quantity': 8.0, 'price_subtotal': 0.0, 'factor': 1.0}]
    assert price_fixes(ol, items) == [(1, 21101.38), (2, 21097.62)]

    # factor price_include (ILA 31,5%): pu se grosea
    ol2 = [{'id': 3, 'name': 'GIN C', 'quantity': 24.0, 'price_subtotal': 0.0, 'factor': 1.315}]
    assert price_fixes(ol2, [{'qty': 24.0, 'monto': 506433.0}]) == [(3, round(506433.0/24*1.315, 2))]

    # redondeo de fraccion de pack (qty 0,17 vs 0,166666) -> EXCLUIDA
    ol3 = [{'id': 4, 'name': 'COCA', 'quantity': 0.17, 'price_subtotal': 939.0, 'factor': 1.0}]
    assert price_fixes(ol3, [{'qty': 0.166666, 'monto': 918.0}]) == []

    # ya cuadra (|subtotal-monto|<=1) -> no toca
    ol4 = [{'id': 5, 'name': 'X', 'quantity': 2.0, 'price_subtotal': 1000.0, 'factor': 1.0}]
    assert price_fixes(ol4, [{'qty': 2.0, 'monto': 1000.5}]) == []

    # flete descuadrado -> no toca (va a cola humana, no es precio pisado)
    ol5 = [{'id': 6, 'name': 'FLETE', 'quantity': 1.0, 'price_subtotal': 500.0, 'factor': 1.0}]
    assert price_fixes(ol5, [{'qty': 1.0, 'monto': 800.0}]) == []

    # conteo distinto (no alineada) -> []
    assert price_fixes([], items) == []
    assert price_fixes(ol, [{'qty': 24.0, 'monto': 506433.0}]) == []

# agregar al __main__:  test_price_fixes(); print('OK test_price_fixes')
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`
Expected: `ImportError: cannot import name 'price_fixes'`

- [ ] **Step 3: Implementar en `helpers.py`**

```python
def price_fixes(odoo_lines, items):
    """Lineas a corregir por precio pisado -> [(line_id, pu_target)].
    odoo_lines: dicts {'id','name','quantity','price_subtotal','factor'} EN ORDEN.
    items: salida de parse_items. Ver diseno §6.
    Excluye a proposito el redondeo de fraccion de pack (qty != QtyItem)."""
    if len(odoo_lines) != len(items) or not items:
        return []
    out = []
    for l, it in zip(odoo_lines, items):
        qty = l['quantity']
        if qty == 0:
            continue
        if abs(qty - it['qty']) > 0.001:          # redondeo/uom -> excluir
            continue
        if abs(l['price_subtotal'] - it['monto']) <= 1.0:   # ya cuadra
            continue
        if _es_flete(l['name']):                   # flete -> cola humana
            continue
        out.append((l['id'], round((it['monto'] / qty) * l['factor'], 2)))
    return out
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`
Expected: `OK test_price_fixes`

- [ ] **Step 5: Commit**

```bash
git add "proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py" "proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py"
git commit -m "cuadre-fiscal: helper price_fixes (fix precio pisado, excluye redondeo) + test"
```

---

### Task 3: Helper puro `motivo_no_cuadra` — clasificar por qué no cuadró (texto de la nota)

**Files:**
- Modify: `proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py`
- Modify: `proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`

**Interfaces:**
- Consumes: `_es_flete` (ya existe).
- Produces: `motivo_no_cuadra(odoo_lines, items, delta) -> str` — uno de `'conteo_lineas'`, `'redondeo_uom'`, `'flete_descuadrado'`, `'residuo'` (primer match gana). `odoo_lines`/`items` como en `price_fixes`; `delta` float (informativo, no cambia la rama).

- [ ] **Step 1: Escribir el test que falla (agregar a `tests/test_helpers.py`)**

```python
from helpers import motivo_no_cuadra

def test_motivo_no_cuadra():
    items = [{'qty': 0.166666, 'monto': 918.0}]
    # conteo distinto
    assert motivo_no_cuadra([], items, 918.0) == 'conteo_lineas'
    # todas las descuadradas tienen qty != DTE -> redondeo
    ol_r = [{'id': 1, 'name': 'COCA', 'quantity': 0.17, 'price_subtotal': 939.0}]
    assert motivo_no_cuadra(ol_r, items, 21.0) == 'redondeo_uom'
    # flete descuadrado
    ol_f = [{'id': 2, 'name': 'FLETE X', 'quantity': 1.0, 'price_subtotal': 500.0}]
    assert motivo_no_cuadra(ol_f, [{'qty': 1.0, 'monto': 800.0}], 300.0) == 'flete_descuadrado'
    # linea con qty que coincide sigue descuadrada -> residuo
    ol_res = [{'id': 3, 'name': 'GIN', 'quantity': 24.0, 'price_subtotal': 0.0}]
    assert motivo_no_cuadra(ol_res, [{'qty': 24.0, 'monto': 506433.0}], 506433.0) == 'residuo'

# agregar al __main__:  test_motivo_no_cuadra(); print('OK test_motivo_no_cuadra')
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`
Expected: `ImportError: cannot import name 'motivo_no_cuadra'`

- [ ] **Step 3: Implementar en `helpers.py`**

```python
def motivo_no_cuadra(odoo_lines, items, delta):
    """Clasifica por que la factura no cuadro (para la nota del chatter).
    Primer match gana. odoo_lines/items en orden (como price_fixes)."""
    if len(odoo_lines) != len(items) or not items:
        return 'conteo_lineas'
    desc = [(l, it) for l, it in zip(odoo_lines, items)
            if abs(l['price_subtotal'] - it['monto']) > 1.0]
    if desc and all(abs(l['quantity'] - it['qty']) > 0.001 for (l, it) in desc):
        return 'redondeo_uom'
    if any(_es_flete(l['name']) for (l, _it) in desc):
        return 'flete_descuadrado'
    return 'residuo'
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py`
Expected: `OK test_motivo_no_cuadra`

- [ ] **Step 5: Commit**

```bash
git add "proyectos/2026-07-05-cuadre-fiscal-dte/helpers.py" "proyectos/2026-07-05-cuadre-fiscal-dte/tests/test_helpers.py"
git commit -m "cuadre-fiscal: helper motivo_no_cuadra + test"
```

---

### Task 4: SA v0.6 — PASO 1.5 (fix de precio con savepoint todo-o-nada)

Integra los helpers en el SA productivo y agrega el PASO 1.5 entre PASO 1 (fpos) y PASO 3 (posteo). El "todo-o-nada" se hace con savepoint SQL. Sin la nota todavía (Task 5). Se valida en Odoo con `DRY_RUN=True` (no hay test local para código con `env`).

**Files:**
- Modify: `06_contabilidad/OH Cuadre Fiscal DTE.py`

**Interfaces:**
- Consumes: `parse_items`, `price_fixes` (copiar de `helpers.py`), `_seg`, `_num`, `_es_flete` (auxiliares).
- Produces: variable `fixed_now` por factura; catálogo `tax_by_id` y `_factor` para el grose price_include.

- [ ] **Step 1: Bump de header y copiar los helpers + catálogo de impuestos**

En `06_contabilidad/OH Cuadre Fiscal DTE.py`, cambiar la primera línea del header a `v0.6` y anotar el PASO 1.5. **Poner `DRY_RUN = True`** (re-validación del nuevo camino; Marco lo pasa a `False` recién cuando el DRY se vea bien).

Tras el bloque de helpers puros existente (después de `es_tabaco`), agregar `_seg`, `_num`, `parse_items`, `price_fixes` (copiados literalmente de `helpers.py`, Tasks 1-2) y `_factor`:

```python
def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f
```

Dentro del bloque `else:` del lock, ANTES del `for (m, td, d0) in lote:`, construir el catálogo una vez:

```python
    _taxes = env['account.tax'].search([('type_tax_use', '=', 'purchase')])
    tax_by_id = {}
    for t in _taxes:
        tax_by_id[t.id] = {'price_include': t.price_include, 'amount': t.amount}
```

- [ ] **Step 2: Insertar el PASO 1.5 en el loop**

En el loop `for (m, td, d0) in lote:`, entre el PASO 1 (fpos, que termina recalculando `delta`) y el PASO 3 (`if abs(delta) > TOL: ... NO cuadra`), insertar:

```python
        # PASO 1.5 — fix de precio pisado (todo-o-nada, savepoint). NO postea esta corrida.
        fixed_now = False
        items = []
        ol = []
        if abs(delta) > TOL:
            xmlm = b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore')
            items = parse_items(xmlm)
            prod_lines = m.invoice_line_ids.filtered(
                lambda x: x.display_type == 'product').sorted(lambda x: (x.sequence, x.id))
            ol = [{'id': l.id, 'name': l.name or '', 'quantity': l.quantity,
                   'price_subtotal': l.price_subtotal,
                   'factor': _factor(l.tax_ids.ids, tax_by_id)} for l in prod_lines]
            fixes = price_fixes(ol, items)
            if fixes:
                by_id = {l.id: l for l in prod_lines}
                env.cr.execute("SAVEPOINT cuadre_fix")
                for (lid, pu) in fixes:
                    by_id[lid].write({'price_unit': pu, 'discount': 0.0})
                env.flush_all()
                new_delta = round(m.amount_total - td, 2)
                if abs(new_delta) <= TOL and not DRY_RUN:
                    env.cr.execute("RELEASE SAVEPOINT cuadre_fix")
                    fixed_now = True
                    delta = new_delta
                    msgs.append('  %s FIX precio %d linea(s) -> cuadra, queda draft'
                                % (m.name, len(fixes)))
                else:
                    env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_fix")
                    m.invalidate_recordset()
                    msgs.append('  %s FIX %d linea(s) -> %s new_delta=%+d%s'
                                % (m.name, len(fixes),
                                   'cuadraria' if abs(new_delta) <= TOL else 'NO cuadra',
                                   new_delta, ' [DRY]' if DRY_RUN else ''))
        if fixed_now:
            continue   # arreglada hoy: se postea la corrida siguiente
```

- [ ] **Step 3: Marco corre el SA en Odoo con `DRY_RUN=True` y comparte el log**

Pegar en `ir.actions.server` (modelo `account.move`, safe_eval). Correr.
Expected en el log:
- Para folios de precio pisado con qty entera (ej. gin `179140148`): `FIX precio N linea(s) -> cuadraria new_delta=0 [DRY]`.
- Para `104046634` (solo redondeo): NO aparece FIX (0 líneas elegibles) → cae en el NO-cuadra del PASO 3.
- **Verificación crítica del savepoint:** como es DRY, NINGUNA factura debe cambiar. Marco confirma en Odoo que ningún `price_unit` quedó modificado tras la corrida (el `ROLLBACK` del DRY debe revertir todo). Si algún precio quedó cambiado en DRY, el orden flush/rollback/invalidate está mal → arreglar antes de seguir.

- [ ] **Step 4: Commit**

```bash
git add "06_contabilidad/OH Cuadre Fiscal DTE.py"
git commit -m "cuadre-fiscal: v0.6 PASO 1.5 fix precio pisado con savepoint todo-o-nada (DRY)"
```

---

### Task 5: SA v0.6 — nota interna en el chatter cuando no cuadra (deduplicada)

**Files:**
- Modify: `06_contabilidad/OH Cuadre Fiscal DTE.py`

**Interfaces:**
- Consumes: `motivo_no_cuadra` (copiar de `helpers.py`, Task 3); `ol`/`items` del PASO 1.5; `delta`.
- Produces: función `ultima_nota_cuadre(m)`; efecto lateral `message_post` en facturas no cuadradas.

- [ ] **Step 1: Copiar `motivo_no_cuadra` y definir `ultima_nota_cuadre`**

Agregar `motivo_no_cuadra` (copiado de `helpers.py`) al bloque de helpers del SA. Y, dentro del `else:` del lock (junto al catálogo `tax_by_id`), definir:

```python
    def ultima_nota_cuadre(m):
        for msg in m.message_ids:            # ordenado por id desc (mas reciente primero)
            body = msg.body or ''
            if '[Cuadre DTE]' in body:
                return body
        return ''
```

- [ ] **Step 2: Postear la nota en la rama "NO cuadra" del PASO 3**

Reemplazar la línea del PASO 3 que hoy dice `if abs(delta) > TOL: ... 'NO cuadra delta=...'` por:

```python
        if abs(delta) > TOL:
            motivo = motivo_no_cuadra(ol, items, delta)
            nota = '[Cuadre DTE] no cuadra %+d vs DTE. Motivo: %s' % (delta, motivo)
            if not DRY_RUN and nota not in ultima_nota_cuadre(m):
                m.message_post(body=nota, subtype_xmlid='mail.mt_note')
            msgs.append('  %s NO cuadra delta=%+d motivo=%s%s'
                        % (m.name, delta, motivo, ' [DRY]' if DRY_RUN else ''))
            continue
```

> Nota: `ol`/`items` fueron poblados en el PASO 1.5 siempre que `abs(delta) > TOL` (misma condición), así que están disponibles aquí. El dedup usa `nota not in body` porque `message_post` envuelve el texto en `<p>…</p>`.

- [ ] **Step 3: Marco corre `DRY_RUN=True` y comparte el log**

Expected:
- `104046634` → `NO cuadra delta=+? motivo=redondeo_uom [DRY]`; en DRY NO se postea la nota (solo se loguearía).
- Ninguna nota creada en DRY (verificar el chatter de un par de folios: sin mensajes `[Cuadre DTE]` nuevos).

- [ ] **Step 4: Commit**

```bash
git add "06_contabilidad/OH Cuadre Fiscal DTE.py"
git commit -m "cuadre-fiscal: v0.6 nota chatter (mail.mt_note) deduplicada cuando no cuadra"
```

---

### Task 6: Rollout controlado — live acotado, cotejar casos, promover

**Files:**
- Modify: `06_contabilidad/OH Cuadre Fiscal DTE.py` (solo perilla `DRY_RUN`)
- Modify: `governance/CHANGELOG.md`

**Interfaces:**
- Consumes: SA v0.6 validado en DRY (Tasks 4-5).

- [ ] **Step 1: Cotejar el DRY contra los casos canónicos**

Con el log de `DRY_RUN=True` sobre el lote del mes, verificar la tabla §10 del diseño:
- gin `179140148`/`179140149` → `FIX ... cuadraria new_delta=0`.
- vino `104036035`/coca `104036085` → `FIX ...` (subconjunto de líneas).
- `104046634` → sin FIX → `NO cuadra motivo=redondeo_uom`.
- Facturas ya cuadradas por fpos → sin FIX, `postearia`.
Si algo no calza, volver a la Task correspondiente. No pasar a live hasta que el DRY sea correcto.

- [ ] **Step 2: Primer lote en vivo**

Marco pone `DRY_RUN = False` (mantener `DO_POST = True`) y corre una vez. Verificar en Odoo:
- las facturas con `FIX ... cuadra, queda draft` quedaron **draft** con el `price_unit` corregido y **NO** posteadas esta corrida;
- las no cuadradas tienen una nota `[Cuadre DTE] ...` en el chatter;
- las limpias fpos-only pasaron a `posted`.

- [ ] **Step 3: Segunda corrida — confirmar el posteo diferido y el dedup**

Correr de nuevo. Verificar:
- las arregladas en la corrida anterior ahora **sí** se postean (ya cuadran, limpias);
- las no cuadradas NO reciben una segunda nota idéntica (dedup) — el chatter no se duplica.

- [ ] **Step 4: Confirmación de Marco + CHANGELOG**

Tras confirmación explícita de Marco de que corrió OK, registrar en `governance/CHANGELOG.md` la v0.6 (PASO 1.5 fix de precio + nota chatter). El SA ya vive en `06_contabilidad/`.

```bash
git add "06_contabilidad/OH Cuadre Fiscal DTE.py" "governance/CHANGELOG.md" "proyectos/2026-07-05-cuadre-fiscal-dte/"
git commit -m "cuadre-fiscal: v0.6 promovida — fix precio pisado + nota chatter"
```

---

## Self-Review (contra el spec)

**Cobertura del spec:**
- PASO 1.5 fix precio (todo-o-nada, savepoint, fix-no-postea) → Task 4. ✓
- Fix solo `qty == QtyItem`, redondeo excluido, factor price_include → Task 2 (`price_fixes`) + Task 4 (`_factor`). ✓
- Umbral línea `>1`, umbral total `TOL=2` → Task 2 + Global Constraints. ✓
- fpos-only se postea; arreglada espera un ciclo (`fixed_now`) → Task 4. ✓
- Nota chatter con motivo + dedup, `mail.mt_note`, sin campo en account.move → Task 3 + Task 5. ✓
- Clasificación humana = detector (cuadre no escribe x_error_dte) → respetado (ninguna Task escribe x_error_dte). ✓
- parse_items reusado del detector; helpers puros testeados → Tasks 1-3. ✓
- Arranca DRY_RUN=True; validación en Odoo → Tasks 4-6. ✓
- Fuera de alcance (anti-clog skip-de-lote, residual ILA) → no hay Task (correcto). ✓

**Placeholder scan:** sin TBD/TODO; todo el código de helpers va completo; los pasos con `env` muestran el código exacto a insertar. ✓

**Type consistency:** `parse_items -> list[dict]` con claves `qty/monto/codigo/ean/nombre/imp`; `price_fixes(odoo_lines, items) -> [(id, pu)]` con `odoo_lines` claves `id/name/quantity/price_subtotal/factor`; `motivo_no_cuadra(odoo_lines, items, delta) -> str`. Las mismas claves se usan al construir `ol` en Task 4. `_factor(tax_ids, tax_by_id)` consistente entre Task 4 y el detector. ✓
