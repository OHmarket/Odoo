# ============================================================
# OH Price Correccion - Detector de cambios de precio y promos
# ============================================================
#
# Version activa: v5.8 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - Detecta cambios de precio y promos en x_price_change_event /
#     x_loyalty_promo_event y emite un factor de correccion por SKU
#     al modelo x_price_coreccion (typo de Studio: una 'r').
#   - El motor HM SI Forecast consume el factor via
#     _load_correccion_context y lo aplica al mu_week despues de los
#     caps P1/P3/P6.
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Lookback diferenciado:
#       - Precios: 52 sem (1 ano). Subidas decaen a 1.0 en 12 sem;
#         bajadas siguen vigentes hasta nuevo cambio.
#       - Promos: 4 sem (cortas, mas atras es ruido).
#   - Decay por tipo:
#       - BAJADA = promo sostenida -> sin decay.
#       - SUBIDA = decay 12 sem.
#   - Elasticidad ABC (solo "sin promo"):
#       - A x1.3 (commodities con alternativas).
#       - B x1.0 (sin cambio).
#       - C x0.7 (cola cautiva).
#     Aplicado como 1 + (factor - 1) * mult. Promos NO se ponderan.
#   - Promo clasificada por minimum_qty:
#       - <=2: pareo, no alertar salvo lift extremo.
#       - 3-4: mixto.
#       - >=6: stock-up (DISPARO_W1, SATURACION_W3+).
#   - target_week_start = period_start del evento (no proxima semana).
#   - Filtro SKU: product.product.active=True AND sale_ok=True.
#   - Modelo destino: x_price_coreccion (typo intencional Studio).
#
# Detalles, fixes historicos y metricas de snapshots: ver CHANGELOG.md.
# ============================================================

VERSION_ID = "PRICE_CORRECCION_v5_9"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009612

# Modelo destino (typo de Studio: una sola 'r' en 'coreccion')
CORR_MODEL_DEFAULT = 'x_price_coreccion'

# Fuentes
PRICE_EVENT_MODEL = 'x_price_change_event'
PROMO_EVENT_MODEL = 'x_loyalty_promo_event'
ABCXYZ_MODEL      = 'x_calculo_abc_xyz'

HARD_RESET_DEFAULT = True
# Lookback diferenciado:
#   - Precios: 52 sem (1 ano). Cubre cambios sostenidos viejos. Subidas
#     con weeks_since >= 12 decaen a factor=1.0 (no ruido); bajadas
#     siguen vigentes hasta nuevo cambio.
#   - Promos:   4 sem (solo eventos activos/recientes).
LOOKBACK_PRICE_WEEKS_DEFAULT = 52
LOOKBACK_PROMO_WEEKS_DEFAULT = 4
# Compatibilidad retro
LOOKBACK_WEEKS_DEFAULT = LOOKBACK_PRICE_WEEKS_DEFAULT

# Pesos canibalizacion por importancia ABC (impacto del COMPETIDOR sobre el SKU)
PESO_ABC = {'A': 1.0, 'B': 0.2, 'C': 0.03}

# Elasticidad por importancia ABC del SKU PROPIO (v5.7).
# A: commodities con alternativas claras -> mas elastico, corregir mas.
# C: cola con clientes cautivos -> menos elastico, corregir menos.
ELASTICIDAD_ABC = {'A': 1.30, 'B': 1.00, 'C': 0.70}

# v5.9: PROMO_PAREO_MODERADO (min_qty<=2 con lift 1.5-2.5).
# baseline_min protege contra ruido (SKUs con baseline=1 y lift=33x son
# anomalias estadisticas, no promos significativas). Calibrado vs distribucion
# de baseline_8w en eventos cerveza/alcohol min_qty<=2:
#   p10=1.2 p25=3.5 p50=10.5 p75=29.2 -> min=5 conserva ~75% sin ruido.
# Cobertura esperada: ~138 nuevos eventos /6 meses sobre cerveza/alcohol.
BASELINE_MIN_PROMO_PAREO_DEFAULT = 5
LIFT_PROMO_PAREO_MODERADO_DEFAULT = 1.5


def _aplicar_elasticidad_abc(factor, abc_letter):
    """Amplifica/reduce la 'distancia desde 1.0' del factor segun el
    ABC del SKU propio. Funciona para subidas (factor<1) y bajadas (>1).
    Ejemplos:
      factor=0.76 (subida fuerte), A -> 1 - (1-0.76)*1.3 = 0.688 (mas agresivo)
      factor=0.76 (subida fuerte), C -> 1 - (1-0.76)*0.7 = 0.832 (mas suave)
      factor=1.20 (bajada fuerte), A -> 1 + (1.20-1)*1.3 = 1.260
      factor=1.20 (bajada fuerte), C -> 1 + (1.20-1)*0.7 = 1.140
    """
    mult = ELASTICIDAD_ABC.get(abc_letter, 1.0)
    return 1.0 + (factor - 1.0) * mult


