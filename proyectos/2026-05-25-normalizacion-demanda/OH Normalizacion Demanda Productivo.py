# ============================================================
# OH Normalizacion Demanda (Fase 2, ESCRIBE) - v1.0
# ------------------------------------------------------------
# Patron canonico SAP IBP "Outlier Correction with Available
# Probability". Persistir overlay separado del raw POS:
#   x_demanda_normalizada(team, sku, week_start) = {qty_obs, qty_norm}
#
# Reglas:
#   1) Para cada (team, sku) con dias de quiebre en la ventana,
#      calcula avail ponderado por perfil weekday (sala/categ/sku).
#   2) Si avail >= AVAIL_FLOOR: qty_norm = qty_obs * min(1/avail, CAP)
#      (metodo='inflate').
#   3) Si avail < AVAIL_FLOOR: usar fallback vecino = mean(qty de
#      semanas limpias dentro de +/-NEIGHBOR_WEEKS del mismo par).
#      qty_norm = max(qty_obs, mean_vecinos)
#      (metodo='fallback_neighbor').
#   4) Si fallback < 2 vecinos disponibles -> skip (no escribe).
#   5) Solo escribe cuando qty_norm > qty_obs (efecto real).
#
# Idempotente: DELETE de la ventana + INSERT batch. Lock advisory.
#
# NO toca HM-SI. Ese patch es paso siguiente y separado.
#
# Diseno: proyectos/2026-05-25-normalizacion-demanda/diseno.md
# Plan:   proyectos/2026-05-25-normalizacion-demanda/plan.md
#
# safe_eval: sin import, sin class, sin getattr. datetime y log() en scope.
# ============================================================

VERSION_ID    = "NORMALIZACION_DEMANDA_v1_0"
TARGET_MODEL  = 'x_demanda_normalizada'
TZ_NAME       = 'America/Santiago'
LOCK_KEY      = 99009442

# Salas (mismas que el resto del pipeline)
FILTERED_TEAM_IDS = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

# Cobertura de x_stock_balance_daily
COVERAGE_FLOOR = (2025, 1, 1)
WINDOW_WEEKS   = 52

# Calibracion: ajustar tras correr DIAG fase 1 y revisar uplift_demanda_pct.
# Default = 0.30 (centro del rango probado en DIAG).
AVAIL_FLOOR          = 0.30
CAP                  = 2.5
MIN_CLEAN_DAYS_LEVEL = 20
NEIGHBOR_WEEKS       = 4    # ventana +/-N semanas para fallback
MIN_NEIGHBORS        = 2    # vecinos limpios minimos para fallback

CREATE_BATCH = 500


def _log(msg, *a):
    log((msg % a) if a else msg, level='info')

def _warn(msg, *a):
    log((msg % a) if a else msg, level='warning')


# ---------------------------------------------------------------
# 0) Lock advisory (concurrencia)
# ---------------------------------------------------------------
env.cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    raise ValueError("LOCK %s ya en uso (otra corrida activa)" % LOCK_KEY)
_log('%s: lock %s adquirido', VERSION_ID, LOCK_KEY)


# ---------------------------------------------------------------
# 0.5) Validar estructura del modelo - fail fast
# ---------------------------------------------------------------
ESPERADOS = {
    'x_studio_team_id', 'x_studio_product_id', 'x_studio_week_start',
    'x_studio_qty_obs', 'x_studio_qty_norm', 'x_studio_factor', 'x_studio_avail',
    'x_studio_n_so', 'x_studio_perfil_level', 'x_studio_metodo',
    'x_studio_run_id', 'x_studio_version_id',
}
finfo = env[TARGET_MODEL].fields_get()
faltantes = [f for f in ESPERADOS if f not in finfo]
if faltantes:
    raise ValueError("Faltan campos en %s: %s" % (TARGET_MODEL, faltantes))
# Verificar tipo de week_start
if finfo['x_studio_week_start'].get('type') != 'date':
    raise ValueError("x_studio_week_start debe ser type='date', tiene type='%s'"
                     % finfo['x_studio_week_start'].get('type'))
_log('%s: estructura del modelo OK', VERSION_ID)


# ---------------------------------------------------------------
# 1) Ventana temporal
# ---------------------------------------------------------------
env.cr.execute("SELECT (now() AT TIME ZONE %s)::date", (TZ_NAME,))
today_local = env.cr.fetchone()[0]
date_to   = today_local - datetime.timedelta(days=1)
floor_d   = datetime.date(*COVERAGE_FLOOR)
date_from = date_to - datetime.timedelta(weeks=WINDOW_WEEKS) + datetime.timedelta(days=1)
if date_from < floor_d:
    date_from = floor_d

