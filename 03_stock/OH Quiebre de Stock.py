# ============================================================
# OH Quiebre de Stock - Deteccion de quiebres POR EVIDENCIA (v3.2)
# ============================================================
#
# Reemplaza STOCKOUT_v2_0. Motiva el rediseno el diagnostico 2026-06-12:
# el metodo viejo (reconstruir balance hacia atras 400 dias y marcar
# `balance<=0`) producia 59,5% de dias-quiebre con balance NEGATIVO
# (imposible: 0 quants negativos en Odoo) y 44,6% con VENTA ese dia (no puede
# ser quiebre: no vendes lo que no tienes). Perpetuacion de hasta 413 dias.
#
# Principio nuevo (canon SAP / Oracle Retail):
#   - La VENTA y el STOCK REAL son prueba de disponibilidad, no el balance
#     contable reconstruido. El on-hand fisico nunca es < 0 (se pisa en 0).
#   - Dia OOS = surtido ACTIVO (vendio en ventana movil N) AND disponibilidad 0.
#   - El stock al momento de ejecutar es verdad del dia: resuelve la mayoria de
#     los falsos perpetuos gratis (64% de los pares >=30d tienen stock real hoy).
#
# Logica por (sala, SKU, dia D). Orden: stock-primero, gate solo arbitra ceros.
#   end_raw   = balance reconstruido (roll backward, SIN pisar -> mantiene aritmetica)
#   disponible = end_raw > 0  OR  out_D > 0          # tiene stock O vendio
#   activo     = vendio (out>0) en los ultimos N=45 dias (PROXY: out-move ~ venta;
#                las salas casi no transfieren hacia afuera, modelo CD pass-through)
#   reliable   = el tramo reciente donde el roll NO cruzo a negativo; al primer
#                dia con balance<0 hacia atras, ese dia y los mas viejos quedan
#                NO confiables (anclaje+moves inconsistentes -> drift). No se
#                marca quiebre total ahi (se evita la cola perpetua fantasma).
#   quiebre_parcial = start>0 AND end_raw<=0 AND out>0     # vendio y quedo en 0 (intradia)
#   quiebre_total   = reliable AND NOT disponible AND start<=0 AND end_raw<=0 AND activo
#
# v3.2: se marca CADA dia mientras el producto falte y siga siendo surtido
#   activo (decision de negocio 2026-06-12: "que siga marcando cuando no
#   esta"). El episodio queda acotado solo por el gate de actividad (45 dias
#   sin venta -> deslistado, deja de marcar). Volumen alto de filas aceptado
#   explicitamente (modelo Studio propio, ~1M filas en backfill completo);
#   el costo a cuidar es de QUERIES, no de datos. v3.1 tenia un bound de
#   onset W=14 que cortaba el episodio a 2 semanas; retirado a pedido.
#
# Asimetria aceptada: ante drift se SUB-marca (false negative), nunca se inventa
# quiebre. Sub-censura -> leve over-forecast (lever de caja), direccion segura.
#
# Reconstruccion: incremental (cron diario) ancla en stock.quant de HOY y
# recalcula solo la cola (tail dias) -> 1-7 dias de drift, confiable. El backfill
# largo es best-effort y se auto-protege con `reliable`.
#
# N=45 es PROXY calibrado (gaps inter-venta: X 99,5% / Y 96,8% cubiertos;
# Z >45d es correcto NO marcar). Recalibrable via context o constante.
#
# Modelo destino: x_stock_balance_daily (Studio). Solo persiste dias de quiebre.
# ============================================================

VERSION_ID = "STOCKOUT_v3_2"

TARGET_MODEL = "x_stock_balance_daily"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009440
BATCH_SIZE = 1000
EPS = 0.0001

