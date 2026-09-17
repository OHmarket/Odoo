# -*- coding: utf-8 -*-
# ============================================================
# OH DIAG Ratios de Participacion sobre Ventas  v0.1
# ir.actions.server / model account.move.line / safe_eval
# ============================================================
#
# READ-ONLY. No crea ni escribe nada: termina SIEMPRE con raise UserError,
# lo que ademas revierte la transaccion. El reporte sale en el dialogo de
# error (copiar/pegar desde ahi) y tambien queda en ir.logging via log().
#
# Que calcula:
#   Analisis vertical (common-size income statement) del periodo
#   YEAR-MONTH_FROM .. YEAR-MONTH_TO, tomado del MAYOR contable:
#   cada cuenta de gasto como % de la venta neta del mismo periodo.
#   Canon: Penman cap.9 / analisis vertical estandar (SAP FI-CO, Oracle EPM).
#
# Fuente y signos:
#   - Venta neta   = -SUM(balance) de cuentas account_type in ('income','income_other')
#                    (el ingreso vive en el haber -> balance negativo).
#   - Costo venta  =  SUM(balance) de account_type 'expense_direct_cost'
#                    (+ cuentas 'expense' cuyo nombre diga costo de venta, ver PROXY).
#   - Gasto        =  SUM(balance) de 'expense' + 'expense_depreciation'.
#   - Solo asientos posted, company = env.company, fecha = date de la linea
#     (devengo, no caja).
#
# PROXY (deuda tecnica visible):
#   El agrupado por partida (ARRIENDO, LUZ, REMUNERACIONES, ...) se arma por
#   PALABRA CLAVE sobre el nombre de la cuenta. Odoo no tiene un campo que
#   diga "esto es ocupacion". Por eso el reporte imprime SIEMPRE el detalle
#   cuenta por cuenta: el agrupado es auditable y corregible a mano, no es
#   verdad dura. Confirmar el mapeo contra el plan de cuentas antes de usar
#   los subtotales para negociar o presupuestar.
#
# Controles que el propio reporte imprime (ver diseno.md s8):
#   - venta neta contable vs venta POS bruta /1.19  -> si se separan > 3%, avisa.
#   - suma de meses == total del periodo.
#   - margen bruto fuera de 15%-40% -> avisa (COGS mal imputado / sin valorizar).
#   - facturas de compra en draft del periodo -> gasto subestimado, lo avisa.
#   - cuentas de gasto sin clasificar -> se listan aparte.
#
# Uso: pegar en un ir.actions.server de tipo code sobre account.move.line y
# correr. Ajustar YEAR / MONTH_FROM / MONTH_TO arriba si cambia el periodo.
# ============================================================

VERSION_ID = 'OH_DIAG_RATIOS_PARTICIPACION_v0_1'

YEAR = 2026
MONTH_FROM = 1
MONTH_TO = 7          # agosto NO esta cerrado: se deja fuera a proposito
TOP_N = 35            # cuentas de gasto en el detalle (el resto va a "otras")
TOL_POS_PCT = 3.0     # % de separacion tolerada venta contable vs POS/1.19
MARGEN_MIN = 15.0
MARGEN_MAX = 40.0
TOL_DRAFT_PCT = 2.0   # % de la venta a partir del cual el draft contamina

INCOME_TYPES = ['income', 'income_other']
COGS_TYPES = ['expense_direct_cost']
OPEX_TYPES = ['expense', 'expense_depreciation']

MES_NOMBRE = {
    1: 'ene', 2: 'feb', 3: 'mar', 4: 'abr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'ago', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dic',
}

