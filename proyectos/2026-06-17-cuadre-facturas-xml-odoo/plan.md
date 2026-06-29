# Plan de Implementación — Monitor de registro de compras (Fase 1)

> **Para ejecución:** tareas en pasos chicos (2-5 min) con checkbox `- [ ]`.
> No hay pytest en el repo: los "tests" son scripts `python` con `assert` y el
> backtest read-only contra junio 2026. La Server Action se valida corriéndola
> en Odoo (Marco la pega). Git solo con OK explícito de Marco (regla del repo).

**Goal:** Server Action que cada día mide el "error de registro" de las facturas
de compra del período y deja un veredicto por factura (color + $ en riesgo +
acción), más la lista de códigos de proveedor sin vínculo y los faltantes vs SII.

**Architecture:** Lógica pura (parser de totales DTE por string, motor de reglas,
conciliación SII) probada en un **prototipo read-only XML-RPC** sobre junio 2026;
luego copiada a una **Server Action safe_eval** que lee moves server-side,
decodifica el XML con `b64decode`, y escribe `x_studio_reg_*` en cada move.

**Tech Stack:** Python 3 + `shared/odoo_xmlrpc.py` (prototipo) · Odoo 17
`ir.actions.server` safe_eval (productivo) · l10n_cl / l10n_cl_edi.

---

## Estructura de archivos (todo en `proyectos/2026-06-17-cuadre-facturas-xml-odoo/`)

| Archivo | Responsabilidad |
|---|---|
| `dte_totales.py` | función pura: XML DTE (str) → dict de totales (MntNeto/IVA/OtrosImp/MntExe/MntTotal) por extracción de tags |
| `reglas_registro.py` | función pura: (datos del move + totales + líneas) → veredicto (color, categorías, monto_riesgo, acción) |
| `concilia_sii.py` | función pura: (set Odoo + filas RCV SII) → faltantes / sobrantes por (RUT,tipo,folio) |
| `test_logica.py` | asserts locales de las 3 funciones puras (sin Odoo, sin pytest) |
| `monitor_prototipo.py` | wiring read-only XML-RPC: lee junio, llama las 3 funciones, emite CSV es-CL + lista códigos sin vínculo |
| `OH Monitor Registro Compras.py` | Server Action productiva (safe_eval): misma lógica, escribe `x_studio_reg_*`, retorna notificación |

Campos Studio a crear en `account.move` (Marco, en Studio) — documentados en Tarea 6.

---

## Tarea 1: Parser de totales del DTE (función pura)

**Files:**
- Create: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/dte_totales.py`
- Test: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`

El XML del DTE SII trae los totales como tags enteros dentro de `<Totales>`:
`<MntNeto>158221</MntNeto>`, `<IVA>30062</IVA>`, `<MntTotal>188283</MntTotal>`,
opcional `<MntExe>` y `<OtrosImp><MntImp>...`. Se extrae por string (safe_eval no
permite `xml.etree`). La misma función corre en el prototipo y se copia a la
Server Action.

- [ ] **Step 1: Escribir el test que falla** (en `test_logica.py`)

```python
# test_logica.py  — corre con: python test_logica.py   (sin pytest)
from dte_totales import totales_dte

XML_OK = (
    '<?xml version="1.0"?><DTE><Documento><Encabezado><Totales>'
    '<MntNeto>158221</MntNeto><IVA>30062</IVA><MntTotal>188283</MntTotal>'
    '</Totales></Encabezado></Documento></DTE>'
)
XML_ILA = (  # bebida con ILA en OtrosImp
    '<Totales><MntNeto>1780</MntNeto><IVA>338</IVA>'
    '<OtrosImp><CodImp>271</CodImp><TasaImp>15.0</TasaImp><MntImp>271</MntImp></OtrosImp>'
    '<MntTotal>2389</MntTotal></Totales>'
)
XML_EXENTA = '<Totales><MntExe>5000</MntExe><MntTotal>5000</MntTotal></Totales>'
XML_ROTO = '<Totales><MntNeto>100</MntNeto></Totales>'  # sin MntTotal

def test_totales():
    t = totales_dte(XML_OK)
    assert t['neto'] == 158221 and t['iva'] == 30062 and t['total'] == 188283, t
    assert t['exento'] == 0 and t['otros_imp'] == 0, t

    t = totales_dte(XML_ILA)
    assert t['neto'] == 1780 and t['iva'] == 338, t
    assert t['otros_imp'] == 271 and t['total'] == 2389, t

    t = totales_dte(XML_EXENTA)
    assert t['exento'] == 5000 and t['total'] == 5000 and t['iva'] == 0, t

    t = totales_dte(XML_ROTO)
    assert t['total'] is None, t  # tag faltante -> None, no se asume cuadre
    print("test_totales OK")

if __name__ == '__main__':
    test_totales()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`
