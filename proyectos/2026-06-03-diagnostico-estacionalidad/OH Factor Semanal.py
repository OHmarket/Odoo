# -*- coding: utf-8 -*-
# ============================================================
# OH FACTOR SEMANAL — v1.0 (FACTOR_SEMANAL_v1.0)
# ============================================================
# Escribe x_forecast_factor_week: factor de correccion por CATEGORIA x SEMANA
# futura (52 semanas), sobre la SEMANA BASE (nivel destendenciado, factor
# centrado en 1). Capas:
#
#   factor_verano : curva estacional por categoria (regresion armonica
#                   Fourier K=3 sobre log-venta semanal, destendenciada,
#                   con dummy de semana-evento que absorbe los spikes).
#                   Gates: amplitud >= SEASONAL_MIN_AMP (categ estacional)
#                   y zona muerta |SI-1| < DEAD_ZONE -> 1.0 (parsimonia:
#                   factor solo donde hay senal).
#   factor_evento : uplift medido por evento x categoria (semana objetivo
#                   vs baseline mediana de semanas limpias +/-6). Arquetipo
#                   A feriado -> semana de la VISPERA; B comercial -> semana
#                   del DIA. Eventos que caen en la misma semana NO se
#                   multiplican: se toma el maximo (bloque).
#
# Proceso: STATELESS hacia adelante. Cada corrida recalcula desde TODA la
# historia del fact (x_pos_week_sku_sale) y regenera las semanas FUTURAS;
# las semanas pasadas quedan congeladas con su factor vigente (historial
# para el monitor de sesgo). El NIVEL de venta lo sigue el motor base
# (Forecast Base, SES) — este factor solo aporta FORMA.
#
# CONSUMO CORRECTO (Analisis de Stock, Fase A): para proyectar la semana T
# desde hoy:  demanda = mu_week * factor_total(T) / factor_verano(semana_hoy)
# (el SES ya trae la estacionalidad de HOY adentro; dividir evita doble conteo).
# El factor_evento no se divide: el cleansing del motor ya excluye eventos.
#
# PROXY / deuda visible:
# - Curva de verano con ~18 meses de fact (1 ciclo). Refinar con backfill 2023.
# - Sin modulacion dia-semana / largo de finde (Fase B del plan).
# - Sin condicional de apertura para irrenunciables (Fase D).
# - Dia de la Madre/Padre excluidos por diseno (uplift flojo medido).
# - safe_eval no tiene math: sin/cos/ln vienen de Postgres, exp = E**x.
#
# Modelo destino (Studio, crear antes de correr):
#   x_forecast_factor_week: x_name, x_studio_categ_id (m2o product.category),
#   x_studio_week_start (date), x_studio_iso_week (int),
#   x_studio_factor_verano (float), x_studio_factor_evento (float),
#   x_studio_evento (char), x_studio_factor_total (float),
#   x_studio_source_version (char)
# ============================================================

VERSION_ID = 'FACTOR_SEMANAL_v1.0'
MODEL = 'x_forecast_factor_week'
SALE_MODEL_TABLE = 'x_pos_week_sku_sale'
HOL_OCC_MODEL = 'x_holiday_occurrence'
LOCK_KEY = 99009614

K_FOURIER = 3
MIN_WEEKS_FIT = 40          # semanas con venta para ajustar la curva
SEASONAL_MIN_AMP = 1.30     # max/min de la curva para considerar categ estacional
DEAD_ZONE = 0.10            # |SI-1| < zona -> factor 1 (hombros solamente)
SI_CLAMP = (0.40, 3.50)

EV_BL_HALF = 6              # +/- semanas para baseline de evento
EV_BL_MIN_WEEKS = 4         # minimo de semanas limpias en baseline
EV_BL_MIN_QTY = 10.0        # baseline minimo (u/sem) para ratio estable
EV_MIN_FACTOR = 1.20        # umbral de senal del factor de evento
EV_CLAMP = (1.0, 8.0)
TOTAL_CLAMP = (0.30, 8.0)

HORIZON_WEEKS = 52
MIN_RECENT_WEEKS = 13       # categ viva: venta en las ultimas N semanas
E = 2.718281828459045