# PROXY: clasificacion por nombre de cuenta. Primer match gana, asi que el
# orden importa (costo de venta antes que cualquier otra cosa).
GRUPOS = [
    ('COSTO DE VENTA (por nombre)', ['costo de venta', 'costos de venta',
                                     'costo de mercader', 'costo mercader',
                                     'costo de los bienes', ' cmv ']),
    ('ARRIENDO Y OCUPACION', ['arriend', 'alquil', 'leasing', 'gastos comunes',
                              'gasto comun']),
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
                                   'comisiones bancarias', 'comision bancaria']),
    ('MERMAS Y AJUSTES DE INVENTARIO', ['merma', 'perdida de inventario',
                                        'ajuste de inventario',
                                        'diferencia de inventario', 'faltante']),
    ('MANTENCION Y REPARACION', ['manten', 'repara']),
    ('ASEO Y SEGURIDAD', ['aseo', 'seguridad', 'vigilancia', 'guardia',
                          'basura', 'residuo', 'alarma']),
    ('TELECOM E INTERNET', ['internet', 'telefon', 'telecom', 'datos moviles']),
    ('MARKETING Y PUBLICIDAD', ['public', 'marketing', 'propaganda', 'promocion']),
    ('IMPUESTOS, PATENTES Y MULTAS', ['patente', 'contribucion', 'impuesto',
                                      'multa', ' tgr ', 'derechos municipales']),
    ('IVA NO RECUPERABLE', ['no recuper', 'no-rec', 'uso comun']),
    ('DEPRECIACION Y AMORTIZACION', ['deprecia', 'amortiza']),
    ('GASTOS FINANCIEROS', ['interes', 'financier', 'banco', 'factoring',
                            'linea de credito']),
    ('SEGUROS', ['seguro', 'poliza']),
    ('SOFTWARE Y SERVICIOS TI', ['software', 'licencia', 'suscripcion', 'odoo',
                                 'sistema']),
]

GRUPO_RESTO = 'OTROS GASTOS'
GRUPO_COGS_TIPO = 'COSTO DE VENTA (por tipo)'


# =========================
# HELPERS (top level: sin closures, safe_eval friendly)
# =========================

def norm_txt(s):
    """minusculas, sin tildes, con padding de espacios para match por palabra."""
    t = (s or '').lower()
    t = t.replace('\xe1', 'a').replace('\xe9', 'e').replace('\xed', 'i')
    t = t.replace('\xf3', 'o').replace('\xfa', 'u').replace('\xfc', 'u')
    t = t.replace('\xf1', 'n')
    t = t.replace('.', ' ').replace(',', ' ').replace('/', ' ')
    return ' ' + t + ' '


def clasificar(nombre_norm, grupos):
    for g in grupos:
        for kw in g[1]:
            if kw in nombre_norm:
                return g[0]
    return GRUPO_RESTO


def fmt_money(v):
    n = int(round(v or 0.0))
    neg = n < 0
    s = str(abs(n))
    out = ''
    while len(s) > 3:
        out = '.' + s[-3:] + out
        s = s[:-3]
    out = s + out
    if neg:
        out = '-' + out
    return out


def fmt_pct(v, base):
    if not base:
        return 'n/a'
    return ('%.1f' % (100.0 * (v or 0.0) / base)).replace('.', ',') + '%'


def pad_r(s, n):
    t = s or ''
    if len(t) > n:
        return t[:n - 1] + '.'
    return t + ' ' * (n - len(t))


def pad_l(s, n):
    t = s or ''
    if len(t) > n:
        return t[:n]
    return ' ' * (n - len(t)) + t


def ultimo_dia(y, m):
    if m == 12:
        return datetime.date(y + 1, 1, 1) - datetime.timedelta(days=1)
    return datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)


# =========================
# 0. CONTEXTO Y VALIDACION DE ESTRUCTURA
# =========================

Account = env['account.account']
AML = env['account.move.line']
AM = env['account.move']

company = env.company
CID = company.id

if 'account_type' not in Account._fields:
    raise UserError(
        'Esta version de Odoo no expone account.account.account_type '
        '(es <= 15, usa user_type_id). El DIAG necesita el mapeo de tipos: '
        'reportar la version antes de seguir.'
    )

HAS_CODE = 'code' in Account._fields
STATE_DOM = ('parent_state', '=', 'posted')
if 'parent_state' not in AML._fields:
    STATE_DOM = ('move_id.state', '=', 'posted')

ALL_TYPES = INCOME_TYPES + COGS_TYPES + OPEX_TYPES
acc_fields = ['name', 'account_type']
if HAS_CODE:
    acc_fields = ['code'] + acc_fields

accs = Account.search_read([('account_type', 'in', ALL_TYPES)], acc_fields)

acc_info = {}
for a in accs:
    codigo = a['code'] if HAS_CODE else ''
    acc_info[a['id']] = {
        'code': codigo or '',
        'name': a['name'] or '',
        'type': a['account_type'],
        'grupo': '',
    }

