# OH Forecast Base - Pronostico semanal por modelo-base auto-seleccionado
# ============================================================
#
# Version activa: v1.5 (2026-06-02)  [reemplaza OH SMA4 Forecast v1.0]
#   v1.1: de-censura por combo con quiebre -> SMA. v1.2: CLEANSING por SEMANA
#         (reemplaza la venta suprimida de cada semana de quiebre por el promedio
#         in-stock, solo-levanta) sobre TODO el periodo + cola SMA(6).
#   v1.3: persiste x_studio_series_type (auditoria; ya se calculaba). Sin cambio
#         de mu/sigma ni de seleccion de modelo.
#   v1.4: no_signal pasa de Mediana(4) a SMA(6) [model_code sma6_ns]. Recupera el
#         intermitente lento vivo (forecast 0 -> tasa media); el SMA da 0 al muerto
#         real, no infla obsoletos. Proxy de TSB.
#   v1.5: cleansing POR DIA ponderado por perfil dia-de-semana (no por semana).
#         demanda = venta / (1 - peso_perdido), peso_perdido = peso dow (perfil GLOBAL
#         de venta de la cadena) de los dias que quebraron -> sabado pesa ~21%, lunes
#         ~9%. Quiebre severo (peso>=0.5): baseline previo. Corrige el over de
#         estacionales que cayeron y quebraban en finde (v1.4 borraba la semana entera
#         y la anclaba al promedio de verano).
#
# Que hace (modelo base AUTO, validado en proyectos/2026-06-02-auto-model-segmento):
#   Por (sala=crm.team, SKU=product.product) clasifica la serie LOCALMENTE
#   (Syntetos-Boylan: ADI/CV2 sobre la venta de ESE combo) y elige el modelo:
#
#       series_type smooth  + ABC=A           -> SES(alfa=0.5)
#       series_type smooth  + ABC=B/C         -> SES(alfa=0.6)
#       series_type erratic                   -> SES(alfa=0.7)
#       series_type intermittent / lumpy      -> SMA(SMA_TAIL_WEEKS=6)
#       series_type no_signal                 -> SMA(6) [model_code sma6_ns]   (v1.4)
#   La cola intermittent/lumpy/no_signal usa SMA (no Mediana): la Mediana(4) da 0 en
#   demanda esporadica (>=3 de 4 sem en cero) -> sub-stockea lo que rota cada tanto. El
#   SMA captura la tasa media y a la vez da 0 a los muertos reales (sin venta en la cola
#   SMA) -> recupera el intermitente lento VIVO sin inflar el obsoleto. Proxy de TSB.
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
#   CLEANSING DE ENTRADA (v1.5 POR DIA + perfil dia-semana, etapa 2 / demand
#   unconstraining, canon SAP IBP):
#   Primero calcula el perfil de venta por dia-de-semana GLOBAL de la cadena (runtime,
#   ultimas DOW_PROFILE_WEEKS sem): peso_dow[Lun..Dom] que suma 1 (sabado ~21%, lunes
#   ~9%). Luego, en cada SEMANA con quiebre (>= CLEANSE_MIN_DAYS dias sin stock):
#     - peso_perdido = suma del peso_dow de los dias que quebraron (fraccion de la
#       venta-semana que se perdio).
#     - quiebre LEVE (peso_perdido < CLEANSE_SEVERE_WEIGHT): completa por disponibilidad
#       -> demanda = venta / (1 - peso_perdido). Un quiebre de sabado levanta mas que uno
#       de lunes. Sigue la demanda RECIENTE.
#     - quiebre SEVERO (peso_perdido >= CLEANSE_SEVERE_WEIGHT): la semana perdio demasiada
#       venta -> promedio de las CLEANSE_BASE_WEEKS semanas CON stock previas (baseline).
#   Siempre SOLO LEVANTA (nunca recorta). Asi el estimador corre sobre demanda NO
#   restringida sin anclarse al baseline de temporada alta en estacionales que cayeron
#   (bug v1.4: 1 dia de quiebre borraba la semana entera y la subia al promedio de
#   verano -> forecast en sentido contrario a la venta). Escanea las ultimas
#   CLEANSE_LOOKBACK_WEEKS sem (default 16). Fuente: stockout / stockout_partial /
#   qty_balance<=0 (criterio motor v3.48). El backtest contra venta censurada mostrara
#   MAS error y es esperado. Se apaga con context decensor_stockout=False.
#
#   Escribe a x_hm_si_forecast con el MISMO contrato:
#     x_studio_mu_week, x_studio_sigma_week, x_studio_product_id (m2o product.product),
#     x_studio_team_id (m2o crm.team), x_studio_week_start (date),
#     x_studio_forecast_model_code (el modelo elegido, para auditoria),
#     x_studio_series_type (la forma de serie LOCAL clasificada, para auditoria;
#       v1.3: el motor ya la calculaba para elegir el modelo, ahora la persiste).
#
# Contexto soportado (backtest/overrides): date_to (cutoff), team_ids, hard_reset,
#   fwd_model, demand_window_weeks, decensor_stockout (default True; False = input
#   crudo, sin cleansing), cleanse_min_days (default 1; dias/sem para marcar quiebre),
#   cleanse_severe_weight (default 0.5; peso-venta perdido >= este -> baseline en vez de
#   escalar), dow_profile_weeks (default 12; ventana del perfil dia-semana),
#   cleanse_base_weeks (default 6; semanas in-stock del baseline), sma_tail_weeks
#   (default 6). Overrides de modelo: force_alpha (SES alfa a TODO),
#   force_median (True -> Mediana(4) a todo). Solo para diagnostico.
#
# No toca stock, compras, transferencias ni OC. Solo escribe el forecast.
# ============================================================

