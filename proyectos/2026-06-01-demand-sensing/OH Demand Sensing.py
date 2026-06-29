# -*- coding: utf-8 -*-
# OH Demand Sensing v0.1 — capa post-forecast (Server Action, safe_eval)
#
# Corre DESPUES de OH Forecast Base en el pipeline. NO toca el motor.
# Para cervezas con evento de precio confirmado (dias_post>=7) reemplaza el nivel
# del forecast por el run-rate reciente MEDIDO (venta de los ultimos 7 dias = MM7x7),
# escribiendo x_studio_mu_week_adjusted. Resto de filas queda en False (passthrough:
# Stock lee COALESCE(adjusted, mu_week)).
#
# Modelo canonico: demand sensing (SAP IBP / Blue Yonder) — medir el salto de nivel,
# no estimarlo. Gate FVA validado vs Forecast Base v1.6 (gate_vs_base.py): solo-evento
# limpio -1.86pp, ds-activo limpio -2.87pp WAPE, ciclo completo, sin quiebre.
#
# safe_eval: sin import/getattr/setattr; datetime inyectado; escribir via .write().

DS_ENABLED = True
DS_CATEG_LIKE = 'Cerveza'        # solo cervezas hasta nuevo gate
CONF_DAYS = 7                    # dias post-evento para confirmar nuevo nivel
QB_SALAS = 3                     # >= salas en stockout en la ventana => MM7 censurado, passthrough
EVENT_LOOKBACK_DAYS = 365        # ventana para buscar el evento mas reciente (semantica del gate validado)
EVENT_MIN_VARPCT = 0.001         # |var_pct| minimo para contar como evento real
FACTOR_MIN = 0.2
FACTOR_MAX = 5.0
POS_STATES = ['paid', 'done', 'invoiced']

# TRIGGER = x_price_coreccion (el detector). Validado en gate_vs_base.py / validar_layer_pcorr.py.
# NO usar x_price_change_event: trigger distinto -> ds net NEGATIVO (validar_layer.py).

FWD = env['x_hm_si_forecast'].sudo()
fields_fwd = FWD._fields

# requisito duro: el campo destino tiene que existir (Studio)
if not DS_ENABLED or 'x_studio_mu_week_adjusted' not in fields_fwd:
    action = {'type': 'ir.actions.client', 'tag': 'display_notification',
              'params': {'title': 'OH Demand Sensing',
                         'message': 'Desactivado o falta campo x_studio_mu_week_adjusted.',
                         'type': 'warning', 'sticky': False}}