# Arquetipo B (comercial -> factor en el DIA). Todo codigo del master = A.
COMMERCIAL_EVENTS = [('SAN_VALENTIN', 2, 14), ('HALLOWEEN', 10, 31)]
B_CODES = set([c for c, _m, _d in COMMERCIAL_EVENTS])
EXCLUDED_CODES = set(['MOTHERS_DAY', 'FATHERS_DAY'])  # uplift flojo, por diseno

# ------------------------------------------------------------
# 0. Lock anti-concurrencia
# ------------------------------------------------------------
env.cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    raise UserError('OH Factor Semanal ya esta corriendo (lock %s).' % LOCK_KEY)

try:
    # --------------------------------------------------------
    # 1. Validar modelo destino y campos
    # --------------------------------------------------------
    if MODEL not in env:
        raise UserError('No existe el modelo %s. Crearlo en Studio primero.' % MODEL)
    Factor = env[MODEL].sudo()
    req = ['x_name', 'x_studio_categ_id', 'x_studio_week_start',
           'x_studio_iso_week', 'x_studio_factor_verano',
           'x_studio_factor_evento', 'x_studio_evento',
           'x_studio_factor_total', 'x_studio_source_version']
    missing = [f for f in req if f not in Factor._fields]
    if missing:
        raise UserError('Faltan campos en %s: %s' % (MODEL, ', '.join(missing)))

    today = datetime.date.today()
    monday_now = today - datetime.timedelta(days=today.weekday())

    # --------------------------------------------------------
    # 2. Base de Fourier desde Postgres (safe_eval no tiene math)
    #    basis[iso_week] = [sin1, cos1, sin2, cos2, sin3, cos3]
    # --------------------------------------------------------
    env.cr.execute("""
        SELECT w,
               sin(2*pi()*1*w/52.0), cos(2*pi()*1*w/52.0),
               sin(2*pi()*2*w/52.0), cos(2*pi()*2*w/52.0),
               sin(2*pi()*3*w/52.0), cos(2*pi()*3*w/52.0)
        FROM generate_series(1, 52) AS w
    """)
    basis = {}
    for row in env.cr.fetchall():
        basis[int(row[0])] = [float(v) for v in row[1:]]

    def iso_week_of(d):
        return min(d.isocalendar()[1], 52)

    def monday_of(d):
        return d - datetime.timedelta(days=d.weekday())

    # --------------------------------------------------------
    # 3. Venta semanal por categoria (toda la historia del fact)
    # --------------------------------------------------------
    env.cr.execute("""
        SELECT x_studio_categ_id, x_studio_week_start,
               SUM(COALESCE(x_studio_qty_sold, 0.0)) AS qty
        FROM """ + SALE_MODEL_TABLE + """
        WHERE x_studio_categ_id IS NOT NULL
          AND x_studio_week_start IS NOT NULL
          AND x_studio_week_start < %s
        GROUP BY 1, 2
        HAVING SUM(COALESCE(x_studio_qty_sold, 0.0)) > 0
    """, (monday_now,))
    series = {}                       # categ_id -> {week(date): qty}
    for cid, wk, qty in env.cr.fetchall():
        if isinstance(wk, datetime.datetime):
            wk = wk.date()
        series.setdefault(int(cid), {})[wk] = float(qty)
    if not series:
        raise UserError('Sin datos en %s.' % SALE_MODEL_TABLE)

    recent_cut = monday_now - datetime.timedelta(weeks=MIN_RECENT_WEEKS)
    categs = [c for c, s in series.items()
              if any(w >= recent_cut for w in s)]
    log('%s: categorias vivas %s de %s' % (VERSION_ID, len(categs), len(series)))

    # --------------------------------------------------------
    # 4. Calendario de eventos (master + comerciales), pasado y futuro
    #    ev = (code, fecha, target_week)
    # --------------------------------------------------------
    hist_min = min([min(s.keys()) for s in series.values()])
    horizon_end = monday_now + datetime.timedelta(weeks=HORIZON_WEEKS)

    events = []
    occs = env[HOL_OCC_MODEL].sudo().search([
        ('x_studio_holiday_id', '!=', False),
        ('x_studio_holiday_date', '!=', False)])
    occ_rows = occs.read(['x_studio_holiday_id', 'x_studio_holiday_date'])
    master_ids = list(set([r['x_studio_holiday_id'][0] for r in occ_rows]))
    code_by_id = {}
    if master_ids:
        for r in env['x_holiday_master'].sudo().browse(master_ids).read(['x_studio_code']):
            code_by_id[r['id']] = (r.get('x_studio_code') or '').strip().upper()
    for r in occ_rows:
        code = code_by_id.get(r['x_studio_holiday_id'][0], '')
        d = r['x_studio_holiday_date']
        if isinstance(d, str):
            d = datetime.date.fromisoformat(d[:10])
        if not code or code in EXCLUDED_CODES:
            continue
        events.append((code, d))
    for code, m, dd in COMMERCIAL_EVENTS:
        for y in range(hist_min.year, horizon_end.year + 1):
            events.append((code, datetime.date(y, m, dd)))
    events = list(set(events))   # dedupe si un comercial entra al master despues

    # semana objetivo por arquetipo; semanas sucias (dia Y vispera de todo evento)
    ev_target = []                    # (code, fecha, target_week)
    dirty_weeks = set()
    for code, d in events:
        tgt = d if code in B_CODES else d - datetime.timedelta(days=1)
        ev_target.append((code, d, monday_of(tgt)))
        dirty_weeks.add(monday_of(d))
        dirty_weeks.add(monday_of(d - datetime.timedelta(days=1)))

    ev_hist = [(c, d, w) for c, d, w in ev_target if w < monday_now]
    ev_futu = [(c, d, w) for c, d, w in ev_target
               if monday_now <= w <= horizon_end]
    log('%s: eventos historicos %s | futuros en horizonte %s' %
        (VERSION_ID, len(ev_hist), len(ev_futu)))

    # --------------------------------------------------------
    # 5. Algebra: resolver Ax=b (Gauss-Jordan, pivoteo parcial)
    # --------------------------------------------------------
    def solve(A, b):
        n = len(b)
        M = [list(A[i]) + [b[i]] for i in range(n)]
        for col in range(n):
            piv = col
            for r in range(col + 1, n):
                if abs(M[r][col]) > abs(M[piv][col]):
                    piv = r
            if abs(M[piv][col]) < 1e-10:
                return None
            M[col], M[piv] = M[piv], M[col]
            dv = M[col][col]
            M[col] = [v / dv for v in M[col]]
            for r in range(n):
                if r != col and M[r][col] != 0.0:
                    f = M[r][col]
                    M[r] = [M[r][j] - f * M[col][j] for j in range(n + 1)]
        return [M[i][n] for i in range(n)]

    def ln(x):
        # ln natural via serie atanh (x>0): ln(x) = 2*atanh((x-1)/(x+1))
        # normalizando a [0.5, 2) con potencias de 2 para convergencia rapida.
        if x <= 0:
            return 0.0
        k = 0
        while x >= 2.0:
            x = x / 2.0
            k += 1
        while x < 0.5:
            x = x * 2.0
            k -= 1
        z = (x - 1.0) / (x + 1.0)
        z2 = z * z
        term, s, i = z, 0.0, 0
        while abs(term) > 1e-12 and i < 60:
            s += term / (2 * i + 1)
            term *= z2
            i += 1
        return 2.0 * s + k * 0.6931471805599453

    # --------------------------------------------------------
    # 6. Por categoria: curva SI (52) + factores de evento
    # --------------------------------------------------------
    def fit_curve(s):
        """Curva estacional centrada en 1 por iso_week, o None."""
        weeks = sorted(s.keys())
        if len(weeks) < MIN_WEEKS_FIT:
            return None
        w0 = weeks[0]
        # dummy de evento solo si tiene variacion (todo-cero = matriz singular)
        has_ev = any([w in dirty_weeks for w in weeks])
        X, y = [], []
        for w in weeks:
            iso = iso_week_of(w)
            t = (w - w0).days / 365.0
            row = [1.0, t] + basis[iso]
            if has_ev:
                row = row + [1.0 if w in dirty_weeks else 0.0]
            X.append(row)
            y.append(ln(s[w]))
        n_par = len(X[0])
        A = [[0.0] * n_par for _i in range(n_par)]
        bv = [0.0] * n_par
        for r_i in range(len(X)):
            xr = X[r_i]
            for i in range(n_par):
                bv[i] += xr[i] * y[r_i]
                for j in range(i, n_par):
                    A[i][j] += xr[i] * xr[j]
        for i in range(n_par):
            for j in range(i + 1, n_par):
                A[j][i] = A[i][j]
        coef = solve(A, bv)
        if coef is None:
            return None
        fcoef = coef[2:2 + 2 * K_FOURIER]
        s_log = []
        for iso in range(1, 53):
            bs = basis[iso]
            s_log.append(sum([bs[i] * fcoef[i] for i in range(2 * K_FOURIER)]))
        mean_s = sum(s_log) / 52.0
        curve = [E ** (v - mean_s) for v in s_log]
        curve = [max(SI_CLAMP[0], min(SI_CLAMP[1], v)) for v in curve]
        if (max(curve) / max(min(curve), 1e-9)) < SEASONAL_MIN_AMP:
            return None                       # categ plana: sin factor
        return {iso: (1.0 if abs(curve[iso - 1] - 1.0) < DEAD_ZONE
                      else curve[iso - 1]) for iso in range(1, 53)}

    def median(vals):
        sv = sorted(vals)
        n = len(sv)
        if n == 0:
            return None
        return sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2.0

    def event_factors(s):
        """code -> factor (mediana entre anos, con gates de senal)."""
        ups = {}
        for code, _d, tw in ev_hist:
            q = s.get(tw, 0.0)
            if q <= 0:
                continue
            clean = [v for w, v in s.items()
                     if abs((w - tw).days) <= EV_BL_HALF * 7
                     and w != tw and w not in dirty_weeks]
            if len(clean) < EV_BL_MIN_WEEKS:
                continue
            bl = median(clean)
            if not bl or bl < EV_BL_MIN_QTY:
                continue
            ups.setdefault(code, []).append(q / bl)
        out = {}
        for code, vals in ups.items():
            med = median(vals)
            if med is None or med < EV_MIN_FACTOR:
                continue
            if len(vals) >= 2 and min(vals) <= 1.0:
                continue                      # inconsistente entre anos
            out[code] = max(EV_CLAMP[0], min(EV_CLAMP[1], med))
        return out

    # --------------------------------------------------------
    # 7. Generar filas futuras y escribir
    # --------------------------------------------------------
    vals_list = []
    n_seasonal, n_event_rows = 0, 0
    for cid in sorted(categs):
        s = series[cid]
        si = fit_curve(s)
        evf = event_factors(s)
        if si:
            n_seasonal += 1
        for h in range(HORIZON_WEEKS):
            wk = monday_now + datetime.timedelta(weeks=h)
            iso = iso_week_of(wk)
            fv = si.get(iso, 1.0) if si else 1.0
            fe, ev_name = 1.0, False
            for code, _d, tw in ev_futu:
                if tw == wk and code in evf and evf[code] > fe:
                    fe, ev_name = evf[code], code
            ft = max(TOTAL_CLAMP[0], min(TOTAL_CLAMP[1], fv * fe))
            if fe > 1.0:
                n_event_rows += 1
            vals_list.append({
                'x_name': '%s:%s' % (cid, wk.isoformat()),
                'x_studio_categ_id': cid,
                'x_studio_week_start': wk.isoformat(),
                'x_studio_iso_week': iso,
                'x_studio_factor_verano': round(fv, 4),
                'x_studio_factor_evento': round(fe, 4),
                'x_studio_evento': ev_name or False,
                'x_studio_factor_total': round(ft, 4),
                'x_studio_source_version': VERSION_ID,
            })

    # Borra SOLO semanas futuras: las pasadas quedan congeladas con el factor
    # que estaba vigente cuando llegaron -> historial auditable para el
    # monitor de sesgo (BIAS = mu x factor_vigente vs venta real).
    old = Factor.search([('x_studio_week_start', '>=', monday_now.isoformat())])
    n_old = len(old)
    if old:
        old.unlink()
    for i in range(0, len(vals_list), 2000):
        Factor.create(vals_list[i:i + 2000])

    msg = ('%s: %s filas creadas (%s borradas) | categs %s | estacionales %s | '
           'semanas-evento con factor %s | horizonte %s -> %s' %
           (VERSION_ID, len(vals_list), n_old, len(categs), n_seasonal,
            n_event_rows, monday_now,
            monday_now + datetime.timedelta(weeks=HORIZON_WEEKS - 1)))
    log(msg)
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {'title': 'OH Factor Semanal',
                   'message': msg, 'type': 'success', 'sticky': True},
    }
finally:
    env.cr.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