def _tipo_studio(tipo_interno, var_pct):
    """Mapea el tipo granular interno al subset de 8 valores de la
    selection x_studio_tipo_alerta en Studio:
      Subida Leve, Subida Fuerte, Subida Fuerte Canibal,
      Bajada Leve, Bajada Fuerte, Bajada Fuerte Canibal,
      Promo Disparo, Promo Saturacion.

    La distincion Leve/Fuerte para subidas/bajadas no-canibal depende
    de abs(var_pct) (>=10% => Fuerte).
    """
    if not tipo_interno:
        return ''
    t = tipo_interno
    if t.startswith('SATURACION_STOCKUP_W') or t.startswith('SATURACION_6X_W'):
        return 'PROMO_SATURACION'
    if t in ('DISPARO_12X_W1', 'DISPARO_STOCKUP_W1', 'DISPARO_MIXTO_W1',
             'PROMO_PAREO_LIFT_EXTREMO', 'PROMO_PAREO_MODERADO',
             'SUBIDA_FUERTE_CON_PROMO_W1'):
        return 'PROMO_DISPARO'
    if t == 'SUBIDA_CANIBAL_FUERTE':
        return 'SUBIDA_FUERTE_CANIBAL'
    if t == 'BAJADA_GANADORA_FUERTE':
        return 'BAJADA_FUERTE_CANIBAL'
    if t in ('SUBIDA_CANIBAL_MODERADO',):
        return 'SUBIDA_FUERTE'
    if t in ('BAJADA_GANADORA_MODERADA', 'BAJADA_DISCONTINUACION'):
        return 'BAJADA_FUERTE'
    mag = abs(float(var_pct or 0.0))
    if t in ('SUBIDA_UNICA', 'SUBIDA_CON_PRESION'):
        return 'SUBIDA_FUERTE' if mag >= 0.10 else 'SUBIDA_LEVE'
    if t in ('BAJADA_UNICA', 'BAJADA_CON_PRESION'):
        return 'BAJADA_FUERTE' if mag >= 0.10 else 'BAJADA_LEVE'
    return t


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


def _get_sub_cat(complete_name):
    """Sub-categoria L3 = 3er nivel del complete_name."""
    if not complete_name:
        return ''
    try:
        parts = str(complete_name).split(' / ')
        if len(parts) >= 3:
            return parts[2]
        return parts[-1]
    except Exception:
        return ''


def _abc_letter(abcxyz):
    s = str(abcxyz or '').strip().upper()
    return s[0] if s else ''


def _extract_mecanica(program_name):
    """Extrae 12X, 6X, 4X, 3X, 2X del nombre del programa."""
    # Sin regex: Odoo safe_eval no permite IMPORT_NAME en server actions
    s = str(program_name or '').upper()
    for i, ch in enumerate(s):
        if ch == 'X' and i > 0 and s[i-1].isdigit():
            j = i - 1
            while j > 0 and s[j-1].isdigit():
                j -= 1
            return s[j:i+1]
    return "OTRO"


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
            # Fallback case-insensitive: aceptar 'AX' aunque el key sea 'ax' o 'Ax'.
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
# Reglas de factor
# ----------------------
def _factor_base_subida(var_pct):
    if var_pct >= 0.15:
        return 0.76
    elif var_pct >= 0.05:
        return 0.85
    return 1.0


def _factor_base_bajada(var_pct):
    if var_pct <= -0.15:
        return 1.20
    elif var_pct <= -0.05:
        return 1.10
    return 1.0


# ----------------------
# Context
# ----------------------
CTX = env.context or {}
CORR_MODEL = str(CTX.get('correccion_model', CORR_MODEL_DEFAULT) or CORR_MODEL_DEFAULT)
HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
LOOKBACK_PRICE_WEEKS = int(CTX.get('lookback_price_weeks', LOOKBACK_PRICE_WEEKS_DEFAULT))
LOOKBACK_PROMO_WEEKS = int(CTX.get('lookback_promo_weeks', LOOKBACK_PROMO_WEEKS_DEFAULT))
BASELINE_MIN_PROMO_PAREO = int(CTX.get('baseline_min_promo_pareo', BASELINE_MIN_PROMO_PAREO_DEFAULT))
LIFT_PROMO_PAREO_MODERADO = float(CTX.get('lift_promo_pareo_moderado', LIFT_PROMO_PAREO_MODERADO_DEFAULT))

company = env.company

# Validar modelo destino
if not _model_exists(CORR_MODEL):
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': VERSION_ID,
            'message': 'Modelo %s no existe. Crear en Studio primero.' % CORR_MODEL,
            'type': 'danger', 'sticky': True,
        }
    }