ACC_IDS = list(acc_info.keys())

if not ACC_IDS:
    raise UserError('No hay cuentas de resultado (income/expense) visibles. Revisar permisos.')

# Clasificacion PROXY: las cuentas de tipo expense_direct_cost quedan en su
# propio grupo por TIPO (canon); el resto se clasifica por nombre.
for aid in ACC_IDS:
    info = acc_info[aid]
    if info['type'] == 'income':
        info['grupo'] = 'VENTA'
    elif info['type'] == 'income_other':
        info['grupo'] = 'OTROS INGRESOS'
    elif info['type'] in COGS_TYPES:
        info['grupo'] = GRUPO_COGS_TIPO
    else:
        info['grupo'] = clasificar(norm_txt(info['name']), GRUPOS)


# =========================
# 1. BARRIDO MES A MES (read_group por cuenta, no search_read masivo)
# =========================

MESES = list(range(MONTH_FROM, MONTH_TO + 1))
D_INI = datetime.date(YEAR, MONTH_FROM, 1)
D_FIN = ultimo_dia(YEAR, MONTH_TO)

tot_acc = {}          # acc_id -> balance acumulado del periodo
mes_acc = {}          # (mes, acc_id) -> balance del mes
lineas_periodo = 0

for m in MESES:
    d0 = datetime.date(YEAR, m, 1)
    d1 = ultimo_dia(YEAR, m)
    dom = [
        STATE_DOM,
        ('company_id', '=', CID),
        ('account_id', 'in', ACC_IDS),
        ('date', '>=', d0.isoformat()),
        ('date', '<=', d1.isoformat()),
    ]
    res = AML.read_group(dom, ['balance:sum'], ['account_id'])
    for r in res:
        ref = r['account_id']
        if not ref:
            continue
        aid = ref[0]
        bal = float(r['balance'] or 0.0)
        lineas_periodo += int(r['__count'] or 0)
        tot_acc[aid] = tot_acc.get(aid, 0.0) + bal
        mes_acc[(m, aid)] = mes_acc.get((m, aid), 0.0) + bal


# =========================
# 2. AGREGADOS
# =========================

venta_periodo = 0.0
otros_ing_periodo = 0.0
cogs_periodo = 0.0
opex_periodo = 0.0
grupo_tot = {}
venta_mes = {}
grupo_mes = {}
cogs_mes = {}
opex_mes = {}

for m in MESES:
    venta_mes[m] = 0.0
    cogs_mes[m] = 0.0
    opex_mes[m] = 0.0

for aid in tot_acc.keys():
    info = acc_info.get(aid)
    if not info:
        continue
    bal = tot_acc[aid]
    grupo = info['grupo']
    if grupo == 'VENTA':
        venta_periodo += -bal
    elif grupo == 'OTROS INGRESOS':
        otros_ing_periodo += -bal
    else:
        grupo_tot[grupo] = grupo_tot.get(grupo, 0.0) + bal
        if grupo == GRUPO_COGS_TIPO or grupo == 'COSTO DE VENTA (por nombre)':
            cogs_periodo += bal
        else:
            opex_periodo += bal

for k in mes_acc.keys():
    m = k[0]
    aid = k[1]
    info = acc_info.get(aid)
    if not info:
        continue
    bal = mes_acc[k]
    grupo = info['grupo']
    if grupo == 'VENTA':
        venta_mes[m] = venta_mes.get(m, 0.0) + (-bal)
    elif grupo == 'OTROS INGRESOS':
        pass
    else:
        grupo_mes[(m, grupo)] = grupo_mes.get((m, grupo), 0.0) + bal
        if grupo == GRUPO_COGS_TIPO or grupo == 'COSTO DE VENTA (por nombre)':
            cogs_mes[m] = cogs_mes.get(m, 0.0) + bal
        else:
            opex_mes[m] = opex_mes.get(m, 0.0) + bal

gasto_total = cogs_periodo + opex_periodo
margen_bruto = venta_periodo - cogs_periodo
resultado = venta_periodo - gasto_total


# =========================
# 3. CONTROLES
# =========================

alertas = []

