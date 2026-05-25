# ============================================================
# OH Normalizacion Demanda (DIAG, READ-ONLY) - Fase 1
# ------------------------------------------------------------
# Mide cuanto sesgo a la baja introduce el stockout en la demanda
# semanal y calibra AVAIL_FLOOR / CAP antes de tocar HM-SI.
# NO escribe nada productivo: solo loguea + retorna una notificacion.
#
# Antecesor read-only de la Fase 2 (normalizacion productiva, escribe):
# misma matematica (perfil weekday + disponibilidad + factor), sin escribir.
#
# Diseno: proyectos/2026-05-25-normalizacion-demanda/diseno.md
# Plan:   proyectos/2026-05-25-normalizacion-demanda/plan.md
#
# safe_eval: sin import, sin class, sin getattr. datetime y log() en scope.
# ============================================================

VERSION_ID = "NORMALIZACION_DIAG_v0_2"
TZ_NAME    = 'America/Santiago'

# Salas (mismas que el resto del pipeline)
FILTERED_TEAM_IDS = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

# Cobertura de x_stock_balance_daily: arranca 2025-01-01
COVERAGE_FLOOR = (2025, 1, 1)
WINDOW_WEEKS   = 52          # ventana de analisis (semanas hacia atras)

MIN_CLEAN_DAYS_LEVEL = 20    # dias limpios para refinar perfil sala -> categ/sku
AVAIL_FLOORS_TO_TEST = [0.20, 0.30, 0.40]
CAP                  = 2.5   # tope al multiplicador de correccion

# SKU de control que NO quiebra (spot-check). 0 = omitir.
CONTROL_SKU_NEVER_STOCKOUT = 0


def _log(msg, *a):
    log((msg % a) if a else msg, level='info')


# ---------------------------------------------------------------
# 1) Ventana temporal (HOY local Chile via SQL)
# ---------------------------------------------------------------
env.cr.execute("SELECT (now() AT TIME ZONE %s)::date", (TZ_NAME,))
today_local = env.cr.fetchone()[0]
date_to   = today_local - datetime.timedelta(days=1)            # dia cerrado = ayer
floor_d   = datetime.date(*COVERAGE_FLOOR)
date_from = date_to - datetime.timedelta(weeks=WINDOW_WEEKS) + datetime.timedelta(days=1)
if date_from < floor_d:
    date_from = floor_d

result = {'version': VERSION_ID, 'date_from': str(date_from), 'date_to': str(date_to)}
_log('%s: ventana [%s .. %s] teams=%s', VERSION_ID, date_from, date_to, FILTERED_TEAM_IDS)


# ---------------------------------------------------------------
# 2) Dias de quiebre desde x_stock_balance_daily
#    (la tabla SOLO persiste dias de quiebre -> presencia = quiebre)
#    full + partial tratados como quiebre en v1.
# ---------------------------------------------------------------
env.cr.execute("""
    SELECT x_studio_team_id, x_studio_product_id, x_studio_date
    FROM x_stock_balance_daily
    WHERE x_studio_team_id = ANY(%s)
      AND x_studio_date >= %s AND x_studio_date <= %s
      AND (x_studio_stockout = TRUE OR x_studio_stockout_partial = TRUE)
""", (list(FILTERED_TEAM_IDS), date_from, date_to))

stockout_days = {}
for tid, pid, d0 in env.cr.fetchall():
    if tid is None or pid is None or d0 is None:
        continue
    stockout_days.setdefault((int(tid), int(pid)), set()).add(d0)

result['pairs_con_quiebre']  = len(stockout_days)
result['dias_quiebre_total'] = sum(len(s) for s in stockout_days.values())
_log('%s: pares (sala,SKU) con quiebre=%s | dias-quiebre=%s',
     VERSION_ID, result['pairs_con_quiebre'], result['dias_quiebre_total'])


# ---------------------------------------------------------------
# 3) Ventas POS diarias (con combo explosion) + mapa producto->categoria
#    Filtro por fecha LOCAL con cast TZ (mismo patron que HM-SI).
# ---------------------------------------------------------------
env.cr.execute("""
    SELECT 1 FROM information_schema.columns
    WHERE table_name='pos_order_line' AND column_name='combo_parent_id' LIMIT 1
""")
use_combo = bool(env.cr.fetchone())

if use_combo:
    standalone_filter = "AND pol.combo_parent_id IS NULL AND pt.type NOT IN ('service','combo')"
    combo_union = """
        UNION ALL
        SELECT pc.crm_team_id AS team_id, pol.product_id,
               (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS d,
               pol.qty AS qty
        FROM pos_order_line pol
        JOIN pos_order po ON po.id = pol.order_id
        JOIN pos_session ps ON ps.id = po.session_id
        JOIN pos_config pc ON pc.id = ps.config_id
        WHERE po.state IN ('paid','invoiced','done')
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(dfrom)s
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(dto)s
          AND pc.crm_team_id = ANY(%(teams)s)
          AND pol.combo_parent_id IS NOT NULL
    """
