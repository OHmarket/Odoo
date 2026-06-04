# ============================================================
# OH Calib Factors - Calibracion por (categ, abc_letter) v2.1
# ============================================================
#
# Version activa: v2.1 (idea Marco - level shift DESESTACIONALIZADO)
#
# Objetivo:
#   Calcula factor multiplicativo por (categ_id, abc_letter) midiendo
#   shift de nivel del cluster en ventas reales POS DESPUES de desestacionalizar.
#   INDEPENDIENTE del motor - cero ciclo, cero dependencia del backtest.
#
# Bug detectado v2.0 (29-05-2026):
#   Producto productivo aplico factores 0.80 saturados en cervezas, helados,
#   gaseosas y snacks. Causa: WINDOW_LONG=26 sem incluye verano (Dic-Feb peak),
#   WINDOW_RECENT=10 sem es post-verano. Ratio recent/long bajaba mecanicamente
#   por estacionalidad, no por declive real.
#
# Fix v2.1 (29-05-2026):
#   Replicar EXACTAMENTE la deflacion SI del motor HM-SI (_calc_si_from_weekly):
#     1. Para cada (categ_id, abc): build serie weekly 52 sem.
#     2. SI_w = avg_by_isoweek[w] / global_avg_serie  (canon HM-SI).
#        Clamp [SI_FLOOR=0.05, SI_CEIL=5.0].
#     3. Deflactar: qty_deflated_w = qty_w / SI_w
#     4. factor = avg(deflated ultimas RECENT sem) / avg(deflated ultimas LONG sem)
#     5. Clamp [0.80, 1.20]
#
# Validacion local (test_v22_si_canon.py, cutoff 2026-05-25):
#   - v2.0 (sin deflacion): avg=0.84, 54 saturados low (76%)  <- BUG
#   - v2.1 (SI canon):      avg=0.90, 19 saturados low (35%), 31 intermedios
#   - Cervezas Premium A: 0.80 -> 0.95 (no over-recorta)
#   - Cervezas Importadas A: 0.90 -> 1.20 (detecta crecimiento real)
#   - Helados: sigue 0.80 (raw 0.70-0.80) - es caida real estructural
#
# Cron: mensual dia 1 02:00. Manual on-demand tambien.
# ============================================================

VERSION_ID = "OH_CALIB_FACTORS_v2_1_SI_CANON"

TZ_NAME = 'America/Santiago'
LOCK_KEY = 99009613

# Modelo destino
CALIB_MODEL_DEFAULT = 'x_categ_calib_factor'

# Modelo segmentacion ABC del SKU
ABCXYZ_MODEL = 'x_calculo_abc_xyz'

# Parametros (configurables via CTX)
WINDOW_RECENT_DEFAULT = 10        # ventana corta (nivel actual)
WINDOW_LONG_DEFAULT   = 26        # ventana larga (nivel historico)
SI_HISTORY_WEEKS_DEFAULT = 52     # ventana para entrenar SI canon
MIN_REAL_UNITS_DEFAULT = 500.0    # min unid en ventana recent para calificar
FACTOR_CLAMP_LOW_DEFAULT  = 0.80  # M1b validado 2026-05-28
FACTOR_CLAMP_HIGH_DEFAULT = 1.20
APPLY_THRESHOLD_DEFAULT = 0.05
HARD_RESET_DEFAULT = True
# SI clamps - identicos al motor HM-SI
SI_FLOOR = 0.05
SI_CEIL  = 5.0

# Regimenes donde aplicar el factor (gate persistido por cluster).
# El motor v3.47 lee este string CSV del registro y aplica solo si el
# regimen del SKU esta en el set. Vacio = aplicar a todos.
# Default: REG-1/2/4/8 (test_L1L2 2026-05-28).
REGIMENES_APLICABLES_DEFAULT = 'REG-1,REG-2,REG-4,REG-8'


# ----------------------
# Helpers basicos
# ----------------------
def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _safe_text(v, maxlen=255):
    if v is None:
        return ''
    try:
        s = str(v)
    except Exception:
        s = ''
    if maxlen and len(s) > maxlen:
        return s[:maxlen]
    return s


def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def _abc_letter(abcxyz):
    s = str(abcxyz or '').strip().upper()
    return s[0] if s and s[0] in ('A', 'B', 'C') else ''


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _iso_w_52(d):
    """Mismo helper que motor HM-SI: iso_week capped a 52."""
    w = d.isocalendar()[1]
    return 52 if w > 52 else w


