"""Clasificacion de error por linea DTE<->Odoo. Funcion pura (sin Odoo).
Se copia tal cual dentro del Server Action; solo usa builtins permitidos.

clasificar_linea(l, it, ctx) -> {'tipo','valor','tax_sug'} | None
  l:  {'name','has_product','quantity','price_subtotal','tax_ids'(set)}
  it: {'nombre','codigo','ean','qty','prc','monto','imp'} | None si no alinea
  ctx:{'es_merc','es_tabaco','tax_by_id','sii_to_tax'}
      tax_by_id[id] = {'sii_code','price_include','amount','name'}
      sii_to_tax[sii_code] = [tax_id,...]
Prioridad: codigo > impuesto(tabaco/ILA) > precio/flete/uom.
"""

FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por')
# Tasa oficial del impuesto adicional por CodImpAdic del DTE (SII).
# 25 y 26 = 20,5% (vino y cerveza misma tasa -> se valida por TASA, no por codigo).
RATE_ILA = {'24': 31.5, '25': 20.5, '26': 20.5, '27': 10.0, '271': 18.0}
SII_IVA = 14
TAX_TABACO = 17
TOL_TASA = 0.3      # pp de tolerancia al comparar tasas


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f


def clasificar_linea(l, it, ctx):
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
