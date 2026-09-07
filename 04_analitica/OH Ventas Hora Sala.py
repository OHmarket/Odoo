# =====================================================================
# OH Ventas por Hora x Sala x Dia operativo  ->  x_ventas_hora_sala
# ir.actions.server (safe_eval).  v3.0  -- FOTO UNICA RODANTE 12 SEMANAS
# ---------------------------------------------------------------------
# Perfil de demanda intradia ("daypart profile"): una fila por
# (sala x dia_semana x hora) con el PROMEDIO por dia operativo sobre una
# ventana rodante de 12 semanas completas.
#
# Cada corrida BORRA TODO y reescribe: es una foto, no un historico.
# Override:  context = {'semanas': 13, 'hora_corte': 5}
#
# ---------------------------------------------------------------------
# DIA OPERATIVO (business date) -- NO es el dia calendario
# ---------------------------------------------------------------------
# La sala abre ~09:00 y cierra ~03:00 del dia siguiente. Entonces una venta
# del sabado 01:00 pertenece al turno del VIERNES, no al sabado. Atribuirla
# por dia calendario (isodow crudo) rompe justo las horas de mayor venta
# (viernes y sabado de noche).
#
# Canon: business date / trading day (SAP Retail, Oracle Retail RMS). Se
# corre el timestamp HORA_CORTE horas hacia atras y recien ahi se extrae el
# dia de semana:
#     dia_operativo = (hora_local - HORA_CORTE horas)::date
#
# HORA_CORTE = 5 (no 9): el corte debe caer en la zona muerta. VALIDADO
# 2026-09-07 sobre 28 dias de POS: venta = 0 en toda la red entre 03:00 y
# 07:59 local. Cortar en 09:00 mandaria las ventas de las 08:00 al dia
# anterior; cortar en 05:00 no mueve nada real y sigue asignando 00-02 al
# dia correcto.
#
# ORDEN CRONOLOGICO: hora_desc usa reloj extendido -> 05:00 .. 23:00,
# luego 24:00 (medianoche), 25:00 (1am), 26:00 (2am)... Asi el orden
# alfabetico del pivot ES el orden cronologico del turno. x_studio_hora
# guarda la hora de reloj real (0-23).
#
# ---------------------------------------------------------------------
# POR QUE 12 SEMANAS Y NO UN MES
# ---------------------------------------------------------------------
# Un mes tiene 4 o 5 de cada dia de semana (agosto 2026: 5 sabados vs 4
# viernes) -> el acumulado mensual infla ~25% al dia que sale 5 veces, por
# puro calendario. Cualquier ventana de 84 dias tiene EXACTAMENTE 12 de
# cada dia de semana -> sesgo de calendario = 0, y 12 observaciones por
# celda dan un promedio estable. Canon: rolling 8-13 semanas para perfiles
# de dotacion (SAP Retail, Manhattan Associates WFM).
#
# ---------------------------------------------------------------------
# METRICAS por celda -- PROMEDIO por dia activo (lo que se lee):
#   dias_activo          = dias de ese dia operativo en que la sala OPERO (max 12)
#   venta_neta_dia_prom  = venta_neta   / dias_activo
#   venta_bruta_dia_prom = venta_bruta  / dias_activo
#   margen_dia_promedio  = margen_monto / dias_activo
#
# !! Si un pivot cruza venta_neta_dia_promedio (1 dia) con margen_monto
#    (acumulado 12 semanas), el margen se ve 12x la venta. Para lecturas por
#    dia usar SIEMPRE la familia *_dia_promedio completa.
#
# METRICAS por celda -- ACUMULADO 12 semanas (base del margen y totales):
#   venta_bruta = SUM(price_subtotal_incl)   (CON IVA, monto de caja)
#   venta_neta  = SUM(price_subtotal)        (SIN IVA, base del margen)
#   costo_total = SUM(qty * cost_oh)         (ESTIMACION)
#   margen_monto= venta_neta - costo_total
#   margen_pct  = margen_monto / venta_neta * 100   (retorno sobre ventas)
#
# margen_pct es un PROMEDIO PONDERADO por venta (ratio de sumas), no el
# promedio simple de los 12 porcentajes diarios: un promedio simple le daria
# el mismo peso a un viernes flojo que a uno fuerte. Por ser ratio es
# IDENTICO en acumulado y en promedio (dividir arriba y abajo por
# dias_activo se cancela).
#
# !! El margen se calcula SIEMPRE sobre venta NETA. cost_oh es neto: usar
#    venta_bruta como base inflaria el margen ~19% (IVA contado como margen).
#
# cost_oh (de shared/cost_reader.py):
#   cost_oh = raw_product_price * factor_ILA  (fallback standard_price).
#   IVA compra recuperable NO se suma (modelo OH).
#
# PROXY / CONTAMINACION (no ocultar):
#   - Combos: precio en linea padre, costo en lineas hijas -> netean a nivel
#     de bucket (sala x dia x hora), NO por SKU. Margen de combos aprox.
#   - Costo ACTUAL del producto, no historico -> margen es ESTIMACION.
#   - Devoluciones (qty<0) INCLUIDAS: netean la venta real.
#   - dias cuenta solo dias CON VENTA: si la sala cerro (feriado
#     irrenunciable, remodelacion) ese dia no diluye el promedio. Un
#     dias < semanas es senal de cierre -> revisar antes de decidir dotacion.
#   - Feriados y promos NO se excluyen: quedan promediados dentro de las 12
#     semanas. Para un dia puntual (18 sep) NO usar este perfil.
#   - Hora LOCAL via doble AT TIME ZONE (UTC -> America/Santiago), maneja
#     DST de Chile. (VALIDADO: sin esto las ventas caen 00-06h.)
#
# Sucursal: las 12 crm.team se llaman TODAS "Sales" (verificado), asi que el
# m2o no es legible. Se usa el mapa canonico team_id -> sucursal, identico al
# de 03_stock/OH Analisis de Stock.py (TEAM_WAREHOUSE_MAP_FALLBACK). El
# nombre y el periodo van en x_name para que el registro se lea solo.
#
# Hora: DOS campos. x_studio_hora (Integer 0-23) para medir/ordenar, y
# x_studio_hora_desc (Char '25:00') para AGRUPAR -- Odoo no ofrece
# Integer/Float como dimension de agrupacion, solo Char/Selection/M2o/
# Date/Boolean. Mismo motivo por el que x_studio_dia es Char '5-Vie'.
#
# Writer TOLERANTE y type-aware: escribe solo los campos que existan y
# castea al tipo real de cada campo.
# =====================================================================