VERSION_ID = "OH_FORECAST_BASE_v1_5"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009438          # mismo lock que el forecast HM-SI/SMA4: mutuamente excluyentes

FWD_MODEL_DEFAULT = 'x_hm_si_forecast'
SEG_MODEL = 'x_calculo_abc_xyz'      # fuente del ABC global
SB_MODEL = 'x_stock_balance_daily'   # fuente del quiebre (de-censura de entrada, etapa 2)
HARD_RESET_DEFAULT = True
FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
DEMAND_WINDOW_WEEKS_DEFAULT = 26     # ventana para clasificar + universo activo
MEDIAN_K = 4                         # Mediana(4) y ventana de sigma
SMA_TAIL_WEEKS_DEFAULT = 6           # SMA para la cola intermittent/lumpy (reemplaza la
                                     # Mediana, que daba ceros en demanda esporadica)
# Cleansing de entrada por quiebre (etapa 2, v1.5: POR DIA con perfil DIA-DE-SEMANA
# GLOBAL). En una semana con quiebre se completa la venta dividiendo por la fraccion de
# venta que SI estuvo disponible: demanda = venta / (1 - peso_perdido), donde
# peso_perdido = suma del peso dow (perfil de venta por dia de la cadena, runtime) de los
# dias que quebraron. Asi un quiebre de sabado (~21% de la venta-semana) pesa mas que uno
# de lunes (~9%). Perfil GLOBAL: los quiebres de la cadena se concentran en finde (donde
# se vende mas); las salas con dia atipico son ruido operativo local (ej. Pangui64 tiene
# bodega al lado y repone cuando quiere) y no se modelan. Si el quiebre es SEVERO
# (peso_perdido >= CLEANSE_SEVERE_WEIGHT: la semana perdio demasiada venta para confiar
# en ella), cae al promedio de las CLEANSE_BASE_WEEKS semanas CON stock previas
# (baseline). Siempre solo-levanta. Sigue la demanda RECIENTE sin anclar al baseline de
# temporada alta (bug v1.4: 1 dia de quiebre borraba la semana entera y la subia al
# promedio de verano).
CLEANSE_MIN_DAYS_DEFAULT = 1          # una semana cuenta como quiebre si >= N dias sin stock
CLEANSE_SEVERE_WEIGHT_DEFAULT = 0.5  # si los dias quebrados pesan >= 50% de la venta-semana
                                     # (perfil dow), la semana no es confiable -> baseline previo
DOW_PROFILE_WEEKS_DEFAULT = 12       # ventana para calcular el perfil de venta por dia-semana
                                     # GLOBAL de la cadena (peso dow)
CLEANSE_BASE_WEEKS_DEFAULT = 6        # baseline = promedio de las 6 sem con stock previas
CLEANSE_LOOKBACK_WEEKS_DEFAULT = 16   # solo escanea quiebre en las ultimas N sem (el SMA6/
                                     # SES no usan mas atras) -> acota el peso del query
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


