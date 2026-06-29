# Detector Error DTE v1.1–v1.3 — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) o superpowers:executing-plans. Los pasos usan checkbox `- [ ]`.

**Goal:** Extender `OH Detector Error DTE` para detectar, por línea, código no
identificado (con recomendación), impuesto mal clasificado (ILA + tabaco) y precio
(con flete aparte), dejando cada fila accionable para un fixer futuro.

**Architecture:** La clasificación por línea se aísla en una **función pura**
`clasificar_linea` (`clasifica_linea.py`), testeada con asserts locales contra los
casos canónicos reales. La misma función se usa en el prototipo read-only
(`diag_detector_v11.py`) y se copia dentro del Server Action `OH Detector Error
DTE.py`. El SA solo lee server-side y crea filas en `x_error_dte` (no escribe en
las facturas).

**Tech Stack:** Python 3 (función pura + asserts, sin pytest) · `shared/odoo_xmlrpc.py`
(prototipo read-only) · Odoo 17 `ir.actions.server` safe_eval (productivo) · l10n_cl.

## Global Constraints

- **safe_eval:** sin `import` (`b64decode`/`datetime` inyectados); `def`/`lambda`
  top-level OK; NO `obj.attr=x` (usar `.write()`); NO `getattr`; lambdas en
  `filtered()` solo sobre su propio parámetro. Releer skill
  `odoo-server-action-safe-eval` antes de tocar el SA.
- **Odoo es productivo:** barrido server-side por período (mes en curso), NO
  `search_read` masivo. Solo `create` en `x_error_dte`; NUNCA `write` en
  `account.move`/`.line` (el detector solo detecta).
- **Modelos `x_*`: `x_name` es required** → setear en cada `create`.
- **Una versión, un cambio:** la función pura se construye y testea por brecha
  (Tareas 2–4); el SA se porta validado y Marco confirma por tipo de error.
- **Git solo con OK explícito de Marco.**
- **Valores verbatim:** `TAX_TABACO = 17` (IVA Compra 19% No Recup.); `SII_IVA = 14`;
  `ILA_CODES = {'24','25','26','27','271'}`; `PROV_TABACO = {'885029000'}`
  (BAT 88502900-0, solo dígitos); tolerancia `max(2, 1% del monto)`.

## Estructura de archivos (en `proyectos/2026-06-17-cuadre-facturas-xml-odoo/`)

| Archivo | Responsabilidad |
|---|---|
| `clasifica_linea.py` | **función pura** `clasificar_linea(l, it, ctx)` → `{tipo, valor, tax_sug}` o `None`. Sin Odoo. |
| `test_clasifica.py` | asserts locales con los casos canónicos reales (sin pytest). |
| `diag_detector_v11.py` | prototipo read-only (ya existe); se re-cablea para usar `clasificar_linea`. |
| `OH Detector Error DTE.py` | Server Action productiva; se le copia la función pura y se re-cablea el loop por línea. |

Studio (Marco, en Odoo): campos nuevos en `x_error_dte` (Tarea 1).

---

## Tarea 1: Campos Studio en `x_error_dte` (Marco, en Odoo)

Prerrequisito: el SA escribirá estos campos. Sin code-test (es config Studio).

**Files:** ninguno (cambio en Odoo Studio).

- [ ] **Step 1:** En Studio, modelo `x_error_dte`, crear 3 campos:
  - `x_studio_line_id` → Many2one `account.move.line` (la línea exacta a corregir).
  - `x_studio_valor_correcto` → Float (precio neto unitario a digitar).
  - `x_studio_tax_sugerido` → Many2one `account.tax` (impuesto correcto).
- [ ] **Step 2:** En `x_studio_tipo_error` (selección) agregar valores:
  `precio`, `impuesto_mal_clasificado`, `flete_descuadrado`.
- [ ] **Step 3:** Confirmar los nombres técnicos exactos (Studio puede sufijar) y
  anotarlos; si difieren, ajustar el `.write()`/`create()` del SA en Tarea 5.

---

## Tarea 2: Función pura — código no identificado (v1.1)

**Files:**
- Create: `clasifica_linea.py`
- Create: `test_clasifica.py`