Expected: `ModuleNotFoundError: No module named 'dte_totales'` (o falla del import).

- [ ] **Step 3: Implementación mínima** (`dte_totales.py`)

```python
"""Extrae totales del XML del DTE SII por busqueda de tags (sin xml parser).
Pensado para correr identico dentro de safe_eval (solo string ops + int)."""


def _tag_int(xml, tag):
    """Devuelve el entero dentro de <tag>...</tag>, o None si no esta."""
    a = xml.find('<' + tag + '>')
    if a == -1:
        return None
    a += len(tag) + 2
    b = xml.find('</' + tag + '>', a)
    if b == -1:
        return None
    txt = xml[a:b].strip()
    # los totales SII son enteros (CLP); tolerar signo
    try:
        return int(round(float(txt)))
    except (ValueError, TypeError):
        return None


def _sum_otros_imp(xml):
    """Suma todos los <MntImp> dentro de bloques <OtrosImp> (ILA/adicionales)."""
    total = 0
    i = 0
    while True:
        a = xml.find('<MntImp>', i)
        if a == -1:
            break
        a += len('<MntImp>')
        b = xml.find('</MntImp>', a)
        if b == -1:
            break
        try:
            total += int(round(float(xml[a:b].strip())))
        except (ValueError, TypeError):
            pass
        i = b
    return total


def totales_dte(xml):
    """xml: str del DTE. Devuelve dict con neto/iva/exento/otros_imp/total.
    Campos ausentes -> 0, salvo 'total' que es None si falta (no se asume cuadre)."""
    neto = _tag_int(xml, 'MntNeto')
    iva = _tag_int(xml, 'IVA')
    exento = _tag_int(xml, 'MntExe')
    total = _tag_int(xml, 'MntTotal')
    return {
        'neto': neto or 0,
        'iva': iva or 0,
        'exento': exento or 0,
        'otros_imp': _sum_otros_imp(xml),
        'total': total,  # None si falta el tag
    }
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`
Expected: `test_totales OK`

---

## Tarea 2: Motor de reglas (función pura)

**Files:**
- Create: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/reglas_registro.py`
- Modify: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`

Recibe un dict con los datos del move ya leídos (state, montos Odoo, totales del
XML, líneas, flags) y devuelve el veredicto. Tolerancia de redondeo = $1.

- [ ] **Step 1: Agregar el test que falla** (en `test_logica.py`)

```python
from reglas_registro import evaluar_move, TOL

def _move(**kw):
    base = dict(state='posted', amount_total=188283, amount_untaxed=158221,
                amount_tax=30062, tiene_xml=True, tipo_code='33',
                xml_total=188283, xml_neto=158221, xml_iva=30062, xml_otros=0,
                n_lineas_prod=2, n_lineas_sin_sku=0, es_duplicado=False)
    base.update(kw)
    return base

def test_reglas():
    # verde
    v = evaluar_move(_move())
    assert v['color'] == 'verde' and v['monto_riesgo'] == 0, v

    # descuadre de monto (XML != Odoo, > TOL)
    v = evaluar_move(_move(xml_total=200000))
    assert v['color'] == 'rojo' and 'descuadre' in v['error'], v
    assert v['monto_riesgo'] == 188283, v

    # redondeo dentro de tolerancia -> sigue verde
    v = evaluar_move(_move(xml_total=188283 + TOL))
    assert v['color'] == 'verde', v

    # draft -> amarillo no contabilizado
    v = evaluar_move(_move(state='draft'))
    assert v['color'] == 'amarillo' and 'no_contabilizado' in v['error'], v

    # linea sin SKU -> amarillo costo sin asignar
    v = evaluar_move(_move(n_lineas_sin_sku=1))
    assert v['color'] == 'amarillo' and 'sin_sku' in v['error'], v

    # sin XML -> rojo
    v = evaluar_move(_move(tiene_xml=False, xml_total=None))
    assert v['color'] == 'rojo' and 'sin_xml' in v['error'], v

    # exenta (IVA 0) no debe marcar descuadre por IVA
    v = evaluar_move(_move(tipo_code='34', amount_tax=0, xml_iva=0,
                           amount_untaxed=5000, amount_total=5000,
                           xml_neto=0, xml_total=5000))
    assert v['color'] == 'verde', v

    # duplicado -> rojo
    v = evaluar_move(_move(es_duplicado=True))
    assert v['color'] == 'rojo' and 'duplicado' in v['error'], v

    # gravedad: draft + descuadre -> gana rojo
    v = evaluar_move(_move(state='draft', xml_total=200000))
    assert v['color'] == 'rojo', v
    print("test_reglas OK")

if __name__ == '__main__':
    test_totales()
    test_reglas()
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`
Expected: `ModuleNotFoundError: No module named 'reglas_registro'`

