# OH SMA4 Forecast - Pronostico de demanda semanal = media movil de 4 semanas
# ============================================================
#
# Version activa: v1.0 (2026-06-01)
#
# Reemplaza el motor HM-SI por un SMA(4) puro tras el FVA mostrar que la media
# movil de 4 semanas le gana al motor en todos los regimenes con volumen
# (FVA -6.1% sobre 6 sem; el motor over-forecastea +14% vs +8% del SMA4). Decision
# del dueno 2026-06-01: "SMA4 y listo". Detalle: proyectos/2026-06-01-fva-vs-sma4/.
#
# Que hace:
#   - mu_week = promedio de las ULTIMAS 4 SEMANAS CERRADAS de venta real POS
#     (combo-expandida), por (sala=crm.team, SKU=product.product).
#   - sigma_week = desviacion estandar de esas 4 semanas (para safety stock).
#   - Venta CRUDA (sin de-censura de quiebre): es el SMA4 que gano el FVA.
#   - SKUs sin venta en las 4 sem -> mu_week=0 (igual que el motor hoy). La red de
#     seguridad (minimo por ABC) vive downstream en OH Analisis de Stock, intacta.
#   - Escribe a x_hm_si_forecast con el MISMO contrato que leia el reabastecimiento:
#     x_studio_mu_week (float), x_studio_sigma_week, x_studio_product_id (m2o
#     product.product), x_studio_team_id (m2o crm.team), x_studio_week_start (date).
#
# Universo: pares (sala, SKU) con >=1 venta en las ultimas DEMAND_WINDOW_WEEKS=26
# sem (= ventana de demanda del motor). SKUs sin venta en 26 sem se omiten (dead).
#
# Contexto soportado (para backtest / overrides):
#   date_to (cutoff, se usa el fin de su semana), team_ids, hard_reset,
#   fwd_model, sma_weeks.
#
# No toca stock, compras, transferencias ni OC. Solo escribe el forecast.
# ============================================================

VERSION_ID = "OH_SMA4_FORECAST_v1_0"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009438          # mismo lock que el forecast HM-SI: mutuamente excluyentes

FWD_MODEL_DEFAULT = 'x_hm_si_forecast'
HARD_RESET_DEFAULT = True
FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
SMA_WEEKS_DEFAULT = 4
# Agregador de la ventana: 'mean' (SMA(4), default — lo que usa operaciones) o
# 'median' (Mediana(4), opcion). El bake-off 2026-06-01 mostro que la Mediana(4)
# da un poco mejor (menor bias), pero se elige SMA(4) por alineacion con el
# metodo del negocio. Override: context agg='median'.
AGG_DEFAULT = 'mean'
DEMAND_WINDOW_WEEKS_DEFAULT = 26     # ventana para definir universo activo
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


# ----------------------
# Contexto
# ----------------------
CTX = env.context or {}
FWD_MODEL  = str(CTX.get('fwd_model', FWD_MODEL_DEFAULT) or FWD_MODEL_DEFAULT)
HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
SMA_WEEKS  = max(1, int(CTX.get('sma_weeks', SMA_WEEKS_DEFAULT)))
DEMAND_WINDOW_WEEKS = int(CTX.get('demand_window_weeks', DEMAND_WINDOW_WEEKS_DEFAULT))
AGG = str(CTX.get('agg', AGG_DEFAULT) or AGG_DEFAULT).strip().lower()
MODEL_CODE = 'median4' if AGG == 'median' else 'sma4'

TEAM_IDS = _to_int_list(CTX.get('team_ids')) or list(FILTERED_TEAM_IDS_DEFAULT)
company = env.company

FWD = env[FWD_MODEL].sudo()
fwd_fields = FWD._fields or {}

# Campos minimos requeridos en el modelo de salida
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
        'title': 'SMA4 Forecast', 'message': 'Faltan campos en %s: %s' % (FWD_MODEL, ', '.join(_missing)),
        'type': 'danger', 'sticky': True}}
