# OH Forecast Base - Pronostico semanal por modelo-base auto-seleccionado
# ============================================================
#
# Version activa: v1.0 (2026-06-02)  [reemplaza OH SMA4 Forecast v1.0]
#
# Que hace (modelo base AUTO, validado en proyectos/2026-06-02-auto-model-segmento):
#   Por (sala=crm.team, SKU=product.product) clasifica la serie LOCALMENTE
#   (Syntetos-Boylan: ADI/CV2 sobre la venta de ESE combo) y elige el modelo:
#
#       series_type smooth  + ABC=A           -> SES(alfa=0.5)
#       series_type smooth  + ABC=B/C         -> SES(alfa=0.6)
#       series_type erratic                   -> SES(alfa=0.7)
#       series_type lumpy/intermittent/no_sig -> Mediana(4)
#
#   ABC se lee GLOBAL de x_calculo_abc_xyz (x_studio_abcxyz, por producto).
#   El regimen persistido es GLOBAL (team_id=False); por eso NO se lee: la forma
#   de la serie se clasifica LOCAL aqui, que es lo que el backtest valido
#   (FVA +6.83% vs SMA(4) plano; WAPE 67.1%->62.5%, bias +18.9%->+9.9%).
#
#   mu_week = pronostico 1-paso (SES nivel suavizado, o Mediana de las 4 cerradas).
#   sigma_week = std de las ULTIMAS 4 sem (para safety stock, igual que antes).
#   Venta CRUDA combo-expandida (sin de-censura de quiebre).
#   SKUs sin venta en DEMAND_WINDOW_WEEKS=26 sem se omiten (dead). El control de
#   muertos vive aguas abajo (dummy de control + minimo por ABC en Analisis Stock).
#
#   Escribe a x_hm_si_forecast con el MISMO contrato:
#     x_studio_mu_week, x_studio_sigma_week, x_studio_product_id (m2o product.product),
#     x_studio_team_id (m2o crm.team), x_studio_week_start (date),
#     x_studio_forecast_model_code (el modelo elegido, para auditoria).
#
# Contexto soportado (backtest/overrides): date_to (cutoff), team_ids, hard_reset,
#   fwd_model, demand_window_weeks. Overrides de modelo: force_alpha (fuerza SES con
#   ese alfa a TODO), force_median (True -> Mediana(4) a todo). Solo para diagnostico.
#
# No toca stock, compras, transferencias ni OC. Solo escribe el forecast.
# ============================================================

VERSION_ID = "OH_FORECAST_BASE_v1_0"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009438          # mismo lock que el forecast HM-SI/SMA4: mutuamente excluyentes

FWD_MODEL_DEFAULT = 'x_hm_si_forecast'
SEG_MODEL = 'x_calculo_abc_xyz'      # fuente del ABC global
HARD_RESET_DEFAULT = True
FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
DEMAND_WINDOW_WEEKS_DEFAULT = 26     # ventana para clasificar + universo activo
MEDIAN_K = 4                         # Mediana(4) y ventana de sigma
# Clasificacion Syntetos-Boylan
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49
MIN_ACTIVE_WEEKS = 4
# Alfas SES por (series_type, ABC)
ALPHA_SMOOTH_A = 0.5
ALPHA_SMOOTH_BC = 0.6
ALPHA_ERRATIC = 0.7
BATCH_SIZE = 500


# ----------------------
# Helpers
# ----------------------
def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _safe_text(v, maxlen=255):
    if v is None:
        return ''
    try:
        s = str(v)
    except Exception:
        s = ''
    return s[:maxlen] if (maxlen and len(s) > maxlen) else s


def _to_int_list(val):
    out = []
    if not val:
        return out
    try:
        for x in val:
            try:
                out.append(int(x))
            except Exception:
                pass
    except Exception:
        try:
            out = [int(val)]
        except Exception:
            out = []
    return out


def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def _field_exists(fields_map, fname):
    return bool(fname) and fname in (fields_map or {})


def _put_field(vals, fields_map, fname, value, maxlen=255):
    f = (fields_map or {}).get(fname)
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
    elif ftype in ('date', 'datetime'):
        vals[fname] = value
    else:
        vals[fname] = value


