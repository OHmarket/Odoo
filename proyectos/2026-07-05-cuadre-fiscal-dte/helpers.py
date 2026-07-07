"""helpers — funciones PURAS (sin env) del SA OH Cuadre Fiscal DTE.

Se testean local con `python tests/test_helpers.py` (sin Odoo) y se copian
literalmente dentro del Server Action safe_eval. Fuente de verdad testeada.
"""


def dte_mnt_total(xml):
    """MntTotal del DTE (0 si no lo encuentra)."""
    a = xml.find('<MntTotal>')
    if a == -1:
        return 0
    a += len('<MntTotal>')
    b = xml.find('</MntTotal>', a)
    if b == -1:
        return 0
    try:
        return int(round(float(xml[a:b].strip())))
    except (ValueError, TypeError):
        return 0


# Tipos de error de x_error_dte que BLOQUEAN el posteo (todo menos 'draft').
BLOQUEAN = frozenset({'codigo_no_vinculado', 'impuesto_mal_clasificado', 'precio',
                      'linea_descuadrada', 'flete_descuadrado', 'uom_no_cuadra',
                      'duplicado', 'sin_xml'})


def decide_post(tipos_error, delta, tol):
    """(True,'ok') si la factura se postea; si no (False, motivo).
    Bloquea cualquier tipo de error != 'draft' y |delta| > tol."""
    bloq = BLOQUEAN & set(tipos_error)
    if bloq:
        return (False, 'bloquea:' + ','.join(sorted(bloq)))
    if abs(delta) > tol:
        return (False, 'descuadre $%.0f' % delta)
    return (True, 'ok')


def _solo_digitos(s):
    r = ''
    for ch in (s or ''):
        if ch.isdigit():
            r += ch
    return r


# Palabras que marcan una linea como flete/cargo (no producto, sin SKU legitimo).
FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por')


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def sku_ok(lines):
    """False si alguna linea de PRODUCTO (no flete) no tiene producto vinculado.
    lines: list de dicts {'is_product': bool, 'has_product': bool, 'name': str}.
    Las lineas de flete/cargo (display_type='product' sin product_id) NO cuentan."""
    for l in lines:
        if l['is_product'] and not l['has_product'] and not _es_flete(l['name']):
            return False
    return True


def es_tabaco(vat, prov_set):
    """True si el RUT (solo digitos) esta en prov_set."""
    return _solo_digitos(vat) in prov_set


# --- parseo de lineas del DTE (copiado de OH Detector Error DTE.py) ---
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


def price_fixes(odoo_lines, items):
    """Lineas a corregir por precio pisado -> [(line_id, pu_target)].
    odoo_lines: dicts {'id','name','quantity','price_subtotal','factor'} EN ORDEN.
    items: salida de parse_items. Ver diseno-paso15-fix-precio.md §6.
    Excluye a proposito el redondeo de fraccion de pack (qty != QtyItem = trampa UoM):
    ahi el precio unitario ya es el correcto del DTE."""
    if len(odoo_lines) != len(items) or not items:
        return []
    out = []
    for l, it in zip(odoo_lines, items):
        qty = l['quantity']
        if qty == 0:
            continue
        if abs(qty - it['qty']) > 0.001:                    # redondeo/uom -> excluir
            continue
        if abs(l['price_subtotal'] - it['monto']) <= 1.0:   # ya cuadra
            continue
        if _es_flete(l['name']):                            # flete -> cola humana
            continue
        out.append((l['id'], round((it['monto'] / qty) * l['factor'], 2)))
    return out


def motivo_no_cuadra(odoo_lines, items, delta):
    """Clasifica por que la factura no cuadro (para la nota del chatter).
    Primer match gana. odoo_lines/items en orden (como price_fixes).
    Loops planos a proposito: se copia dentro del SA safe_eval (sin genexp
    dentro de def, para no arriesgar MAKE_CELL)."""
    if len(odoo_lines) != len(items) or not items:
        return 'conteo_lineas'
    desc = []
    for l, it in zip(odoo_lines, items):
        if abs(l['price_subtotal'] - it['monto']) > 1.0:
            desc.append((l, it))
    if not desc:
        return 'residuo'
    todos_redondeo = True
    hay_flete = False
    for (l, it) in desc:
        if abs(l['quantity'] - it['qty']) <= 0.001:
            todos_redondeo = False
        if _es_flete(l['name']):
            hay_flete = True
    if todos_redondeo:
        return 'redondeo_uom'
    if hay_flete:
        return 'flete_descuadrado'
    return 'residuo'