def _cleanse_stockout(raw_vals, weeks_list, tid, pid, qweight, min_days, base_k, severe_w):
    """Cleansing de entrada por quiebre (etapa 2 / demand unconstraining, v1.5 POR DIA
    con perfil dia-de-semana). qweight[(tid,pid,w)] = (n_days, peso_perdido), donde
    peso_perdido = fraccion de la venta-semana (perfil dow GLOBAL) que cae en los dias
    que quebraron -> un quiebre de sabado pesa ~21%, uno de lunes ~9%.
    En una semana con quiebre (n_days >= min_days y peso_perdido > 0):
      - quiebre LEVE (peso_perdido < severe_w): completa por disponibilidad ->
        demanda = venta / (1 - peso_perdido). Sigue la demanda RECIENTE.
      - quiebre SEVERO (peso_perdido >= severe_w, la semana perdio demasiada venta): cae
        al promedio de las base_k semanas CON stock previas (baseline).
    Siempre SOLO LEVANTA: nunca recorta. Loop explicito (sin comprehension que capture
    locales) por el safe_eval de Odoo. Retorna (vector_limpio, n_semanas_levantadas)."""
    out = []
    instock = []
    n_lift = 0
    for i in range(len(weeks_list)):
        w = weeks_list[i]
        y = raw_vals[i]
        info = qweight.get((tid, pid, w))
        nd = info[0] if info else 0
        pw = info[1] if info else 0.0
        if nd >= min_days and pw > 0.0:
            if pw < severe_w and pw < 0.95:
                # quiebre leve: escala por la fraccion de venta-semana disponible
                val = y / (1.0 - pw)
                out.append(val)
                if val > y + 1e-9:
                    n_lift += 1
            elif instock:
                # quiebre severo: baseline de semanas in-stock previas (solo-levanta)
                recent = instock[-base_k:]
                base = sum(recent) / len(recent)
                if base > y:
                    out.append(base)
                    n_lift += 1
                else:
                    out.append(y)
            else:
                out.append(y)                    # sin referencia previa -> crudo
        else:
            out.append(y)
            instock.append(y)                    # referencia limpia = semanas con stock
    return out, n_lift


