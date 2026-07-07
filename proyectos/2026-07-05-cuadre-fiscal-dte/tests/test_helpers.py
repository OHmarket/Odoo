"""Tests de los helpers puros. Correr: python tests/test_helpers.py (sin pytest)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import (dte_mnt_total, decide_post, sku_ok, es_tabaco,  # noqa: E402
                     parse_items, price_fixes, motivo_no_cuadra)


def test_dte_mnt_total():
    xml = '<Totales><MntNeto>502677</MntNeto><IVA>95509</IVA><MntTotal>598186</MntTotal></Totales>'
    assert dte_mnt_total(xml) == 598186
    assert dte_mnt_total('<Totales><MntNeto>1</MntNeto></Totales>') == 0   # sin MntTotal
    assert dte_mnt_total('') == 0
    assert dte_mnt_total('<MntTotal>1678588.0</MntTotal>') == 1678588      # con decimal


def test_decide_post():
    assert decide_post({'draft'}, 0.0, 2.0) == (True, 'ok')
    assert decide_post(set(), 1.0, 2.0) == (True, 'ok')                    # sin errores, delta bajo tol
    ok, motivo = decide_post({'draft', 'impuesto_mal_clasificado'}, 0.0, 2.0)
    assert ok is False and 'impuesto_mal_clasificado' in motivo
    ok, motivo = decide_post({'draft', 'codigo_no_vinculado'}, 0.0, 2.0)
    assert ok is False and 'codigo_no_vinculado' in motivo
    ok, motivo = decide_post({'draft', 'precio'}, 0.0, 2.0)
    assert ok is False and 'precio' in motivo
    ok, motivo = decide_post({'draft'}, 8.0, 2.0)                          # cuadra en tipos pero descuadre monto
    assert ok is False and 'descuadre' in motivo


def test_sku_ok():
    assert sku_ok([{'is_product': True, 'has_product': True, 'name': 'CERVEZA'}]) is True
    assert sku_ok([{'is_product': True, 'has_product': True, 'name': 'X'},
                   {'is_product': False, 'has_product': False, 'name': 'IVA'}]) is True   # tax line OK
    assert sku_ok([{'is_product': True, 'has_product': False, 'name': 'PRODUCTO RARO'}]) is False   # producto sin SKU
    # flete/recargo con display_type='product' y sin product_id NO cuentan
    assert sku_ok([{'is_product': True, 'has_product': False, 'name': 'Flete de Mercaderias'}]) is True
    assert sku_ok([{'is_product': True, 'has_product': False, 'name': 'RECARGO'}]) is True
    assert sku_ok([]) is True


def test_es_tabaco():
    assert es_tabaco('88502900-0', {'885029000'}) is True
    assert es_tabaco('88.502.900-0', {'885029000'}) is True               # con puntos/guion
    assert es_tabaco('99554560-8', {'885029000'}) is False
    assert es_tabaco('', {'885029000'}) is False


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


def test_price_fixes():
    items = [{'qty': 24.0, 'monto': 506433.0}, {'qty': 8.0, 'monto': 168781.0}]
    # ambas pisadas (subtotal 0), qty coincide, factor 1.0 (no price_include)
    ol = [{'id': 1, 'name': 'GIN A', 'quantity': 24.0, 'price_subtotal': 0.0, 'factor': 1.0},
          {'id': 2, 'name': 'GIN B', 'quantity': 8.0, 'price_subtotal': 0.0, 'factor': 1.0}]
    assert price_fixes(ol, items) == [(1, 21101.38), (2, 21097.62)]

    # factor price_include (ILA 31,5%): pu se grosea
    ol2 = [{'id': 3, 'name': 'GIN C', 'quantity': 24.0, 'price_subtotal': 0.0, 'factor': 1.315}]
    assert price_fixes(ol2, [{'qty': 24.0, 'monto': 506433.0}]) == [(3, round(506433.0 / 24 * 1.315, 2))]

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


if __name__ == '__main__':
    test_dte_mnt_total(); print('OK test_dte_mnt_total')
    test_decide_post(); print('OK test_decide_post')
    test_sku_ok(); print('OK test_sku_ok')
    test_es_tabaco(); print('OK test_es_tabaco')
    test_parse_items(); print('OK test_parse_items')
    test_price_fixes(); print('OK test_price_fixes')
    test_motivo_no_cuadra(); print('OK test_motivo_no_cuadra')
    print('== todos los tests OK ==')