else:
    # ----------------------
    # Lock
    # ----------------------
    env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
    locked = env.cr.fetchone()[0]

    if not locked:
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': VERSION_ID,
                'message': 'Otro proceso PRICE_CORRECCION esta corriendo.',
                'type': 'warning', 'sticky': False,
            }
        }
    else:
        try:
            CorrModel = env[CORR_MODEL].sudo()
            corr_fields = CorrModel._fields or {}

            # Fecha objetivo: proxima semana
            env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
            today_local = env.cr.fetchone()[0]
            target_week_start = _week_start(today_local) + datetime.timedelta(weeks=1)
            price_lookback_start = target_week_start - datetime.timedelta(weeks=LOOKBACK_PRICE_WEEKS)
            promo_lookback_start = target_week_start - datetime.timedelta(weeks=LOOKBACK_PROMO_WEEKS)

            # Universo de SKUs vendibles (filtro v5.6):
            # excluye productos archivados, no-vendibles, liquidaciones cerradas.
            skus_vendibles = set()
            try:
                Prod = env['product.product'].sudo()
                pdomain = [('active', '=', True), ('sale_ok', '=', True)]
                skus_vendibles = set(Prod.search(pdomain).ids)
            except Exception:
                pass

            # Purge correcciones previas (v5.6: ya no por target_week porque cada
            # alerta usa fecha del evento; purgamos TODO el activo y recreamos
            # el snapshot de la semana actual).
            purge_count = 0
            if HARD_RESET:
                active_field = _first_field(CorrModel, ['x_studio_active', 'active'])
                if active_field:
                    old = CorrModel.search([(active_field, '=', True)])
                else:
                    old = CorrModel.search([])
                purge_count = len(old)
                if old:
                    old.unlink()

            # ----------------------
            # Cargar SKU -> ABC y SKU -> sub_cat
            # ----------------------
            sku_to_abc = {}        # pid -> letra (A/B/C) para CPI
            sku_to_abcxyz = {}     # pid -> string completo (AX/AY/AZ/BX...) para persistir
            sku_to_subcat = {}     # pid -> sub-cat L3 (denominador CPI)
            sku_count_by_subcat = {}

            if _model_exists(ABCXYZ_MODEL):
                Abc = env[ABCXYZ_MODEL].sudo()
                af = Abc._fields or {}
                abc_pf = _first_m2o_field(Abc, ['x_studio_product_id'], 'product.product')
                abc_letter_f = _first_field(Abc, ['x_studio_abcxyz', 'x_abcxyz'])
                abc_categ_f = _first_field(Abc, ['x_studio_categ_id'])
                if abc_pf and abc_letter_f:
                    read_fields = [abc_pf, abc_letter_f]
                    if abc_categ_f:
                        read_fields.append(abc_categ_f)
                    abc_records = Abc.search([]).read(read_fields)
                    for r in abc_records:
                        pv = r.get(abc_pf)
                        pid = pv[0] if isinstance(pv, (list, tuple)) else _safe_int(pv)
                        if not pid:
                            continue
                        abcxyz_full = _safe_text(r.get(abc_letter_f), 10).strip().upper()
                        sku_to_abcxyz[pid] = abcxyz_full
                        sku_to_abc[pid] = _abc_letter(r.get(abc_letter_f))
                        # sub_cat L3 desde categoria m2o
                        if abc_categ_f:
                            cv = r.get(abc_categ_f)
                            cid = cv[0] if isinstance(cv, (list, tuple)) else _safe_int(cv)
                            if cid:
                                try:
                                    cat = env['product.category'].sudo().browse(cid)
                                    sku_to_subcat[pid] = _get_sub_cat(cat.complete_name)
                                except Exception:
                                    pass

            # Conteo SKUs por sub-categoria L3 (para denominador de CPI)
            for sc in sku_to_subcat.values():
                sku_count_by_subcat[sc] = sku_count_by_subcat.get(sc, 0) + 1

            # ----------------------
            # Cargar cambios de precio recientes
            # ----------------------
            price_changes_by_sku = {}  # variant_id -> ultimo cambio
            cambios_subes_subcat = {}  # sub_cat -> [variant_ids que subieron]
            cambios_bajas_subcat = {}  # sub_cat -> [variant_ids que bajaron]

            if _model_exists(PRICE_EVENT_MODEL):
                Ev = env[PRICE_EVENT_MODEL].sudo()
                ef = Ev._fields or {}
                ev_pf = _first_m2o_field(Ev, [
                    'x_studio_product_variant_id', 'x_studio_product_product_id',
                    'x_product_variant_id', 'x_studio_product_id',
                ], 'product.product')
                ev_date_f = _first_field(Ev, [
                    'x_studio_period_start', 'x_studio_fecha',
                    'x_studio_date', 'x_studio_week_start',
                ])
                ev_var_f = _first_field(Ev, [
                    'x_studio_delta_pct', 'x_studio_variacion_pct',
                    'x_studio_variacion',
                ])
                ev_dir_f = _first_field(Ev, [
                    'x_studio_direction', 'x_studio_direccion',
                ])
                ev_categ_f = _first_field(Ev, ['x_studio_categoria', 'x_studio_categ_id'])
                ev_real_f = _first_field(Ev, ['x_studio_is_real_change'])

                if ev_pf and ev_date_f and ev_var_f:
                    domain = [(ev_date_f, '>=', price_lookback_start),
                              (ev_date_f, '<=', target_week_start)]
                    # Filtrar solo cambios reales si el campo existe
                    if ev_real_f:
                        domain.append((ev_real_f, '=', True))
                    rfields = [ev_pf, ev_date_f, ev_var_f]
                    if ev_dir_f: rfields.append(ev_dir_f)
                    if ev_categ_f: rfields.append(ev_categ_f)
                    rows = Ev.search(domain, order='%s desc' % ev_date_f).read(rfields)
                    for r in rows:
                        pv = r.get(ev_pf)
                        pid = pv[0] if isinstance(pv, (list, tuple)) else _safe_int(pv)
                        if not pid:
                            continue
                        # Quedarnos con el cambio mas reciente por SKU
                        if pid in price_changes_by_sku:
                            continue
                        var_pct = _safe_float(r.get(ev_var_f), 0.0)
                        direccion = _safe_text(r.get(ev_dir_f), 20).strip()
                        price_changes_by_sku[pid] = {
                            'fecha': r.get(ev_date_f),
                            'var_pct': var_pct,
                            'direccion': direccion,
                        }
                        sub_cat = sku_to_subcat.get(pid, '')
                        if sub_cat:
                            if direccion in ('Sube', 'sube', 'SUBE'):
                                cambios_subes_subcat.setdefault(sub_cat, []).append(pid)
                            elif direccion in ('Baja', 'baja', 'BAJA'):
                                cambios_bajas_subcat.setdefault(sub_cat, []).append(pid)

            # ----------------------
            # Cargar promos activas
            # ----------------------
            promos_by_sku = {}        # variant_id -> info promo mas reciente
            promos_activas_subcat = {}  # sub_cat -> [variant_ids con promo]

            if _model_exists(PROMO_EVENT_MODEL):
                Pr = env[PROMO_EVENT_MODEL].sudo()
                pf = Pr._fields or {}
                pr_pf = _first_m2o_field(Pr, [
                    'x_studio_product_variant_id', 'x_studio_product_product_id',
                ], 'product.product')
                pr_period_f = _first_field(Pr, ['x_studio_period_start'])
                pr_lift_f = _first_field(Pr, ['x_studio_lift_qty'])
                pr_program_f = _first_field(Pr, ['x_studio_program_name'])
                pr_categ_f = _first_field(Pr, ['x_studio_categ_id', 'x_studio_categoria'])
                pr_minqty_f = _first_field(Pr, ['x_studio_minimum_qty', 'minimum_qty'])
                # v5.9: baseline_8w para guard rail anti-ruido en rama PROMO_PAREO_MODERADO.
                pr_baseline_f = _first_field(Pr, ['x_studio_qty_baseline_8w', 'qty_baseline_8w'])

                if pr_pf and pr_period_f:
                    domain = [(pr_period_f, '>=', promo_lookback_start),
                              (pr_period_f, '<=', target_week_start)]
                    rfields = [pr_pf, pr_period_f]
                    if pr_lift_f: rfields.append(pr_lift_f)
                    if pr_program_f: rfields.append(pr_program_f)
                    if pr_minqty_f: rfields.append(pr_minqty_f)
                    if pr_baseline_f: rfields.append(pr_baseline_f)
                    # v5.9: ordenar por lift_qty DESC (no period_start DESC) para
                    # quedarnos con el evento de MAYOR lift en lookback. Casos como
                    # CUSQUENA tienen promo activa con lift 1.98 una semana y 0.94 la
                    # siguiente (saturacion); el detector debe alertar segun el peak,
                    # no la cola. En empates de lift, period_start DESC desempata
                    # con el evento mas reciente.
                    order_clause = '%s desc, %s desc' % (pr_lift_f, pr_period_f) if pr_lift_f else '%s desc' % pr_period_f
                    rows = Pr.search(domain, order=order_clause).read(rfields)
                    for r in rows:
                        pv = r.get(pr_pf)
                        pid = pv[0] if isinstance(pv, (list, tuple)) else _safe_int(pv)
                        if not pid:
                            continue
                        if pid in promos_by_sku:
                            continue
                        lift = _safe_float(r.get(pr_lift_f, 1.0), 1.0) if pr_lift_f else 1.0
                        program = r.get(pr_program_f, '') if pr_program_f else ''
                        min_qty = _safe_int(r.get(pr_minqty_f, 0), 0) if pr_minqty_f else 0
                        period = r.get(pr_period_f)
                        # Fallback: si no hay minimum_qty leer del nombre (12X, 6X, etc.)
                        mecanica = _extract_mecanica(program)
                        if min_qty == 0 and mecanica != "OTRO":
                            try:
                                min_qty = int(mecanica.rstrip('X'))
                            except Exception:
                                min_qty = 0
                        weeks_active = 1
                        try:
                            weeks_active = max(1, ((target_week_start - period).days // 7) + 1)
                        except Exception:
                            weeks_active = 1
                        baseline_8w = _safe_float(r.get(pr_baseline_f, 0.0), 0.0) if pr_baseline_f else 0.0
                        promos_by_sku[pid] = {
                            'period_start': period,
                            'lift_qty': lift,
                            'program_name': program,
                            'mecanica': mecanica,
                            'min_qty': min_qty,
                            'weeks_active': weeks_active,
                            'baseline_8w': baseline_8w,
                        }
                        sub_cat = sku_to_subcat.get(pid, '')
                        if sub_cat:
                            promos_activas_subcat.setdefault(sub_cat, []).append(pid)

            # ----------------------
            # Calcular CPI por sub-cat × direccion
            # ----------------------
            def cpi_ponderado(sub_cat, direccion_propia, sku_propio):
                """Score ponderado por ABC de competidores opuestos / n_total_sub_cat."""
                if direccion_propia == 'Sube':
                    # Opuestos: bajadas + promos
                    score = 0.0
                    for pid in cambios_bajas_subcat.get(sub_cat, []):
                        if pid != sku_propio:
                            score += PESO_ABC.get(sku_to_abc.get(pid, ''), 0.0)
                    for pid in promos_activas_subcat.get(sub_cat, []):
                        if pid != sku_propio:
                            score += PESO_ABC.get(sku_to_abc.get(pid, ''), 0.0)
                elif direccion_propia == 'Baja':
                    # Opuestos: subidas
                    score = 0.0
                    for pid in cambios_subes_subcat.get(sub_cat, []):
                        if pid != sku_propio:
                            score += PESO_ABC.get(sku_to_abc.get(pid, ''), 0.0)
                else:
                    return 0.0
                n_total = sku_count_by_subcat.get(sub_cat, 1)
                return score / max(1, n_total)

            # ----------------------
            # APLICAR REGLAS POR SKU
            # ----------------------
            alertas = []
            skus_potenciales = set(price_changes_by_sku.keys()) | set(promos_by_sku.keys())
            # v5.6: filtrar a productos vendibles (active=True AND sale_ok=True)
            if skus_vendibles:
                skus_potenciales = skus_potenciales & skus_vendibles

            for pid in skus_potenciales:
                sub_cat = sku_to_subcat.get(pid, '')
                abc = sku_to_abc.get(pid, '')
                abcxyz = sku_to_abcxyz.get(pid, '')
                cambio = price_changes_by_sku.get(pid)
                promo = promos_by_sku.get(pid)

                # ============ CASO: subida + promo propia ============
                # v5.8: solo emitia SUBIDA_FUERTE_CON_PROMO_W1 (var>=20%, wa=1, lift>=1.5).
                # v5.9: fallback a PROMO_PAREO_MODERADO si min_qty<=2 con lift>=1.5
                # y baseline>=5 (CUSQUENA, MAD CHARLIES y otras 2X DESCUENTO de cerveza
                # tienen subida de precio nominal + promo, antes quedaban sin alerta).
                if cambio and promo and cambio['direccion'] in ('Sube', 'sube', 'SUBE'):
                    var_pct = cambio['var_pct']
                    lift = promo['lift_qty']
                    wa = promo['weeks_active']
                    min_qty = promo.get('min_qty', 0)
                    mec = promo['mecanica']
                    baseline_8w = _safe_float(promo.get('baseline_8w'), 0.0)
                    if var_pct >= 0.20 and wa == 1 and lift >= 1.5:
                        factor = min(1.8, 1.0 + (lift - 1.0) * 0.6)
                        alertas.append({
                            'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                            'event_date': promo.get('period_start') or cambio['fecha'],
                            'tipo': 'SUBIDA_FUERTE_CON_PROMO_W1',
                            'factor_corr': round(factor, 3),
                            'razon': 'Sube %+.0f%% + %s W1 lift %.2f' % (var_pct*100, mec, lift),
                            'source': 'mixto', 'indice_canibal': 0.0,
                            'var_pct': var_pct, 'lift_qty': lift,
                            'weeks_since_change': 0,
                        })
                    elif min_qty <= 2 and lift >= LIFT_PROMO_PAREO_MODERADO and baseline_8w >= BASELINE_MIN_PROMO_PAREO:
                        # v5.9 fallback: promo de pareo con subida moderada de precio.
                        # Domina el efecto promo: factor < 1 reduce forecast post-promo.
                        factor = min(1.7, 1.0 + (lift - 1.0) * 0.6)
                        alertas.append({
                            'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                            'event_date': promo.get('period_start') or cambio['fecha'],
                            'tipo': 'PROMO_PAREO_MODERADO',
                            'factor_corr': round(factor, 3),
                            'razon': '%s (min_qty=%d) lift %.2f bl=%.0f (+ sube %+.0f%%)' % (mec, min_qty, lift, baseline_8w, var_pct*100),
                            'source': 'mixto', 'indice_canibal': 0.0,
                            'var_pct': var_pct, 'lift_qty': lift,
                            'weeks_since_change': wa,
                        })
                    continue

                # ============ CASO: bajada >=30% = liquidacion ============
                if cambio and cambio['direccion'] in ('Baja', 'baja', 'BAJA') and cambio['var_pct'] <= -0.30:
                    alertas.append({
                        'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                        'event_date': cambio['fecha'],
                        'tipo': 'BAJADA_DISCONTINUACION',
                        'factor_corr': 1.0,
                        'razon': 'Baja %+.0f%% (liquidacion)' % (cambio['var_pct']*100),
                        'source': 'price_change', 'indice_canibal': 0.0,
                        'var_pct': cambio['var_pct'], 'lift_qty': 0.0,
                        'weeks_since_change': 0,
                    })
                    continue

                # ============ CASO: solo promo (sin cambio precio) ============
                # v5.2: clasificacion por minimum_qty (no solo por nombre)
                #   min_qty <= 2: pareo, no alertar salvo lift extremo
                #   min_qty 3-4: mixto (intermedio)
                #   min_qty >= 6: stock-up (DISPARO_W1 / SATURACION_W3+)
                if promo and not cambio:
                    lift = promo['lift_qty']
                    wa = promo['weeks_active']
                    mec = promo['mecanica']
                    min_qty = promo.get('min_qty', 0)

                    promo_evt_date = promo.get('period_start')

                    # PROMO DE PAREO (min_qty <= 2):
                    #   - lift >= 2.5: extremo (v5.8 existente, sin cambio).
                    #   - lift 1.5-2.5 con baseline >= BASELINE_MIN_PROMO_PAREO:
                    #     moderado (v5.9 NUEVO). El baseline_min evita ruido de
                    #     SKUs con muy poca venta donde lift es anomalia.
                    #   - resto: descartar (ruido).
                    if min_qty <= 2:
                        baseline_8w = _safe_float(promo.get('baseline_8w'), 0.0)
                        if lift >= 2.5:
                            factor = min(2.0, lift * 0.7)
                            alertas.append({
                                'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                                'event_date': promo_evt_date,
                                'tipo': 'PROMO_PAREO_LIFT_EXTREMO',
                                'factor_corr': round(factor, 3),
                                'razon': '%s (min_qty=%d) lift extremo %.2f' % (mec, min_qty, lift),
                                'source': 'promo', 'indice_canibal': 0.0,
                                'var_pct': 0.0, 'lift_qty': lift,
                                'weeks_since_change': wa,
                            })
                        elif lift >= LIFT_PROMO_PAREO_MODERADO and baseline_8w >= BASELINE_MIN_PROMO_PAREO:
                            # v5.9: factor moderado, lift escala suave.
                            # lift=1.5 -> factor=1.30; lift=2.0 -> factor=1.60; lift=2.5 -> factor=1.90 (cap=1.7).
                            factor = min(1.7, 1.0 + (lift - 1.0) * 0.6)
                            alertas.append({
                                'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                                'event_date': promo_evt_date,
                                'tipo': 'PROMO_PAREO_MODERADO',
                                'factor_corr': round(factor, 3),
                                'razon': '%s (min_qty=%d) lift moderado %.2f (baseline=%.0f)' % (mec, min_qty, lift, baseline_8w),
                                'source': 'promo', 'indice_canibal': 0.0,
                                'var_pct': 0.0, 'lift_qty': lift,
                                'weeks_since_change': wa,
                            })
                        # else: no alertar (lift < 1.5 o baseline < min = ruido)
                        continue

                    # PROMO STOCK-UP (min_qty >= 6): mecanica clasica
                    if min_qty >= 6:
                        if wa <= 1 and lift >= 1.5:
                            factor = min(2.0, 1.0 + (lift - 1.0) * 0.7)
                            alertas.append({
                                'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                                'event_date': promo_evt_date,
                                'tipo': 'DISPARO_STOCKUP_W1',
                                'factor_corr': round(factor, 3),
                                'razon': '%s W1 lift %.2f (min_qty=%d, cliente carga)' % (mec, lift, min_qty),
                                'source': 'promo', 'indice_canibal': 0.0,
                                'var_pct': 0.0, 'lift_qty': lift,
                                'weeks_since_change': wa,
                            })
                        elif wa >= 3 and 0.5 < lift < 0.8:
                            factor = max(0.6, lift)
                            alertas.append({
                                'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                                'event_date': promo_evt_date,
                                'tipo': 'SATURACION_STOCKUP_W%d' % wa,
                                'factor_corr': round(factor, 3),
                                'razon': '%s W%d lift %.2f (min_qty=%d, cliente saturado)' % (mec, wa, lift, min_qty),
                                'source': 'promo', 'indice_canibal': 0.0,
                                'var_pct': 0.0, 'lift_qty': lift,
                                'weeks_since_change': wa,
                            })
                        # NO alertar W2 con lift<=0.5 (era ruido en v4)
                        continue

                    # PROMO MIXTA (min_qty 3-4): solo casos muy claros
                    if min_qty in (3, 4):
                        if wa <= 1 and lift >= 1.8:  # lift mas alto para alertar
                            factor = min(1.8, 1.0 + (lift - 1.0) * 0.6)
                            alertas.append({
                                'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                                'event_date': promo_evt_date,
                                'tipo': 'DISPARO_MIXTO_W1',
                                'factor_corr': round(factor, 3),
                                'razon': '%s W1 lift %.2f (min_qty=%d)' % (mec, lift, min_qty),
                                'source': 'promo', 'indice_canibal': 0.0,
                                'var_pct': 0.0, 'lift_qty': lift,
                                'weeks_since_change': wa,
                            })
                        continue

                # ============ CASO: solo cambio precio (sin promo) ============
                if cambio and not promo:
                    var_pct = cambio['var_pct']
                    direccion = cambio['direccion']

                    if abs(var_pct) < 0.05:
                        continue

                    weeks_since = 0
                    try:
                        weeks_since = max(0, (target_week_start - cambio['fecha']).days // 7)
                    except Exception:
                        pass
                    # v5.2: subidas con decay 12 semanas (adaptacion gradual del consumidor)
                    decay_subida = max(0.0, 1.0 - weeks_since / 12.0)

                    if direccion in ('Sube', 'sube', 'SUBE'):
                        factor_b = _factor_base_subida(var_pct)
                        idx = cpi_ponderado(sub_cat, 'Sube', pid)
                        if var_pct >= 0.20: piso = 0.40
                        elif var_pct >= 0.10: piso = 0.55
                        else: piso = 0.75
                        if idx >= 0.50:
                            tipo = 'SUBIDA_CANIBAL_FUERTE'
                            factor = factor_b * max(piso, 1.0 - idx * 0.6)
                        elif idx >= 0.25:
                            tipo = 'SUBIDA_CANIBAL_MODERADO'
                            factor = factor_b * max(piso + 0.10, 1.0 - idx * 0.4)
                        elif idx >= 0.10:
                            tipo = 'SUBIDA_CON_PRESION'
                            factor = factor_b * (1.0 - idx * 0.2)
                        else:
                            tipo = 'SUBIDA_UNICA'
                            factor = factor_b
                        # v5.2: decay 12 semanas para subidas (adaptacion gradual)
                        factor = 1.0 - (1.0 - factor) * decay_subida
                        # v5.7: ponderar elasticidad por ABC del SKU propio
                        factor = _aplicar_elasticidad_abc(factor, abc)
                        alertas.append({
                            'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                            'event_date': cambio['fecha'],
                            'tipo': tipo, 'factor_corr': round(factor, 3),
                            'razon': 'Sube %+.0f%% + canibal %.2f' % (var_pct*100, idx),
                            'source': 'price_change', 'indice_canibal': round(idx, 3),
                            'var_pct': var_pct, 'lift_qty': 0.0,
                            'weeks_since_change': weeks_since,
                        })
                    elif direccion in ('Baja', 'baja', 'BAJA'):
                        factor_b = _factor_base_bajada(var_pct)
                        idx = cpi_ponderado(sub_cat, 'Baja', pid)
                        if idx >= 0.50:
                            tipo = 'BAJADA_GANADORA_FUERTE'
                            factor = factor_b * (1.0 + idx * 0.6)
                        elif idx >= 0.25:
                            tipo = 'BAJADA_GANADORA_MODERADA'
                            factor = factor_b * (1.0 + idx * 0.4)
                        elif idx >= 0.10:
                            tipo = 'BAJADA_CON_PRESION'
                            factor = factor_b * (1.0 + idx * 0.2)
                        else:
                            tipo = 'BAJADA_UNICA'
                            factor = factor_b
                        # v5.2: BAJADAS son cambios de lista sostenidos -> sin decay
                        # La promo vive hasta que el precio cambie otra vez (nuevo registro)
                        # factor SE MANTIENE
                        # v5.7: ponderar elasticidad por ABC del SKU propio
                        factor = _aplicar_elasticidad_abc(factor, abc)
                        alertas.append({
                            'product_id': pid, 'sub_cat': sub_cat, 'abcxyz': abcxyz,
                            'event_date': cambio['fecha'],
                            'tipo': tipo, 'factor_corr': round(factor, 3),
                            'razon': 'Baja %+.0f%% + canibal %.2f' % (var_pct*100, idx),
                            'source': 'price_change', 'indice_canibal': round(idx, 3),
                            'var_pct': var_pct, 'lift_qty': 0.0,
                            'weeks_since_change': weeks_since,
                        })

            # ----------------------
            # Persistir alertas en x_price_correccion
            # ----------------------
            batch = []
            total_created = 0
            tipo_counts = {}

            corr_create = CorrModel.with_context(
                tracking_disable=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notrack=True,
            ).create

            # v5.6: contadores de diagnostico para abcxyz
            abcxyz_field_exists = 'x_studio_abcxyz' in corr_fields
            abcxyz_with_value = 0
            abcxyz_empty = 0

            for a in alertas:
                tipo_interno = a['tipo']
                tipo_studio = _tipo_studio(tipo_interno, a.get('var_pct', 0.0))
                tipo_counts[tipo_interno] = tipo_counts.get(tipo_interno, 0) + 1
                if a.get('abcxyz', ''):
                    abcxyz_with_value += 1
                else:
                    abcxyz_empty += 1
                # v5.6: target_week_start = fecha del evento (period_start),
                # no la proxima semana. Fallback a la proxima si no hay fecha.
                evt_date = a.get('event_date') or target_week_start
                # Normalizar a inicio de semana (lunes) por consistencia con el motor
                try:
                    evt_week = _week_start(evt_date)
                except Exception:
                    evt_week = target_week_start
                rec_name = 'CORR %s PP%s' % (evt_week, a['product_id'])

                vals = {}
                if 'x_name' in corr_fields:
                    vals['x_name'] = rec_name
                _put_field(vals, corr_fields, 'x_studio_product_id', a['product_id'])
                _put_field(vals, corr_fields, 'x_studio_target_week_start', evt_week)
                _put_field(vals, corr_fields, 'x_studio_factor_corr', a['factor_corr'])
                _put_field(vals, corr_fields, 'x_studio_tipo_alerta', tipo_studio, 60)
                _put_field(vals, corr_fields, 'x_studio_razon', a['razon'], 240)
                _put_field(vals, corr_fields, 'x_studio_indice_canibal', a['indice_canibal'])
                _put_field(vals, corr_fields, 'x_studio_source', a['source'], 20)
                _put_field(vals, corr_fields, 'x_studio_sub_cat', a['sub_cat'], 80)
                _put_field(vals, corr_fields, 'x_studio_var_pct', a['var_pct'])
                _put_field(vals, corr_fields, 'x_studio_lift_qty', a['lift_qty'])
                _put_field(vals, corr_fields, 'x_studio_weeks_since_change', a['weeks_since_change'])
                # v5.6: persistir ABCXYZ del SKU para auditoria
                _put_field(vals, corr_fields, 'x_studio_abcxyz', a.get('abcxyz', ''), 10)
                if 'x_studio_active' in corr_fields:
                    vals['x_studio_active'] = True

                batch.append(vals)
                if len(batch) >= 500:
                    corr_create(batch)
                    total_created += len(batch)
                    batch = []

            if batch:
                corr_create(batch)
                total_created += len(batch)

            # ----------------------
            # Log y notificacion
            # ----------------------
            tipo_summary = ','.join(['%s:%s' % (k, v) for k, v in sorted(tipo_counts.items())])
            try:
                log(
                    '%s | target_week=%s | purged=%s | alertas=%s | tipos=%s' % (
                        VERSION_ID, target_week_start, purge_count, total_created, tipo_summary
                    ),
                    level='info'
                )
            except Exception:
                pass

            diag = 'abcxyz_field=%s con_valor=%s vacio=%s' % (
                abcxyz_field_exists, abcxyz_with_value, abcxyz_empty
            )
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': VERSION_ID,
                    'message': 'target=%s | purged=%s | creadas=%s | %s | tipos=%s' % (
                        target_week_start, purge_count, total_created,
                        diag, tipo_summary[:180]
                    ),
                    'type': 'success', 'sticky': True,
                }
            }

        finally:
            env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