- [ ] **Step 3: Implementación** (`reglas_registro.py`)

```python
"""Motor de reglas de error de registro. Funcion pura, sin Odoo.
Copiar tal cual dentro de la Server Action (solo usa builtins permitidos)."""

TOL = 1  # tolerancia de redondeo en CLP

# prioridad de color: rojo > amarillo > verde
_ROJO = 'rojo'
_AMARILLO = 'amarillo'
_VERDE = 'verde'


def evaluar_move(m):
    """m: dict con los datos ya leidos del move. Devuelve dict veredicto."""
    errores = []
    riesgo = 0

    # --- ROJO ---
    if not m['tiene_xml'] or not m.get('tipo_code'):
        errores.append('sin_xml')
        riesgo = max(riesgo, m['amount_total'])
    if m.get('es_duplicado'):
        errores.append('duplicado')
        riesgo = max(riesgo, m['amount_total'])
    # descuadre: solo si hay XML parseado (xml_total no None)
    if m['tiene_xml'] and m.get('xml_total') is not None:
        desc = (abs(m['xml_total'] - m['amount_total']) > TOL or
                abs(m['xml_neto'] - m['amount_untaxed']) > TOL or
                abs((m['xml_iva'] + m['xml_otros']) - m['amount_tax']) > TOL)
        if desc:
            errores.append('descuadre')
            riesgo = max(riesgo, m['amount_total'])
    elif m['tiene_xml'] and m.get('xml_total') is None:
        errores.append('xml_no_parseable')
        riesgo = max(riesgo, m['amount_total'])

    # --- AMARILLO ---
    if m['state'] == 'draft':
        errores.append('no_contabilizado')
        riesgo = max(riesgo, m['amount_total'])
    if m['n_lineas_sin_sku'] > 0:
        errores.append('sin_sku')
        # riesgo de SKU: monto de las lineas sin sku se pasa aparte si se quiere;
        # aqui usamos amount_total como cota superior conservadora
        riesgo = max(riesgo, m['amount_total'])

    rojos = {'sin_xml', 'duplicado', 'descuadre', 'xml_no_parseable'}
    if any(e in rojos for e in errores):
        color = _ROJO
    elif errores:
        color = _AMARILLO
    else:
        color = _VERDE
        riesgo = 0

    return {
        'color': color,
        'error': ','.join(errores),
        'monto_riesgo': riesgo,
        'accion': _accion(color, errores),
    }


def _accion(color, errores):
    if color == _VERDE:
        return ''
    msg = []
    if 'sin_xml' in errores:
        msg.append('adjuntar/registrar DTE')
    if 'duplicado' in errores:
        msg.append('anular duplicado')
    if 'descuadre' in errores or 'xml_no_parseable' in errores:
        msg.append('revisar montos vs DTE (ILA/flete?)')
    if 'no_contabilizado' in errores:
        msg.append('postear')
    if 'sin_sku' in errores:
        msg.append('vincular SKU en maestro')
    return '; '.join(msg)
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`
Expected: `test_totales OK` y `test_reglas OK`

---

## Tarea 3: Conciliación contra el RCV del SII (función pura)

