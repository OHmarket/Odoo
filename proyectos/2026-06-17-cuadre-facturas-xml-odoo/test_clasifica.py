"""Asserts locales de clasificar_linea (sin pytest). Corre: python test_clasifica.py
Casos canonicos = datos reales validados 2026-06-18."""
from clasifica_linea import clasificar_linea


def test_codigo():
    CTX = {'es_merc': True, 'es_tabaco': False, 'tax_by_id': {}, 'sii_to_tax': {}}
    l = {'name': 'PK 2 Trencito 150g', 'has_product': False,
         'quantity': 1, 'price_subtotal': 4990, 'tax_ids': set()}
    it = {'nombre': 'PK 2 Trencito', 'codigo': '', 'ean': '', 'qty': 1,
          'prc': 4990, 'monto': 4990, 'imp': ''}
    assert clasificar_linea(l, it, CTX)['tipo'] == 'codigo_no_vinculado'
    # flete sin producto -> NO codigo
    r = clasificar_linea(dict(l, name='Delivery Latas'), it, CTX)
    assert r is None or r['tipo'] != 'codigo_no_vinculado'
    # no mercaderia -> no marca codigo
    r = clasificar_linea(l, it, dict(CTX, es_merc=False))
    assert r is None or r['tipo'] != 'codigo_no_vinculado'
    print('test_codigo OK')


def test_impuesto():
    # tabaco: tax_ids != {17} -> impuesto, tax_sug=17
    ctx_t = {'es_merc': False, 'es_tabaco': True, 'tax_by_id': {}, 'rate_to_tax': {}}
    l = {'name': 'Pall Mall Azul', 'has_product': True, 'quantity': 1,
         'price_subtotal': 37999, 'tax_ids': set()}
    it = {'nombre': 'Pall Mall', 'codigo': '', 'ean': '', 'qty': 1,
          'prc': 31613, 'monto': 31613, 'imp': '14'}
    r = clasificar_linea(l, it, ctx_t)
    assert r['tipo'] == 'impuesto_mal_clasificado' and r['tax_sug'] == 17, r
    r = clasificar_linea(dict(l, tax_ids={17}), it, ctx_t)
    assert r is None or r['tipo'] != 'impuesto_mal_clasificado', r

    # ILA por TASA. cod 25 y 26 = 20,5%, 24 = 31,5%, 27 = 10%
    tax_by_id = {2: {'sii_code': 14, 'price_include': False, 'amount': 19, 'name': 'IVA'},
                 11: {'sii_code': 25, 'price_include': False, 'amount': 20.5, 'name': 'Vinos'},
                 12: {'sii_code': 24, 'price_include': False, 'amount': 31.5, 'name': 'ILA 31.5'},
                 9: {'sii_code': 27, 'price_include': False, 'amount': 10.0, 'name': 'Beb 10'}}
    rate_to_tax = {20.5: 11, 31.5: 12, 10.0: 9}
    ctx_i = {'es_merc': False, 'es_tabaco': False, 'tax_by_id': tax_by_id,
             'rate_to_tax': rate_to_tax}

    # cerveza cod 26 con Vinos 20,5% -> tasa calza -> NO marca (clave de Marco)
    l_cerv = {'name': 'CERVEZA', 'has_product': True, 'quantity': 120,
              'price_subtotal': 60000, 'tax_ids': {2, 11}}
    it_cerv = {'nombre': 'cerv', 'codigo': '', 'ean': '', 'qty': 120,
               'prc': 500, 'monto': 60000, 'imp': '26'}
    assert clasificar_linea(l_cerv, it_cerv, ctx_i) is None, clasificar_linea(l_cerv, it_cerv, ctx_i)

    # radler cod 27 SIN ILA -> tasa 0 != 10 -> marca faltante, tax_sug=9
    l_rad = {'name': 'RADLER', 'has_product': True, 'quantity': 1,
             'price_subtotal': 8320, 'tax_ids': {2}}
    it_rad = {'nombre': 'rad', 'codigo': '', 'ean': '', 'qty': 1,
              'prc': 8320, 'monto': 8320, 'imp': '27'}
    r = clasificar_linea(l_rad, it_rad, ctx_i)
    assert r['tipo'] == 'impuesto_mal_clasificado' and r['tax_sug'] == 9, r

    # licor cod 24 con tax 20,5% donde va 31,5% -> tasa errada -> marca, tax_sug=12
    l_lic = {'name': 'PISCO', 'has_product': True, 'quantity': 1,
             'price_subtotal': 10000, 'tax_ids': {2, 11}}
    it_lic = {'nombre': 'pisco', 'codigo': '', 'ean': '', 'qty': 1,
              'prc': 10000, 'monto': 10000, 'imp': '24'}
    r = clasificar_linea(l_lic, it_lic, ctx_i)
    assert r['tipo'] == 'impuesto_mal_clasificado' and r['tax_sug'] == 12, r
    print('test_impuesto OK')


def test_precio_flete():
    ctx = {'es_merc': False, 'es_tabaco': False, 'tax_by_id': {}, 'sii_to_tax': {}}
    # precio: valor desde MontoItem/Qty (12306), NO PrcItem (18710)
    l = {'name': 'VINO MERLOT', 'has_product': True, 'quantity': 30,
         'price_subtotal': 256951, 'tax_ids': set()}
    it = {'nombre': 'VINO', 'codigo': '', 'ean': '', 'qty': 30,
          'prc': 18710, 'monto': 369180, 'imp': ''}
    r = clasificar_linea(l, it, ctx)
    assert r['tipo'] == 'precio' and r['valor'] == 12306.0, r

    lf = {'name': 'Delivery Latas', 'has_product': True, 'quantity': 240,
          'price_subtotal': 171216, 'tax_ids': set()}
    itf = {'nombre': 'Delivery', 'codigo': '', 'ean': '', 'qty': 240,
           'prc': 1300, 'monto': 312000, 'imp': ''}
    r = clasificar_linea(lf, itf, ctx)
    assert r['tipo'] == 'flete_descuadrado' and r['valor'] is None, r

    lu = {'name': 'CERVEZA', 'has_product': True, 'quantity': 1,
          'price_subtotal': 6000, 'tax_ids': set()}
    itu = {'nombre': 'Cerveza', 'codigo': '', 'ean': '', 'qty': 12,
           'prc': 500, 'monto': 6000, 'imp': ''}
    assert clasificar_linea(lu, itu, ctx)['tipo'] == 'uom_no_cuadra'

    lo = {'name': 'OK', 'has_product': True, 'quantity': 2,
          'price_subtotal': 1000, 'tax_ids': set()}
    ito = {'nombre': 'ok', 'codigo': '', 'ean': '', 'qty': 2,
           'prc': 500, 'monto': 1000, 'imp': ''}
    assert clasificar_linea(lo, ito, ctx) is None

    # precio con price_include: factor 1.19
    tbi = {28: {'sii_code': 14, 'price_include': True, 'amount': 19, 'name': 'IVA OC'}}
    lpi = {'name': 'X', 'has_product': True, 'quantity': 1,
           'price_subtotal': 1000, 'tax_ids': {28}}
    itpi = {'nombre': 'x', 'codigo': '', 'ean': '', 'qty': 1,
            'prc': 0, 'monto': 1190, 'imp': ''}
    r = clasificar_linea(lpi, itpi, dict(ctx, tax_by_id=tbi))
    assert r['tipo'] == 'precio' and round(r['valor']) == 1416, r  # 1190*1.19
    print('test_precio_flete OK')


if __name__ == '__main__':
    test_codigo()
    test_impuesto()
    test_precio_flete()
    print('TODOS OK')