MODEL = 'x_ventas_hora_sala'
SEMANAS_DEFAULT = 12
HORA_CORTE_DEFAULT = 5      # inicio del dia operativo (zona muerta validada)

# Mapa canonico team_id -> sucursal (mismo que OH Analisis de Stock.py:303)
TEAM_SUCURSAL = {
    5:  'Panguipulli 790',
    6:  'Los Lagos',
    7:  'Futrono',
    8:  'Panguipulli 645',
    9:  'Panguipulli 763',
    10: 'Lautaro',
    11: 'San Jos\xe9',
    12: 'Paillaco',
    13: 'Mehuin Express',
    16: 'Co\xf1aripe',
    17: 'Nueva Imperial',
    18: 'Malalhue',
}
DOW = {1: 'Lun', 2: 'Mar', 3: 'Mie', 4: 'Jue', 5: 'Vie', 6: 'Sab', 7: 'Dom'}
_ILA_KW = ('ila', 'adicional', 'lujo', 'especifico', 'espec\xedfico')


# ---- helpers de impuestos (de cost_reader.py, adaptados a safe_eval) ----
def flatten_taxes(tax):
    out = []
    if not tax:
        return out
    if tax.amount_type == 'group' and tax.children_tax_ids:
        for ch in tax.children_tax_ids:
            out = out + flatten_taxes(ch)
    else:
        out.append({'name': tax.name or '', 'amount': tax.amount,
                    'amount_type': tax.amount_type})
    return out


def sum_ila_factor(tmpl):
    factor = 1.0
    for tax in tmpl.supplier_taxes_id:
        for t in flatten_taxes(tax):
            nm = (t['name'] or '').lower()
            is_ila = False
            for k in _ILA_KW:
                if k in nm:
                    is_ila = True
            if t['amount_type'] == 'percent' and t['amount'] > 0 and is_ila:
                factor = factor * (1.0 + t['amount'] / 100.0)
    return factor


