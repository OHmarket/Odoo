# ============================================================
# Stock Balance Daily - Reconstruccion diaria de stock por SKU/sala
# ============================================================
#
# Version activa: v2.0 (ver CHANGELOG.md para historial completo)
#
# Objetivo:
#   - Reconstruir balance diario de stock por (team, warehouse, producto)
#     para detectar quiebres reales (stockouts) y separar "error de modelo"
#     de "no habia stock" en el backtest.
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Estrategia: snapshot actual (stock.quant) + roll backward sobre
#     stock.move completados:
#       balance[D] = balance[D+1] - qty_in_(D+1) + qty_out_(D+1)
#   - Modo dual:
#       - mode="backfill"    -> rango [date_from, date_to] explicito.
#       - mode="incremental" -> tail_window_days (default 7) + hoy.
#         No toca dias anteriores. Lo corre el cron diario.
#   - Anchor: stock.quant de HOY. Aceptacion explicita: balance
#     reconstruido es inferencia matematica desde quant actual, NO un
#     snapshot real de ese momento.
#   - Backdating > tail_window_days NO se captura en incremental.
#     Mitigacion: backfill manual o cron semanal con tail=30.
#   - Modelo destino: x_stock_balance_daily (Studio).
#     Indice recomendado: (team_id, warehouse_id, product_id, date).
#   - Stockout: balance <= 0. Stockout partial: start > 0 AND end <= 0.
#
# Detalles, fixes historicos y esquema completo: ver CHANGELOG.md.
# ============================================================

VERSION_ID = "STOCKOUT_v2_0"

TARGET_MODEL = "x_stock_balance_daily"

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009440
BATCH_SIZE = 1000

# Parametros default (overridable via context)
TAIL_WINDOW_DAYS_DEFAULT  = 7                 # cola de re-calculo en modo incremental
BACKFILL_FLOOR_DEFAULT    = (2025, 1, 1)      # piso historico, no retrocede mas atras
FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

# Toggle: borrado total de x_stock_balance_daily al inicio de cada corrida.
# Mantenerlo en False en operacion normal -> el delete-range del rango efectivo
# (ultimos 7 dias en incremental) es suficiente. Activar a True solo si hay
# que rehacer el historico completo despues de un cambio de diseno.
WIPE_ALL_AT_START = False

# Mapeo team -> warehouse. Hardcoded igual que en OH Analisis de Stock
# (TEAM_WAREHOUSE_MAP_FALLBACK). Razon: pos.config.warehouse_id en este Odoo
# esta mal poblado (los 28 POS apuntan al mismo WH=1 central). El warehouse
# real vive en pos.config.picking_type_id.warehouse_id, pero usar este MAP
# hardcoded es mas robusto que depender de la configuracion de Odoo.
TEAM_WAREHOUSE_MAP_DEFAULT = {
    5:  1,    # Panguipulli 790  -> PA790
    6:  4,    # Los Lagos        -> LL200
    7:  2,    # Futrono          -> FU120
    8:  3,    # Panguipulli 645  -> PA645
    9:  16,   # Panguipulli 763  -> PA763
    10: 8,    # Lautaro          -> LA812
    11: 5,    # San Jose         -> SJ121
    12: 9,    # Paillaco         -> PA706
    13: 10,   # Mehuin Express   -> MEHEX
    16: 12,   # Conaripe         -> CO899
    17: 14,   # Nueva Imperial   -> IM495
    18: 13,   # Malalhue         -> ML402
}


# Nota: safe_eval de Odoo Server Actions prohibe `import`, declarar `class`,
# y otros opcodes. `datetime` ya viene disponible como modulo en el scope.
# `uuid` NO esta disponible: el run_id se genera via SQL (md5 + clock_timestamp).
#
# En Odoo 17, `log` es una funcion (no un logger): log(msg, level='info').
# Wrappers con %s-format para mantener llamadas legibles tipo log.info/warning.


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
    """Acepta date, datetime, 'YYYY-MM-DD' (o vacio). Retorna date|None."""
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
    """Ultima fecha con datos en x_stock_balance_daily para los teams dados."""
    if not team_ids:
        return None
    env.cr.execute("""
        SELECT MAX(x_studio_date) FROM x_stock_balance_daily
        WHERE x_studio_team_id = ANY(%s)
    """, (list(team_ids),))
    row = env.cr.fetchone()
    return row[0] if row and row[0] else None