def _calc_si_canon(weekly_by_isoweek):
    """Replica EXACTA de _calc_si_from_weekly del motor HM-SI.

    weekly_by_isoweek: dict {iso_w: [qty_year1, qty_year2, ...]}
    Devuelve dict {iso_w: si_factor} con clamp [SI_FLOOR, SI_CEIL].
    Semanas sin datos -> SI=1.0 (neutro).
    """
    avg_by_week = {}
    for w, totals in (weekly_by_isoweek or {}).items():
        clean = []
        for x in (totals or []):
            xf = _safe_float(x, 0.0)
            if xf >= 0.0:
                clean.append(xf)
        if clean:
            avg_by_week[w] = sum(clean) / float(len(clean))
    if not avg_by_week:
        return {w: 1.0 for w in range(1, 53)}
    global_avg = sum(avg_by_week.values()) / float(len(avg_by_week))
    if global_avg <= 0.0:
        return {w: 1.0 for w in range(1, 53)}
    si_norm = {}
    for w, v in avg_by_week.items():
        si_norm[w] = _clamp(v / global_avg, SI_FLOOR, SI_CEIL)
    for w in range(1, 53):
        if w not in si_norm:
            si_norm[w] = 1.0
    return si_norm


def _first_field(model_obj, candidates):
    fields_map = model_obj._fields or {}
    for fname in candidates:
        if fname in fields_map:
            return fname
    return False


def _first_m2o_field(model_obj, candidates, comodel_name):
    fields_map = model_obj._fields or {}
    for fname in candidates:
        f = fields_map.get(fname)
        if not f:
            continue
        try:
            if f.type == 'many2one' and f.comodel_name == comodel_name:
                return fname
        except Exception:
            pass
    return False


def _model_exists(name):
    try:
        env[name]
        return True
    except Exception:
        return False


def _put_field(vals, fields_map, fname, value, maxlen=255):
    f = fields_map.get(fname)
    if not f:
        return
    try:
        ftype = f.type or ''
    except Exception:
        ftype = ''
    if ftype in ('float', 'monetary'):
        vals[fname] = _safe_float(value, 0.0)
    elif ftype == 'integer':
        vals[fname] = _safe_int(value, 0)
    elif ftype == 'boolean':
        vals[fname] = bool(value)
    elif ftype == 'many2one':
        vals[fname] = value or False
    elif ftype in ('char', 'text', 'html'):
        vals[fname] = _safe_text(value, maxlen)
    elif ftype == 'selection':
        keys = []
        try:
            sel = f.selection or []
            if not callable(sel):
                for item in sel:
                    try:
                        keys.append(item[0])
                    except Exception:
                        pass
        except Exception:
            pass
        txt = _safe_text(value, maxlen)
        if not keys:
            vals[fname] = txt
        elif txt in keys:
            vals[fname] = txt
        else:
            txt_lc = txt.lower()
            for k in keys:
                if str(k).lower() == txt_lc:
                    vals[fname] = k
                    break
    elif ftype in ('date', 'datetime'):
        vals[fname] = value
    else:
        vals[fname] = value


# ----------------------
# Configuracion runtime
# ----------------------
CTX = (env.context or {})

CALIB_MODEL = CTX.get('calib_model', CALIB_MODEL_DEFAULT)
WINDOW_RECENT = int(CTX.get('window_recent', WINDOW_RECENT_DEFAULT))
WINDOW_LONG = int(CTX.get('window_long', WINDOW_LONG_DEFAULT))
SI_HISTORY_WEEKS = int(CTX.get('si_history_weeks', SI_HISTORY_WEEKS_DEFAULT))
MIN_REAL_UNITS = float(CTX.get('min_real_units', MIN_REAL_UNITS_DEFAULT))
FACTOR_CLAMP_LOW = float(CTX.get('factor_clamp_low', FACTOR_CLAMP_LOW_DEFAULT))
FACTOR_CLAMP_HIGH = float(CTX.get('factor_clamp_high', FACTOR_CLAMP_HIGH_DEFAULT))
APPLY_THRESHOLD = float(CTX.get('apply_threshold', APPLY_THRESHOLD_DEFAULT))
HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
REGIMENES_APLICABLES = str(CTX.get('regimenes_aplicables', REGIMENES_APLICABLES_DEFAULT))