def cost_oh_of(p):
    tmpl = p.product_tmpl_id
    raw = 0.0
    if 'x_studio_raw_product_price' in p._fields:
        raw = p.x_studio_raw_product_price or 0.0
    elif 'x_studio_raw_product_price' in tmpl._fields:
        raw = tmpl.x_studio_raw_product_price or 0.0
    if not raw:
        raw = p.standard_price or 0.0
    return (raw or 0.0) * sum_ila_factor(tmpl)


# ---- 0) el modelo destino debe existir (creado en Studio) ----
if not env['ir.model'].search_count([('model', '=', MODEL)]):
    raise UserError('Falta crear el modelo %s en Studio (ver MODELO_STUDIO.md).' % MODEL)
MFIELDS = env[MODEL]._fields


def keep_existing(vals):
    # Writer tolerante y type-aware (patron put_field de shared/field_map.py).
    out = {}
    for k in vals:
        if k not in MFIELDS:
            continue
        t = MFIELDS[k].type
        v = vals[k]
        if v is None:
            out[k] = False
        elif t == 'char':
            out[k] = str(v)
        elif t == 'integer':
            out[k] = int(v)
        elif t == 'float':
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ---- 1) ventana: N semanas COMPLETAS, terminadas el domingo pasado ----
semanas = int(env.context.get('semanas') or SEMANAS_DEFAULT)
corte = int(env.context.get('hora_corte') or HORA_CORTE_DEFAULT)
today = datetime.date.today()
d2 = today - datetime.timedelta(days=today.weekday())   # lunes de esta semana (excl.)
d1 = d2 - datetime.timedelta(days=7 * semanas)          # lunes de hace N semanas
d_hasta = d2 - datetime.timedelta(days=1)               # ultimo domingo (incl.)
d1s, d2s = d1.isoformat(), d2.isoformat()

STATES = ('paid', 'invoiced', 'done')
# Hora local real -> solo para EXTRACT(hour): la hora de reloj que se muestra.
LOCAL = "(po.date_order AT TIME ZONE 'UTC' AT TIME ZONE 'America/Santiago')"
# Timestamp corrido al dia OPERATIVO -> para EXTRACT(isodow), contar dias Y
# FILTRAR LA VENTANA. Filtrar por hora local pero agrupar por dia operativo
# mete un dia parcial extra al inicio (las 00:00-04:59 del primer lunes caen
# en el domingo anterior) -> 13 domingos en vez de 12, diluyendo ese promedio
# ~8%. Detectado en el preview del 2026-09-07.
BIZ = "(" + LOCAL + " - interval '%d hours')" % corte
cr = env.cr

# ---- 2) productos vendidos en la ventana -> costo precomputado ----
cr.execute("""
    SELECT DISTINCT pol.product_id
    FROM pos_order_line pol
    JOIN pos_order po ON po.id = pol.order_id
    WHERE po.state IN %(st)s
      AND """ + BIZ + """ >= %(d1)s
      AND """ + BIZ + """ <  %(d2)s
      AND pol.product_id IS NOT NULL
""", {'st': STATES, 'd1': d1s, 'd2': d2s})
pids = [r[0] for r in cr.fetchall()]

costs = []
for p in env['product.product'].browse(pids):
    costs.append(cost_oh_of(p))

# ---- 3) agregado sala x dia_operativo x hora, costo inyectado via unnest ----
cr.execute("""
    SELECT
        pc.crm_team_id AS team_id,
        EXTRACT(isodow FROM """ + BIZ + """)::int AS dow,
        EXTRACT(hour   FROM """ + LOCAL + """)::int AS hod,
        SUM(pol.price_subtotal_incl)             AS venta_bruta,
        SUM(pol.price_subtotal)                  AS venta_neta,
        SUM(pol.qty * COALESCE(c.cost_oh, 0.0))  AS costo_total
    FROM pos_order_line pol
    JOIN pos_order   po ON po.id = pol.order_id
    JOIN pos_session ps ON ps.id = po.session_id
    JOIN pos_config  pc ON pc.id = ps.config_id
    LEFT JOIN (
        SELECT unnest(%(pids)s::int[])      AS product_id,
               unnest(%(costs)s::numeric[]) AS cost_oh
    ) c ON c.product_id = pol.product_id
    WHERE po.state IN %(st)s
      AND """ + BIZ + """ >= %(d1)s
      AND """ + BIZ + """ <  %(d2)s
      AND pc.crm_team_id IS NOT NULL
    GROUP BY pc.crm_team_id,
             EXTRACT(isodow FROM """ + BIZ + """)::int,
             EXTRACT(hour   FROM """ + LOCAL + """)::int
""", {'pids': pids, 'costs': costs, 'st': STATES, 'd1': d1s, 'd2': d2s})
rows = cr.fetchall()