def _resolve_mode(ctx, today, team_ids):
    """Retorna (mode, effective_d_from, effective_d_to, tail_window).

    - mode='backfill': rango explicito; tail_window=None.
    - mode='incremental': rango = [last_processed - (tail-1), today].
      Si no hay datos previos, degrada a backfill desde BACKFILL_FLOOR_DEFAULT.

    Aplica clamp con BACKFILL_FLOOR_DEFAULT como piso historico.
    """
    floor = datetime.date(*BACKFILL_FLOOR_DEFAULT)
    mode = (ctx.get('mode') or 'incremental').lower()

    if mode == 'backfill':
        d_from = _parse_iso_date(ctx.get('date_from')) or floor
        # date_to siempre = today: el roll backward ancla en stock.quant ACTUAL,
        # asi que el rango efectivo debe terminar en hoy. Si CTX pasa otro valor,
        # lo ignoramos con warning (no rompemos por compat, pero alertamos).
        ctx_d_to = _parse_iso_date(ctx.get('date_to'))
        if ctx_d_to is not None and ctx_d_to != today:
            _log_warn(
                'STOCKOUT %s: date_to=%s ignorado (forzado a today=%s). '
                'El ancla del roll backward es stock.quant actual, no historico.',
                VERSION_ID, ctx_d_to, today)
        d_to = today
        if d_from < floor:
            d_from = floor
        if d_from > d_to:
            d_from = d_to
        return ('backfill', d_from, d_to, None)

    # incremental
    last = _detect_last_processed_date(team_ids)
    if last is None:
        _log_warn(
            'STOCKOUT %s: incremental sin datos previos; degradando a backfill desde %s',
            VERSION_ID, floor)
        return ('backfill', floor, today, None)

    tail = int(ctx.get('tail_window_days', TAIL_WINDOW_DAYS_DEFAULT))
    if tail < 1:
        tail = 1
    d_from = last - datetime.timedelta(days=tail - 1)
    if d_from < floor:
        d_from = floor
    # Warning si el gap entre last y today es muy grande (cron parado, set de teams cambio, etc.)
    gap_days = (today - last).days
    if gap_days > tail * 2:
        _log_warn(
            'STOCKOUT %s: last_processed=%s lleva %s dias sin actualizar (tail=%s). '
            'Posible cron caido o cambio de FILTERED_TEAM_IDS. Considera correr backfill manual.',
            VERSION_ID, last, gap_days, tail)
    return ('incremental', d_from, today, tail)


TEAM_IDS = _to_int_list(CTX.get('team_ids')) or list(FILTERED_TEAM_IDS_DEFAULT)

# Legacy: aceptados por compat con cron antiguo pero NO usados en v2.0
if 'hard_reset' in CTX:
    _log_warn(
        'STOCKOUT %s: hard_reset es legacy en v2.0; el delete-range ahora opera '
        'solo sobre el rango efectivo. Parametro ignorado.', VERSION_ID)
if 'history_weeks' in CTX:
    _log_warn(
        'STOCKOUT %s: history_weeks es legacy en v2.0; usa mode=backfill con '
        'date_from/date_to, o mode=incremental con tail_window_days.', VERSION_ID)


# Lock para evitar corridas concurrentes
env.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    _log_warn('STOCKOUT %s: lock %s ocupado, abortando', VERSION_ID, LOCK_KEY)
    result = {'aborted': True, 'reason': 'lock_busy'}