# 3.1 Control cruzado con POS (bruto con IVA -> se netea /1.19, PROXY: asume
#     que toda la venta POS es afecta a IVA 19% y sin ILA).
pos_bruto = 0.0
pos_ok = True
if 'pos.order' in env:
    pos_dom = [
        ('company_id', '=', CID),
        ('state', 'in', ['paid', 'done', 'invoiced']),
        ('date_order', '>=', D_INI.isoformat() + ' 00:00:00'),
        ('date_order', '<=', D_FIN.isoformat() + ' 23:59:59'),
    ]
    pos_res = env['pos.order'].read_group(pos_dom, ['amount_total:sum'], [])
    if pos_res:
        pos_bruto = float(pos_res[0]['amount_total'] or 0.0)
else:
    pos_ok = False

pos_neto = pos_bruto / 1.19 if pos_bruto else 0.0
if pos_neto and venta_periodo:
    dif_pct = 100.0 * (venta_periodo - pos_neto) / pos_neto
    if dif_pct > TOL_POS_PCT or dif_pct < -TOL_POS_PCT:
        alertas.append(
            'VENTA: la venta neta contable se separa %s del POS neteado '
            '(%s vs %s). Puede ser venta no-POS (facturas), exento/ILA, o '
            'contabilidad incompleta. Revisar antes de publicar los ratios.'
            % (('%.1f' % dif_pct).replace('.', ',') + '%',
               fmt_money(venta_periodo), fmt_money(pos_neto))
        )

# 3.2 Suma de meses == total
suma_meses = 0.0
for m in MESES:
    suma_meses += venta_mes.get(m, 0.0)
if abs(suma_meses - venta_periodo) > 1.0:
    alertas.append('CONSISTENCIA: la suma de meses (%s) no cuadra con el total (%s).'
                   % (fmt_money(suma_meses), fmt_money(venta_periodo)))

# 3.3 Margen bruto plausible
if venta_periodo:
    mb_pct = 100.0 * margen_bruto / venta_periodo
    if mb_pct < MARGEN_MIN or mb_pct > MARGEN_MAX:
        alertas.append(
            'MARGEN: margen bruto %s, fuera del rango plausible %s-%s%% para '
            'retail de conveniencia. Casi siempre significa costo de venta mal '
            'imputado o inventario sin valorizar, no margen real.'
            % (('%.1f' % mb_pct).replace('.', ',') + '%',
               int(MARGEN_MIN), int(MARGEN_MAX))
        )
if not venta_periodo and otros_ing_periodo:
    alertas.append(
        'VENTA = 0 con otros ingresos por %s: el plan de cuentas tiene la venta '
        'tipificada como income_other. Corregir el tipo de cuenta o mover '
        'income_other al denominador a mano.' % fmt_money(otros_ing_periodo)
    )

if not venta_periodo:
    raise UserError(
        'No hay venta en cuentas de tipo "income" entre %s y %s para "%s". '
        'Sin denominador no hay ratio: revisar periodo, compania o el tipo de '
        'las cuentas de ingreso antes de seguir.'
        % (D_INI.isoformat(), D_FIN.isoformat(), company.name)
    )

if not cogs_periodo:
    alertas.append(
        'COSTO DE VENTA = 0: no hay cuentas expense_direct_cost con movimiento '
        'ni cuentas cuyo nombre lo declare. Sin valorizacion de inventario en '
        'el mayor, el costo de venta hay que sacarlo del POS (04_analitica/'
        'OH Calculo de Margen.py), no de la contabilidad.'
    )

# 3.4 Facturas de compra en draft (gasto que aun no llega al mayor)
draft_monto = 0.0
draft_n = 0
dr = AM.read_group(
    [
        ('company_id', '=', CID),
        ('move_type', 'in', ['in_invoice', 'in_refund']),
        ('state', '=', 'draft'),
        ('invoice_date', '>=', D_INI.isoformat()),
        ('invoice_date', '<=', D_FIN.isoformat()),
    ],
    ['amount_untaxed_signed:sum'],
    [],
)
if dr:
    draft_monto = float(dr[0]['amount_untaxed_signed'] or 0.0)
    draft_n = int(dr[0]['__count'] or 0)

if venta_periodo and abs(draft_monto) > venta_periodo * TOL_DRAFT_PCT / 100.0:
    alertas.append(
        'CONTAMINACION: %s facturas de compra del periodo siguen en BORRADOR '
        'por %s neto (%s de la venta). Ese gasto NO esta en estos ratios: '
        'los %% sobre venta estan subestimados.'
        % (draft_n, fmt_money(draft_monto), fmt_pct(abs(draft_monto), venta_periodo))
    )