**Interfaces:**
- Produces: `clasificar_linea(l, it, ctx) -> dict|None`.
  - `l`: `{'name': str, 'has_product': bool, 'quantity': float, 'price_subtotal': float, 'tax_ids': set[int]}`
  - `it`: `{'nombre': str, 'codigo': str, 'ean': str, 'qty': float, 'prc': float, 'monto': float, 'imp': str}` o `None` si la factura no alinea línea a línea.
  - `ctx`: `{'es_merc': bool, 'es_tabaco': bool, 'tax_by_id': dict, 'sii_to_tax': dict}`
    - `tax_by_id[id] = {'sii_code': int, 'price_include': bool, 'amount': float, 'name': str}`
    - `sii_to_tax[sii_code] = [tax_id, ...]`
  - return `{'tipo': str, 'valor': float|None, 'tax_sug': int|None}` o `None` (sin error).

- [ ] **Step 1: Escribir el test que falla** (`test_clasifica.py`)

```python
# test_clasifica.py — corre con: python test_clasifica.py   (sin pytest)
from clasifica_linea import clasificar_linea

CTX = {'es_merc': True, 'es_tabaco': False, 'tax_by_id': {}, 'sii_to_tax': {}}

def test_codigo():
    # mercaderia, linea sin producto, no flete -> codigo_no_vinculado
    l = {'name': 'PK 2 Trencito 150g', 'has_product': False,
         'quantity': 1, 'price_subtotal': 4990, 'tax_ids': set()}
    it = {'nombre': 'PK 2 Trencito', 'codigo': '', 'ean': '', 'qty': 1,
          'prc': 4990, 'monto': 4990, 'imp': ''}
    r = clasificar_linea(l, it, CTX)
    assert r and r['tipo'] == 'codigo_no_vinculado', r

    # flete sin producto -> NO es codigo_no_vinculado
    l2 = dict(l, name='Delivery Latas')
    assert clasificar_linea(l2, it, CTX) is None or \
        clasificar_linea(l2, it, CTX)['tipo'] != 'codigo_no_vinculado', 'flete no es codigo'

    # proveedor NO mercaderia -> no marca codigo
    r3 = clasificar_linea(l, it, dict(CTX, es_merc=False))
    assert r3 is None or r3['tipo'] != 'codigo_no_vinculado', r3
    print('test_codigo OK')

if __name__ == '__main__':
    test_codigo()
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_clasifica.py`
Expected: `ModuleNotFoundError: No module named 'clasifica_linea'`.

- [ ] **Step 3: Implementación mínima** (`clasifica_linea.py`)

```python
"""Clasificacion de error por linea DTE<->Odoo. Funcion pura (sin Odoo).
Se copia tal cual dentro del Server Action; solo usa builtins permitidos."""

FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por')


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def clasificar_linea(l, it, ctx):
    # 1) CODIGO NO IDENTIFICADO: mercaderia, sin producto, no flete
    if ctx['es_merc'] and not l['has_product'] and not _es_flete(l['name']):
        return {'tipo': 'codigo_no_vinculado', 'valor': None, 'tax_sug': None}
    return None
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_clasifica.py`
Expected: `test_codigo OK`.

- [ ] **Step 5: Commit** (con OK de Marco)

```bash
git add proyectos/2026-06-17-cuadre-facturas-xml-odoo/clasifica_linea.py \
        proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_clasifica.py
git commit -m "detector dte: clasificador de linea (v1.1 codigo no identificado)"
```

---

## Tarea 3: Función pura — impuesto mal clasificado (v1.2)

**Files:**
- Modify: `clasifica_linea.py`
- Modify: `test_clasifica.py`

**Interfaces:** misma firma; agrega ramas tabaco (BAT → tax 17) e ILA
(`CodImpAdic` ≠ `sii_code` de la línea → tax por `sii_to_tax`).

- [ ] **Step 1: Agregar el test que falla** (`test_clasifica.py`)