elif not locked:
    action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
        'title': 'SMA4 Forecast', 'message': 'Otro forecast esta ejecutandose.', 'type': 'warning', 'sticky': False}}
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
        target_date = last_closed_monday + datetime.timedelta(weeks=1)       # semana a pronosticar
        # ventana SMA: las SMA_WEEKS semanas cerradas que terminan en date_to
        sma_weeks_list = [last_closed_monday - datetime.timedelta(weeks=k) for k in range(SMA_WEEKS - 1, -1, -1)]
        sma_weeks_set = set(sma_weeks_list)
        window_from = last_closed_monday - datetime.timedelta(weeks=max(DEMAND_WINDOW_WEEKS - 1, 0))

        # ----------------------
        # Venta semanal POS (combo-expandida), por (team, product)
        # ----------------------
        pt_fields = env['product.template']._fields or {}
        dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

        # team en POS
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
                'title': 'SMA4 Forecast', 'message': 'No hay crm_team_id/team_id en pos.config.',
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
            # acumular por combo: {(team, pid): {week: qty}}
            sales = {}
            for team_id, product_id, week, qty in env.cr.fetchall():
                tid = _safe_int(team_id); pid = _safe_int(product_id)
                if not tid or not pid or not week:
                    continue
                q = _safe_float(qty, 0.0)
                if q < 0.0:
                    q = 0.0
                sales.setdefault((tid, pid), {})[week] = sales.get((tid, pid), {}).get(week, 0.0) + q

            # categoria por product.product
            categ_of = {}
            pids = list(set(p for (_t, p) in sales.keys()))
            if pids:
                env.cr.execute("""
                    SELECT pp.id, pt.categ_id
                    FROM product_product pp JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE pp.id = ANY(%s)
                """, (pids,))
                for pid, cid in env.cr.fetchall():
                    categ_of[_safe_int(pid)] = _safe_int(cid)

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
            for (tid, pid), wkmap in sales.items():
                vals4 = [_safe_float(wkmap.get(w, 0.0), 0.0) for w in sma_weeks_list]
                n = len(vals4)
                mean_v = sum(vals4) / n if n else 0.0
                if n == 0:
                    mu = 0.0
                elif AGG == 'median':
                    sv = sorted(vals4)
                    mu = sv[n // 2] if (n % 2) else (sv[n // 2 - 1] + sv[n // 2]) / 2.0
                else:
                    mu = mean_v
                # sigma siempre desde la media (para safety stock); robusto a 1 dato
                if n > 1:
                    sigma = (sum((x - mean_v) ** 2 for x in vals4) / n) ** 0.5
                else:
                    sigma = 0.0
                mu_total += mu
                if mu > 0.0:
                    n_nonzero += 1

                vals = {}
                if _field_exists(fwd_fields, 'x_name'):
                    vals['x_name'] = '%s LOC%s PP%s' % (MODEL_CODE.upper(), tid, pid)
                _put_field(vals, fwd_fields, 'x_studio_product_id', pid)
                _put_field(vals, fwd_fields, 'x_studio_team_id', tid)
                _put_field(vals, fwd_fields, 'x_studio_categ_id', categ_of.get(pid) or False)
                _put_field(vals, fwd_fields, 'x_studio_week_start', target_date)
                _put_field(vals, fwd_fields, 'x_studio_mu_week', mu)
                _put_field(vals, fwd_fields, 'x_studio_sigma_week', sigma)
                # compatibilidad con lectores (backtest): pre_bias = mu (sin capas)
                _put_field(vals, fwd_fields, 'x_studio_mu_week_pre_bias', mu)
                _put_field(vals, fwd_fields, 'x_studio_forecast_model_code', MODEL_CODE, 60)
                batch.append(vals)

                if len(batch) >= BATCH_SIZE:
                    FWD.create(batch)
                    n_created += len(batch)
                    batch = []
            if batch:
                FWD.create(batch)
                n_created += len(batch)

            try:
                log('%s | target=%s | sma_weeks=%s..%s | purged=%s | created=%s | nonzero=%s | mu_sum=%s | teams=%s' % (
                    VERSION_ID, target_date, sma_weeks_list[0], sma_weeks_list[-1],
                    purge_count, n_created, n_nonzero, round(mu_total, 1), len(TEAM_IDS)), level='info')
            except Exception:
                pass

            action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': 'SMA4 Forecast v1.0',
                'message': 'OK | target=%s | filas=%s | con venta=%s | mu_sum=%s' % (
                    target_date, n_created, n_nonzero, round(mu_total, 0)),
                'type': 'success', 'sticky': True}}
    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