company = env.company

if not _model_exists(CALIB_MODEL):
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': VERSION_ID,
            'message': 'Modelo %s no existe. Crear en Studio primero.' % CALIB_MODEL,
            'type': 'danger', 'sticky': True,
        },
    }
elif not _model_exists(ABCXYZ_MODEL):
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': VERSION_ID,
            'message': 'Modelo %s no existe (necesario para ABC por SKU).' % ABCXYZ_MODEL,
            'type': 'danger', 'sticky': True,
        },
    }
else:
    env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
    locked = env.cr.fetchone()[0]
    if not locked:
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': VERSION_ID,
                'message': 'Otro proceso CALIB_FACTORS esta corriendo.',
                'type': 'warning', 'sticky': False,
            },
        }
    else:
        try:
            CalibModel = env[CALIB_MODEL].sudo()
            calib_fields = CalibModel._fields or {}

            # ----------------------
            # Ventana temporal
            # ----------------------
            # v2.1: ampliamos pull a SI_HISTORY_WEEKS (52 sem default) para
            # entrenar el SI canon por cluster. Las ventanas RECENT y LONG
            # son sub-ventanas dentro del pull.
            env.cr.execute("SELECT (timezone(%s, now())::date)", (TZ_NAME,))
            today_local = env.cr.fetchone()[0]
            # cutoff = lunes de esta semana (la actual NO esta cerrada)
            this_monday = _week_start(today_local)
            week_recent_start = this_monday - datetime.timedelta(weeks=WINDOW_RECENT)
            week_long_start = this_monday - datetime.timedelta(weeks=WINDOW_LONG)
            # SI training: 52 sem para detectar patron estacional anual
            week_si_start = this_monday - datetime.timedelta(weeks=SI_HISTORY_WEEKS)
            window_end = this_monday - datetime.timedelta(days=1)

            # ----------------------
            # Cargar ABC por SKU (de x_calculo_abc_xyz)
            # ----------------------
            Abc = env[ABCXYZ_MODEL].sudo()
            abc_pf = _first_m2o_field(Abc, ['x_studio_product_id'], 'product.product')
            abc_lf = _first_field(Abc, ['x_studio_abcxyz', 'x_studio_abc_xyz', 'x_studio_abc'])
            sku_to_abc = {}
            if abc_pf and abc_lf:
                abc_recs = Abc.search([]).read([abc_pf, abc_lf])
                for r in abc_recs:
                    pv = r.get(abc_pf)
                    pid = pv[0] if isinstance(pv, (list, tuple)) else _safe_int(pv)
                    if not pid:
                        continue
                    letter = _abc_letter(r.get(abc_lf))
                    if letter:
                        sku_to_abc[pid] = letter

            if not sku_to_abc:
                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': VERSION_ID,
                        'message': 'No se pudo cargar ABC por SKU desde %s. Verificar campos.' % ABCXYZ_MODEL,
                        'type': 'danger', 'sticky': True,
                    },
                }
            else:
                # ----------------------
                # SQL: ventas POS por (categ_id, sku, semana) en SI_HISTORY_WEEKS
                # ----------------------
                # v2.1: pull 52 sem para entrenar el SI canon. La agregacion
                # por cluster se hace en Python para tener weekly + iso_w totals.
                pos_sql = """
                    SELECT
                        pt.categ_id AS categ_id,
                        pp.id AS product_id,
                        date_trunc('week',
                            po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s
                        )::date AS wk,
                        SUM(COALESCE(pol.qty, 0.0)) AS qty
                    FROM pos_order_line pol
                    JOIN pos_order po ON po.id = pol.order_id
                    JOIN product_product pp ON pp.id = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE po.company_id = %(company_id)s
                      AND po.state IN ('paid', 'done', 'invoiced')
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(week_si_start)s
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(window_end)s
                      AND pp.active = TRUE
                      AND pt.sale_ok = TRUE
                      AND pt.active = TRUE
                    GROUP BY pt.categ_id, pp.id, 3
                """
                env.cr.execute(pos_sql, {
                    'tz': TZ_NAME,
                    'company_id': company.id,
                    'week_si_start': week_si_start,
                    'window_end': window_end,
                })
                rows = env.cr.fetchall()

                # ----------------------
                # Agregar por (categ, abc) - estructura para SI canon
                # ----------------------
                # acc[(categ, abc)] = {
                #   'weekly': {week_date: total_qty},   # para deflacion
                #   'iso_totals': {iso_w: [qty1, qty2,...]}, # para SI training
                #   'skus': set
                # }
                acc = {}
                for categ_id, pid, wk, qty in rows:
                    if not categ_id or not pid or not wk:
                        continue
                    letter = sku_to_abc.get(int(pid))
                    if not letter:
                        continue
                    key = (int(categ_id), letter)
                    b = acc.get(key)
                    if b is None:
                        b = {'weekly': {}, 'iso_totals': {}, 'skus': set()}
                        acc[key] = b
                    qf = _safe_float(qty, 0.0)
                    # Acumular weekly por (cluster, week_date)
                    b['weekly'][wk] = b['weekly'].get(wk, 0.0) + qf
                    b['skus'].add(int(pid))

                # Build iso_totals despues de tener weekly agregado por cluster
                for key, b in acc.items():
                    for wk_date, q in b['weekly'].items():
                        iw = _iso_w_52(wk_date)
                        b['iso_totals'].setdefault(iw, []).append(q)

                # ----------------------
                # Calculo de factores con SI canon
                # ----------------------
                # Para cada cluster:
                #   1. Calc SI dict canon (replica motor)
                #   2. Para cada semana de RECENT y LONG, deflactar qty/SI[iso_w]
                #   3. factor = avg(recent_deflated) / avg(long_deflated)
                candidates = []
                for (cid, letter), b in acc.items():
                    weekly = b['weekly']
                    if not weekly:
                        continue
                    # SI canon de este cluster
                    si_dict = _calc_si_canon(b['iso_totals'])

                    # Sumar qty_deflated en cada ventana
                    sum_def_recent = 0.0
                    sum_def_long = 0.0
                    sum_raw_recent = 0.0  # para min_units check
                    n_w_recent = 0
                    n_w_long = 0
                    for wk_date, qty_obs in weekly.items():
                        if wk_date < week_long_start or wk_date > window_end:
                            continue
                        iw = _iso_w_52(wk_date)
                        si_w = si_dict.get(iw, 1.0)
                        if si_w <= 0.0:
                            si_w = 1.0
                        qty_def = qty_obs / si_w
                        if wk_date >= week_recent_start:
                            sum_def_recent += qty_def
                            sum_raw_recent += qty_obs
                            n_w_recent += 1
                        sum_def_long += qty_def
                        n_w_long += 1

                    if sum_raw_recent < MIN_REAL_UNITS:
                        continue
                    if n_w_recent <= 0 or n_w_long <= 0:
                        continue
                    nivel_recent = sum_def_recent / float(n_w_recent)
                    nivel_long = sum_def_long / float(n_w_long)
                    if nivel_long <= 0:
                        continue
                    raw = nivel_recent / nivel_long
                    clamped = _clamp(raw, FACTOR_CLAMP_LOW, FACTOR_CLAMP_HIGH)
                    if abs(clamped - 1.0) < APPLY_THRESHOLD:
                        continue
                    bias_pct = (nivel_recent - nivel_long) / nivel_long * 100.0
                    candidates.append({
                        'categ_id': cid,
                        'abc_letter': letter,
                        'factor_corr': clamped,
                        'raw_factor': raw,
                        'n_real_units': sum_raw_recent,
                        'n_sample_pairs': len(b['skus']),
                        'bias_pct_pre': bias_pct,
                    })

                # ----------------------
                # Resolver campos del modelo destino
                # ----------------------
                catf = _first_m2o_field(CalibModel, ['x_studio_categ_id'], 'product.category')
                abcf = _first_field(CalibModel, ['x_studio_abc_letter'])
                facf = _first_field(CalibModel, ['x_studio_factor_corr'])
                rawf = _first_field(CalibModel, ['x_studio_raw_factor'])
                nruf = _first_field(CalibModel, ['x_studio_n_real_units'])
                nspf = _first_field(CalibModel, ['x_studio_n_sample_pairs'])
                biasf = _first_field(CalibModel, ['x_studio_bias_pct_pre'])
                twf = _first_field(CalibModel, ['x_studio_target_week', 'x_studio_target_week_start'])
                runidf = _first_field(CalibModel, ['x_studio_calc_run_id'])
                activef = _first_field(CalibModel, ['x_studio_active', 'active'])
                regf = _first_field(CalibModel, ['x_studio_regimenes_aplicables'])

                if not (catf and abcf and facf and twf):
                    action = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': VERSION_ID,
                            'message': ('Modelo %s falta campos requeridos '
                                        '(categ_id/abc_letter/factor_corr/target_week).') % CALIB_MODEL,
                            'type': 'danger', 'sticky': True,
                        },
                    }
                else:
                    # ----------------------
                    # HARD_RESET: marcar inactivos clusters previos
                    # ----------------------
                    purged_count = 0
                    if HARD_RESET and activef and candidates:
                        for c in candidates:
                            # Selection key minuscula; busqueda case-sensitive
                            prev = CalibModel.search([
                                (catf, '=', c['categ_id']),
                                (abcf, 'in', [c['abc_letter'].lower(),
                                              c['abc_letter'].upper()]),
                                (activef, '=', True),
                            ])
                            if prev:
                                prev.write({activef: False})
                                purged_count += len(prev)

                    # ----------------------
                    # Crear nuevos registros
                    # ----------------------
                    calib_create = CalibModel.with_context(
                        tracking_disable=True,
                        mail_create_nosubscribe=True,
                        mail_create_nolog=True,
                        mail_notrack=True,
                    ).create

                    try:
                        _ts = today_local.strftime('%Y%m%d_%H%M%S')
                    except Exception:
                        _ts = str(today_local)
                    run_id = '%s_%s' % (VERSION_ID, _ts)
                    target_week_persist = this_monday

                    created = 0
                    batch = []
                    for c in candidates:
                        vals = {}
                        if 'x_name' in calib_fields:
                            vals['x_name'] = 'categ=%s|abc=%s|%s' % (
                                c['categ_id'], c['abc_letter'], target_week_persist)
                        _put_field(vals, calib_fields, catf, c['categ_id'])
                        # Selection x_studio_abc_letter usa keys minusculas:
                        # [(a,A),(b,B),(c,C)]. Forzamos lower antes de pasar.
                        _put_field(vals, calib_fields, abcf, c['abc_letter'].lower(), 1)
                        _put_field(vals, calib_fields, facf, c['factor_corr'])
                        if rawf:
                            _put_field(vals, calib_fields, rawf, c['raw_factor'])
                        if nruf:
                            _put_field(vals, calib_fields, nruf, c['n_real_units'])
                        if nspf:
                            _put_field(vals, calib_fields, nspf, c['n_sample_pairs'])
                        if biasf:
                            _put_field(vals, calib_fields, biasf, c['bias_pct_pre'])
                        _put_field(vals, calib_fields, twf, target_week_persist)
                        if runidf:
                            _put_field(vals, calib_fields, runidf, run_id, 60)
                        if regf:
                            _put_field(vals, calib_fields, regf, REGIMENES_APLICABLES, 120)
                        if activef:
                            vals[activef] = True
                        batch.append(vals)
                        if len(batch) >= 200:
                            calib_create(batch)
                            created += len(batch)
                            batch = []
                    if batch:
                        calib_create(batch)
                        created += len(batch)

                    # ----------------------
                    # Resumen para notify
                    # ----------------------
                    top_factors = sorted(
                        candidates,
                        key=lambda x: abs(x['factor_corr'] - 1.0),
                        reverse=True,
                    )[:8]
                    factor_summary = ' '.join(
                        'cat%s/%s:f=%.2f' % (c['categ_id'], c['abc_letter'], c['factor_corr'])
                        for c in top_factors
                    )

                    msg = (
                        'SI-canon | si_train=%s..%s (%dsem) recent=%dsem long=%dsem | '
                        'rows_pos=%s clusters=%s | persisted=%s (purged=%s) | top: %s'
                    ) % (
                        week_si_start, window_end, SI_HISTORY_WEEKS,
                        WINDOW_RECENT, WINDOW_LONG,
                        len(rows), len(acc),
                        created, purged_count,
                        factor_summary[:200],
                    )
                    try:
                        log('%s | %s' % (VERSION_ID, msg), level='info')
                    except Exception:
                        pass
                    action = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': VERSION_ID,
                            'message': msg,
                            'type': 'success', 'sticky': True,
                        },
                    }
        finally:
            env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