```python
def test_impuesto():
    # tabaco BAT: linea con taxes != {17} -> impuesto_mal_clasificado, tax_sug=17
    ctx_t = {'es_merc': False, 'es_tabaco': True, 'tax_by_id': {}, 'sii_to_tax': {}}
    l = {'name': 'Pall Mall Azul', 'has_product': True, 'quantity': 1,
         'price_subtotal': 37999, 'tax_ids': set()}        # sin tax
    it = {'nombre': 'Pall Mall', 'codigo': '', 'ean': '', 'qty': 1,
          'prc': 31613, 'monto': 31613, 'imp': '14'}
    r = clasificar_linea(l, it, ctx_t)
    assert r and r['tipo'] == 'impuesto_mal_clasificado' and r['tax_sug'] == 17, r
    # tabaco ya con exactamente {17} -> no marca impuesto
    l_ok = dict(l, tax_ids={17})
    r = clasificar_linea(l_ok, it, ctx_t)
    assert r is None or r['tipo'] != 'impuesto_mal_clasificado', r

    # ILA cod 26 pero la linea trae tax sii_code 25 -> impuesto_mal_clasificado, tax_sug = tax de 26
    tax_by_id = {2: {'sii_code': 14, 'price_include': False, 'amount': 19, 'name': 'IVA'},
                 11: {'sii_code': 25, 'price_include': False, 'amount': 20.5, 'name': 'Vinos'},
                 12: {'sii_code': 26, 'price_include': False, 'amount': 20.5, 'name': 'Cervezas'}}
    ctx_i = {'es_merc': False, 'es_tabaco': False, 'tax_by_id': tax_by_id,
             'sii_to_tax': {25: [11], 26: [12]}}
    l_ila = {'name': 'West Coast IPA', 'has_product': True, 'quantity': 120,
             'price_subtotal': 60000, 'tax_ids': {2, 11}}
    it_ila = {'nombre': 'IPA', 'codigo': '', 'ean': '', 'qty': 120,
              'prc': 500, 'monto': 60000, 'imp': '26'}
    r = clasificar_linea(l_ila, it_ila, ctx_i)
    assert r and r['tipo'] == 'impuesto_mal_clasificado' and r['tax_sug'] == 12, r
    # misma linea pero ya con el tax correcto (26) -> no marca
    r = clasificar_linea(dict(l_ila, tax_ids={2, 12}), it_ila, ctx_i)
    assert r is None or r['tipo'] != 'impuesto_mal_clasificado', r
    print('test_impuesto OK')
```
(agregar `test_impuesto()` al bloque `__main__`).

- [ ] **Step 2: Correr y verificar que falla**

Run: `python .../test_clasifica.py`
Expected: `AssertionError` o `KeyError` (la rama de impuesto aún no existe).

- [ ] **Step 3: Implementación** — agregar a `clasifica_linea.py`, ANTES del `return None`:

```python
ILA_CODES = {'24', '25', '26', '27', '271'}
SII_IVA = 14
TAX_TABACO = 17
```
(constantes al tope del módulo) y dentro de `clasificar_linea`, tras la rama código:

```python
    tax_ids = set(l.get('tax_ids') or ())
    tax_by_id = ctx['tax_by_id']

    # 2) IMPUESTO — tabaco (regla por proveedor)
    if ctx['es_tabaco'] and tax_ids != {TAX_TABACO}:
        return {'tipo': 'impuesto_mal_clasificado', 'valor': None, 'tax_sug': TAX_TABACO}

    # 2b) IMPUESTO — ILA por CodImpAdic vs sii_code de la linea
    if it and it['imp'] in ILA_CODES:
        add = set(tax_by_id[t]['sii_code'] for t in tax_ids
                  if t in tax_by_id and tax_by_id[t]['sii_code'] != SII_IVA)
        cod_imp = int(it['imp'])
        if cod_imp not in add:
            cand = ctx['sii_to_tax'].get(cod_imp, [])
            return {'tipo': 'impuesto_mal_clasificado', 'valor': None,
                    'tax_sug': cand[0] if cand else None}
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python .../test_clasifica.py`
Expected: `test_codigo OK` y `test_impuesto OK`.

- [ ] **Step 5: Commit** (con OK de Marco)

```bash
git add proyectos/2026-06-17-cuadre-facturas-xml-odoo/clasifica_linea.py \
        proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_clasifica.py
git commit -m "detector dte: impuesto mal clasificado ILA + tabaco (v1.2)"
```

---

## Tarea 4: Función pura — precio / flete / uom (v1.3)

**Files:**
- Modify: `clasifica_linea.py`
- Modify: `test_clasifica.py`

**Interfaces:** misma firma; agrega precio (qty calza), flete_descuadrado, uom,
linea_descuadrada. `valor` sale de `MontoItem/Qty × factor`.

- [ ] **Step 1: Agregar el test que falla** (`test_clasifica.py`)