# ---- 3b) dias OPERATIVOS de cada (sala, dow) -- denominador del promedio ----
# A nivel ORDEN (no linea) y solo dias con venta: si la sala cerro, ese dia no
# diluye el promedio. Se cuenta sobre el dia OPERATIVO (BIZ), asi la madrugada
# no cuenta como un dia extra. Se calcula por (sala, dow) y NO por hora: una
# hora sin venta dentro de un dia abierto es informacion (venta 0), no un dia
# menos.
cr.execute("""
    SELECT
        pc.crm_team_id AS team_id,
        EXTRACT(isodow FROM """ + BIZ + """)::int AS dow,
        COUNT(DISTINCT (""" + BIZ + """)::date) AS dias
    FROM pos_order   po
    JOIN pos_session ps ON ps.id = po.session_id
    JOIN pos_config  pc ON pc.id = ps.config_id
    WHERE po.state IN %(st)s
      AND """ + BIZ + """ >= %(d1)s
      AND """ + BIZ + """ <  %(d2)s
      AND pc.crm_team_id IS NOT NULL
    GROUP BY pc.crm_team_id, EXTRACT(isodow FROM """ + BIZ + """)::int
""", {'st': STATES, 'd1': d1s, 'd2': d2s})
dias_map = {}
for team_id, dow, dias in cr.fetchall():
    dias_map[(team_id, dow)] = int(dias or 0)

# ---- 4) FOTO UNICA: borrar todo y reescribir ----
env[MODEL].search([]).unlink()

now = datetime.datetime.now()
vals_list = []
tot_neta = 0.0
tot_bruta = 0.0
tot_costo = 0.0
for team_id, dow, hod, bruta, neta, costo in rows:
    bruta = float(bruta or 0.0)
    neta = float(neta or 0.0)
    costo = float(costo or 0.0)
    tot_bruta = tot_bruta + bruta
    tot_neta = tot_neta + neta
    tot_costo = tot_costo + costo
    margen = neta - costo
    pct = round(margen / neta * 100.0, 2) if neta != 0.0 else 0.0
    dias = dias_map.get((team_id, dow), 0)
    neta_dia = round(neta / dias, 2) if dias else 0.0
    bruta_dia = round(bruta / dias, 2) if dias else 0.0
    margen_dia = round(margen / dias, 2) if dias else 0.0
    sucursal = TEAM_SUCURSAL.get(team_id, 'team %s' % team_id)
    dia_lbl = '%s-%s' % (dow, DOW.get(dow, dow))      # '5-Vie' -> ordena bien
    # Reloj extendido: las horas anteriores al corte pertenecen al turno del
    # dia anterior -> se muestran como 24:00, 25:00, 26:00... para que el
    # orden alfabetico sea el orden cronologico del turno.
    hora_ext = hod if hod >= corte else hod + 24
    hora_desc = '%02d:00' % hora_ext
    vals_list.append(keep_existing({
        # x_name (Descripcion): legible, unico y autodescriptivo. Lleva el
        # periodo porque la foto es una sola y todas las filas lo comparten.
        #   'Panguipulli 790 | 5-Vie | 25:00 | 12sem al 2026-09-06'
        'x_name': '%s | %s | %s | %dsem al %s' % (
            sucursal, dia_lbl, hora_desc, semanas, d_hasta.isoformat()),
        'x_studio_team_id': team_id,
        'x_studio_sucursal': sucursal,
        'x_studio_dia_semana': dow,
        'x_studio_dia': dia_lbl,
        'x_studio_hora': hod,              # hora de reloj real 0-23
        'x_studio_hora_desc': hora_desc,   # reloj extendido, agrupable
        # --- PROMEDIO por dia operativo (lo que se lee) ---
        # OJO: dias_activo (CUANTOS viernes hubo, ~12) no es dia_semana
        # (CUAL dia es, 5=viernes). Uno es denominador, el otro dimension.
        # Se escriben ambos nombres; keep_existing usa el que exista.
        'x_studio_dias_activo': dias,
        'x_studio_dias': dias,
        # Promedio por dia activo = acumulado / dias_activo.
        # Se escriben las variantes de nombre; keep_existing usa la que exista.
        'x_studio_venta_neta_dia_promedio': neta_dia,
        'x_studio_venta_neta_promedio': neta_dia,
        'x_studio_venta_neta_dia': neta_dia,
        'x_studio_venta_bruta_dia_promedio': bruta_dia,
        'x_studio_venta_bruta_promedio': bruta_dia,
        'x_studio_venta_bruta_dia': bruta_dia,
        # Margen $ POR DIA. Sin esto, un pivot que cruce venta_neta_dia_promedio
        # (1 dia) con margen_monto (12 dias) muestra el margen 12x la venta.
        'x_studio_margen_dia_promedio': margen_dia,
        # --- ACUMULADO de la ventana (base del margen y totales) ---
        'x_studio_venta_bruta': round(bruta, 2),
        'x_studio_venta_neta': round(neta, 2),
        'x_studio_costo_total': round(costo, 2),
        'x_studio_margen_monto': round(margen, 2),
        'x_studio_margen_pct': pct,
        # Fechas del periodo: OPCIONALES (el periodo ya va en x_name).
        # 'mes' es LEGACY: con foto rodante el nombre ya no aplica.
        'x_studio_desde': d1,
        'x_studio_hasta': d_hasta,
        'x_studio_mes': d1,
        'x_studio_calculo': now,
    }))

