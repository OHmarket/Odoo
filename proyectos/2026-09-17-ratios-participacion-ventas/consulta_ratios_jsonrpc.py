# -*- coding: utf-8 -*-
"""Ratios de participacion sobre ventas — cliente EXTERNO read-only.

Misma logica que DIAG_ratios_participacion.py (que corre dentro de Odoo bajo
safe_eval), pero ejecutable desde fuera. Usa JSON-RPC sobre requests porque
xmlrpc.client no respeta HTTPS_PROXY y este host sale por proxy.

Read-only por diseno: solo metodos de la whitelist. Cualquier otro lanza
PermissionError sin tocar la red. Credenciales desde .env de la raiz del repo;
NUNCA se imprimen.

  python3 consulta_ratios_jsonrpc.py [YEAR] [MES_DESDE] [MES_HASTA]
"""
import io
import json
import os
import sys

import requests

ALLOWED = frozenset({'search_read', 'read_group', 'search_count', 'read',
                     'fields_get', 'name_get'})

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env():
    path = os.path.join(ROOT, '.env')
    out = {}
    for raw in io.open(path, encoding='utf-8').read().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class Odoo(object):
    def __init__(self):
        env = load_env()
        self.url = env['ODOO_URL'].rstrip('/')
        self.db = env['ODOO_DB']
        self.user = env['ODOO_USER']
        self._key = env['ODOO_API_KEY']
        self.session = requests.Session()
        self.uid = self._rpc('common', 'login', [self.db, self.user, self._key])
        if not self.uid:
            raise RuntimeError('Login rechazado por Odoo (revisar .env)')

    def _rpc(self, service, method, args):
        payload = {'jsonrpc': '2.0', 'method': 'call',
                   'params': {'service': service, 'method': method, 'args': args}}
        r = self.session.post(self.url + '/jsonrpc', json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        if 'error' in data:
            err = data['error']
            msg = err.get('data', {}).get('message') or err.get('message')
            raise RuntimeError('Odoo error: %s' % msg)
        return data['result']

    def call(self, model, method, *args, **kwargs):
        if method not in ALLOWED:
            raise PermissionError('Metodo no permitido (cliente read-only): %s' % method)
        return self._rpc('object', 'execute_kw',
                         [self.db, self.uid, self._key, model, method, list(args), kwargs])


def fmt_money(v):
    n = int(round(v or 0.0))
    neg = n < 0
    s = str(abs(n))
    out = ''
    while len(s) > 3:
        out = '.' + s[-3:] + out
        s = s[:-3]
    out = s + out
    return ('-' + out) if neg else out


def fmt_pct(v, base):
    if not base:
        return 'n/a'
    return ('%.1f' % (100.0 * (v or 0.0) / base)).replace('.', ',') + '%'


def pad_r(s, n):
    t = s or ''
    return t[:n - 1] + '.' if len(t) > n else t + ' ' * (n - len(t))


def pad_l(s, n):
    t = s or ''
    return t[:n] if len(t) > n else ' ' * (n - len(t)) + t


def norm_txt(s):
    t = (s or '').lower()
    for a, b in [('\xe1', 'a'), ('\xe9', 'e'), ('\xed', 'i'), ('\xf3', 'o'),
                 ('\xfa', 'u'), ('\xfc', 'u'), ('\xf1', 'n'), ('.', ' '),
                 (',', ' '), ('/', ' ')]:
        t = t.replace(a, b)
    return ' ' + t + ' '


GRUPOS = [
    ('COSTO DE VENTA (por nombre)', ['costo de venta', 'costos de venta',
                                     'costo de mercader', 'costo mercader',
                                     'costo de los bienes', ' cmv ']),
    ('ARRIENDO Y OCUPACION', ['arriend', 'alquil', 'leasing', 'gastos comunes',
                              'gasto comun']),
    ('MANTENCION Y REPARACION', ['manten', 'repara']),
    ('ELECTRICIDAD (LUZ)', ['electric', 'energ', ' luz ', ' enel', ' cge ',
                            'saesa', 'frontel', 'chilquinta', 'edelmag']),
    ('AGUA Y ALCANTARILLADO', [' agua', 'essbio', 'esval', 'nuevosur',
                               'aguas andinas', 'alcantarill']),
    ('GAS Y COMBUSTIBLE', [' gas ', 'gas licuado', 'combustible', 'petroleo',
                           'diesel', 'bencina', 'lipigas', 'abastible']),
    ('REMUNERACIONES Y LEYES SOCIALES', ['remunera', 'sueldo', 'salario',
                                         'finiquito', 'leyes sociales',
                                         'previsional', 'gratificacion',
                                         'aguinaldo', 'colacion', 'movilizacion',
                                         'mutual', 'vacacion', 'indemnizacion']),
    ('HONORARIOS Y ASESORIAS', ['honorario', 'asesor', 'auditor', 'abogado',
                                'contabil', 'legal']),
    ('COMISIONES MEDIOS DE PAGO', ['transbank', 'getnet', 'redelcom', 'klap',
                                   'comision tarjeta', 'medios de pago',
                                   'comisiones bancarias', 'comision bancaria',
                                   'mercado pago', 'mercadopago', 'webpay']),
    ('MERMAS Y AJUSTES DE INVENTARIO', ['merma', 'perdida de inventario',
                                        'ajuste de inventario',
                                        'diferencia de inventario', 'faltante']),
    ('ASEO Y SEGURIDAD', ['aseo', 'seguridad', 'vigilancia', 'guardia',
                          'basura', 'residuo', 'alarma']),
    ('TELECOM E INTERNET', ['internet', 'telefon', 'telecom', 'datos moviles']),
    ('MARKETING Y PUBLICIDAD', ['public', 'marketing', 'propaganda', 'promocion']),
    ('IMPUESTOS, PATENTES Y MULTAS', ['patente', 'contribucion', 'impuesto',
                                      'multa', ' tgr ', 'derechos municipales']),
    ('IVA NO RECUPERABLE', ['no recuper', 'no-rec', 'uso comun']),
    ('DEPRECIACION Y AMORTIZACION', ['deprecia', 'amortiza']),
    ('GASTOS FINANCIEROS', ['interes', 'financier', 'banco', 'bancari', 'factoring',
                            'linea de credito']),
    ('SEGUROS', ['seguro', 'poliza']),
    ('SOFTWARE Y SERVICIOS TI', ['software', 'licencia', 'suscripcion', 'odoo',
                                 'sistema']),
]
GRUPO_RESTO = 'OTROS GASTOS'
GRUPO_COGS_TIPO = 'COSTO DE VENTA (por tipo)'
MES = {1: 'ene', 2: 'feb', 3: 'mar', 4: 'abr', 5: 'may', 6: 'jun', 7: 'jul',
       8: 'ago', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dic'}


def clasificar(n):
    for g in GRUPOS:
        for kw in g[1]:
            if kw in n:
                return g[0]
    return GRUPO_RESTO


def ultimo_dia(y, m):
    import datetime
    if m == 12:
        return datetime.date(y + 1, 1, 1) - datetime.timedelta(days=1)
    return datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    m_ini = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    m_fin = int(sys.argv[3]) if len(sys.argv) > 3 else 7

    o = Odoo()
    sys.stderr.write('conectado (uid=%s)\n' % o.uid)

    accs = o.call('account.account', 'search_read',
                  [('account_type', 'in', ['income', 'income_other', 'expense',
                                           'expense_direct_cost', 'expense_depreciation'])],
                  ['code', 'name', 'account_type'])
    info = {}
    for a in accs:
        t = a['account_type']
        if t == 'income':
            g = 'VENTA'
        elif t == 'income_other':
            g = 'OTROS INGRESOS'
        elif t == 'expense_direct_cost':
            g = GRUPO_COGS_TIPO
        else:
            g = clasificar(norm_txt(a['name']))
        info[a['id']] = {'code': a.get('code') or '', 'name': a['name'] or '',
                         'type': t, 'grupo': g}
    acc_ids = list(info.keys())
    sys.stderr.write('cuentas de resultado: %s\n' % len(acc_ids))

    meses = list(range(m_ini, m_fin + 1))
    tot = {}
    mes_acc = {}
    nlin = 0
    for m in meses:
        import datetime
        d0 = datetime.date(year, m, 1).isoformat()
        d1 = ultimo_dia(year, m).isoformat()
        rows = o.call('account.move.line', 'read_group',
                      [('parent_state', '=', 'posted'),
                       ('account_id', 'in', acc_ids),
                       ('date', '>=', d0), ('date', '<=', d1)],
                      ['balance:sum'], ['account_id'])
        for r in rows:
            if not r.get('account_id'):
                continue
            aid = r['account_id'][0]
            bal = float(r.get('balance') or 0.0)
            nlin += int(r.get('__count') or 0)
            tot[aid] = tot.get(aid, 0.0) + bal
            mes_acc[(m, aid)] = mes_acc.get((m, aid), 0.0) + bal
        sys.stderr.write('  %s-%s ok (%s cuentas con movimiento)\n' % (MES[m], year, len(rows)))

    venta = otros_ing = cogs = opex = 0.0
    gtot = {}
    vmes = {}
    gmes = {}
    cmes = {}
    omes = {}
    for m in meses:
        vmes[m] = cmes[m] = omes[m] = 0.0
    for aid, bal in tot.items():
        g = info[aid]['grupo']
        if g == 'VENTA':
            venta += -bal
        elif g == 'OTROS INGRESOS':
            otros_ing += -bal
        else:
            gtot[g] = gtot.get(g, 0.0) + bal
            if g in (GRUPO_COGS_TIPO, 'COSTO DE VENTA (por nombre)'):
                cogs += bal
            else:
                opex += bal
    for (m, aid), bal in mes_acc.items():
        g = info[aid]['grupo']
        if g == 'VENTA':
            vmes[m] += -bal
        elif g == 'OTROS INGRESOS':
            pass
        else:
            gmes[(m, g)] = gmes.get((m, g), 0.0) + bal
            if g in (GRUPO_COGS_TIPO, 'COSTO DE VENTA (por nombre)'):
                cmes[m] += bal
            else:
                omes[m] += bal

    import datetime
    d_ini = datetime.date(year, m_ini, 1).isoformat()
    d_fin = ultimo_dia(year, m_fin).isoformat()

    pos = o.call('pos.order', 'read_group',
                 [('state', 'in', ['paid', 'done', 'invoiced']),
                  ('date_order', '>=', d_ini + ' 00:00:00'),
                  ('date_order', '<=', d_fin + ' 23:59:59')],
                 ['amount_total:sum'], [])
    pos_bruto = float(pos[0].get('amount_total') or 0.0) if pos else 0.0

    dr = o.call('account.move', 'read_group',
                [('move_type', 'in', ['in_invoice', 'in_refund']),
                 ('state', '=', 'draft'),
                 ('invoice_date', '>=', d_ini), ('invoice_date', '<=', d_fin)],
                ['amount_untaxed_signed:sum'], [])
    draft_monto = float(dr[0].get('amount_untaxed_signed') or 0.0) if dr else 0.0
    draft_n = int(dr[0].get('__count') or 0) if dr else 0

    out = {
        'periodo': [d_ini, d_fin], 'lineas': nlin,
        'venta': venta, 'otros_ingresos': otros_ing, 'cogs': cogs, 'opex': opex,
        'pos_bruto': pos_bruto, 'draft_monto': draft_monto, 'draft_n': draft_n,
        'grupos': gtot,
        'venta_mes': vmes, 'cogs_mes': cmes, 'opex_mes': omes,
        'grupo_mes': dict([('%s|%s' % (k[0], k[1]), v) for k, v in gmes.items()]),
        'cuentas': dict([(str(aid), {'code': info[aid]['code'],
                                     'name': info[aid]['name'],
                                     'grupo': info[aid]['grupo'],
                                     'monto': bal})
                         for aid, bal in tot.items()]),
    }
    io.open('resultados/ratios_%s_%02d_%02d.json' % (year, m_ini, m_fin), 'w',
            encoding='utf-8').write(json.dumps(out, indent=1, ensure_ascii=False))

    L = []
    L.append('=' * 78)
    L.append('RATIOS DE PARTICIPACION SOBRE VENTAS   %s a %s' % (d_ini, d_fin))
    L.append('Mayor contable, solo posted, 1 compania. %s cuentas con movimiento.'
             % len(tot))
    L.append('=' * 78)
    L.append('1) BASE')
    L.append('  Venta neta (sin IVA) ......... | %s | 100,0%%' % pad_l(fmt_money(venta), 16))
    L.append('  Costo de venta ............... | %s | %s' % (pad_l(fmt_money(cogs), 16), fmt_pct(cogs, venta)))
    L.append('  MARGEN BRUTO ................. | %s | %s' % (pad_l(fmt_money(venta - cogs), 16), fmt_pct(venta - cogs, venta)))
    L.append('  Gastos operacionales ......... | %s | %s' % (pad_l(fmt_money(opex), 16), fmt_pct(opex, venta)))
    L.append('  RESULTADO .................... | %s | %s' % (pad_l(fmt_money(venta - cogs - opex), 16), fmt_pct(venta - cogs - opex, venta)))
    L.append('  [memo] Otros ingresos ........ | %s | %s  (fuera del denominador)' % (pad_l(fmt_money(otros_ing), 16), fmt_pct(otros_ing, venta)))
    L.append('  [control] Venta POS bruta .... | %s' % pad_l(fmt_money(pos_bruto), 16))
    L.append('  [control] POS neteada /1,19 .. | %s' % pad_l(fmt_money(pos_bruto / 1.19), 16))
    L.append('')
    L.append('2) PARTIDAS (%% sobre venta neta)')
    for g, v in sorted(gtot.items(), key=lambda r: -r[1]):
        L.append('  %s | %s | %s' % (pad_r(g, 38), pad_l(fmt_money(v), 16), fmt_pct(v, venta)))
    L.append('  %s | %s | %s' % (pad_r('TOTAL COSTO + GASTO', 38), pad_l(fmt_money(cogs + opex), 16), fmt_pct(cogs + opex, venta)))
    L.append('')
    L.append('3) MENSUAL')
    L.append('  %s | %s | %s | %s | %s | %s' % (pad_r('MES', 8), pad_l('VENTA NETA', 14), pad_l('COSTO %', 9), pad_l('ARRIEND %', 10), pad_l('LUZ %', 8), pad_l('GASTO %', 9)))
    for m in meses:
        v = vmes[m]
        L.append('  %s | %s | %s | %s | %s | %s'
                 % (pad_r('%s-%s' % (MES[m], year), 8), pad_l(fmt_money(v), 14),
                    pad_l(fmt_pct(cmes[m], v), 9),
                    pad_l(fmt_pct(gmes.get((m, 'ARRIENDO Y OCUPACION'), 0.0), v), 10),
                    pad_l(fmt_pct(gmes.get((m, 'ELECTRICIDAD (LUZ)'), 0.0), v), 8),
                    pad_l(fmt_pct(omes[m], v), 9)))
    L.append('')
    L.append('4) DETALLE CUENTA POR CUENTA (gasto, top 40)')
    det = sorted([(('%s %s' % (info[a]['code'], info[a]['name'])).strip(), b, info[a]['grupo'])
                  for a, b in tot.items() if info[a]['grupo'] not in ('VENTA', 'OTROS INGRESOS')],
                 key=lambda r: -r[1])
    for r in det[:40]:
        L.append('  %s | %s | %s | %s' % (pad_r(r[0], 44), pad_l(fmt_money(r[1]), 14), pad_l(fmt_pct(r[1], venta), 7), r[2]))
    L.append('')
    L.append('5) DETALLE DE LA VENTA')
    ing = sorted([(('%s %s' % (info[a]['code'], info[a]['name'])).strip(), -b, info[a]['grupo'])
                  for a, b in tot.items() if info[a]['grupo'] in ('VENTA', 'OTROS INGRESOS')],
                 key=lambda r: -r[1])
    for r in ing[:20]:
        L.append('  %s | %s | %s | %s' % (pad_r(r[0], 44), pad_l(fmt_money(r[1]), 14), pad_l(fmt_pct(r[1], venta), 7), r[2]))
    L.append('')
    L.append('6) CONTROLES')
    L.append('  Facturas de compra del periodo en BORRADOR: %s por %s neto (%s de la venta)'
             % (draft_n, fmt_money(draft_monto), fmt_pct(abs(draft_monto), venta)))
    L.append('  Gasto sin clasificar: %s (%s)' % (fmt_money(gtot.get(GRUPO_RESTO, 0.0)), fmt_pct(gtot.get(GRUPO_RESTO, 0.0), venta)))
    if venta and pos_bruto:
        d = 100.0 * (venta - pos_bruto / 1.19) / (pos_bruto / 1.19)
        L.append('  Venta contable vs POS neteado: %s' % (('%.1f' % d).replace('.', ',') + '%'))
    L.append('=' * 78)
    print('\n'.join(L))


if __name__ == '__main__':
    main()