def _classify_series_type(vals):
    """Syntetos-Boylan sobre el vector semanal (incluye ceros). PROXY del Script 1.
    ADI = semanas / semanas_con_demanda ; CV2 = var/mu^2 sobre periodos con qty>0.
    Loops explicitos (sin comprehensions que capturen locales) por el safe_eval
    de Odoo, que prohibe closures (MAKE_CELL/LOAD_DEREF) dentro de funciones."""
    n = 0
    active = 0
    total = 0.0
    for x in vals:
        n += 1
        if x > 0.0:
            active += 1
            total += x
    if active < MIN_ACTIVE_WEEKS:
        return 'no_signal'
    adi = float(n) / active if active else 0.0
    if adi <= 0:
        return 'no_signal'
    mu = total / active
    if mu <= 0:
        return 'no_signal'
    sumsq = 0.0
    for x in vals:
        if x > 0.0:
            d = x - mu
            sumsq += d * d
    cv2 = (sumsq / active) / (mu * mu)   # var poblacional (ddof=0), como el harness
    intermittent = adi >= ADI_THRESHOLD
    high_var = cv2 >= CV2_THRESHOLD
    if intermittent:
        return 'lumpy' if high_var else 'intermittent'
    return 'erratic' if high_var else 'smooth'


def _ses_level(vals, alpha):
    """Nivel SES (adjust=False) tras la ultima semana cerrada = forecast 1-paso."""
    level = None
    for y in vals:
        if level is None:
            level = y
        else:
            level = alpha * y + (1.0 - alpha) * level
    return level if level is not None else 0.0


def _median(seq):
    s = sorted(seq)
    k = len(s)
    if k == 0:
        return 0.0
    return s[k // 2] if (k % 2) else (s[k // 2 - 1] + s[k // 2]) / 2.0


# ----------------------
# Contexto
# ----------------------
CTX = env.context or {}
FWD_MODEL  = str(CTX.get('fwd_model', FWD_MODEL_DEFAULT) or FWD_MODEL_DEFAULT)
HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
DEMAND_WINDOW_WEEKS = int(CTX.get('demand_window_weeks', DEMAND_WINDOW_WEEKS_DEFAULT))
FORCE_ALPHA = CTX.get('force_alpha')          # diagnostico: SES(alpha) a todo
FORCE_MEDIAN = bool(CTX.get('force_median'))  # diagnostico: Mediana(4) a todo

TEAM_IDS = _to_int_list(CTX.get('team_ids')) or list(FILTERED_TEAM_IDS_DEFAULT)
company = env.company

FWD = env[FWD_MODEL].sudo()
fwd_fields = FWD._fields or {}

_missing = [f for f in ['x_studio_product_id', 'x_studio_team_id', 'x_studio_week_start', 'x_studio_mu_week']
            if not _field_exists(fwd_fields, f)]


# ----------------------
# Lock
# ----------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
locked = env.cr.fetchone()[0]

if _missing:
    if locked:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
    action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
        'title': 'Forecast Base', 'message': 'Faltan campos en %s: %s' % (FWD_MODEL, ', '.join(_missing)),
        'type': 'danger', 'sticky': True}}
elif not locked:
    action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
        'title': 'Forecast Base', 'message': 'Otro forecast esta ejecutandose.', 'type': 'warning', 'sticky': False}}