# Parametros default (overridable via context)
TAIL_WINDOW_DAYS_DEFAULT   = 7                 # cola de re-calculo en modo incremental
BACKFILL_FLOOR_DEFAULT     = (2025, 1, 1)      # piso historico
ACTIVE_WINDOW_DAYS_DEFAULT = 45                # ventana de surtido activo (PROXY, T1)
FILTERED_TEAM_IDS_DEFAULT  = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

WIPE_ALL_AT_START = False

TEAM_WAREHOUSE_MAP_DEFAULT = {
    5:  1, 6:  4, 7:  2, 8:  3, 9:  16, 10: 8,
    11: 5, 12: 9, 13: 10, 16: 12, 17: 14, 18: 13,
}


def _log_info(msg, *args):
    log((msg % args) if args else msg, level='info')


def _log_warn(msg, *args):
    log((msg % args) if args else msg, level='warn')


CTX = (env.context or {})


def _to_int_list(v):
    if not v:
        return []
    if isinstance(v, (list, tuple, set)):
        out = []
        for x in v:
            try:
                out.append(int(x))
            except Exception:
                pass
        return out
    try:
        return [int(v)]
    except Exception:
        return []


def _parse_iso_date(v):
    if v is None or v is False or v == '':
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.datetime.strptime(str(v)[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def _detect_last_processed_date(team_ids):
    if not team_ids:
        return None
    env.cr.execute("""
        SELECT MAX(x_studio_date) FROM x_stock_balance_daily
        WHERE x_studio_team_id = ANY(%s)
    """, (list(team_ids),))
    row = env.cr.fetchone()
    return row[0] if row and row[0] else None


def _resolve_mode(ctx, today, team_ids):
    floor = datetime.date(*BACKFILL_FLOOR_DEFAULT)
    mode = (ctx.get('mode') or 'incremental').lower()

    if mode == 'backfill':
        d_from = _parse_iso_date(ctx.get('date_from')) or floor
        ctx_d_to = _parse_iso_date(ctx.get('date_to'))
        if ctx_d_to is not None and ctx_d_to != today:
            _log_warn('STOCKOUT %s: date_to=%s ignorado (forzado a today=%s). '
                      'El ancla del roll backward es stock.quant actual.',
                      VERSION_ID, ctx_d_to, today)
        d_to = today
        if d_from < floor:
            d_from = floor
        if d_from > d_to:
            d_from = d_to
        return ('backfill', d_from, d_to, None)

    last = _detect_last_processed_date(team_ids)
    if last is None:
        _log_warn('STOCKOUT %s: incremental sin datos previos; degradando a backfill desde %s',
                  VERSION_ID, floor)
        return ('backfill', floor, today, None)

    tail = int(ctx.get('tail_window_days', TAIL_WINDOW_DAYS_DEFAULT))
    if tail < 1:
        tail = 1
    d_from = last - datetime.timedelta(days=tail - 1)
    if d_from < floor:
        d_from = floor
    gap_days = (today - last).days
    if gap_days > tail * 2:
        _log_warn('STOCKOUT %s: last_processed=%s lleva %s dias sin actualizar (tail=%s). '
                  'Posible cron caido. Considera backfill manual.',
                  VERSION_ID, last, gap_days, tail)
    return ('incremental', d_from, today, tail)


TEAM_IDS = _to_int_list(CTX.get('team_ids')) or list(FILTERED_TEAM_IDS_DEFAULT)
ACTIVE_WINDOW_DAYS = int(CTX.get('active_window_days', ACTIVE_WINDOW_DAYS_DEFAULT))
if ACTIVE_WINDOW_DAYS < 1:
    ACTIVE_WINDOW_DAYS = 1

env.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    _log_warn('STOCKOUT %s: lock %s ocupado, abortando', VERSION_ID, LOCK_KEY)
    result = {'aborted': True, 'reason': 'lock_busy'}
else:
    if WIPE_ALL_AT_START:
        env.cr.execute('DELETE FROM x_stock_balance_daily')
        _log_warn('STOCKOUT %s: WIPE_ALL_AT_START=True -> borradas %s filas',
                  VERSION_ID, env.cr.rowcount)

    env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
    date_today = env.cr.fetchone()[0]

    # 1) Teams -> warehouses
    team_to_warehouses = {}
    warehouse_to_team  = {}
    for tid in TEAM_IDS:
        wid = TEAM_WAREHOUSE_MAP_DEFAULT.get(tid)
        if not wid:
            continue
        team_to_warehouses.setdefault(tid, set()).add(wid)
        warehouse_to_team.setdefault(wid, tid)

    if not team_to_warehouses:
        result = {'aborted': True, 'reason': 'no_warehouse_for_teams', 'teams': TEAM_IDS}
    else:
        warehouse_ids = list({w for ws in team_to_warehouses.values() for w in ws})

        mode, date_from, date_to, tail_window = _resolve_mode(
            CTX, date_today, list(team_to_warehouses.keys()))
        env.cr.execute("SELECT substr(md5(clock_timestamp()::text || random()::text), 1, 12)")
        run_id = env.cr.fetchone()[0]
        _log_info('STOCKOUT %s: mode=%s rango=[%s..%s] tail=%s N_activo=%s run_id=%s teams=%s',
                  VERSION_ID, mode, date_from, date_to, tail_window, ACTIVE_WINDOW_DAYS,
                  run_id, sorted(team_to_warehouses.keys()))

        # 2) Locations internas de cada warehouse
        StockLocation = env['stock.location'].sudo()
        Warehouse     = env['stock.warehouse'].sudo()
        warehouses    = Warehouse.browse(warehouse_ids)

        location_to_warehouse = {}
        for wh in warehouses:
            if not wh.lot_stock_id:
                continue
            child_locs = StockLocation.search([
                ('id', 'child_of', wh.lot_stock_id.id),
                ('usage', '=', 'internal'),
            ])
            for cl in child_locs:
                location_to_warehouse[cl.id] = wh.id

        internal_location_ids = list(location_to_warehouse.keys())

        if not internal_location_ids:
            result = {'aborted': True, 'reason': 'no_internal_locations'}
        else:
            # 3) Snapshot actual: stock.quant -> balance fin de hoy (ANCLA, verdad)
            env.cr.execute("""
                SELECT location_id, product_id, SUM(quantity) AS qty
                FROM stock_quant
                WHERE location_id = ANY(%s)
                GROUP BY location_id, product_id
            """, (internal_location_ids,))
            current_qty = {}
            for loc_id, pid, qty in env.cr.fetchall():
                wh = location_to_warehouse.get(loc_id)
                if wh:
                    key = (wh, int(pid))
                    current_qty[key] = current_qty.get(key, 0.0) + float(qty or 0.0)

            # 4) Movimientos en ventana [date_from .. date_to]
            date_to_inclusive_end = date_to + datetime.timedelta(days=1)
            env.cr.execute("""
                SELECT location_id, location_dest_id, product_id,
                       (date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS move_date,
                       SUM(product_qty) AS qty
                FROM stock_move
                WHERE state = 'done'
                  AND date >= %(date_from)s
                  AND date <  %(date_to)s
                  AND (location_id = ANY(%(locs)s) OR location_dest_id = ANY(%(locs)s))
                GROUP BY location_id, location_dest_id, product_id, move_date
            """, {'tz': TZ_NAME, 'date_from': date_from,
                  'date_to': date_to_inclusive_end, 'locs': internal_location_ids})

            movements = {}   # (wh, pid, date) -> {'in','out'}
            orphan_moves_count = 0
            for loc_id, dest_id, pid, mv_date, qty in env.cr.fetchall():
                qty = float(qty or 0.0)
                pid = int(pid)
                src_wh = location_to_warehouse.get(loc_id)
                dst_wh = location_to_warehouse.get(dest_id)
                if src_wh is None and dst_wh is None:
                    orphan_moves_count += 1
                    continue
                if src_wh is not None and dst_wh != src_wh:
                    key = (src_wh, pid, mv_date)
                    rec = movements.get(key)
                    if rec is None:
                        movements[key] = {'in': 0.0, 'out': qty}
                    else:
                        rec['out'] += qty
                if dst_wh is not None and dst_wh != src_wh:
                    key = (dst_wh, pid, mv_date)
                    rec = movements.get(key)
                    if rec is None:
                        movements[key] = {'in': qty, 'out': 0.0}
                    else:
                        rec['in'] += qty

            # 4b) Fechas de VENTA (out-move) en ventana extendida [date_from - N .. date_to]
            #     para el gate de surtido activo. sale_days[(wh,pid)] = sorted dates.
            active_from = date_from - datetime.timedelta(days=ACTIVE_WINDOW_DAYS)
            env.cr.execute("""
                SELECT location_id, location_dest_id, product_id,
                       (date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS move_date
                FROM stock_move
                WHERE state = 'done'
                  AND date >= %(afrom)s
                  AND date <  %(ato)s
                  AND location_id = ANY(%(locs)s)
                GROUP BY location_id, location_dest_id, product_id, move_date
            """, {'tz': TZ_NAME, 'afrom': active_from,
                  'ato': date_to_inclusive_end, 'locs': internal_location_ids})
            sale_days_set = {}   # (wh,pid) -> set(date)
            for loc_id, dest_id, pid, mv_date in env.cr.fetchall():
                src_wh = location_to_warehouse.get(loc_id)
                dst_wh = location_to_warehouse.get(dest_id)
                if src_wh is not None and dst_wh != src_wh:
                    sale_days_set.setdefault((src_wh, int(pid)), set()).add(mv_date)

            # 5) Productos vendibles (active, sale_ok, type=product)
            env.cr.execute("""
                SELECT pp.id
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE pp.active = TRUE AND pt.active = TRUE
                  AND pt.sale_ok = TRUE AND pt.type = 'product'
            """)
            sellable_pids = {row[0] for row in env.cr.fetchall()}

            relevant = set()
            for (wh, pid) in current_qty.keys():
                if pid in sellable_pids:
                    relevant.add((wh, pid))
            for (wh, pid, _) in movements.keys():
                if pid in sellable_pids:
                    relevant.add((wh, pid))

            # 5b) Lookups categoria / proveedor / abcxyz
            relevant_pids = list({pid for (_, pid) in relevant})
            product_categ = {}
            product_supplier = {}
            product_abcxyz = {}
            if relevant_pids:
                env.cr.execute("""
                    SELECT pp.id, pt.categ_id FROM product_product pp
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE pp.id = ANY(%s)
                """, (relevant_pids,))
                for pid, categ_id in env.cr.fetchall():
                    if categ_id:
                        product_categ[int(pid)] = int(categ_id)
                env.cr.execute("""
                    SELECT DISTINCT ON (pp.id) pp.id, psi.partner_id
                    FROM product_product pp
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    JOIN product_supplierinfo psi ON psi.product_tmpl_id = pt.id
                    WHERE pp.id = ANY(%s) AND psi.partner_id IS NOT NULL
                    ORDER BY pp.id, psi.sequence ASC NULLS LAST, psi.id ASC
                """, (relevant_pids,))
                for pid, partner_id in env.cr.fetchall():
                    if partner_id:
                        product_supplier[int(pid)] = int(partner_id)
                try:
                    AbcModel = env['x_calculo_abc_xyz'].sudo()
                    abc_fields = AbcModel._fields or {}
                    if 'x_studio_product_id' in abc_fields and 'x_studio_abcxyz' in abc_fields:
                        domain = [('x_studio_product_id', 'in', relevant_pids)]
                        if 'x_studio_company_id' in abc_fields:
                            domain.append(('x_studio_company_id', '=', env.company.id))
                        if 'x_active' in abc_fields:
                            domain.append(('x_active', '=', True))
                        for r in AbcModel.search_read(domain, ['x_studio_product_id', 'x_studio_abcxyz']):
                            pid_t = r.get('x_studio_product_id')
                            pid_i = pid_t[0] if pid_t else None
                            abc_v = r.get('x_studio_abcxyz') or ''
                            if pid_i and abc_v:
                                product_abcxyz[int(pid_i)] = str(abc_v)
                except Exception:
                    pass

            # Dias en orden ascendente
            days = []
            d = date_from
            while d <= date_to:
                days.append(d)
                d += datetime.timedelta(days=1)
            n_days = len(days)

            # 6) Roll backward + deteccion por evidencia
            target = env[TARGET_MODEL].sudo()
            target_fields = target._fields or {}
            has_run_id = 'x_studio_run_id' in target_fields
            has_mode   = 'x_studio_mode'   in target_fields

            env.cr.execute("""
                DELETE FROM x_stock_balance_daily
                WHERE x_studio_team_id = ANY(%(teams)s)
                  AND x_studio_date BETWEEN %(d_from)s AND %(d_to)s
            """, {'teams': list(team_to_warehouses.keys()),
                  'd_from': date_from, 'd_to': date_to})
            purge_count = env.cr.rowcount

            create_call = target.with_context(
                tracking_disable=True, mail_create_nosubscribe=True,
                mail_create_nolog=True, mail_notrack=True).create

            now_dt = datetime.datetime.now()
            batch = []
            total_created = 0
            stockout_full = 0
            stockout_partial = 0
            drift_days = 0          # dias candidatos no marcados por no-confiables (drift)
            cut_inactive = 0        # dias candidatos no marcados por inactivo
            rescued_by_sale = 0     # dias con end<=0 PERO vendio -> no quiebre (caso 44,6% viejo)
            stockout_by_abcxyz = {}
            stockout_by_supplier = {}

            for (wh_id, pid) in relevant:
                team_id = warehouse_to_team.get(wh_id)
                if not team_id:
                    continue

                balance_end = current_qty.get((wh_id, pid), 0.0)
                balance_end_arr = [0.0] * n_days
                balance_end_arr[n_days - 1] = balance_end

                for i in range(n_days - 1, 0, -1):
                    mv = movements.get((wh_id, pid, days[i]))
                    qin  = mv['in']  if mv else 0.0
                    qout = mv['out'] if mv else 0.0
                    balance_end_arr[i - 1] = balance_end_arr[i] - qin + qout

                # reliable: tramo reciente hasta el primer dia (hacia atras) con balance<0
                reliable = [True] * n_days
                hit = False
                for i in range(n_days - 1, -1, -1):
                    if balance_end_arr[i] < -EPS:
                        hit = True
                    if hit:
                        reliable[i] = False

                # surtido activo por dia (two-pointer sobre fechas de venta)
                sd = sorted(sale_days_set.get((wh_id, pid), ()))
                ptr = 0
                last_sale = None

                for i in range(n_days):
                    d_i = days[i]
                    mv = movements.get((wh_id, pid, d_i))
                    qin  = mv['in']  if mv else 0.0
                    qout = mv['out'] if mv else 0.0
                    end_raw   = balance_end_arr[i]
                    start_raw = balance_end_arr[i - 1] if i > 0 else (end_raw - qin + qout)

                    while ptr < len(sd) and sd[ptr] <= d_i:
                        last_sale = sd[ptr]
                        ptr += 1
                    activo = last_sale is not None and (d_i - last_sale).days <= ACTIVE_WINDOW_DAYS

                    disponible = end_raw > EPS or qout > EPS

                    is_partial = start_raw > EPS and end_raw <= EPS and qout > EPS
                    is_full = (reliable[i] and (not disponible)
                               and start_raw <= EPS and end_raw <= EPS and activo)
                    is_stockout = is_partial or is_full

                    # telemetria (sobre dias que el metodo viejo habria marcado: end<=0)
                    if end_raw <= EPS and not is_stockout:
                        if qout > EPS:
                            rescued_by_sale += 1          # vendio ese dia (no es quiebre)
                        elif not reliable[i]:
                            drift_days += 1               # tramo no confiable (drift)
                        elif not activo:
                            cut_inactive += 1             # inactivo / deslistado

                    if not is_stockout:
                        # skip filas sin quiebre (no se persisten)
                        continue

                    if is_full:
                        stockout_full += 1
                    if is_partial:
                        stockout_partial += 1
                    _abc = product_abcxyz.get(pid) or '(sin abcxyz)'
                    stockout_by_abcxyz[_abc] = stockout_by_abcxyz.get(_abc, 0) + 1
                    _sup = product_supplier.get(pid)
                    if _sup:
                        stockout_by_supplier[_sup] = stockout_by_supplier.get(_sup, 0) + 1

                    # balance reportado pisado en 0 (on-hand fisico nunca < 0)
                    bal_end_rep   = end_raw   if end_raw   > 0 else 0.0
                    bal_start_rep = start_raw if start_raw > 0 else 0.0

                    vals = {
                        'x_name':                    'T%s/W%s/P%s/%s' % (team_id, wh_id, pid, d_i),
                        'x_studio_team_id':          team_id,
                        'x_studio_warehouse_id':     wh_id,
                        'x_studio_product_id':       pid,
                        'x_studio_categ_id':         product_categ.get(pid) or False,
                        'x_studio_supplier_id':      product_supplier.get(pid) or False,
                        'x_studio_abcxyz':           product_abcxyz.get(pid) or '',
                        'x_studio_date':             d_i,
                        'x_studio_qty_balance':      bal_end_rep,
                        'x_studio_qty_start':        bal_start_rep,
                        'x_studio_qty_in':           qin,
                        'x_studio_qty_out':          qout,
                        'x_studio_stockout':         True,
                        'x_studio_stockout_partial': is_partial,
                        'x_studio_run_version':      VERSION_ID,
                        'x_studio_run_at':           now_dt,
                    }
                    if has_run_id:
                        vals['x_studio_run_id'] = run_id
                    if has_mode:
                        vals['x_studio_mode'] = mode
                    batch.append(vals)

                    if len(batch) >= BATCH_SIZE:
                        create_call(batch)
                        total_created += len(batch)
                        batch = []

            if batch:
                create_call(batch)
                total_created += len(batch)

            top_abcxyz = sorted(stockout_by_abcxyz.items(), key=lambda x: -x[1])[:10]
            top_supplier = sorted(stockout_by_supplier.items(), key=lambda x: -x[1])[:10]

            result = {
                'version': VERSION_ID, 'mode': mode, 'run_id': run_id,
                'date_from': str(date_from), 'date_to': str(date_to),
                'date_today': str(date_today), 'tail_window_days': tail_window,
                'active_window_days': ACTIVE_WINDOW_DAYS,
                'teams': len(team_to_warehouses), 'warehouses': len(warehouse_ids),
                'products_unique': len({p for (_, p) in relevant}),
                'wh_product_pairs': len(relevant),
                'records_purged': purge_count, 'records_created': total_created,
                'stockout_days_full': stockout_full,
                'stockout_days_partial': stockout_partial,
                'drift_days_skipped': drift_days,
                'cut_inactive_days': cut_inactive,
                'rescued_by_sale_days': rescued_by_sale,
                'stockout_by_abcxyz': dict(top_abcxyz),
                'stockout_top_suppliers': top_supplier,
                'orphan_moves_count': orphan_moves_count,
            }
            _log_info('STOCKOUT %s OK: %s', VERSION_ID, result)