# ----------------------
# Contexto
# ----------------------
CTX = env.context or {}
FWD_MODEL  = str(CTX.get('fwd_model', FWD_MODEL_DEFAULT) or FWD_MODEL_DEFAULT)
HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
DEMAND_WINDOW_WEEKS = int(CTX.get('demand_window_weeks', DEMAND_WINDOW_WEEKS_DEFAULT))
FORCE_ALPHA = CTX.get('force_alpha')          # diagnostico: SES(alpha) a todo
FORCE_MEDIAN = bool(CTX.get('force_median'))  # diagnostico: Mediana(4) a todo
DECENSOR = bool(CTX.get('decensor_stockout', True))  # etapa 2: cleansing de entrada (default ON)
CLEANSE_MIN_DAYS = max(1, int(CTX.get('cleanse_min_days', CLEANSE_MIN_DAYS_DEFAULT)))
CLEANSE_SEVERE_WEIGHT = _safe_float(CTX.get('cleanse_severe_weight', CLEANSE_SEVERE_WEIGHT_DEFAULT), CLEANSE_SEVERE_WEIGHT_DEFAULT)
DOW_PROFILE_WEEKS = max(1, int(CTX.get('dow_profile_weeks', DOW_PROFILE_WEEKS_DEFAULT)))
CLEANSE_BASE_WEEKS = max(1, int(CTX.get('cleanse_base_weeks', CLEANSE_BASE_WEEKS_DEFAULT)))
CLEANSE_LOOKBACK_WEEKS = max(1, int(CTX.get('cleanse_lookback_weeks', CLEANSE_LOOKBACK_WEEKS_DEFAULT)))
SMA_TAIL_WEEKS = max(1, int(CTX.get('sma_tail_weeks', SMA_TAIL_WEEKS_DEFAULT)))

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
            # Perfil de venta por DIA-DE-SEMANA (GLOBAL de la cadena, runtime). Pondera el
            # peso de cada dia para la de-censura: un quiebre de sabado (~21% de la venta
            # semanal) pesa mas que uno de lunes (~9%). isodow 1=Lun..7=Dom. Si no hay datos,
            # cae a uniforme 1/7. Una sola query agregada sobre DOW_PROFILE_WEEKS sem.
            # ----------------------
            dow_weight = {}   # {isodow(1..7): peso (suma 1)}
            try:
                prof_from = last_closed_monday - datetime.timedelta(weeks=max(DOW_PROFILE_WEEKS - 1, 0))
                prof_params = {'company_id': company.id, 'date_from': prof_from, 'date_to': date_to, 'tz': TZ_NAME}
                prof_team = ''
                if TEAM_IDS:
                    prof_team = ' AND ' + team_col_sql + ' = ANY(%(team_ids)s) '
                    prof_params['team_ids'] = TEAM_IDS
                prof_sql = """
                    SELECT EXTRACT(ISODOW FROM (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s))::int AS iso,
                           SUM(COALESCE(pol.qty, 0.0)) AS units
                    FROM pos_order_line pol
                    JOIN pos_order po ON po.id = pol.order_id
                    LEFT JOIN pos_session ps ON ps.id = po.session_id
                    LEFT JOIN pos_config pc ON pc.id = ps.config_id
                    WHERE po.company_id = %(company_id)s
                      AND po.state IN ('paid','done','invoiced')
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(date_from)s
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                      AND {team_col} IS NOT NULL {team_filter}
                    GROUP BY 1
                """.format(team_col=team_col_sql, team_filter=prof_team)
                env.cr.execute(prof_sql, prof_params)
                _raw_dow = {}
                _tot_dow = 0.0
                for _iso, _u in env.cr.fetchall():
                    iv = _safe_int(_iso, 0); uv = _safe_float(_u, 0.0)
                    if iv >= 1 and iv <= 7 and uv > 0.0:
                        _raw_dow[iv] = uv
                        _tot_dow += uv
                if _tot_dow > 0.0:
                    for iv in range(1, 8):
                        dow_weight[iv] = _raw_dow.get(iv, 0.0) / _tot_dow
            except Exception:
                dow_weight = {}
            if not dow_weight:
                for iv in range(1, 8):
                    dow_weight[iv] = 1.0 / 7.0   # fallback uniforme

            # ----------------------
            # Quiebre por (combo, SEMANA, dia-semana) en las ultimas CLEANSE_LOOKBACK_WEEKS
            # sem. Un dia es quiebre si stockout OR stockout_partial OR qty_balance<=0
            # (criterio motor v3.48). Para cada (tid, pid, semana) acumula:
            #   n_days       = nro de dias de quiebre
            #   peso_perdido = suma del peso dow de esos dias (perfil GLOBAL) -> fraccion de
            #                  la venta-semana que se perdio. qweight = {key: [n_days, peso]}.
            # ----------------------
            qweight = {}
            if DECENSOR and pids:
                try:
                    env[SB_MODEL]          # valida que el modelo exista (KeyError si no)
                    cl_from = last_closed_monday - datetime.timedelta(weeks=max(CLEANSE_LOOKBACK_WEEKS - 1, 0))
                    team_clause = ''
                    so_params = {'pids': pids, 'date_from': cl_from, 'date_to': date_to}
                    if TEAM_IDS:
                        team_clause = ' AND x_studio_team_id = ANY(%(team_ids)s) '
                        so_params['team_ids'] = TEAM_IDS
                    so_sql = ("""
                        SELECT x_studio_product_id, x_studio_team_id,
                               date_trunc('week', x_studio_date)::date AS wk,
                               EXTRACT(ISODOW FROM x_studio_date)::int AS iso,
                               COUNT(DISTINCT x_studio_date) AS ndays
                        FROM x_stock_balance_daily
                        WHERE x_studio_product_id = ANY(%(pids)s)
                          AND x_studio_date >= %(date_from)s AND x_studio_date <= %(date_to)s
                          AND (COALESCE(x_studio_stockout, FALSE) = TRUE
                               OR COALESCE(x_studio_stockout_partial, FALSE) = TRUE
                               OR COALESCE(x_studio_qty_balance, 0.0) <= 0.0)
                        """ + team_clause + """
                        GROUP BY x_studio_product_id, x_studio_team_id, 3, 4
                    """)
                    env.cr.execute(so_sql, so_params)
                    for _pid, _tid, _wk, _iso, _nd in env.cr.fetchall():
                        if _pid is None or _tid is None or _wk is None:
                            continue
                        key = (int(_tid), int(_pid), _wk)
                        ndays = int(_nd or 0)
                        wpenalty = dow_weight.get(_safe_int(_iso, 0), 1.0 / 7.0) * ndays
                        e = qweight.get(key)
                        if e is None:
                            qweight[key] = [ndays, wpenalty]
                        else:
                            e[0] += ndays
                            e[1] += wpenalty
                except Exception:
                    qweight = {}   # modelo/campos ausentes -> sin cleansing (input crudo)

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
            n_cleansed = 0            # combos con >=1 semana levantada por cleansing
            model_counts = {}
            for (tid, pid), wkmap in sales.items():
                raw_vals = [_safe_float(wkmap.get(w, 0.0), 0.0) for w in window_weeks]   # crudo
                # etapa 2: cleansing por dia (de-censura ponderada por perfil dow)
                if DECENSOR and qweight:
                    vals, n_lift = _cleanse_stockout(raw_vals, window_weeks, tid, pid,
                                                     qweight, CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS,
                                                     CLEANSE_SEVERE_WEIGHT)
                    if n_lift > 0:
                        n_cleansed += 1
                else:
                    vals = raw_vals
                last4 = vals[-MEDIAN_K:] if len(vals) >= MEDIAN_K else vals
                mean4 = sum(last4) / len(last4) if last4 else 0.0

                stype = _classify_series_type(vals)
                abc = abc_letter.get(pid, '')

                # --- seleccion de modelo (sobre la serie YA limpia) ---
                if FORCE_MEDIAN:
                    model_code = 'median4'; mu = _median(last4)
                elif FORCE_ALPHA is not None:
                    a = _safe_float(FORCE_ALPHA, 0.6); model_code = 'ses_a%.2f' % a; mu = _ses_level(vals, a)
                elif stype == 'smooth':
                    a = ALPHA_SMOOTH_A if abc == 'A' else ALPHA_SMOOTH_BC
                    model_code = 'ses_a%.2f' % a; mu = _ses_level(vals, a)
                elif stype == 'erratic':
                    a = ALPHA_ERRATIC; model_code = 'ses_a%.2f' % a; mu = _ses_level(vals, a)
                elif stype == 'no_signal':
                    # casi-muerto: <4 sem con venta en 26. v1.4: antes Mediana(4)=0 sub-stockeaba
                    # los intermitentes lentos VIVOS (venta esporadica reciente). SMA(SMA_TAIL_WEEKS)
                    # los recupera y a la vez da 0 a los muertos reales (sin venta en la cola SMA),
                    # asi NO infla obsoletos. Proxy de TSB (intermitente con obsolescencia). model_code
                    # 'sma6_ns' distinto del intermittent para auditar el corte en el backtest.
                    tail_vals = vals[-SMA_TAIL_WEEKS:] if len(vals) >= 1 else vals
                    model_code = 'sma%d_ns' % SMA_TAIL_WEEKS
                    mu = (sum(tail_vals) / len(tail_vals)) if tail_vals else 0.0
                else:   # intermittent / lumpy -> SMA(SMA_TAIL_WEEKS): la Mediana(4) da 0 en
                    # demanda esporadica (>=3 de 4 sem en cero). El SMA captura la TASA media.
                    tail_vals = vals[-SMA_TAIL_WEEKS:] if len(vals) >= 1 else vals
                    model_code = 'sma%d' % SMA_TAIL_WEEKS
                    mu = (sum(tail_vals) / len(tail_vals)) if tail_vals else 0.0

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
                _put_field(vals_w, fwd_fields, 'x_studio_series_type', stype, 20)   # auditoria: tipo de serie LOCAL que eligio el modelo
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
                dec = ('ON cleansed_combos=%s base%sw min%sd sev%s qsem=%s' % (n_cleansed, CLEANSE_BASE_WEEKS, CLEANSE_MIN_DAYS, CLEANSE_SEVERE_WEIGHT, len(qweight))) if DECENSOR else 'OFF'
                log('%s | target=%s | win=%s..%s | purged=%s | created=%s | nonzero=%s | mu_sum=%s | models[%s] | decensor[%s] | teams=%s' % (
                    VERSION_ID, target_date, window_weeks[0], window_weeks[-1],
                    purge_count, n_created, n_nonzero, round(mu_total, 1), mc, dec, len(TEAM_IDS)), level='info')
            except Exception:
                pass

            action = {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': 'Forecast Base v1.5',
                'message': 'OK | target=%s | filas=%s | con venta=%s | mu_sum=%s | cleansed=%s' % (
                    target_date, n_created, n_nonzero, round(mu_total, 0),
                    ('%s combos' % n_cleansed) if DECENSOR else 'off'),
                'type': 'success', 'sticky': True}}
    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