else:
    try:
        # ----------------------
        # Fechas: date_to = fin de la ultima semana cerrada; target = sig. semana
        # ----------------------
        env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
        today_local = env.cr.fetchone()[0]
        current_week_start = _week_start(today_local)
        last_closed_week_end = current_week_start - datetime.timedelta(days=1)

        date_to_ctx = CTX.get('date_to')
        if date_to_ctx:
            try:
                raw_date = datetime.datetime.fromisoformat(str(date_to_ctx)).date()
                date_to = _week_start(raw_date) + datetime.timedelta(days=6)
                if date_to >= current_week_start:
                    date_to = last_closed_week_end
            except Exception:
                date_to = last_closed_week_end
        else:
            date_to = last_closed_week_end

        last_closed_monday = _week_start(date_to)
        target_date = last_closed_monday + datetime.timedelta(weeks=1)   # semana a pronosticar
        # vector semanal completo de la ventana (orden cronologico), relleno con 0
        window_weeks = [last_closed_monday - datetime.timedelta(weeks=k)
                        for k in range(DEMAND_WINDOW_WEEKS - 1, -1, -1)]
        window_from = window_weeks[0]

        # ----------------------
        # Venta semanal POS (combo-expandida), por (team, product)
        # ----------------------
        pt_fields = env['product.template']._fields or {}
        dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

        pc_fields = env['pos.config']._fields or {}
        team_col_sql = None
        f = pc_fields.get('crm_team_id')
        if f and f.type == 'many2one' and f.comodel_name == 'crm.team':
            team_col_sql = 'pc.crm_team_id'
        if not team_col_sql:
            f = pc_fields.get('team_id')
            if f and f.type == 'many2one' and f.comodel_name == 'crm.team':
                team_col_sql = 'pc.team_id'

        if not team_col_sql:
            action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': 'Forecast Base', 'message': 'No hay crm_team_id/team_id en pos.config.',
                'type': 'danger', 'sticky': True}}
        else:
            team_filter_sql = ''
            params = {'company_id': company.id, 'date_from': window_from,
                      'date_to': date_to, 'tz': TZ_NAME}
            if TEAM_IDS:
                team_filter_sql = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '
                params['team_ids'] = TEAM_IDS

            sql = """
                WITH base AS (
                    SELECT {team_col} AS team_id, pol.id AS line_id, pol.combo_parent_id,
                           pp.id AS product_id, {dtype_sql} AS dtype,
                           date_trunc('week', po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS week,
                           COALESCE(pol.qty, 0.0) AS qty
                    FROM pos_order_line pol
                    JOIN pos_order po ON po.id = pol.order_id
                    LEFT JOIN pos_session ps ON ps.id = po.session_id
                    LEFT JOIN pos_config pc ON pc.id = ps.config_id
                    JOIN product_product pp ON pp.id = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE po.company_id = %(company_id)s
                      AND po.state IN ('paid','done','invoiced')
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(date_from)s
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                      AND pp.active = TRUE AND pt.sale_ok = TRUE AND pt.active = TRUE
                      AND {team_col} IS NOT NULL
                      {team_filter}
                ),
                standalone AS (
                    SELECT team_id, product_id, week, SUM(qty) AS units
                    FROM base
                    WHERE combo_parent_id IS NULL AND COALESCE(dtype,'') NOT IN ('combo','service')
                    GROUP BY 1,2,3
                ),
                combo_children AS (
                    SELECT c.team_id, c.product_id, c.week, SUM(c.qty) AS units
                    FROM base c JOIN base p ON p.line_id = c.combo_parent_id
                    WHERE c.combo_parent_id IS NOT NULL AND COALESCE(c.dtype,'') <> 'service'
                    GROUP BY 1,2,3
                )
                SELECT team_id, product_id, week, SUM(units) AS units
                FROM (SELECT * FROM standalone UNION ALL SELECT * FROM combo_children) su
                GROUP BY 1,2,3
            """.format(team_col=team_col_sql, dtype_sql=dtype_sql, team_filter=team_filter_sql)

            env.cr.execute(sql, params)
            sales = {}
            for team_id, product_id, week, qty in env.cr.fetchall():
                tid = _safe_int(team_id); pid = _safe_int(product_id)
                if not tid or not pid or not week:
                    continue
                q = _safe_float(qty, 0.0)
                if q < 0.0:
                    q = 0.0
                sales.setdefault((tid, pid), {})[week] = sales.get((tid, pid), {}).get(week, 0.0) + q

            pids = list(set(p for (_t, p) in sales.keys()))

            # categoria por product.product
            categ_of = {}
            if pids:
                env.cr.execute("""
                    SELECT pp.id, pt.categ_id
                    FROM product_product pp JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE pp.id = ANY(%s)
                """, (pids,))
                for pid, cid in env.cr.fetchall():
                    categ_of[_safe_int(pid)] = _safe_int(cid)

            # ABC GLOBAL por producto desde x_calculo_abc_xyz (x_studio_abcxyz)
            abc_letter = {}
            try:
                Seg = env[SEG_MODEL].sudo()
                seg_fields = Seg._fields or {}
                if _field_exists(seg_fields, 'x_studio_product_id') and _field_exists(seg_fields, 'x_studio_abcxyz') and pids:
                    for rec in Seg.search_read([('x_studio_product_id', 'in', pids)],
                                               ['x_studio_product_id', 'x_studio_abcxyz']):
                        pr = rec.get('x_studio_product_id')
                        prid = _safe_int(pr[0] if isinstance(pr, (list, tuple)) else pr)
                        ltr = (_safe_text(rec.get('x_studio_abcxyz'), 3) or '')[:1].upper()
                        if prid and ltr:
                            abc_letter[prid] = ltr
            except Exception:
                abc_letter = {}   # sin ABC -> smooth usa alfa 0.6 (no-A)

            # ----------------------
            # Purga + escritura
            # ----------------------
            if HARD_RESET:
                purge_domain = [('x_studio_team_id', 'in', TEAM_IDS)] if TEAM_IDS else [('x_studio_team_id', '!=', False)]
                old = FWD.search(purge_domain)
                purge_count = len(old)
                if old:
                    old.unlink()
            else:
                purge_count = 0

            batch = []
            n_created = 0
            n_nonzero = 0
            mu_total = 0.0
            model_counts = {}
            for (tid, pid), wkmap in sales.items():
                vals = [_safe_float(wkmap.get(w, 0.0), 0.0) for w in window_weeks]   # vector cronologico
                last4 = vals[-MEDIAN_K:] if len(vals) >= MEDIAN_K else vals
                mean4 = sum(last4) / len(last4) if last4 else 0.0

                stype = _classify_series_type(vals)
                abc = abc_letter.get(pid, '')

                # --- seleccion de modelo ---
                if FORCE_MEDIAN:
                    model_code = 'median4'; mu = _median(last4)
                elif FORCE_ALPHA is not None:
                    a = _safe_float(FORCE_ALPHA, 0.6); model_code = 'ses_a%.2f' % a; mu = _ses_level(vals, a)
                elif stype == 'smooth':
                    a = ALPHA_SMOOTH_A if abc == 'A' else ALPHA_SMOOTH_BC
                    model_code = 'ses_a%.2f' % a; mu = _ses_level(vals, a)
                elif stype == 'erratic':
                    a = ALPHA_ERRATIC; model_code = 'ses_a%.2f' % a; mu = _ses_level(vals, a)
                else:   # lumpy / intermittent / no_signal
                    model_code = 'median4'; mu = _median(last4)

                if mu < 0.0:
                    mu = 0.0
                # sigma desde la media de las 4 (safety stock), robusto a 1 dato
                if len(last4) > 1:
                    sigma = (sum((x - mean4) ** 2 for x in last4) / len(last4)) ** 0.5
                else:
                    sigma = 0.0

                mu_total += mu
                if mu > 0.0:
                    n_nonzero += 1
                model_counts[model_code] = model_counts.get(model_code, 0) + 1

                vals_w = {}
                if _field_exists(fwd_fields, 'x_name'):
                    vals_w['x_name'] = 'BASE %s LOC%s PP%s' % (stype[:4].upper(), tid, pid)
                _put_field(vals_w, fwd_fields, 'x_studio_product_id', pid)
                _put_field(vals_w, fwd_fields, 'x_studio_team_id', tid)
                _put_field(vals_w, fwd_fields, 'x_studio_categ_id', categ_of.get(pid) or False)
                _put_field(vals_w, fwd_fields, 'x_studio_week_start', target_date)
                _put_field(vals_w, fwd_fields, 'x_studio_mu_week', mu)
                _put_field(vals_w, fwd_fields, 'x_studio_sigma_week', sigma)
                _put_field(vals_w, fwd_fields, 'x_studio_mu_week_pre_bias', mu)
                _put_field(vals_w, fwd_fields, 'x_studio_forecast_model_code', model_code, 60)
                batch.append(vals_w)

                if len(batch) >= BATCH_SIZE:
                    FWD.create(batch)
                    n_created += len(batch)
                    batch = []
            if batch:
                FWD.create(batch)
                n_created += len(batch)

            try:
                mc = ' '.join('%s=%s' % (k, v) for k, v in sorted(model_counts.items()))
                log('%s | target=%s | win=%s..%s | purged=%s | created=%s | nonzero=%s | mu_sum=%s | models[%s] | teams=%s' % (
                    VERSION_ID, target_date, window_weeks[0], window_weeks[-1],
                    purge_count, n_created, n_nonzero, round(mu_total, 1), mc, len(TEAM_IDS)), level='info')
            except Exception:
                pass

            action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': 'Forecast Base v1.0',
                'message': 'OK | target=%s | filas=%s | con venta=%s | mu_sum=%s' % (
                    target_date, n_created, n_nonzero, round(mu_total, 0)),
                'type': 'success', 'sticky': True}}
    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