```python
def test_precio_flete():
    ctx = {'es_merc': False, 'es_tabaco': False, 'tax_by_id': {}, 'sii_to_tax': {}}
    # precio: qty calza, subtotal no; valor desde MontoItem/Qty (post-descuento), NO PrcItem
    l = {'name': 'VINO MERLOT', 'has_product': True, 'quantity': 30,
         'price_subtotal': 256951, 'tax_ids': set()}
    it = {'nombre': 'VINO', 'codigo': '', 'ean': '', 'qty': 30,
          'prc': 18710, 'monto': 369180, 'imp': ''}   # PrcItem 18710 != 369180/30=12306
    r = clasificar_linea(l, it, ctx)
    assert r and r['tipo'] == 'precio' and r['valor'] == 12306.0, r

    # flete con descuadre -> flete_descuadrado (sin valor)
    lf = {'name': 'Delivery Latas', 'has_product': True, 'quantity': 240,
          'price_subtotal': 171216, 'tax_ids': set()}
    itf = {'nombre': 'Delivery', 'codigo': '', 'ean': '', 'qty': 240,
           'prc': 1300, 'monto': 312000, 'imp': ''}
    r = clasificar_linea(lf, itf, ctx)
    assert r and r['tipo'] == 'flete_descuadrado' and r['valor'] is None, r

    # uom: subtotal calza pero qty difiere -> uom_no_cuadra
    lu = {'name': 'CERVEZA', 'has_product': True, 'quantity': 1,
          'price_subtotal': 6000, 'tax_ids': set()}
    itu = {'nombre': 'Cerveza', 'codigo': '', 'ean': '', 'qty': 12,
           'prc': 500, 'monto': 6000, 'imp': ''}
    r = clasificar_linea(lu, itu, ctx)
    assert r and r['tipo'] == 'uom_no_cuadra', r

    # subtotal y qty calzan -> None (linea OK)
    lo = {'name': 'OK', 'has_product': True, 'quantity': 2,
          'price_subtotal': 1000, 'tax_ids': set()}
    ito = {'nombre': 'ok', 'codigo': '', 'ean': '', 'qty': 2,
           'prc': 500, 'monto': 1000, 'imp': ''}
    assert clasificar_linea(lo, ito, ctx) is None, clasificar_linea(lo, ito, ctx)

    # precio con price_include: factor multiplica el neto
    tbi = {28: {'sii_code': 14, 'price_include': True, 'amount': 19, 'name': 'IVA OC'}}
    ctx_pi = dict(ctx, tax_by_id=tbi)
    lpi = {'name': 'X', 'has_product': True, 'quantity': 1,
           'price_subtotal': 1000, 'tax_ids': {28}}
    itpi = {'nombre': 'x', 'codigo': '', 'ean': '', 'qty': 1,
            'prc': 0, 'monto': 1190, 'imp': ''}
    r = clasificar_linea(lpi, itpi, ctx_pi)
    assert r and r['tipo'] == 'precio' and round(r['valor']) == 1416, r  # 1190*1.19
    print('test_precio_flete OK')
```
(agregar `test_precio_flete()` al bloque `__main__`).

- [ ] **Step 2: Correr y verificar que falla**

Run: `python .../test_clasifica.py`
Expected: `AssertionError` (precio/flete/uom aún no existen).

- [ ] **Step 3: Implementación** — agregar `_factor` al módulo:

```python
def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f
```
y en `clasificar_linea`, tras la rama de impuesto y ANTES del `return None`:

```python
    # 3) PRECIO / FLETE / UOM (solo con linea alineada)
    if it:
        factor = _factor(tax_ids, tax_by_id)
        tol = max(2.0, abs(it['monto']) * 0.01)
        d_sub = abs(l['price_subtotal'] - it['monto'])
        qty_match = abs(l['quantity'] - it['qty']) <= 0.001
        if d_sub > tol:
            if _es_flete(l['name']):
                return {'tipo': 'flete_descuadrado', 'valor': None, 'tax_sug': None}
            if qty_match:
                net_unit = it['monto'] / it['qty'] if it['qty'] else it['monto']
                return {'tipo': 'precio', 'valor': round(net_unit * factor, 2), 'tax_sug': None}
            return {'tipo': 'linea_descuadrada', 'valor': None, 'tax_sug': None}
        if not qty_match:
            return {'tipo': 'uom_no_cuadra', 'valor': None, 'tax_sug': None}
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python .../test_clasifica.py`
Expected: las 3 líneas `... OK`.