**Files:**
- Create: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/concilia_sii.py`
- Modify: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`

Identidad = `(rut, tipo, folio)` normalizada. La función no parsea el CSV (eso es
wiring); recibe listas de tuplas-clave y devuelve faltantes/sobrantes.

- [ ] **Step 1: Agregar el test que falla**

```python
from concilia_sii import clave, conciliar

def test_concilia():
    assert clave('76.853.601-5', '33', '003564') == ('768536015', '33', '3564'), clave('76.853.601-5','33','003564')
    sii = [('768536015', '33', '3564'), ('931000001', '33', '10')]
    odoo = [('768536015', '33', '3564')]
    r = conciliar(sii_keys=sii, odoo_keys=odoo)
    assert r['faltan_en_odoo'] == [('931000001', '33', '10')], r
    assert r['sobran_en_odoo'] == [], r
    print("test_concilia OK")
```
(agregar `test_concilia()` al bloque `__main__`).

- [ ] **Step 2: Correr y verificar que falla**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`
Expected: `ModuleNotFoundError: No module named 'concilia_sii'`

- [ ] **Step 3: Implementación** (`concilia_sii.py`)

```python
"""Conciliacion de completitud Odoo <-> RCV del SII. Funcion pura."""


def clave(rut, tipo, folio):
    """Normaliza identidad: rut sin puntos/guion/DV-lower, tipo str, folio sin ceros."""
    r = ''.join(c for c in str(rut) if c.isdigit())  # quita puntos, guion y DV no-digito
    t = str(tipo).strip()
    f = str(folio).strip().lstrip('0') or '0'
    return (r, t, f)


def conciliar(sii_keys, odoo_keys):
    s = set(sii_keys)
    o = set(odoo_keys)
    return {
        'faltan_en_odoo': sorted(s - o),  # en SII, no en Odoo -> ROJO completitud
        'sobran_en_odoo': sorted(o - s),  # en Odoo, no en SII -> revisar
    }
```

Nota: `clave()` quita el dígito verificador junto con puntos/guion (toma solo
dígitos del cuerpo+DV; como ambos lados se normalizan igual, el match es estable).
Si el RCV trae el RUT con DV y Odoo igual, ambos colapsan al mismo string.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/test_logica.py`
Expected: las 3 líneas `... OK`.

---

## Tarea 4: Prototipo read-only sobre junio 2026 (banco de pruebas)

**Files:**
- Create: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/monitor_prototipo.py`

Lee los moves de junio vía XML-RPC, descarga `l10n_cl_dte_file.datas`, llama las 3
funciones puras, y emite CSV es-CL + lista de códigos sin vínculo. Valida la
lógica contra los conteos ya medidos (DIAG): 431 facturas, 77 draft, 2 sin XML,
~616 líneas sin SKU.

- [ ] **Step 1: Escribir el prototipo**

```python
"""Banco de pruebas read-only del monitor. NO escribe en Odoo.
Corre: python proyectos/2026-06-17-cuadre-facturas-xml-odoo/monitor_prototipo.py"""
from __future__ import annotations
import sys, base64, csv
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader
from dte_totales import totales_dte
from reglas_registro import evaluar_move
from concilia_sii import clave, conciliar

P_INI, P_FIN = '2026-06-01', '2026-06-30'
OUT = Path(__file__).resolve().parent / 'resultados'