if len(env.companies.ids) > 1:
    alertas.append(
        'MULTI-COMPANY: hay %s companias activas en el contexto; este reporte '
        'es SOLO de "%s". Correrlo por compania o consolidar aparte.'
        % (len(env.companies.ids), company.name)
    )


# =========================
# 4. REPORTE
# =========================

L = []
L.append('=' * 78)
L.append('RATIOS DE PARTICIPACION SOBRE VENTAS  -  %s' % company.name)
L.append('Periodo: %s a %s  (%s-%s %s)  | solo asientos posted | devengo'
         % (D_INI.isoformat(), D_FIN.isoformat(), MES_NOMBRE[MONTH_FROM],
            MES_NOMBRE[MONTH_TO], YEAR))
L.append('Fuente: mayor contable (account.move.line). %s lineas, %s cuentas con movimiento.'
         % (lineas_periodo, len(tot_acc)))
L.append('%s' % VERSION_ID)
L.append('=' * 78)
L.append('')
L.append('1) BASE')
L.append('-' * 78)
L.append('  Venta neta (sin IVA, neta de NC) ... | %s | 100,0%%' % pad_l(fmt_money(venta_periodo), 16))
L.append('  Costo de venta ..................... | %s | %s'
         % (pad_l(fmt_money(cogs_periodo), 16), fmt_pct(cogs_periodo, venta_periodo)))
L.append('  MARGEN BRUTO ....................... | %s | %s'
         % (pad_l(fmt_money(margen_bruto), 16), fmt_pct(margen_bruto, venta_periodo)))
L.append('  Gastos operacionales ............... | %s | %s'
         % (pad_l(fmt_money(opex_periodo), 16), fmt_pct(opex_periodo, venta_periodo)))
L.append('  RESULTADO (venta - costo - gastos) . | %s | %s'
         % (pad_l(fmt_money(resultado), 16), fmt_pct(resultado, venta_periodo)))
L.append('  [memo] Otros ingresos (income_other)  | %s | %s   <- NO entra al denominador'
         % (pad_l(fmt_money(otros_ing_periodo), 16), fmt_pct(otros_ing_periodo, venta_periodo)))
L.append('')
if pos_ok:
    L.append('  [control] Venta POS bruta          | %s' % pad_l(fmt_money(pos_bruto), 16))
    L.append('  [control] Venta POS neteada /1,19  | %s  (PROXY: asume todo afecto 19%%, sin ILA)'
             % pad_l(fmt_money(pos_neto), 16))
L.append('')
L.append('2) PARTIDAS PRINCIPALES (% sobre venta neta)')
L.append('-' * 78)
L.append('  %s | %s | %s' % (pad_r('PARTIDA', 38), pad_l('MONTO', 16), '% VENTA'))
L.append('-' * 78)

g_rows = []
for g in grupo_tot.keys():
    g_rows.append((g, grupo_tot[g]))
g_rows = sorted(g_rows, key=lambda r: -r[1])
for r in g_rows:
    L.append('  %s | %s | %s'
             % (pad_r(r[0], 38), pad_l(fmt_money(r[1]), 16), fmt_pct(r[1], venta_periodo)))
L.append('-' * 78)
L.append('  %s | %s | %s' % (pad_r('TOTAL COSTO + GASTO', 38),
                             pad_l(fmt_money(gasto_total), 16),
                             fmt_pct(gasto_total, venta_periodo)))
L.append('')
L.append('  NOTA: el agrupado por nombre de cuenta es PROXY (ver header).')
L.append('  Auditarlo contra el detalle de la seccion 4 antes de usarlo.')
L.append('')

L.append('3) EVOLUCION MENSUAL (% sobre venta neta del mes)')
L.append('-' * 78)
L.append('  %s | %s | %s | %s | %s | %s'
         % (pad_r('MES', 8), pad_l('VENTA NETA', 14), pad_l('COSTO %', 9),
            pad_l('ARRIEND %', 10), pad_l('LUZ %', 8), pad_l('GASTO %', 9)))
