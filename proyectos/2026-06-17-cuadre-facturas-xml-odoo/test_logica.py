# Tests locales de las 3 funciones puras. Corre con: python test_logica.py (sin pytest)
from dte_totales import totales_dte
from reglas_registro import evaluar_move, TOL
from concilia_sii import clave, conciliar

XML_OK = (
    '<?xml version="1.0"?><DTE><Documento><Encabezado><Totales>'
    '<MntNeto>158221</MntNeto><IVA>30062</IVA><MntTotal>188283</MntTotal>'
    '</Totales></Encabezado></Documento></DTE>'
)
XML_ILA = (  # estructura real SII: impuesto adicional en <ImptoReten><MontoImp>
    '<Totales><MntNeto>1780</MntNeto><TasaIVA>19.00</TasaIVA><IVA>338</IVA>'
    '<ImptoReten><TipoImp>271</TipoImp><TasaImp>15.0</TasaImp><MontoImp>271</MontoImp></ImptoReten>'
    '<MntTotal>2389</MntTotal></Totales>'
)
XML_OTROSIMP = (  # forma alternativa <OtrosImp><MntImp>
    '<Totales><MntNeto>1000</MntNeto><IVA>190</IVA>'
    '<OtrosImp><CodImp>27</CodImp><MntImp>50</MntImp></OtrosImp>'
    '<MntTotal>1240</MntTotal></Totales>'
)
XML_EXENTA = '<Totales><MntExe>5000</MntExe><MntTotal>5000</MntTotal></Totales>'
XML_ROTO = '<Totales><MntNeto>100</MntNeto></Totales>'


def test_totales():
    t = totales_dte(XML_OK)
    assert t['neto'] == 158221 and t['iva'] == 30062 and t['total'] == 188283, t
    assert t['exento'] == 0 and t['otros_imp'] == 0, t

    t = totales_dte(XML_ILA)
    assert t['neto'] == 1780 and t['iva'] == 338, t
    assert t['otros_imp'] == 271 and t['total'] == 2389, t

    t = totales_dte(XML_OTROSIMP)
    assert t['otros_imp'] == 50 and t['total'] == 1240, t

    t = totales_dte(XML_EXENTA)
    assert t['exento'] == 5000 and t['total'] == 5000 and t['iva'] == 0, t

    t = totales_dte(XML_ROTO)
    assert t['total'] is None, t
    print("test_totales OK")


def _move(**kw):
    base = dict(state='posted', amount_total=188283, amount_untaxed=158221,
                amount_tax=30062, tiene_xml=True, tipo_code='33',
                xml_total=188283, xml_neto=158221, xml_iva=30062, xml_otros=0,
                xml_exento=0, n_lineas_prod=2, n_lineas_sin_sku=0, es_duplicado=False)
    base.update(kw)
    return base


def test_reglas():
    v = evaluar_move(_move())
    assert v['color'] == 'verde' and v['monto_riesgo'] == 0, v

    # total no cuadra -> rojo descuadre_total
    v = evaluar_move(_move(xml_total=200000))
    assert v['color'] == 'rojo' and 'descuadre_total' in v['error'], v
    assert v['monto_riesgo'] == 188283, v

    # total cuadra dentro de tolerancia -> verde
    v = evaluar_move(_move(xml_total=188283 + TOL))
    assert v['color'] == 'verde', v

    # total OK pero impuesto mal clasificado (>0.5%) -> amarillo impuesto_mal
    # total=188283 ok; tax Odoo 30062 vs XML iva+otros = 10000 -> diff 20062 > 941
    v = evaluar_move(_move(xml_iva=10000, xml_otros=0))
    assert v['color'] == 'amarillo' and 'impuesto_mal' in v['error'], v
    assert v['monto_riesgo'] == 20062, v

    # split chico (rounding) dentro de materialidad -> verde
    v = evaluar_move(_move(amount_tax=30064))  # diff 2 < max(100, 0.5%*188283)
    assert v['color'] == 'verde', v

    v = evaluar_move(_move(state='draft'))
    assert v['color'] == 'amarillo' and 'no_contabilizado' in v['error'], v

    v = evaluar_move(_move(n_lineas_sin_sku=1))
    assert v['color'] == 'amarillo' and 'sin_sku' in v['error'], v

    v = evaluar_move(_move(tiene_xml=False, xml_total=None))
    assert v['color'] == 'rojo' and 'sin_xml' in v['error'], v

    v = evaluar_move(_move(tipo_code='34', amount_tax=0, xml_iva=0,
                           amount_untaxed=5000, amount_total=5000,
                           xml_neto=0, xml_exento=5000, xml_total=5000))
    assert v['color'] == 'verde', v

    v = evaluar_move(_move(es_duplicado=True))
    assert v['color'] == 'rojo' and 'duplicado' in v['error'], v

    v = evaluar_move(_move(state='draft', xml_total=200000))
    assert v['color'] == 'rojo', v
    print("test_reglas OK")


def test_concilia():
    assert clave('76.853.601-5', '33', '003564') == ('768536015', '33', '3564'), \
        clave('76.853.601-5', '33', '003564')
    sii = [('768536015', '33', '3564'), ('931000001', '33', '10')]
    odoo = [('768536015', '33', '3564')]
    r = conciliar(sii_keys=sii, odoo_keys=odoo)
    assert r['faltan_en_odoo'] == [('931000001', '33', '10')], r
    assert r['sobran_en_odoo'] == [], r
    print("test_concilia OK")


if __name__ == '__main__':
    test_totales()
    test_reglas()
    test_concilia()