else:
    # Wipe TEMPORAL: borrado total de la tabla. Ver WIPE_ALL_AT_START arriba.
    if WIPE_ALL_AT_START:
        env.cr.execute('DELETE FROM x_stock_balance_daily')
        _wiped = env.cr.rowcount
        _log_warn(
            'STOCKOUT %s: WIPE_ALL_AT_START=True -> borradas %s filas (toggle temporal)',
            VERSION_ID, _wiped)

    # Rango temporal en la zona horaria del negocio
    env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
    date_today = env.cr.fetchone()[0]
    # date_from / date_to se resuelven mas abajo via _resolve_mode una vez que
    # tenemos team_to_warehouses (necesario para _detect_last_processed_date).

    # =========================================================
    # 1) Mapear teams -> warehouses via TEAM_WAREHOUSE_MAP_DEFAULT
    #
    # Hardcoded a proposito (ver constante arriba). No leemos de
    # pos.config porque ese dato esta mal poblado en este Odoo.
    # =========================================================
    team_to_warehouses = {}    # team_id -> set(warehouse_id)
    warehouse_to_team  = {}    # warehouse_id -> team_id (primer match)
    for tid in TEAM_IDS:
        wid = TEAM_WAREHOUSE_MAP_DEFAULT.get(tid)
        if not wid:
            continue
        team_to_warehouses.setdefault(tid, set()).add(wid)
        warehouse_to_team.setdefault(wid, tid)

    if not team_to_warehouses:
        result = {'aborted': True, 'reason': 'no_pos_config_for_teams', 'teams': TEAM_IDS}
    else:
        warehouse_ids = list({w for ws in team_to_warehouses.values() for w in ws})

        # =========================================================
        # 1b) Resolver modo (backfill | incremental) y rango efectivo
        # =========================================================
        mode, date_from, date_to, tail_window = _resolve_mode(
            CTX, date_today, list(team_to_warehouses.keys()))
        # safe_eval no permite `import uuid`; generamos run_id en PostgreSQL.
        env.cr.execute(
            "SELECT substr(md5(clock_timestamp()::text || random()::text), 1, 12)")
        run_id = env.cr.fetchone()[0]
        _log_info(
            'STOCKOUT %s: mode=%s rango=[%s..%s] tail=%s run_id=%s teams=%s',
            VERSION_ID, mode, date_from, date_to, tail_window, run_id,
            sorted(team_to_warehouses.keys()))

        # =========================================================
        # 2) Obtener locations internas de cada warehouse
        #    (incluye lot_stock_id y todos sus child con usage='internal')
        # =========================================================
        StockLocation = env['stock.location'].sudo()
        Warehouse     = env['stock.warehouse'].sudo()
        warehouses    = Warehouse.browse(warehouse_ids)

        location_to_warehouse = {}    # location_id -> warehouse_id
        warehouse_locations   = {}    # warehouse_id -> [location_ids]
        for wh in warehouses:
            if not wh.lot_stock_id:
                continue
            child_locs = StockLocation.search([
                ('id', 'child_of', wh.lot_stock_id.id),
                ('usage', '=', 'internal'),
            ])
            for cl in child_locs:
                location_to_warehouse[cl.id] = wh.id
                warehouse_locations.setdefault(wh.id, []).append(cl.id)

        internal_location_ids = list(location_to_warehouse.keys())

        if not internal_location_ids:
            result = {'aborted': True, 'reason': 'no_internal_locations'}
        else:
            # =========================================================
            # 3) Snapshot actual: stock.quant -> balance al final de hoy
            # =========================================================
            env.cr.execute("""
                SELECT location_id, product_id, SUM(quantity) AS qty
                FROM stock_quant
                WHERE location_id = ANY(%s)
                GROUP BY location_id, product_id
            """, (internal_location_ids,))

            current_qty = {}    # (warehouse_id, product_id) -> qty fin de hoy
            for loc_id, pid, qty in env.cr.fetchall():
                wh = location_to_warehouse.get(loc_id)
                if wh:
                    key = (wh, int(pid))
                    current_qty[key] = current_qty.get(key, 0.0) + float(qty or 0.0)

            # =========================================================
            # 4) Movimientos en la ventana efectiva: agrupar por (loc_src, loc_dst, product, date)
            # =========================================================
            date_to_inclusive_end = date_to + datetime.timedelta(days=1)

            env.cr.execute("""
                SELECT
                    location_id,
                    location_dest_id,
                    product_id,
                    (date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS move_date,
                    SUM(product_qty) AS qty
                FROM stock_move
                WHERE state = 'done'
                  AND date >= %(date_from)s
                  AND date <  %(date_to)s
                  AND (location_id = ANY(%(locs)s) OR location_dest_id = ANY(%(locs)s))
                GROUP BY location_id, location_dest_id, product_id, move_date
            """, {
                'tz': TZ_NAME,
                'date_from': date_from,
                'date_to': date_to_inclusive_end,
                'locs': internal_location_ids,
            })

            # movements[(warehouse_id, product_id, date)] = {'in': float, 'out': float}
            # Movimientos "internos" (entre dos locations del MISMO warehouse) se ignoran:
            # no afectan el balance del warehouse en agregado.
            movements = {}

            # v2.0 - telemetria de movimientos huerfanos: si ambos extremos
            # (origen y destino) caen fuera del mapeo location_to_warehouse,
            # el movimiento se ignora silenciosamente (la query ya filtra que
            # AL MENOS UNO de los dos sea internal a algun WH del set). Si
            # esto ocurre es porque la query devolvio una location interna a
            # un WH que nosotros NO mapeamos (caso raro: location con usage
            # alterado a 'transit', o nueva ubicacion bajo lot_stock_id que
            # no es 'internal'). Contamos y muestreamos para que el operador
            # investigue manualmente; NO auto-mapeamos.
            orphan_moves_count = 0
            orphan_sample      = []

            for loc_id, dest_id, pid, mv_date, qty in env.cr.fetchall():
                qty = float(qty or 0.0)
                pid = int(pid)
                src_wh = location_to_warehouse.get(loc_id)
                dst_wh = location_to_warehouse.get(dest_id)

                if src_wh is None and dst_wh is None:
                    orphan_moves_count += 1
                    if len(orphan_sample) < 20:
                        orphan_sample.append({
                            'loc_src': int(loc_id) if loc_id else None,
                            'loc_dst': int(dest_id) if dest_id else None,
                            'product_id': pid,
                            'date': str(mv_date),
                            'qty': qty,
                        })
                    continue

                # Salida: origen es interno al warehouse, destino fuera del warehouse
                if src_wh is not None and dst_wh != src_wh:
                    key = (src_wh, pid, mv_date)
                    rec = movements.get(key)
                    if rec is None:
                        movements[key] = {'in': 0.0, 'out': qty}
                    else:
                        rec['out'] += qty

                # Entrada: destino es interno al warehouse, origen fuera del warehouse
                if dst_wh is not None and dst_wh != src_wh:
                    key = (dst_wh, pid, mv_date)
                    rec = movements.get(key)
                    if rec is None:
                        movements[key] = {'in': qty, 'out': 0.0}
                    else:
                        rec['in'] += qty

            if orphan_moves_count:
                _log_warn(
                    'STOCKOUT %s: %s movimientos huerfanos detectados en ventana '
                    '(origen y destino ambos fuera del mapeo). Muestra: %s',
                    VERSION_ID, orphan_moves_count, orphan_sample[:5])

            # =========================================================
            # 5) Productos relevantes: con stock actual o movimiento en ventana
            #    Pre-filtro: solo productos vendibles (active, sale_ok, type=product).
            #    Excluye archivados, insumos internos, consumibles, servicios.
            #    Razon: un quiebre de un insumo no genera decision comercial,
            #    es ruido en los reportes.
            # =========================================================
            env.cr.execute("""
                SELECT pp.id
                FROM product_product pp
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE pp.active = TRUE
                  AND pt.active = TRUE
                  AND pt.sale_ok = TRUE
                  AND pt.type = 'product'
            """)
            sellable_pids = {row[0] for row in env.cr.fetchall()}

            relevant = set()
            for (wh, pid) in current_qty.keys():
                if pid in sellable_pids:
                    relevant.add((wh, pid))
            for (wh, pid, _) in movements.keys():
                if pid in sellable_pids:
                    relevant.add((wh, pid))

            # =========================================================
            # 5b) Lookup batch de categoria + proveedor + ABCXYZ por producto
            # =========================================================
            relevant_pids = list({pid for (_, pid) in relevant})

            product_categ    = {}   # pid -> categ_id
            product_supplier = {}   # pid -> partner_id (proveedor principal)
            product_abcxyz   = {}   # pid -> "AX" / "BY" / etc. (desde x_calculo_abc_xyz)

            if relevant_pids:
                # Categoria via product.product -> product.template -> product.category
                env.cr.execute("""
                    SELECT pp.id, pt.categ_id
                    FROM product_product pp
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE pp.id = ANY(%s)
                """, (relevant_pids,))
                for pid, categ_id in env.cr.fetchall():
                    if categ_id:
                        product_categ[int(pid)] = int(categ_id)

                # Proveedor principal: el de menor sequence en product.supplierinfo
                # vinculado al template del producto. DISTINCT ON garantiza 1 por template.
                env.cr.execute("""
                    SELECT DISTINCT ON (pp.id) pp.id, psi.partner_id
                    FROM product_product pp
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    JOIN product_supplierinfo psi ON psi.product_tmpl_id = pt.id
                    WHERE pp.id = ANY(%s)
                      AND psi.partner_id IS NOT NULL
                    ORDER BY pp.id, psi.sequence ASC NULLS LAST, psi.id ASC
                """, (relevant_pids,))
                for pid, partner_id in env.cr.fetchall():
                    if partner_id:
                        product_supplier[int(pid)] = int(partner_id)

                # ABCXYZ desde x_calculo_abc_xyz (filtrado por compania actual)
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

            # Lista de dias en orden ascendente (date_from .. date_to inclusive).
            # date_to == date_today por diseno (ver _resolve_mode); por eso el
            # ancla del roll backward (current_qty) coincide con el ultimo dia.
            days = []
            d = date_from
            while d <= date_to:
                days.append(d)
                d += datetime.timedelta(days=1)
            n_days = len(days)

            # =========================================================
            # 6) Roll backward por (warehouse, producto):
            #    balance[D] = balance[D+1] - qty_in_(D+1) + qty_out_(D+1)
            # =========================================================
            #
            # Escribimos directamente al batch sin acumular todo en memoria
            # para evitar OOM con muchos productos y dias.
            target = env[TARGET_MODEL].sudo()
            target_fields = target._fields or {}
            has_run_id = 'x_studio_run_id' in target_fields
            has_mode   = 'x_studio_mode'   in target_fields

            # Delete-range del rango efectivo via SQL directo. Evita cargar
            # 100k+ filas al cache del ORM en backfills grandes (vs unlink()).
            # En incremental solo borra los ultimos tail dias; los anteriores
            # quedan intactos.
            env.cr.execute("""
                DELETE FROM x_stock_balance_daily
                WHERE x_studio_team_id = ANY(%(teams)s)
                  AND x_studio_date BETWEEN %(d_from)s AND %(d_to)s
            """, {
                'teams':  list(team_to_warehouses.keys()),
                'd_from': date_from,
                'd_to':   date_to,
            })
            purge_count = env.cr.rowcount

            create_call = target.with_context(
                tracking_disable=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notrack=True,
            ).create

            now_dt = datetime.datetime.now()
            batch = []
            total_created = 0
            stockout_full = 0
            stockout_partial = 0
            stockout_by_abcxyz   = {}    # 'AX' / 'BY' / ... -> count de dias en quiebre
            stockout_by_supplier = {}    # partner_id -> count de dias en quiebre

            for (wh_id, pid) in relevant:
                team_id = warehouse_to_team.get(wh_id)
                if not team_id:
                    continue

                # balance al final de date_today
                balance_end = current_qty.get((wh_id, pid), 0.0)

                # buffers de balance por dia (end-of-day) en orden ascendente
                # los iremos llenando en orden DESCENDENTE
                balance_end_arr = [0.0] * n_days
                balance_end_arr[n_days - 1] = balance_end

                # Roll backward
                for i in range(n_days - 1, 0, -1):
                    d_curr = days[i]
                    mv = movements.get((wh_id, pid, d_curr))
                    qty_in_curr  = mv['in']  if mv else 0.0
                    qty_out_curr = mv['out'] if mv else 0.0
                    # balance fin del dia anterior
                    balance_end_arr[i - 1] = balance_end_arr[i] - qty_in_curr + qty_out_curr

                # Generar registros
                for i in range(n_days):
                    d_i = days[i]
                    mv = movements.get((wh_id, pid, d_i))
                    qty_in_i  = mv['in']  if mv else 0.0
                    qty_out_i = mv['out'] if mv else 0.0
                    bal_end   = balance_end_arr[i]
                    bal_start = balance_end_arr[i - 1] if i > 0 else (bal_end - qty_in_i + qty_out_i)

                    # skip filas totalmente vacias (sin stock ni movimiento) para no inflar la tabla
                    if abs(bal_end) < 0.0001 and abs(bal_start) < 0.0001 and qty_in_i == 0.0 and qty_out_i == 0.0:
                        continue

                    is_full_stockout    = bal_end <= 0.0001 and bal_start <= 0.0001 and qty_in_i <= 0.0001
                    is_partial_stockout = bal_start > 0.0001 and bal_end <= 0.0001
                    is_stockout         = bal_end <= 0.0001

                    if is_full_stockout:
                        stockout_full += 1
                    if is_partial_stockout:
                        stockout_partial += 1
                    if is_stockout:
                        _abc = product_abcxyz.get(pid) or '(sin abcxyz)'
                        stockout_by_abcxyz[_abc] = stockout_by_abcxyz.get(_abc, 0) + 1
                        _sup = product_supplier.get(pid)
                        if _sup:
                            stockout_by_supplier[_sup] = stockout_by_supplier.get(_sup, 0) + 1

                    # Solo persistimos dias con quiebre (full o partial). Los
                    # contadores agregados ya quedaron actualizados arriba; el
                    # balance fuera de quiebre puede reconstruirse desde
                    # stock.move si se necesita.
                    if not is_stockout and not is_partial_stockout:
                        continue

                    # x_name es required por Studio (display name); lo generamos
                    # sintetico para que sea unico e identificable en vistas lista.
                    vals = {
                        'x_name':                    'T%s/W%s/P%s/%s' % (team_id, wh_id, pid, d_i),
                        'x_studio_team_id':          team_id,
                        'x_studio_warehouse_id':     wh_id,
                        'x_studio_product_id':       pid,
                        'x_studio_categ_id':         product_categ.get(pid) or False,
                        'x_studio_supplier_id':      product_supplier.get(pid) or False,
                        'x_studio_abcxyz':           product_abcxyz.get(pid) or '',
                        'x_studio_date':             d_i,
                        'x_studio_qty_balance':      bal_end,
                        'x_studio_qty_start':        bal_start,
                        'x_studio_qty_in':           qty_in_i,
                        'x_studio_qty_out':          qty_out_i,
                        'x_studio_stockout':         is_stockout,
                        'x_studio_stockout_partial': is_partial_stockout,
                        'x_studio_run_version':      VERSION_ID,
                        'x_studio_run_at':           now_dt,
                    }
                    # Campos opcionales v2.0: solo escribir si existen en Studio.
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

            # Top 10 ABCXYZ y top 10 proveedores con más quiebres
            top_abcxyz = sorted(stockout_by_abcxyz.items(), key=lambda x: -x[1])[:10]
            top_supplier = sorted(stockout_by_supplier.items(), key=lambda x: -x[1])[:10]

            result = {
                'version':                VERSION_ID,
                'mode':                   mode,
                'run_id':                 run_id,
                'date_from':              str(date_from),
                'date_to':                str(date_to),
                'date_today':             str(date_today),
                'tail_window_days':       tail_window,
                'teams':                  len(team_to_warehouses),
                'warehouses':             len(warehouse_ids),
                'products_unique':        len({p for (_, p) in relevant}),
                'wh_product_pairs':       len(relevant),
                'records_purged':         purge_count,
                'records_created':        total_created,
                'stockout_days_full':     stockout_full,
                'stockout_days_partial':  stockout_partial,
                'stockout_by_abcxyz':     dict(top_abcxyz),
                'stockout_top_suppliers': top_supplier,
                'orphan_moves_count':     orphan_moves_count,
                'orphan_sample':          orphan_sample[:5],
            }

            _log_info('STOCKOUT %s OK: %s', VERSION_ID, result)