else:
    standalone_filter = "AND pt.type NOT IN ('service','combo')"
    combo_union = ""

sql_pos = """
    SELECT team_id, product_id, d, SUM(qty) AS qty FROM (
        SELECT pc.crm_team_id AS team_id, pol.product_id,
               (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS d,
               pol.qty AS qty
        FROM pos_order_line pol
        JOIN pos_order po ON po.id = pol.order_id
        JOIN pos_session ps ON ps.id = po.session_id
        JOIN pos_config pc ON pc.id = ps.config_id
        JOIN product_product pp ON pp.id = pol.product_id
        JOIN product_template pt ON pt.id = pp.product_tmpl_id
        WHERE po.state IN ('paid','invoiced','done')
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(dfrom)s
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(dto)s
          AND pc.crm_team_id = ANY(%(teams)s)
          AND pp.active = TRUE AND pt.sale_ok = TRUE
          {standalone_filter}
        {combo_union}
    ) s
    GROUP BY team_id, product_id, d
""".format(standalone_filter=standalone_filter, combo_union=combo_union)

env.cr.execute(sql_pos, {
    'tz': TZ_NAME, 'dfrom': date_from, 'dto': date_to, 'teams': list(FILTERED_TEAM_IDS),
})

pos_daily = {}   # (team, product) -> { fecha: qty }
for tid, pid, d0, qty in env.cr.fetchall():
    if tid is None or pid is None or d0 is None:
        continue
    pos_daily.setdefault((int(tid), int(pid)), {})[d0] = float(qty or 0.0)

result['pares_pos'] = len(pos_daily)
_log('%s: pares (sala,SKU) con venta POS=%s | use_combo=%s', VERSION_ID, len(pos_daily), use_combo)

all_pids = list({pid for (_, pid) in pos_daily.keys()} | {pid for (_, pid) in stockout_days.keys()})
product_categ = {}
if all_pids:
    env.cr.execute("""
        SELECT pp.id, pt.categ_id FROM product_product pp
        JOIN product_template pt ON pt.id = pp.product_tmpl_id
        WHERE pp.id = ANY(%s)
    """, (all_pids,))
    for pid, cid in env.cr.fetchall():
        product_categ[int(pid)] = int(cid) if cid else 0


# ---------------------------------------------------------------
# 4) Perfil weekday (sala base, refinar a categ/sku si hay data)
# ---------------------------------------------------------------
wd_sala       = {}   # team -> [7]
wd_sala_categ = {}   # (team, categ) -> [7]
wd_sala_sku   = {}   # (team, product) -> [7]
clean_categ   = {}   # (team, categ) -> set(fechas limpias)
clean_sku     = {}   # (team, product) -> set(fechas limpias)


def _add7(dct, key, wd, qty):
    arr = dct.get(key)
    if arr is None:
        arr = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        dct[key] = arr
    arr[wd] += qty


for (tid, pid), day_map in pos_daily.items():
    so = stockout_days.get((tid, pid), set())
    categ = product_categ.get(pid, 0)
    for d0, qty in day_map.items():
        if d0 in so:
            continue   # dia contaminado: fuera del perfil limpio
        wd = d0.weekday()
        _add7(wd_sala, tid, wd, qty)
        _add7(wd_sala_categ, (tid, categ), wd, qty)
        _add7(wd_sala_sku, (tid, pid), wd, qty)
        clean_categ.setdefault((tid, categ), set()).add(d0)
        clean_sku.setdefault((tid, pid), set()).add(d0)


def _normalize7(arr):
    tot = sum(arr)
    if tot <= 0.0:
        return None
    return [x / tot for x in arr]


share_sala       = {}
share_sala_categ = {}
share_sala_sku   = {}
for k, arr in wd_sala.items():
    sh = _normalize7(arr)
    if sh:
        share_sala[k] = sh
for k, arr in wd_sala_categ.items():
    if len(clean_categ.get(k, set())) >= MIN_CLEAN_DAYS_LEVEL:
        sh = _normalize7(arr)
        if sh:
            share_sala_categ[k] = sh
for k, arr in wd_sala_sku.items():
    if len(clean_sku.get(k, set())) >= MIN_CLEAN_DAYS_LEVEL:
        sh = _normalize7(arr)
        if sh:
            share_sala_sku[k] = sh


def _weekday_share(tid, pid):
    sh = share_sala_sku.get((tid, pid))
    if sh:
        return sh, 'sku'
    sh = share_sala_categ.get((tid, product_categ.get(pid, 0)))
    if sh:
        return sh, 'categ'
    sh = share_sala.get(tid)
    if sh:
        return sh, 'sala'
    return None, 'none'