if vals_list:
    env[MODEL].create(vals_list)

# ---- 5) reporte de calidad ----
incompletos = []
for key in dias_map:
    if dias_map[key] < semanas:
        incompletos.append('%s %s=%d' % (
            TEAM_SUCURSAL.get(key[0], key[0]), DOW.get(key[1], key[1]), dias_map[key]))

CRITICOS = ['x_studio_venta_neta', 'x_studio_margen_monto']
OPCIONALES = ['x_studio_margen_pct', 'x_studio_sucursal', 'x_studio_hora_desc']
# Campos con nombre alternativo: basta con que exista UNO de los dos.
ALIAS = [
    ['x_studio_dias_activo', 'x_studio_dias'],
    ['x_studio_venta_neta_dia_promedio', 'x_studio_venta_neta_promedio',
     'x_studio_venta_neta_dia'],
    ['x_studio_venta_bruta_dia_promedio', 'x_studio_venta_bruta_promedio',
     'x_studio_venta_bruta_dia'],
    ['x_studio_margen_dia_promedio'],
]
for grupo in ALIAS:
    hay = False
    for n in grupo:
        if n in MFIELDS:
            hay = True
    if not hay:
        OPCIONALES = OPCIONALES + [grupo[0]]
falta_crit = []
for f in CRITICOS:
    if f not in MFIELDS:
        falta_crit.append(f)
falta_opt = []
for f in OPCIONALES:
    if f not in MFIELDS:
        falta_opt.append(f)

mg_global = round((tot_neta - tot_costo) / tot_neta * 100.0, 2) if tot_neta else 0.0
log('Perfil hora x sala x dia operativo | %s a %s (%d sem, corte %02d:00) | '
    'filas=%d | neta acum=%d | margen global=%s%%' % (
        d1s, d_hasta.isoformat(), semanas, corte, len(vals_list),
        int(round(tot_neta)), mg_global))
if incompletos:
    log('OJO dias<%d (posible cierre, revisar antes de decidir dotacion): %s'
        % (semanas, incompletos))
if falta_crit:
    log('CRITICO: faltan campos en %s -> %s (margen no auditable)' % (MODEL, falta_crit))
if falta_opt:
    log('INFO: campos opcionales ausentes en %s -> %s' % (MODEL, falta_opt))

msg = '%d filas | %s a %s (%d sem) | neta acum $%d | margen %s%%' % (
    len(vals_list), d1s, d_hasta.isoformat(), semanas, int(round(tot_neta)), mg_global)
if falta_crit:
    msg = msg + ' | FALTAN campos criticos: %s' % ', '.join(falta_crit)

action = {
    'type': 'ir.actions.client', 'tag': 'display_notification',
    'params': {'title': 'Perfil ventas x hora x sala', 'message': msg,
               'type': 'warning' if falta_crit else 'success',
               'sticky': bool(falta_crit)},
}