else:
    # ---- 1. semana objetivo del forecast recien escrito ----
    weeks = FWD.read_group([], ['x_studio_week_start'], ['x_studio_week_start:week'])
    week_dates = []
    for w in weeks:
        rng = w.get('__range') or {}
        rk = rng.get('x_studio_week_start:week') or {}
        if rk.get('from'):
            week_dates.append(rk['from'])
    target_str = max(week_dates) if week_dates else None

    if not target_str:
        action = {'type': 'ir.actions.client', 'tag': 'display_notification',
                  'params': {'title': 'OH Demand Sensing',
                             'message': 'Sin forecast para procesar.', 'type': 'warning'}}
    else:
        y, m, d = [int(x) for x in target_str[:10].split('-')]
        target_date = datetime.date(y, m, d)
        cutoff = target_date - datetime.timedelta(days=1)            # sabado anterior
        win_from = cutoff - datetime.timedelta(days=6)               # ventana MM7 [cutoff-6, cutoff]
        ev_from = cutoff - datetime.timedelta(days=EVENT_LOOKBACK_DAYS)

        # ---- 2. universo: cervezas con evento de precio real reciente ----
        Prod = env['product.product'].sudo()
        cerv = Prod.search([('categ_id.complete_name', 'like', DS_CATEG_LIKE)])
        cerv_ids = cerv.ids

        ev_last = {}   # pid -> fecha evento mas reciente (date)
        if cerv_ids:
            PCO = env['x_price_coreccion'].sudo()
            ev_rows = PCO.search([
                ('x_studio_product_id', 'in', cerv_ids),
                ('x_studio_target_week_start', '>=', ev_from.isoformat()),
                ('x_studio_target_week_start', '<=', cutoff.isoformat()),
            ])
            for r in ev_rows:
                if abs(float(r.x_studio_var_pct or 0.0)) <= EVENT_MIN_VARPCT:
                    continue
                p = r.x_studio_product_id.id
                ps = r.x_studio_target_week_start   # date
                if ps and (p not in ev_last or ps > ev_last[p]):
                    ev_last[p] = ps

        evt_pids = sorted(ev_last.keys())

        # ---- 3. quiebre material en la ventana de medicion (MM7 censurado) ----
        qb_pids = set()
        if evt_pids:
            SB = env['x_stock_balance_daily'].sudo()
            sb_rows = SB.search([
                ('x_studio_product_id', 'in', evt_pids),
                ('x_studio_date', '>=', win_from.isoformat()),
                ('x_studio_date', '<=', cutoff.isoformat()),
                '|', ('x_studio_stockout', '=', True),
                ('x_studio_stockout_partial', '=', True),
            ])
            teams_por_pid = {}
            for r in sb_rows:
                p = r.x_studio_product_id.id
                t = r.x_studio_team_id.id if r.x_studio_team_id else 0
                teams_por_pid.setdefault(p, set()).add(t)
            for p, ts in teams_por_pid.items():
                if len(ts) >= QB_SALAS:
                    qb_pids.add(p)

        # ---- 4. senal diaria: suma venta ultimos 7 dias = MM7x7 (un read_group) ----
        ds_level = {}   # pid -> unidades semana medidas
        if evt_pids:
            POL = env['pos.order.line'].sudo()
            grp = POL.read_group(
                [('product_id', 'in', evt_pids),
                 ('order_id.date_order', '>=', win_from.isoformat() + ' 00:00:00'),
                 ('order_id.date_order', '<=', cutoff.isoformat() + ' 23:59:59'),
                 ('order_id.state', 'in', POS_STATES)],
                ['qty:sum'], ['product_id'])
            for g in grp:
                pr = g.get('product_id')
                if pr:
                    ds_level[pr[0]] = float(g.get('qty') or 0.0)

        # ---- 5. motor_total por producto (suma sobre teams) del forecast actual ----
        motor_total = {}
        fwd_evt = FWD.search([('x_studio_product_id', 'in', evt_pids),
                              ('x_studio_week_start', '=', target_date.isoformat())]) if evt_pids else FWD.browse([])
        for r in fwd_evt:
            p = r.x_studio_product_id.id
            motor_total[p] = motor_total.get(p, 0.0) + float(r.x_studio_mu_week or 0.0)

        # ---- 6. factor por producto (ds-activo, sin quiebre) ----
        factor = {}
        n_flag = 0
        n_pre = 0
        n_qb = 0
        for p in evt_pids:
            dp = (cutoff - ev_last[p]).days
            if dp < 0:
                n_pre += 1
                continue
            if dp < CONF_DAYS:
                n_flag += 1
                continue
            if p in qb_pids:
                n_qb += 1
                continue
            mt = motor_total.get(p, 0.0)
            lvl = ds_level.get(p)
            if mt <= 0.0 or lvl is None:
                continue
            f = lvl / mt
            if f < FACTOR_MIN:
                f = FACTOR_MIN
            elif f > FACTOR_MAX:
                f = FACTOR_MAX
            factor[p] = f

        # ---- 7. escribir adjusted por fila (solo ds-activas) ----
        n_rows = 0
        for r in fwd_evt:
            p = r.x_studio_product_id.id
            f = factor.get(p)
            if f is None:
                continue
            r.write({'x_studio_mu_week_adjusted': float(r.x_studio_mu_week or 0.0) * f})
            n_rows += 1

        log('OH_DEMAND_SENSING_v0_1 | target=%s | cutoff=%s | cervezas=%s | evt=%s | '
            'ds_activos=%s | filas_ajustadas=%s | flag=%s pre=%s quiebre=%s' % (
                target_date.isoformat(), cutoff.isoformat(), len(cerv_ids), len(evt_pids),
                len(factor), n_rows, n_flag, n_pre, n_qb), level='info')

        action = {'type': 'ir.actions.client', 'tag': 'display_notification',
                  'params': {'title': 'OH Demand Sensing',
                             'message': 'target %s | %s SKU ds-activos | %s filas ajustadas (flag=%s, quiebre=%s)' % (
                                 target_date.isoformat(), len(factor), n_rows, n_flag, n_qb),
                             'type': 'success', 'sticky': False}}