- [ ] **Step 5: Commit** (con OK de Marco)

```bash
git add proyectos/2026-06-17-cuadre-facturas-xml-odoo/clasifica_linea.py \
        proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_clasifica.py
git commit -m "detector dte: precio (post-descuento) + flete + uom (v1.3)"
```

---

## Tarea 5: Integración read-only contra junio (banco de pruebas)

**Files:**
- Modify: `diag_detector_v11.py` (re-cablear para usar `clasificar_linea`).

Valida la función pura contra datos reales y confirma que los conteos cuadran con
lo ya medido (precio 71, impuesto 109, código 59, flete 7 sobre draft).

- [ ] **Step 1:** En `diag_detector_v11.py`, importar la función pura:

```python
from clasifica_linea import clasificar_linea
```

- [ ] **Step 2:** Reemplazar el bloque de clasificación inline por la llamada:
construir `l` (`name`, `has_product=bool(l['product_id'])`, `quantity`,
`price_subtotal`, `tax_ids=set(l['tax_ids'])`), `it` (el item del DTE o `None`),
`ctx` (`es_merc`, `es_tabaco`, `tax_by_id`, `sii_to_tax`), y llamar
`clasificar_linea(l, it, ctx)`. La recomendación de producto (`find_product`) y el
`x_studio_line_id` se agregan en el wiring, no en la función pura.

- [ ] **Step 3: Correr y comparar conteos**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/diag_detector_v11.py`
Expected (cuadra con la validación 2026-06-18): `codigo_no_vinculado 59`,
`impuesto_mal_clasificado 109`, `precio 71`, `flete_descuadrado 7`. Spot-check:
FAC 7468844 vino `valor=12306`; FAC 17263580 tabaco `tax=17`; FAC 007088 delivery
`flete_descuadrado`.

- [ ] **Step 4: Commit** (con OK de Marco)

```bash
git add proyectos/2026-06-17-cuadre-facturas-xml-odoo/diag_detector_v11.py
git commit -m "detector dte: prototipo usa clasificador puro; valida vs junio"
```

---

## Tarea 6: Portar al Server Action `OH Detector Error DTE.py`

**Files:**
- Modify: `OH Detector Error DTE.py`

Copiar la función pura `clasificar_linea` (+ `_es_flete`, `_factor`, constantes) al
tope del SA, construir `ctx` server-side, recorrer el loop por línea y crear filas
en `x_error_dte` con los campos nuevos. Solo `create`, nunca `write` en facturas.

- [ ] **Step 1: Releer la skill** `odoo-server-action-safe-eval` y la memoria
  [[ref_odoo_server_action_oh]] (no import, no `obj.attr=x`, lambdas sobre su
  parámetro, `x_name` required).

- [ ] **Step 2:** Pegar al tope del SA (nivel módulo, hoisteadas) las funciones
  puras `FLETE`, `_es_flete`, `_factor`, constantes `ILA_CODES/SII_IVA/TAX_TABACO`
  y `clasificar_linea` — copia EXACTA de `clasifica_linea.py`.

- [ ] **Step 3:** Construir el catálogo de taxes y el contexto server-side, una vez:

```python
PROV_TABACO = {'885029000'}   # BAT 88502900-0 (solo digitos), extensible
_taxes = env['account.tax'].search([('type_tax_use', '=', 'purchase')])
tax_by_id = {}
sii_to_tax = {}
for t in _taxes:
    tax_by_id[t.id] = {'sii_code': t.l10n_cl_sii_code, 'price_include': t.price_include,
                       'amount': t.amount, 'name': t.name}
    sii_to_tax.setdefault(t.l10n_cl_sii_code, []).append(t.id)
