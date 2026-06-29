"""Extrae los items del <Detalle> del DTE SII por string (sin xml parser).
Cada item: codigo de proveedor (CdgItem/VlrCodigo), nombre (NmbItem), monto.
Mismo enfoque que dte_totales: corre identico dentro de safe_eval."""


def _between(s, open_t, close_t):
    a = s.find(open_t)
    if a == -1:
        return None
    a += len(open_t)
    b = s.find(close_t, a)
    if b == -1:
        return None
    return s[a:b].strip()


def items_dte(xml):
    """Lista de dicts {codigo, nombre, monto} por linea del Detalle."""
    out = []
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        cod = _between(blk, '<VlrCodigo>', '</VlrCodigo>')
        nmb = _between(blk, '<NmbItem>', '</NmbItem>')
        monto = _between(blk, '<MontoItem>', '</MontoItem>')
        out.append({'codigo': cod or '', 'nombre': (nmb or '').strip(),
                    'monto': monto or ''})
        i = b
    return out
