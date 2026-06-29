"""Motor de reglas de error de registro. Funcion pura, sin Odoo.
Copiar tal cual dentro de la Server Action (solo usa builtins permitidos)."""

TOL = 1            # tolerancia de redondeo del TOTAL en CLP
SPLIT_ABS = 100    # piso de materialidad para el split neto/impuesto
SPLIT_PCT = 0.005  # 0.5% del total: sobre eso el split se considera material

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
        d_total = abs(m['xml_total'] - m['amount_total'])
        # impuesto del DTE = IVA + adicionales (ILA/retencion/tabaco); Odoo los
        # suma en amount_tax. Si total OK pero el split difiere -> impuesto mal.
        d_tax = abs((m['xml_iva'] + m['xml_otros']) - m['amount_tax'])
        split_tol = max(SPLIT_ABS, SPLIT_PCT * m['amount_total'])
        if d_total > TOL:
            # ROJO: el total a pagar no coincide con el DTE
            errores.append('descuadre_total')
            riesgo = max(riesgo, m['amount_total'])
        elif d_tax > split_tol:
            # AMARILLO: total OK pero impuesto (ILA/tabaco) mal clasificado
            errores.append('impuesto_mal')
            riesgo = max(riesgo, d_tax)
    elif m['tiene_xml'] and m.get('xml_total') is None:
        errores.append('xml_no_parseable')
        riesgo = max(riesgo, m['amount_total'])

    # --- AMARILLO ---
    if m['state'] == 'draft':
        errores.append('no_contabilizado')
        riesgo = max(riesgo, m['amount_total'])
    if m['n_lineas_sin_sku'] > 0:
        errores.append('sin_sku')
        riesgo = max(riesgo, m['amount_total'])

    rojos = {'sin_xml', 'duplicado', 'descuadre_total', 'xml_no_parseable'}
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
    if 'descuadre_total' in errores or 'xml_no_parseable' in errores:
        msg.append('revisar total vs DTE')
    if 'impuesto_mal' in errores:
        msg.append('revisar impuesto/ILA en maestro')
    if 'no_contabilizado' in errores:
        msg.append('postear')
    if 'sin_sku' in errores:
        msg.append('vincular SKU en maestro')
    return '; '.join(msg)
