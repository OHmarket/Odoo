# OH Detector Error DTE v1.3  (ir.actions.server / safe_eval) — Cron 1
# Barre facturas de compra del periodo, clasifica cada linea (funcion pura
# clasificar_linea) y recrea x_error_dte. Tipos por linea: codigo_no_vinculado,
# impuesto_mal_clasificado, precio, flete_descuadrado, uom_no_cuadra,
# linea_descuadrada. Nivel-factura: draft, sin_xml, duplicado.
# Deja cada fila ACCIONABLE (x_studio_line_id / valor_correcto / tax_sugerido /
# product_id) para el fixer de Fase 2. Este SA solo DETECTA: create en x_error_dte,
# nunca write en account.move(.line).
# safe_eval: sin import (b64decode inyectado), string parse, defs top-level,
# x_name required, no obj.attr=x.

HOY = datetime.date.today()
DESDE = HOY.replace(day=1).isoformat()
if HOY.month == 12:
    _fin = datetime.date(HOY.year + 1, 1, 1)
else:
    _fin = datetime.date(HOY.year, HOY.month + 1, 1)
HASTA = (_fin - datetime.timedelta(days=1)).isoformat()

# --- constantes de negocio ---
PROV_TABACO = {'885029000'}                 # BAT 88502900-0 (solo digitos). Extensible.
TAX_TABACO = 17                             # IVA Compra 19% No Recup.
# Tasa oficial del impuesto adicional por CodImpAdic (SII). 25 y 26 = 20,5%
# (vino y cerveza misma tasa -> se valida por TASA, no por codigo).
RATE_ILA = {'24': 31.5, '25': 20.5, '26': 20.5, '27': 10.0, '271': 18.0}
SII_IVA = 14
TOL_TASA = 0.3
FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por')


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


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


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


def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f


def clasificar_linea(l, it, ctx):
    """Funcion PURA. l: dict linea Odoo; it: dict item DTE (o None); ctx: contexto.
    Devuelve {'tipo','valor','tax_sug'} o None. Prioridad:
    codigo > impuesto(tabaco/ILA) > precio/flete/uom."""
    tax_ids = set(l.get('tax_ids') or ())
    tax_by_id = ctx['tax_by_id']

    # 1) CODIGO NO IDENTIFICADO: mercaderia, sin producto, no flete
    if ctx['es_merc'] and not l['has_product'] and not _es_flete(l['name']):
        return {'tipo': 'codigo_no_vinculado', 'valor': None, 'tax_sug': None}

    # 2) IMPUESTO — tabaco (regla por proveedor): debe ser exactamente {17}
    if ctx['es_tabaco'] and tax_ids != {TAX_TABACO}:
        return {'tipo': 'impuesto_mal_clasificado', 'valor': None, 'tax_sug': TAX_TABACO}

    # 2b) IMPUESTO — ILA por TASA (no por codigo): cod 25 y 26 son ambos 20,5%,
    # reusar el mismo tax es correcto. Marca solo si la tasa ILA de la linea no
    # coincide con la oficial del CodImpAdic (faltante = tasa 0, o tasa errada).
    if it and it['imp'] in RATE_ILA:
        expected = RATE_ILA[it['imp']]
        actual = 0.0
        for t in tax_ids:
            tt = tax_by_id.get(t)
            if tt and tt['sii_code'] != SII_IVA:
                actual += tt['amount']
        if abs(actual - expected) > TOL_TASA:
            return {'tipo': 'impuesto_mal_clasificado', 'valor': None,
                    'tax_sug': ctx['rate_to_tax'].get(round(expected, 1))}

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
    return None


# --- entorno Odoo ---
Err = env['x_error_dte']
Prod = env['product.product']


def find_product(codigo, ean, nombre):
    """Recomienda producto SOLO si el match es unico. Devuelve recordset (vacio si dudoso)."""
    if ean:
        p = Prod.search([('barcode', '=', ean), ('active', 'in', [True, False])], limit=2)
        if len(p) == 1:
            return p
    if codigo:
        p = Prod.search([('default_code', '=', codigo), ('active', 'in', [True, False])], limit=2)
        if len(p) == 1:
            return p
    if nombre:
        p = Prod.search([('name', '=ilike', nombre), ('active', 'in', [True, False])], limit=2)
        if len(p) == 1:
            return p
    return Prod


def crear(key, vals):
    vals['x_name'] = key
    vals['x_studio_estado'] = 'pendiente'
    Err.create(vals)


# --- catalogo de impuestos de compra (una vez) ---
_taxes = env['account.tax'].search([('type_tax_use', '=', 'purchase')])
tax_by_id = {}
rate_to_tax = {}   # tasa -> tax id no-IVA, variante "(2024)" (no price_include)
# ordenado por sii_code asc: a igual tasa, gana el codigo mas bajo
# (20,5% -> 25 Vinos, no 26 Cervezas; cod 25 y 26 recomiendan ambos el 25).
for t in _taxes.sorted(lambda x: (x.l10n_cl_sii_code or 0)):
    tax_by_id[t.id] = {'sii_code': t.l10n_cl_sii_code, 'price_include': t.price_include,
                       'amount': t.amount, 'name': t.name}
    if t.l10n_cl_sii_code != SII_IVA and not t.price_include:
        rate_to_tax.setdefault(round(t.amount, 1), t.id)

Move = env['account.move']
moves = Move.search([('move_type', '=', 'in_invoice'),
                     ('invoice_date', '>=', DESDE), ('invoice_date', '<=', HASTA)])


