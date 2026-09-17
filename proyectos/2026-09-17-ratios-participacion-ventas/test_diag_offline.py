# -*- coding: utf-8 -*-
"""Corrida en seco del DIAG contra un env FALSO (plan de cuentas y mayor
inventados). No toca Odoo. Sirve para validar formato, signos y controles
antes de pegar el script en produccion.

  python3 test_diag_offline.py            -> caso normal
  python3 test_diag_offline.py sin_cogs    -> sin costo de venta valorizado
  python3 test_diag_offline.py sin_venta   -> denominador 0 (corte duro)
  python3 test_diag_offline.py pos_gap     -> contabilidad no captura toda la venta
"""
import datetime as _dt
import io
import sys


class UserError(Exception):
    pass


# --- plan de cuentas falso -------------------------------------------------
ACCS = [
    (1, '4101', 'Ingresos por venta mercaderia', 'income'),
    (2, '4102', 'Ingresos por venta exenta', 'income'),
    (3, '4301', 'Otros ingresos fuera de explotacion', 'income_other'),
    (4, '5101', 'Costo de venta mercaderia', 'expense_direct_cost'),
    (5, '5201', 'Arriendo locales comerciales', 'expense'),
    (6, '5202', 'Gastos comunes locales', 'expense'),
    (7, '5203', 'Electricidad', 'expense'),
    (8, '5204', 'Agua potable', 'expense'),
    (9, '5205', 'Remuneraciones personal sala', 'expense'),
    (10, '5206', 'Leyes sociales', 'expense'),
    (11, '5207', 'Comision tarjeta Transbank', 'expense'),
    (12, '5208', 'Mermas de inventario', 'expense'),
    (13, '5209', 'Patente municipal', 'expense'),
    (14, '5210', 'Honorarios contables', 'expense'),
    (15, '5211', 'Publicidad y promocion', 'expense'),
    (16, '5212', 'Internet y telefonia', 'expense'),
    (17, '5213', 'Utiles de aseo y seguridad', 'expense'),
    (18, '5299', 'Gastos varios sin glosa', 'expense'),
    (19, '5301', 'Depreciacion del ejercicio', 'expense_depreciation'),
]

# balance MENSUAL por cuenta (signo Odoo: ingreso negativo, gasto positivo)
MENSUAL = {
    1: -180000000.0, 2: -12000000.0, 3: -1500000.0,
    4: 142000000.0,
    5: 9500000.0, 6: 1200000.0, 7: 4200000.0, 8: 650000.0,
    9: 18000000.0, 10: 3600000.0, 11: 2900000.0, 12: 1100000.0,
    13: 400000.0, 14: 900000.0, 15: 600000.0, 16: 350000.0,
    17: 450000.0, 18: 800000.0, 19: 1500000.0,
}

MODO = sys.argv[1] if len(sys.argv) > 1 else 'normal'
if MODO == 'sin_cogs':
    MENSUAL[4] = 0.0
if MODO == 'sin_venta':
    MENSUAL[1] = 0.0
    MENSUAL[2] = 0.0
if MODO == 'pos_gap':
    # la contabilidad captura solo la mitad de la venta que paso por caja
    MENSUAL[1] = -90000000.0


class FieldsStub(dict):
    pass


class AccountStub(object):
    _fields = FieldsStub({'code': 1, 'name': 1, 'account_type': 1})

    def search_read(self, domain, fields):
        tipos = domain[0][2]
        out = []
        for a in ACCS:
            if a[3] in tipos:
                out.append({'id': a[0], 'code': a[1], 'name': a[2], 'account_type': a[3]})
        return out


class AmlStub(object):
    _fields = FieldsStub({'parent_state': 1, 'balance': 1, 'date': 1})

    def read_group(self, domain, aggs, groupby):
        acc_ids = None
        for d in domain:
            if d[0] == 'account_id':
                acc_ids = d[2]
        rows = []
        for aid in acc_ids:
            bal = MENSUAL.get(aid, 0.0)
            if bal:
                rows.append({'account_id': (aid, 'cuenta %s' % aid),
                             'balance': bal, '__count': 12})
        return rows


class AmStub(object):
    _fields = FieldsStub({})

    def read_group(self, domain, aggs, groupby):
        return [{'amount_untaxed_signed': 41000000.0, '__count': 118}]


class PosStub(object):
    _fields = FieldsStub({})

    def read_group(self, domain, aggs, groupby):
        # 7 meses * (180M + 12M) netos -> bruto aprox con IVA sobre lo afecto
        return [{'amount_total': 7 * (180000000.0 * 1.19 + 12000000.0), '__count': 999}]


class CompanyStub(object):
    id = 1
    name = 'OH! Market SpA (FAKE)'


class CompaniesStub(object):
    ids = [1]


class EnvStub(object):
    company = CompanyStub()
    companies = CompaniesStub()

    def __contains__(self, name):
        return name in ('pos.order', 'account.move', 'account.move.line', 'account.account')

    def __getitem__(self, name):
        if name == 'account.account':
            return AccountStub()
        if name == 'account.move.line':
            return AmlStub()
        if name == 'account.move':
            return AmStub()
        if name == 'pos.order':
            return PosStub()
        raise KeyError(name)


LOGGED = []


def log(msg, level='info'):
    LOGGED.append(msg)


src = io.open('DIAG_ratios_participacion.py', encoding='utf-8').read()
ns = {
    'env': EnvStub(),
    'UserError': UserError,
    'log': log,
    'datetime': _dt,
    '__builtins__': __builtins__,
}

try:
    exec(compile(src, 'DIAG', 'exec'), ns)
    print('FALLO: el script termino sin raise UserError (deberia reportar siempre)')
    sys.exit(1)
except UserError as e:
    msg = str(e)
    print(msg)
    if 'Sin denominador no hay ratio' in msg:
        # corte duro esperado: sin venta no hay ratio que reportar
        print('\n[test] modo=%s  corte duro por denominador 0 OK' % MODO)
    else:
        assert LOGGED, 'FALLO: no se registro el reporte en log()'
        print('\n[test] modo=%s  reporte generado y logueado OK' % MODO)
