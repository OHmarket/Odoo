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
    # los totales SII son enteros (CLP); tolerar decimales/signo
    try:
        return int(round(float(txt)))
    except (ValueError, TypeError):
        return None


def _sum_tag(xml, tag):
    """Suma todas las apariciones del entero dentro de <tag>...</tag>."""
    total = 0
    i = 0
    open_t, close_t = '<' + tag + '>', '</' + tag + '>'
    while True:
        a = xml.find(open_t, i)
        if a == -1:
            break
        a += len(open_t)
        b = xml.find(close_t, a)
        if b == -1:
            break
        try:
            total += int(round(float(xml[a:b].strip())))
        except (ValueError, TypeError):
            pass
        i = b
    return total


def _sum_imp_adicionales(xml):
    """Impuestos adicionales del DTE (ILA, retenciones, otros).
    El SII los pone como <ImptoReten><MontoImp> y/o <OtrosImp><MntImp>.
    Odoo los suma junto al IVA en amount_tax."""
    return _sum_tag(xml, 'MontoImp') + _sum_tag(xml, 'MntImp')


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
        'otros_imp': _sum_imp_adicionales(xml),
        'total': total,  # None si falta el tag
    }