# duplicados: (rut,tipo,folio)
def _clave(m):
    rut = ''
    for ch in (m.partner_id.vat or ''):
        if ch.isdigit():
            rut += ch
    folio = (m.l10n_latam_document_number or '0').lstrip('0') or '0'
    return rut + '|' + (m.l10n_latam_document_type_id_code or '') + '|' + folio


clave_cont = {}
for m in moves:
    k = _clave(m)
    clave_cont[k] = clave_cont.get(k, 0) + 1

# borra TODO al inicio y recrea solo lo que detecta -> los arreglados desaparecen
Err.search([]).unlink()

n = 0
for m in moves:
    base = {'x_studio_factura': m.id, 'x_studio_proveedor': m.partner_id.id,
            'x_studio_fecha_check': HOY}
    nm = m.name

    # --- nivel factura: draft / duplicado / sin_xml ---
    if m.state == 'draft':
        v = dict(base); v.update({'x_studio_tipo_error': 'draft', 'x_studio_codigo': '',
                                  'x_studio_monto_riesgo': m.amount_total,
                                  'x_studio_sugerencia': 'postear'})
        crear(nm + ':draft:', v); n += 1

    if clave_cont.get(_clave(m), 0) > 1:
        v = dict(base); v.update({'x_studio_tipo_error': 'duplicado', 'x_studio_codigo': '',
                                  'x_studio_monto_riesgo': m.amount_total,
                                  'x_studio_sugerencia': 'anular duplicado'})
        crear(nm + ':duplicado:', v); n += 1

    if not m.l10n_cl_dte_file or not m.l10n_latam_document_type_id_code:
        v = dict(base); v.update({'x_studio_tipo_error': 'sin_xml', 'x_studio_codigo': '',
                                  'x_studio_monto_riesgo': m.amount_total,
                                  'x_studio_sugerencia': 'registrar DTE'})
        crear(nm + ':sin_xml:', v); n += 1
        continue

    # --- por linea: clasificador puro ---
    items = parse_items(b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore'))
    prod_lines = m.invoice_line_ids.filtered(lambda x: x.display_type == 'product')
    prod_lines = prod_lines.sorted(lambda x: (x.sequence, x.id))
    alineada = (len(prod_lines) == len(items) and len(items) > 0)

    vat = ''
    for ch in (m.partner_id.vat or ''):
        if ch.isdigit():
            vat += ch
    ctx = {'es_merc': (m.partner_id.x_studio_tipo_proveedor == 'Mercaderia'),
           'es_tabaco': vat in PROV_TABACO,
           'tax_by_id': tax_by_id, 'rate_to_tax': rate_to_tax}

    pos = 0
    for l in prod_lines:
        it = items[pos] if alineada else None
        pos += 1
        ld = {'name': l.name or '', 'has_product': bool(l.product_id),
              'quantity': l.quantity, 'price_subtotal': l.price_subtotal,
              'tax_ids': set(l.tax_ids.ids)}
        r = clasificar_linea(ld, it, ctx)
        if not r:
            continue
        riesgo = abs((it['monto'] if it else l.price_subtotal) - l.price_subtotal)
        if riesgo < 1:
            riesgo = l.price_subtotal
        v = dict(base)
        v['x_studio_tipo_error'] = r['tipo']
        v['x_studio_line_id'] = l.id
        v['x_studio_codigo'] = (it['codigo'] if it else '') or ''
        v['x_studio_monto_riesgo'] = riesgo
        if r['valor'] is not None:
            v['x_studio_valor_correcto'] = r['valor']
        if r['tax_sug']:
            v['x_studio_tax_sugerido'] = r['tax_sug']
        if r['tipo'] == 'codigo_no_vinculado':
            prod = find_product(it['codigo'] if it else '', it['ean'] if it else '', l.name)
            if prod:
                v['x_studio_product_id'] = prod.id
                sug = 'vincular a ' + prod.name
                if it and it['codigo'] and prod.default_code != it['codigo']:
                    sug += ' | poblar default_code con ' + it['codigo']
                v['x_studio_sugerencia'] = sug
            else:
                v['x_studio_sugerencia'] = 'revisar: producto ambiguo/no encontrado'
        elif r['tipo'] == 'precio':
            v['x_studio_sugerencia'] = 'DIGITAR price_unit $%s (neto DTE) - %s' % (
                r['valor'], (it['nombre'][:24] if it else ''))
        elif r['tipo'] == 'impuesto_mal_clasificado':
            tn = tax_by_id.get(r['tax_sug'], {}).get('name', '?') if r['tax_sug'] else '?'
            v['x_studio_sugerencia'] = 'aplicar impuesto: %s' % tn
        elif r['tipo'] == 'flete_descuadrado':
            v['x_studio_sugerencia'] = 'flete Odoo $%s vs DTE $%s - revisar' % (
                int(round(l.price_subtotal)), int(round(it['monto'])) if it else '?')
        else:
            v['x_studio_sugerencia'] = 'revisar linea (qty/uom)'
        crear('%s:%s:%s' % (nm, r['tipo'], l.id), v)
        n += 1

log('detector error dte v1.3: %s filas, %s facturas (%s a %s)' % (n, len(moves), DESDE, HASTA))
action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
    'title': 'Detector Error DTE v1.3',
    'message': '%s errores detectados en %s facturas' % (n, len(moves)),
    'type': 'success', 'sticky': True}}