def main():
    odoo = OdooReader()
    dom = [('move_type', '=', 'in_invoice'),
           ('invoice_date', '>=', P_INI), ('invoice_date', '<=', P_FIN)]
    moves = odoo.search_read('account.move', dom, fields=[
        'name', 'state', 'partner_id', 'amount_total', 'amount_untaxed',
        'amount_tax', 'l10n_latam_document_type_id_code', 'l10n_latam_document_number',
        'l10n_cl_dte_file', 'invoice_line_ids'], order='amount_total desc')
    print(f"moves junio: {len(moves)}")

    # RUT por partner (para clave/duplicados)
    pids = list({m['partner_id'][0] for m in moves if m['partner_id']})
    partners = {p['id']: p.get('vat') for p in
                odoo.search_read('res.partner', [('id', 'in', pids)], ['vat'])}

    # detectar duplicados por (rut,tipo,folio)
    seen, dup_keys = set(), set()
    for m in moves:
        k = clave(partners.get(m['partner_id'][0] if m['partner_id'] else 0),
                  m.get('l10n_latam_document_type_id_code'),
                  m.get('l10n_latam_document_number') or '0')
        if k in seen:
            dup_keys.add(k)
        seen.add(k)

    # lineas: traer product_id y datos para sin-sku (batch)
    line_ids = [lid for m in moves for lid in m['invoice_line_ids']]
    lines = {l['id']: l for l in odoo.search_read(
        'account.move.line', [('id', 'in', line_ids)],
        ['move_id', 'display_type', 'product_id', 'price_total', 'name'])}

    filas, codigos_sin_vinculo = [], []
    for m in moves:
        pid = m['partner_id'][0] if m['partner_id'] else 0
        rut = partners.get(pid)
        mlines = [lines[i] for i in m['invoice_line_ids'] if i in lines]
        prod = [l for l in mlines if l.get('display_type') == 'product']
        sin_sku = [l for l in prod if not l.get('product_id')]
        for l in sin_sku:
            codigos_sin_vinculo.append((rut, m['name'], l.get('name'), l.get('price_total')))

        # parsear XML si existe
        tiene_xml = bool(m.get('l10n_cl_dte_file'))
        tot = {'total': None, 'neto': 0, 'iva': 0, 'otros_imp': 0, 'exento': 0}
        if tiene_xml:
            att_id = m['l10n_cl_dte_file'][0]
            att = odoo.search_read('ir.attachment', [('id', '=', att_id)], ['datas'])
            if att and att[0].get('datas'):
                try:
                    xml = base64.b64decode(att[0]['datas']).decode('latin-1', 'ignore')
                    tot = totales_dte(xml)
                except Exception:
                    tot = {'total': None, 'neto': 0, 'iva': 0, 'otros_imp': 0, 'exento': 0}

        k = clave(rut, m.get('l10n_latam_document_type_id_code'),
                  m.get('l10n_latam_document_number') or '0')
        v = evaluar_move(dict(
            state=m['state'], amount_total=m['amount_total'],
            amount_untaxed=m['amount_untaxed'], amount_tax=m['amount_tax'],
            tiene_xml=tiene_xml, tipo_code=m.get('l10n_latam_document_type_id_code'),
            xml_total=tot['total'], xml_neto=tot['neto'], xml_iva=tot['iva'],
            xml_otros=tot['otros_imp'], n_lineas_prod=len(prod),
            n_lineas_sin_sku=len(sin_sku), es_duplicado=k in dup_keys))
        filas.append((v['color'], m['name'],
                      m['partner_id'][1] if m['partner_id'] else '',
                      m.get('l10n_latam_document_type_id_code'),
                      m.get('l10n_latam_document_number'), v['error'],
                      v['monto_riesgo'], v['accion'], m['amount_total'], tot['total']))

    OUT.mkdir(exist_ok=True)
    with open(OUT / 'monitor_junio.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['color', 'factura', 'proveedor', 'tipo', 'folio', 'error',
                    'monto_riesgo', 'accion', 'total_odoo', 'total_xml'])
        for row in sorted(filas, key=lambda r: -r[6]):
            w.writerow(row)
    with open(OUT / 'codigos_sin_vinculo.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['rut_proveedor', 'factura', 'descripcion_linea', 'monto'])
        for row in codigos_sin_vinculo:
            w.writerow(row)

    # resumen para validar contra DIAG
    from collections import Counter
    c = Counter(r[0] for r in filas)
    print("por color:", dict(c))
    print("draft (no_contabilizado):", sum('no_contabilizado' in r[5] for r in filas))
    print("sin_xml:", sum('sin_xml' in r[5] for r in filas))
    print("lineas sin sku:", len(codigos_sin_vinculo))


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Correr el prototipo**

Run: `python proyectos/2026-06-17-cuadre-facturas-xml-odoo/monitor_prototipo.py`
Expected (cuadra con DIAG): `moves junio: 431`, `draft ...: 77`, `sin_xml: 2`,
`lineas sin sku: 616`. Genera `resultados/monitor_junio.csv` y
`resultados/codigos_sin_vinculo.csv`.

- [ ] **Step 3: Validar casos canónicos a mano**

Abrir `monitor_junio.csv` y confirmar:
- una factura CCU/Embonor con ILA: `total_xml == total_odoo` → `verde` (o `rojo
  descuadre` si Odoo no capturó el ILA — hallazgo real).
- una NORKOSHE: aparece `amarillo` con `sin_sku` y en `codigos_sin_vinculo.csv`.
- las 77 draft: `amarillo no_contabilizado`.
- las 2 sin XML: `rojo sin_xml`.
Anotar hallazgos en `resultados/` (qué % cuadra, cuántos descuadres reales de ILA).

- [ ] **Step 4: Checkpoint con Marco** — revisar el CSV juntos antes de portar a
Server Action. Si las reglas necesitan ajuste, volver a Tarea 2.

---

## Tarea 5: Server Action productiva (safe_eval)

**Files:**
- Create: `proyectos/2026-06-17-cuadre-facturas-xml-odoo/OH Monitor Registro Compras.py`

Misma lógica, server-side. Copia el cuerpo de `dte_totales.py` y
`reglas_registro.py` (funciones puras) dentro del archivo. Lee moves vía `env`,
decodifica con `b64decode` (inyectado), escribe `x_studio_reg_*` con `.write()`,
retorna `display_notification`. **Antes de escribir, releer skill
`odoo-server-action-safe-eval`** (no import, no `obj.attr=x`, no closures sobre
locals de función).

- [ ] **Step 1: Escribir la Server Action**

Estructura (esqueleto; el engineer pega las funciones puras de Tareas 1-2 al tope,
hoisteadas a nivel módulo para evitar closures):

```python
# OH Monitor Registro Compras v1.0
# ir.actions.server / safe_eval. Lee facturas de compra del periodo, evalua error
# de registro, escribe x_studio_reg_* por move. SOLO write sobre moves existentes.

# --- funciones puras (copia EXACTA de dte_totales.py y reglas_registro.py) ---
TOL = 1
def _tag_int(xml, tag):
    ...  # (copiar de dte_totales.py)
def _sum_otros_imp(xml):
    ...
def totales_dte(xml):
    ...
def evaluar_move(m):
    ...
def _accion(color, errores):
    ...

# --- wiring server-side ---
P_INI = datetime.date.today().replace(day=1).isoformat()
P_FIN = datetime.date.today().isoformat()
Move = env['account.move']
moves = Move.search([('move_type', '=', 'in_invoice'),
                     ('invoice_date', '>=', P_INI), ('invoice_date', '<=', P_FIN)])

# duplicados por (rut,tipo,folio)
def _clave(m):
    rut = ''.join(c for c in (m.partner_id.vat or '') if c.isdigit())
    folio = (m.l10n_latam_document_number or '0').lstrip('0') or '0'
    return (rut, m.l10n_latam_document_type_id_code or '', folio)
vistos = {}
for m in moves:
    vistos[_clave(m)] = vistos.get(_clave(m), 0) + 1

resumen = {'verde': 0, 'amarillo': 0, 'rojo': 0}
monto_draft = 0
for m in moves:
    prod = m.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
    sin_sku = prod.filtered(lambda l: not l.product_id)
    tiene_xml = bool(m.l10n_cl_dte_file)
    tot = {'total': None, 'neto': 0, 'iva': 0, 'otros_imp': 0, 'exento': 0}
    if tiene_xml and m.l10n_cl_dte_file.datas:
        xml = b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore')
        tot = totales_dte(xml)
    v = evaluar_move({
        'state': m.state, 'amount_total': m.amount_total,
        'amount_untaxed': m.amount_untaxed, 'amount_tax': m.amount_tax,
        'tiene_xml': tiene_xml, 'tipo_code': m.l10n_latam_document_type_id_code,
        'xml_total': tot['total'], 'xml_neto': tot['neto'], 'xml_iva': tot['iva'],
        'xml_otros': tot['otros_imp'], 'n_lineas_prod': len(prod),
        'n_lineas_sin_sku': len(sin_sku), 'es_duplicado': vistos[_clave(m)] > 1})
    m.write({
        'x_studio_reg_color': v['color'], 'x_studio_reg_error': v['error'],
        'x_studio_reg_monto_riesgo': v['monto_riesgo'],
        'x_studio_reg_accion': v['accion'],
        'x_studio_reg_fecha_check': datetime.date.today()})
    resumen[v['color']] += 1
    if m.state == 'draft':
        monto_draft += m.amount_total

log('monitor registro: %s' % resumen)
action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
    'title': 'Monitor registro compras',
    'message': 'Periodo %s a %s | verde %s, amarillo %s, rojo %s | draft $%s' % (
        P_INI, P_FIN, resumen['verde'], resumen['amarillo'], resumen['rojo'],
        '{:,.0f}'.format(monto_draft)),
    'type': 'warning' if resumen['rojo'] else 'success', 'sticky': True}}
```

(El `filtered(lambda ...)` sobre `l.display_type`/`l.product_id` usa la variable del
comprehension/lambda como parámetro, no captura un local de función externa → OK en
safe_eval, verificado en prod. Las funciones puras se hoistean a nivel módulo.)

- [ ] **Step 2: Pre-chequeo de closures/opcodes** — releer el archivo buscando
`obj.attr =`, `import`, `getattr`, y lambdas que capturen locals de función. Si
alguna lambda referencia una variable de función externa, parametrizarla.

- [ ] **Step 3: Marco crea los campos Studio** (Tarea 6) y pega la Server Action en
Odoo con dominio acotado a 1 proveedor para probar (ej. NORKOSHE) — NO todo junio
en el primer run.

- [ ] **Step 4: Marco corre la Server Action de prueba** y confirma que el resumen
cuadra con el prototipo para ese proveedor. Si OK, ampliar a todo el período.

---

## Tarea 6: Campos Studio (Marco, en Odoo)

**Modelo:** `account.move`. Crear en Studio (tipo entre paréntesis):

| Campo | Tipo |
|---|---|
| `x_studio_reg_color` | Selección (verde/amarillo/rojo) o Char |
| `x_studio_reg_error` | Char |
| `x_studio_reg_monto_riesgo` | Monetario (o Float) |
| `x_studio_reg_accion` | Char |
| `x_studio_reg_fecha_check` | Fecha |

- [ ] **Step 1:** crear los 5 campos en Studio sobre `account.move`.
- [ ] **Step 2:** crear una **vista lista** "Cola de reparación" filtrada por
`x_studio_reg_color != verde`, ordenada por `x_studio_reg_monto_riesgo` desc.
- [ ] **Step 3:** confirmar nombres técnicos exactos (Studio puede sufijar) y, si
difieren, actualizar el `.write()` de la Server Action.

---

## Tarea 7: Cierre

- [ ] **Step 1:** Marco corre la Server Action sobre todo junio y revisa la cola.
- [ ] **Step 2:** documentar hallazgos en `resultados/` (descuadres ILA reales,
% touchless de junio = verdes / total).
- [ ] **Step 3 (git, con OK explícito de Marco):**

```bash
git add proyectos/2026-06-17-cuadre-facturas-xml-odoo/
git commit -m "facturas: monitor de error de registro de compras (Fase 1, deteccion)"
```

---

## Self-review (cobertura del spec)

- Completitud SII (5.2) → Tarea 3 (`concilia_sii`) + pendiente wiring del CSV SII
  en el prototipo: **GAP conocido** — el parseo del archivo RCV real depende de ver
  un export del SII (headers exactos). Se hace en una iteración chica cuando Marco
  suba un archivo de muestra; la función pura ya está testeada.
- Parser totales/ILA (5.3) → Tarea 1. Reglas/colores (5.4) → Tarea 2.
- Veredicto en move + cola Studio (5.5) → Tareas 5 y 6. Códigos sin vínculo (5.5)
  → Tarea 4 (prototipo) y extensión de la Server Action.
- Resumen (5.6) → Tarea 5 (notificación).
- safe_eval (5.7) → Tarea 5 (pre-chequeo) + skill.
- Casos canónicos (spec §7) → Tarea 4 Step 3.

**GAP a cerrar:** (1) wiring del CSV del RCV SII (necesita archivo de muestra).
(2) la Server Action de Tarea 5 aún no emite la lista de códigos sin vínculo como
adjunto — el prototipo sí; se agrega tras validar reglas.