result['niveles_perfil'] = {'sala': len(share_sala),
                            'sala_categ': len(share_sala_categ),
                            'sala_sku': len(share_sala_sku)}


# ---------------------------------------------------------------
# 5) Disponibilidad ponderada por (sala, SKU, semana con quiebre)
# ---------------------------------------------------------------
def _week_monday(d0):
    return d0 - datetime.timedelta(days=d0.weekday())


cells = {}   # (team, product, lunes) -> {avail, obs, level, n_so}
for (tid, pid), so_set in stockout_days.items():
    sh, lvl = _weekday_share(tid, pid)
    if not sh:
        continue
    day_map = pos_daily.get((tid, pid), {})
    weeks = {}
    for d0 in so_set:
        weeks.setdefault(_week_monday(d0), set()).add(d0)
    for monday, so_week in weeks.items():
        sunday = monday + datetime.timedelta(days=6)
        if monday < date_from or sunday > date_to:
            continue   # semana parcial en el borde de cobertura -> excluir
        avail = 0.0
        obs = 0.0
        d = monday
        while d <= sunday:
            if d not in so_week:
                avail += sh[d.weekday()]
            obs += day_map.get(d, 0.0)
            d += datetime.timedelta(days=1)
        cells[(tid, pid, monday)] = {'avail': avail, 'obs': obs, 'level': lvl, 'n_so': len(so_week)}

result['celdas_semana_con_quiebre'] = len(cells)
_log('%s: celdas (sala,SKU,semana) con quiebre y perfil=%s', VERSION_ID, len(cells))


# ---------------------------------------------------------------
# 6) Metricas de calibracion + invariantes
# ---------------------------------------------------------------
def _bucket(x):
    if x <= 0.10: return '0.00-0.10'
    if x <= 0.20: return '0.10-0.20'
    if x <= 0.30: return '0.20-0.30'
    if x <= 0.40: return '0.30-0.40'
    if x <= 0.60: return '0.40-0.60'
    if x <= 0.80: return '0.60-0.80'
    return '0.80-1.00'


hist_avail = {}
for c in cells.values():
    b = _bucket(c['avail'])
    hist_avail[b] = hist_avail.get(b, 0) + 1
result['hist_avail'] = hist_avail

calib = {}
for fl in AVAIL_FLOORS_TO_TEST:
    n_inflate = 0
    n_fallback = 0
    obs_tot = 0.0
    corr_tot = 0.0
    for c in cells.values():
        obs = c['obs']
        obs_tot += obs
        if c['avail'] >= fl and c['avail'] > 0.0:
            n_inflate += 1
            mult = 1.0 / c['avail']
            if mult > CAP:
                mult = CAP
            corr_tot += obs * mult
        else:
            n_fallback += 1
            corr_tot += obs   # el fallback se modela en Fase 2; aqui no infla
    uplift = (corr_tot / obs_tot - 1.0) if obs_tot > 0 else 0.0
    calib[str(fl)] = {'n_inflate': n_inflate, 'n_fallback': n_fallback,
                      'uplift_demanda_pct': round(uplift * 100.0, 1)}
result['calibracion_por_floor'] = calib

chronic = 0
for c in cells.values():
    if c['avail'] < 0.30:
        chronic += 1
result['celdas_bajo_0_30'] = chronic

inv = {}
inv['share_sala_suma_1'] = all(abs(sum(v) - 1.0) < 1e-6 for v in share_sala.values())
# avail=0 ocurre cuando una semana esta full-quiebre los 7 dias. Es valido
# (cae a n_fallback). Por eso el limite inferior es 0.0 inclusive.
inv['avail_en_rango'] = all(0.0 <= c['avail'] <= 1.0 + 1e-9 for c in cells.values())
if CONTROL_SKU_NEVER_STOCKOUT:
    inv['control_sku_sin_correccion'] = not any(
        pid == CONTROL_SKU_NEVER_STOCKOUT for (_, pid, _) in cells.keys())
result['invariantes'] = inv

_log('%s OK | invariantes=%s | calib=%s', VERSION_ID, inv, calib)


# ---------------------------------------------------------------
# 7) Notificacion en UI (resumen). Detalle completo en el log.
# ---------------------------------------------------------------
_resumen = 'Celdas=%s | bajo0.30=%s | floors: ' % (
    result['celdas_semana_con_quiebre'], result['celdas_bajo_0_30'])
_resumen += ' / '.join(
    '%s -> +%s%% (inf=%s,fb=%s)' % (k, v['uplift_demanda_pct'], v['n_inflate'], v['n_fallback'])
    for k, v in calib.items())

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'OH Normalizacion Demanda %s' % VERSION_ID,
        'message': _resumen + ' | invariantes OK=%s' % all(inv.values()),
        'type': 'success' if all(inv.values()) else 'warning',
        'sticky': True,
    },
}