```

- [ ] **Step 4:** En el loop por línea (donde hoy están `linea_descuadrada` /
  `codigo_no_vinculado` / `uom_no_cuadra`), reemplazar por una sola llamada por
  línea de producto. `it` = item del DTE alineado por posición (o `None`):

```python
vat = ''.join(c for c in (m.partner_id.vat or '') if c.isdigit())
es_tabaco = vat in PROV_TABACO
es_merc = (m.partner_id.x_studio_tipo_proveedor == 'Mercaderia')
prod_lines = m.invoice_line_ids.filtered(lambda x: x.display_type == 'product')
alineada = (len(prod_lines) == len(items) and len(items) > 0)
pos = 0
for l in prod_lines:
    it = items[pos] if alineada else None
    pos += 1
    ld = {'name': l.name or '', 'has_product': bool(l.product_id),
          'quantity': l.quantity, 'price_subtotal': l.price_subtotal,
          'tax_ids': set(l.tax_ids.ids)}
    r = clasificar_linea(ld, it, {'es_merc': es_merc, 'es_tabaco': es_tabaco,
                                  'tax_by_id': tax_by_id, 'sii_to_tax': sii_to_tax})
    if not r:
        continue
    v = dict(base)
    v['x_studio_tipo_error'] = r['tipo']
    v['x_studio_line_id'] = l.id
    v['x_studio_codigo'] = (it['codigo'] if it else '') or ''
    v['x_studio_monto_riesgo'] = abs((it['monto'] if it else l.price_subtotal) - l.price_subtotal) or l.price_subtotal
    if r['valor'] is not None:
        v['x_studio_valor_correcto'] = r['valor']
    if r['tax_sug']:
        v['x_studio_tax_sugerido'] = r['tax_sug']
    if r['tipo'] == 'codigo_no_vinculado':
        prod = find_product(it['codigo'] if it else '', it['ean'] if it else '', l.name)
        if prod:
            v['x_studio_product_id'] = prod.id
            v['x_studio_sugerencia'] = 'vincular a %s' % prod.name
            if it and it['codigo'] and prod.default_code != it['codigo']:
                v['x_studio_sugerencia'] += ' | poblar default_code con %s' % it['codigo']
        else:
            v['x_studio_sugerencia'] = 'revisar: producto ambiguo/no encontrado'
    crear('%s:%s:%s' % (nm, r['tipo'], l.id), v)
    n += 1
```
  (Nota: `find_product`, `parse_dte`/`items`, `base`, `nm`, `crear`, `n` ya existen
  en el SA v1.0. Mantener los bloques de nivel-factura `draft`/`sin_xml`/
  `duplicado` sin cambios.)

- [ ] **Step 5: Pre-chequeo safe_eval** — releer el SA buscando `import`,
  `obj.attr =`, `getattr`, y lambdas que capturen locals de función. `clasificar_linea`
  no debe referenciar nada fuera de sus parámetros.

- [ ] **Step 6: Marco corre el SA acotado** — pegar en Odoo con el dominio limitado
  a 1 proveedor por tipo y confirmar contra el prototipo:
  - BAT (`88502900-0`) → filas `impuesto_mal_clasificado` con `tax_sugerido = 17`.
  - PEUMO (`85037900-9`) vino → `precio` con `valor_correcto` = MontoItem/Qty.
  - un proveedor Mercadería con packs → `codigo_no_vinculado` con recomendación.
  - una factura con delivery → `flete_descuadrado`.
  Verificar que NO se modificó ninguna factura (solo filas en `x_error_dte`).

- [ ] **Step 7: Ampliar a todo el período** y revisar la cola por tipo. Confirmar
  conteos vs el prototipo de junio.

- [ ] **Step 8: Commit** (con OK explícito de Marco)

```bash
git add "proyectos/2026-06-17-cuadre-facturas-xml-odoo/OH Detector Error DTE.py"
git commit -m "detector dte: clasificacion por linea (codigo/impuesto/precio/flete) v1.3"
```

---

## Self-review (cobertura del spec)

- Brecha 1 (código sin gate de cuenta, solo Mercadería, + recomendación) → Tarea 2
  (tipo) + Tarea 6 Step 4 (recomendación vía `find_product`).
- Brecha 2/3/5 (impuesto ILA + tabaco + `tax_sugerido`) → Tarea 3 + campos Tarea 1.
- Brecha 4 (precio post-descuento, flete, uom; sin `cantidad`) → Tarea 4.
- Campos `x_studio_line_id`/`valor_correcto`/`tax_sugerido` → Tarea 1 + Tarea 6.
- Contrato detector→fixer: el detector deja todo accionable; el fixer (Fase 2) es
  otro proyecto. Cubierto como salida estructurada, no como auto-fix.
- safe_eval / Odoo productivo / x_name required → Global Constraints + Tarea 6.

**GAP conocido (aceptado):** la recomendación de producto da bajo hit-rate en packs
promocionales (nombre del DTE ≠ nombre del producto). Marco los vincula a mano; no
bloquea. Mejora futura: match difuso por tokens (fuera de alcance v1.x).