L.append('-' * 78)
for m in MESES:
    vm = venta_mes.get(m, 0.0)
    L.append('  %s | %s | %s | %s | %s | %s'
             % (pad_r('%s-%s' % (MES_NOMBRE[m], YEAR), 8),
                pad_l(fmt_money(vm), 14),
                pad_l(fmt_pct(cogs_mes.get(m, 0.0), vm), 9),
                pad_l(fmt_pct(grupo_mes.get((m, 'ARRIENDO Y OCUPACION'), 0.0), vm), 10),
                pad_l(fmt_pct(grupo_mes.get((m, 'ELECTRICIDAD (LUZ)'), 0.0), vm), 8),
                pad_l(fmt_pct(opex_mes.get(m, 0.0), vm), 9)))
L.append('-' * 78)
L.append('  %s | %s | %s | %s | %s | %s'
         % (pad_r('TOTAL', 8),
            pad_l(fmt_money(venta_periodo), 14),
            pad_l(fmt_pct(cogs_periodo, venta_periodo), 9),
            pad_l(fmt_pct(grupo_tot.get('ARRIENDO Y OCUPACION', 0.0), venta_periodo), 10),
            pad_l(fmt_pct(grupo_tot.get('ELECTRICIDAD (LUZ)', 0.0), venta_periodo), 8),
            pad_l(fmt_pct(opex_periodo, venta_periodo), 9)))
L.append('')

L.append('4) DETALLE CUENTA POR CUENTA (top %s por monto)' % TOP_N)
L.append('-' * 78)
L.append('  %s | %s | %s | %s' % (pad_r('CUENTA', 44), pad_l('MONTO', 14), pad_l('%VTA', 7), 'GRUPO'))
L.append('-' * 78)

det = []
for aid in tot_acc.keys():
    info = acc_info.get(aid)
    if not info or info['grupo'] in ('VENTA', 'OTROS INGRESOS'):
        continue
    etiqueta = ('%s %s' % (info['code'], info['name'])).strip()
    det.append((etiqueta, tot_acc[aid], info['grupo']))
det = sorted(det, key=lambda r: -r[1])

mostradas = det[:TOP_N]
resto = det[TOP_N:]
for r in mostradas:
    L.append('  %s | %s | %s | %s'
             % (pad_r(r[0], 44), pad_l(fmt_money(r[1]), 14),
                pad_l(fmt_pct(r[1], venta_periodo), 7), r[2]))
if resto:
    resto_monto = 0.0
    for r in resto:
        resto_monto += r[1]
    L.append('  %s | %s | %s |'
             % (pad_r('(otras %s cuentas)' % len(resto), 44),
                pad_l(fmt_money(resto_monto), 14),
                pad_l(fmt_pct(resto_monto, venta_periodo), 7)))
L.append('')

L.append('5) DETALLE DE LA VENTA (cuentas de ingreso)')
L.append('-' * 78)
ing = []
for aid in tot_acc.keys():
    info = acc_info.get(aid)
    if not info or info['grupo'] not in ('VENTA', 'OTROS INGRESOS'):
        continue
    ing.append((('%s %s' % (info['code'], info['name'])).strip(),
                -tot_acc[aid], info['grupo']))
ing = sorted(ing, key=lambda r: -r[1])
for r in ing[:20]:
    L.append('  %s | %s | %s | %s'
             % (pad_r(r[0], 44), pad_l(fmt_money(r[1]), 14),
                pad_l(fmt_pct(r[1], venta_periodo), 7), r[2]))
L.append('')

sin_clasificar = grupo_tot.get(GRUPO_RESTO, 0.0)
L.append('6) CONTROLES Y CONTAMINACION')
L.append('-' * 78)
L.append('  Facturas de compra del periodo en BORRADOR: %s por %s neto (%s de la venta)'
         % (draft_n, fmt_money(draft_monto), fmt_pct(abs(draft_monto), venta_periodo)))
L.append('  Gasto sin clasificar en ningun grupo: %s (%s)'
         % (fmt_money(sin_clasificar), fmt_pct(sin_clasificar, venta_periodo)))
if not alertas:
    L.append('  Sin alertas: los controles de diseno.md s8 pasaron.')
else:
    for a in alertas:
        L.append('  [!] %s' % a)
L.append('=' * 78)

reporte = '\n'.join(L)
log(reporte)
raise UserError(reporte)