run_id = '%s_%s' % (VERSION_ID, datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
_log('%s: ventana [%s .. %s] run_id=%s', VERSION_ID, date_from, date_to, run_id)


# ---------------------------------------------------------------
# 2) Dias de quiebre desde x_stock_balance_daily
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
_log('%s: pares con quiebre=%s | dias-quiebre=%s',
     VERSION_ID, len(stockout_days), sum(len(s) for s in stockout_days.values()))


# ---------------------------------------------------------------
# 3) Ventas POS diarias (combo explosion)
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

pos_daily = {}
for tid, pid, d0, qty in env.cr.fetchall():
    if tid is None or pid is None or d0 is None:
        continue
    pos_daily.setdefault((int(tid), int(pid)), {})[d0] = float(qty or 0.0)
_log('%s: pares con venta POS=%s | use_combo=%s', VERSION_ID, len(pos_daily), use_combo)


# ---------------------------------------------------------------
# 4) Mapa producto -> categoria
# ---------------------------------------------------------------
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
# 5) qty semanal precomputada por (team, sku, lunes)
#    Sirve para fallback de vecinos limpios y para cells.
# ---------------------------------------------------------------
def _week_monday(d0):
    return d0 - datetime.timedelta(days=d0.weekday())

qty_weekly = {}    # (team, product, monday) -> qty_semana
weeks_with_pos = {}   # (team, product) -> set(monday)
for (tid, pid), day_map in pos_daily.items():
    for d0, q in day_map.items():
        m = _week_monday(d0)
        qty_weekly[(tid, pid, m)] = qty_weekly.get((tid, pid, m), 0.0) + q
        weeks_with_pos.setdefault((tid, pid), set()).add(m)


# ---------------------------------------------------------------
# 6) Perfil weekday (sala base, refinar a categ/sku)
# ---------------------------------------------------------------
wd_sala = {}; wd_sala_categ = {}; wd_sala_sku = {}
clean_categ = {}; clean_sku = {}

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
            continue
        wd = d0.weekday()
        _add7(wd_sala, tid, wd, qty)
        _add7(wd_sala_categ, (tid, categ), wd, qty)
        _add7(wd_sala_sku, (tid, pid), wd, qty)
        clean_categ.setdefault((tid, categ), set()).add(d0)
        clean_sku.setdefault((tid, pid), set()).add(d0)

def _normalize7(arr):
    # Clampar negativos: un weekday con venta NETA negativa (devoluciones
    # > ventas) no contribuye al perfil. Sin clamp, avail podia superar 1.0
    # cuando el dia con share negativo caia justo en quiebre (1.0 - (-X) > 1).
    arr_pos = [x if x > 0.0 else 0.0 for x in arr]
    tot = sum(arr_pos)
    if tot <= 0.0:
        return None
    return [x / tot for x in arr_pos]

share_sala = {}; share_sala_categ = {}; share_sala_sku = {}
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


# ---------------------------------------------------------------
# 7) Celdas (team, sku, semana con quiebre) con avail
# ---------------------------------------------------------------
cells = {}   # (team, product, lunes) -> {avail, obs, level, n_so}
weeks_with_quiebre = {}   # (team, product) -> set(monday)
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
            continue
        avail = 0.0
        obs = 0.0
        d = monday
        while d <= sunday:
            if d not in so_week:
                avail += sh[d.weekday()]
            obs += day_map.get(d, 0.0)
            d += datetime.timedelta(days=1)
        cells[(tid, pid, monday)] = {
            'avail': avail, 'obs': obs, 'level': lvl, 'n_so': len(so_week),
        }
        weeks_with_quiebre.setdefault((tid, pid), set()).add(monday)
_log('%s: celdas con quiebre=%s', VERSION_ID, len(cells))


# ---------------------------------------------------------------
# 8) Fallback: mean de vecinos limpios (semanas sin quiebre)
#    dentro de +/-NEIGHBOR_WEEKS. Usa qty_weekly precomputado.
# ---------------------------------------------------------------
def _fallback_qty(tid, pid, target_monday):
    pos_weeks = weeks_with_pos.get((tid, pid), set())
    so_weeks  = weeks_with_quiebre.get((tid, pid), set())
    candidates = []
    for delta in range(-NEIGHBOR_WEEKS, NEIGHBOR_WEEKS + 1):
        if delta == 0:
            continue
        w = target_monday + datetime.timedelta(weeks=delta)
        if w not in pos_weeks or w in so_weeks:
            continue
        candidates.append(qty_weekly.get((tid, pid, w), 0.0))
    if len(candidates) < MIN_NEIGHBORS:
        return None
    return sum(candidates) / len(candidates)


# ---------------------------------------------------------------
# 9) Computar qty_norm + metodo por celda
# ---------------------------------------------------------------
to_persist = []   # lista de dicts para create batch
n_inflate = 0
n_fallback = 0
n_skipped_no_neighbors = 0
n_skipped_no_effect = 0
sum_obs = 0.0
sum_norm = 0.0

for (tid, pid, monday), c in cells.items():
    qty_obs = c['obs']
    avail = c['avail']

    if avail >= AVAIL_FLOOR:
        # Inflate: 1/avail capped at CAP
        mult = 1.0 / avail if avail > 0 else CAP
        if mult > CAP:
            mult = CAP
        qty_norm = qty_obs * mult
        metodo = 'inflate'
        factor = mult
        n_inflate += 1
    else:
        fb = _fallback_qty(tid, pid, monday)
        if fb is None:
            n_skipped_no_neighbors += 1
            continue
        qty_norm = max(qty_obs, fb)
        metodo = 'fallback_neighbor'
        # factor solo expresivo: ratio post/pre. Si qty_obs=0, lo dejamos en 0.0.
        factor = (qty_norm / qty_obs) if qty_obs > 0 else 0.0
        n_fallback += 1

    # Solo persistir si hay efecto real (qty_norm > qty_obs).
    if qty_norm <= qty_obs + 1e-9:
        n_skipped_no_effect += 1
        continue

    to_persist.append({
        'x_name'                : '%s:%s:%s' % (tid, pid, monday),  # required en Studio
        'x_studio_team_id'      : tid,
        'x_studio_product_id'   : pid,
        'x_studio_week_start'   : monday,
        'x_studio_qty_obs'      : round(qty_obs, 4),
        'x_studio_qty_norm'     : round(qty_norm, 4),
        'x_studio_factor'       : round(factor, 4),
        'x_studio_avail'        : round(avail, 4),
        'x_studio_n_so'         : c['n_so'],
        'x_studio_perfil_level' : c['level'],
        'x_studio_metodo'       : metodo,
        'x_studio_run_id'       : run_id,
        'x_studio_version_id'   : VERSION_ID,
    })
    sum_obs += qty_obs
    sum_norm += qty_norm

_log('%s: a_persistir=%s | inflate=%s | fallback=%s | skip_no_neigh=%s | skip_no_effect=%s',
     VERSION_ID, len(to_persist), n_inflate, n_fallback,
     n_skipped_no_neighbors, n_skipped_no_effect)


# ---------------------------------------------------------------
# 10) DELETE existente en la ventana (idempotencia) + INSERT batch
# ---------------------------------------------------------------
Target = env[TARGET_MODEL].sudo()

existing = Target.search([
    ('x_studio_team_id', 'in', FILTERED_TEAM_IDS),
    ('x_studio_week_start', '>=', date_from),
    ('x_studio_week_start', '<=', date_to),
])
n_deleted = len(existing)
existing.unlink()
_log('%s: borrados %s registros previos de la ventana', VERSION_ID, n_deleted)

n_created = 0
for i in range(0, len(to_persist), CREATE_BATCH):
    Target.create(to_persist[i:i + CREATE_BATCH])
    n_created += min(CREATE_BATCH, len(to_persist) - i)
_log('%s: creados %s registros en %s', VERSION_ID, n_created, TARGET_MODEL)


# ---------------------------------------------------------------
# 11) Stats finales + notificacion
# ---------------------------------------------------------------
uplift_pct = ((sum_norm / sum_obs - 1.0) * 100.0) if sum_obs > 0 else 0.0

result = {
    'version'         : VERSION_ID,
    'run_id'          : run_id,
    'date_from'       : str(date_from),
    'date_to'         : str(date_to),
    'avail_floor'     : AVAIL_FLOOR,
    'cap'             : CAP,
    'cells_total'     : len(cells),
    'n_inflate'       : n_inflate,
    'n_fallback'      : n_fallback,
    'n_skip_no_neigh' : n_skipped_no_neighbors,
    'n_skip_no_eff'   : n_skipped_no_effect,
    'n_deleted'       : n_deleted,
    'n_created'       : n_created,
    'sum_qty_obs'     : round(sum_obs, 1),
    'sum_qty_norm'    : round(sum_norm, 1),
    'uplift_pct'      : round(uplift_pct, 2),
}
_log('%s OK | %s', VERSION_ID, result)

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'OH Normalizacion Demanda Productivo %s' % VERSION_ID,
        'message': ('Persistidas=%s (inflate=%s, fallback=%s) | '
                    'skip=%s+%s | uplift=+%s%% | floor=%s cap=%s') % (
            n_created, n_inflate, n_fallback,
            n_skipped_no_neighbors, n_skipped_no_effect,
            result['uplift_pct'], AVAIL_FLOOR, CAP),
        'type': 'success',
        'sticky': True,
    },
}
