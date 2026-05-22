# Margen por Producto (POS + SO) — Margen SIN ILA de venta
# Versión:
# - sin L1/L2
# - fix moneda -> x_studio_currency_id
# - semáforo de plausibilidad de margen (cigarrillos vs resto)
# - llena categoría base, precio unitario y rentab_sobre_costo
# - SAFE_EVAL friendly
# - AJUSTE BRUTO 2026-04-07:
#   * POS: bruto = neto + IVA (sin ILA venta)
#   * SO: ILA venta parametrizable por contexto, default = none
#   * objetivo: evitar inflar bruto cuando la venta normal solo lleva IVA
MODEL = 'x_margen_por_producto_'
TZ_NAME = 'America/Santiago'
EPS = 1e-6

ILA_KEY = 'ila'
IVA_KEY = 'iva'
EXENTO_KEY = 'exento'

# --- Modo ILA venta ---
# Contexto opcional:
#   ila_sales_mode = 'none' | 'so' | 'all'
#     none -> no suma ILA venta a ningún canal (default recomendado hoy)
#     so   -> suma ILA venta solo a SO
#     all  -> suma ILA venta a POS + SO (comportamiento cercano al script anterior)
#
# Nota técnica:
# Con sale.report NO podemos distinguir con certeza "factura afecta a ILA" vs otro documento.
# Por eso el default queda en 'none'. Si después quieres exactitud documental,
# conviene rehacer la parte SO leyendo account.move / account.move.line.
ILA_SALES_MODE_DEFAULT = 'none'

# --- Semáforo ---
# Contexto opcional:
#   cigarette_category_ids = [id1, id2, ...]
# Default OH! Market: categoria 1628 = cigarros
CIGARETTE_CATEGORY_IDS_DEFAULT = (1628,)

MARGIN_NORMAL_GREEN_MIN = 0.20
MARGIN_NORMAL_GREEN_MAX = 0.45
MARGIN_NORMAL_YELLOW_MIN = 0.10
MARGIN_NORMAL_YELLOW_MAX = 0.60

MARGIN_CIG_GREEN_MIN = 0.02
MARGIN_CIG_GREEN_MAX = 0.08
MARGIN_CIG_YELLOW_MIN = 0.00
MARGIN_CIG_YELLOW_MAX = 0.12

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
        return out
    except Exception:
        try:
            return [int(val)]
        except Exception:
            return []

def _safe_float(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default

def _normalize_ila_sales_mode(v):
    try:
        s = (v or '').strip().lower()
    except Exception:
        s = ''
    if s in ('none', 'so', 'all'):
        return s
    return ILA_SALES_MODE_DEFAULT

def _flatten_taxes(taxes):
    flat = []
    for tx in (taxes or []):
        ch = []
        try:
            ch = list(tx.children_tax_ids or [])
        except Exception:
            ch = []
        if ch:
            for txx in ch:
                flat.append(txx)
        else:
            flat.append(tx)
    return flat

# ---------- Detectores de impuestos ----------
def _iva_compra_factor(prod):
    taxes = []
    try:
        taxes = list(prod.supplier_taxes_id or [])
    except Exception:
        taxes = []
    flat = _flatten_taxes(taxes)
    if not flat:
        return 0.0

    for tx in flat:
        name = (tx.name or '').lower()
        grp  = ((tx.tax_group_id and tx.tax_group_id.name) or '').lower()
        if (EXENTO_KEY in name) or (EXENTO_KEY in grp):
            return 0.0

    s = 0.0
    for tx in flat:
        name = (tx.name or '').lower()
        grp  = ((tx.tax_group_id and tx.tax_group_id.name) or '').lower()
        try:
            amt = float(tx.amount or 0.0)
        except Exception:
            amt = 0.0
        if (IVA_KEY in name) or (IVA_KEY in grp):
            s += amt / 100.0
    return s or 0.0

def _iva_venta_so_factor(prod):
    taxes = []
    try:
        taxes = list(prod.taxes_id or [])
    except Exception:
        taxes = []
    flat = _flatten_taxes(taxes)
    if not flat:
        return 0.0

    for tx in flat:
        name = (tx.name or '').lower()
        grp  = ((tx.tax_group_id and tx.tax_group_id.name) or '').lower()
        if (EXENTO_KEY in name) or (EXENTO_KEY in grp):
            return 0.0

    s = 0.0
    for tx in flat:
        name = (tx.name or '').lower()
        grp  = ((tx.tax_group_id and tx.tax_group_id.name) or '').lower()
        try:
            amt = float(tx.amount or 0.0)
        except Exception:
            amt = 0.0
        if (IVA_KEY in name) or (IVA_KEY in grp):
            s += amt / 100.0
    return s or 0.0

def _sum_ila_factor(prod):
    taxes = []
    try:
        taxes = list(prod.taxes_id or [])
    except Exception:
        taxes = []
    flat = _flatten_taxes(taxes)
    s = 0.0
    for tx in flat:
        name = (tx.name or '').lower()
        grp  = ((tx.tax_group_id and tx.tax_group_id.name) or '').lower()
        try:
            amt = float(tx.amount or 0.0)
        except Exception:
            amt = 0.0
        if (ILA_KEY in name) or (ILA_KEY in grp):
            s += amt / 100.0
    return s

def _classify_margin(margin_pct, is_cigarette, flag_raw_zero, flag_cost_fallback):
    if margin_pct is None:
        return ('gris', 'sin_margen_evaluable', False, 0.0, 0.0)

    if is_cigarette:
        exp_min = MARGIN_CIG_GREEN_MIN
        exp_max = MARGIN_CIG_GREEN_MAX

        if margin_pct < 0.0:
            sem = 'rojo'
            reason = 'cigarro_margen_negativo'
        elif (margin_pct >= MARGIN_CIG_GREEN_MIN) and (margin_pct <= MARGIN_CIG_GREEN_MAX):
            sem = 'verde'
            reason = 'ok_cigarro'
        elif (margin_pct >= MARGIN_CIG_YELLOW_MIN) and (margin_pct <= MARGIN_CIG_YELLOW_MAX):
            sem = 'amarillo'
            reason = 'cigarro_fuera_rango_objetivo'
        else:
            sem = 'rojo'
            reason = 'cigarro_margen_extremo'
    else:
        exp_min = MARGIN_NORMAL_GREEN_MIN
        exp_max = MARGIN_NORMAL_GREEN_MAX

        if margin_pct < 0.0:
            sem = 'rojo'
            reason = 'margen_negativo'
        elif (margin_pct >= MARGIN_NORMAL_GREEN_MIN) and (margin_pct <= MARGIN_NORMAL_GREEN_MAX):
            sem = 'verde'
            reason = 'ok'
        elif (margin_pct >= MARGIN_NORMAL_YELLOW_MIN and margin_pct < MARGIN_NORMAL_GREEN_MIN) or (margin_pct > MARGIN_NORMAL_GREEN_MAX and margin_pct <= MARGIN_NORMAL_YELLOW_MAX):
            sem = 'amarillo'
            reason = 'fuera_rango_objetivo'
        else:
            sem = 'rojo'
            reason = 'margen_extremo'

    if flag_raw_zero or flag_cost_fallback:
        if sem == 'verde':
            sem = 'amarillo'
        if flag_raw_zero and flag_cost_fallback:
            reason = reason + '|sin_raw_y_fallback_std'
        elif flag_raw_zero:
            reason = reason + '|sin_raw'
        elif flag_cost_fallback:
            reason = reason + '|fallback_std'

    return (sem, reason, is_cigarette, exp_min, exp_max)

# --- Fechas (desde contexto; por defecto MES en curso)
df = env.context.get('date_from')
dt = env.context.get('date_to')
dtex = env.context.get('date_to_exclusive')
if not df or not dt or not dtex:
    env.cr.execute("""
        SELECT
          date_trunc('month', CURRENT_DATE)::date                                 AS d1,
          (date_trunc('month', CURRENT_DATE) + interval '1 month - 1 day')::date AS d2,
          (date_trunc('month', CURRENT_DATE) + interval '1 month')::date         AS d3
    """)
    d1, d2, d3 = env.cr.fetchone()
    df   = str(d1)
    dt   = str(d2)
    dtex = str(d3)

# --- TZ
ctx = dict(env.context or {})
if not ctx.get('tz'):
    ctx['tz'] = TZ_NAME
local_tz = ctx.get('tz') or TZ_NAME

# --- Equipo (opcional)
TEAM_IDS = set(_to_int_list(env.context.get('team_ids')))

# --- Cigarrillos (opcional por contexto)
CIGARETTE_CATEGORY_IDS = set(_to_int_list(env.context.get('cigarette_category_ids')) or list(CIGARETTE_CATEGORY_IDS_DEFAULT))

# --- ILA venta (contexto)
ILA_SALES_MODE = _normalize_ila_sales_mode(env.context.get('ila_sales_mode'))

company  = env.company
currency = company.currency_id

Marg = env[MODEL].sudo()
mfields = Marg._fields or {}

HAS_CURRENCY_ID_FIELD   = True if mfields.get('x_studio_currency_id') else False
HAS_CAT_FIELD           = True if mfields.get('x_studio_categoria') else False
HAS_IVA_VENTA_FIELD     = True if mfields.get('x_studio_iva_venta') else False
HAS_ILA_VENTA_SO_FIELD  = True if mfields.get('x_studio_ila_venta_so') else False
HAS_PRECIO_NETO_UNIT    = True if mfields.get('x_studio_precio_neto_unit') else False
HAS_PRECIO_BRUTO_UNIT   = True if mfields.get('x_studio_precio_bruto_unit') else False
HAS_RENTAB_COSTO        = True if mfields.get('x_studio_rentab_sobre_costo') else False
HAS_SEM_FIELD           = True if mfields.get('x_studio_semaforo_margen') else False
HAS_SEM_REASON_FIELD    = True if mfields.get('x_studio_motivo_semaforo') else False
HAS_EXPECT_MIN_FIELD    = True if mfields.get('x_studio_margin_expected_min') else False
HAS_EXPECT_MAX_FIELD    = True if mfields.get('x_studio_margin_expected_max') else False
HAS_IS_CIG_FIELD        = True if mfields.get('x_studio_es_cigarro') else False

# --- Purga del período (por solapamiento)
purge_domain = [
    ('x_studio_compania','=', company.id),
    ('x_studio_fecha_desde','<=', dt),
    ('x_studio_fecha_hasta','>=', df),
]
old = Marg.search(purge_domain)
if old:
    i = 0
    while i < len(old):
        old[i:i+1000].unlink()
        i += 1000

# ========= POS (SQL agregado: product + team) =========
params_pos = {
    'company_id': company.id,
    'dfrom': df,
    'dto_ex': dtex,
    'tz': local_tz,
}

pc_fields = env['pos.config']._fields
_team_col = None
try:
    f = pc_fields.get('crm_team_id')
    if f:
        t = ''
        m = ''
        try:
            t = f.type or ''
        except Exception:
            t = ''
        try:
            m = f.comodel_name or ''
        except Exception:
            m = ''
        if (t == 'many2one') and (m == 'crm.team'):
            _team_col = 'pc.crm_team_id'
except Exception:
    _team_col = _team_col

if not _team_col:
    try:
        f = pc_fields.get('team_id')
        if f:
            t = ''
            m = ''
            try:
                t = f.type or ''
            except Exception:
                t = ''
            try:
                m = f.comodel_name or ''
            except Exception:
                m = ''
            if (t == 'many2one') and (m == 'crm.team'):
                _team_col = 'pc.team_id'
    except Exception:
        _team_col = _team_col

team_col_select = (_team_col or 'NULL') + ' AS team_id'
team_filter_sql = ""
if TEAM_IDS and _team_col:
    team_filter_sql = "AND {col} = ANY(%(team_ids)s)".format(col=_team_col)
    params_pos['team_ids'] = list(TEAM_IDS)

SQL_POS = """
    SELECT
        {team_col_select},
        pol.product_id                       AS product_id,
        SUM(pol.qty)                         AS qty,
        SUM(pol.price_subtotal)              AS net
    FROM pos_order_line pol
    JOIN pos_order   po ON po.id = pol.order_id
    LEFT JOIN pos_session ps ON ps.id = po.session_id
    LEFT JOIN pos_config  pc ON pc.id = ps.config_id
    WHERE po.company_id = %(company_id)s
      AND po.state IN ('paid','invoiced','done')
      AND ((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s) >= %(dfrom)s::date
      AND ((po.date_order AT TIME ZONE 'UTC') AT TIME ZONE %(tz)s) <  %(dto_ex)s::date
      AND pol.price_subtotal <> 0
      {team_filter}
    GROUP BY 1,2
""".format(team_col_select=team_col_select, team_filter=team_filter_sql)

env.cr.execute(SQL_POS, params_pos)
rows_pos = env.cr.fetchall()

pos_qty = {}
pos_net = {}
for team_id, prod_id, q, net in rows_pos:
    tid = int(team_id) if team_id not in (None, False) else False
    pid = int(prod_id) if prod_id else False
    if not pid:
        continue
    pos_qty[(tid, pid)] = float(q or 0.0)
    pos_net[(tid, pid)] = float(net or 0.0)

# ========= SO (sale.report) =========
so_qty = {}
so_net = {}

domain_so = [
    ('date','>=', df), ('date','<=', dt),
    ('state','in',['sale','done']),
    ('company_id','=', company.id),
    ('price_subtotal','!=', 0),
]
if TEAM_IDS:
    domain_so.append(('team_id','in', list(TEAM_IDS)))

rg_so = env['sale.report'].with_context(ctx).read_group(
    domain_so,
    ['product_uom_qty','price_subtotal'], ['team_id','product_id'], lazy=False
)
for row in rg_so:
    t = row.get('team_id')
    p = row.get('product_id')
    tid = t and (t[0] if isinstance(t, (list, tuple)) else t) or False
    pid = p and (p[0] if isinstance(p, (list, tuple)) else p) or False
    if not pid:
        continue
    q   = float(row.get('product_uom_qty', 0.0) or 0.0)
    net = float(row.get('price_subtotal', 0.0) or 0.0)
    key = (tid or False, pid)
    so_qty[key] = so_qty.get(key, 0.0) + q
    so_net[key] = so_net.get(key, 0.0) + net

# ========= Consolidación =========
keys_pos = set([k for k, v in pos_net.items() if abs(v) > EPS])
keys_so  = set([k for k, v in so_net.items() if abs(v) > EPS])
keys = keys_pos | keys_so

if not keys:
    action = {
        'type':'ir.actions.client','tag':'display_notification',
        'params': {'title':'Margen','message':'No hay ventas en el período (neto=0).',
                   'type':'warning','sticky': False}
    }
else:
    prod_ids = list(set([pid for (_, pid) in keys]))
    prods = {p.id: p for p in env['product.product'].with_context(prefetch_fields=False).sudo().browse(prod_ids)}

    meta_cache = {}
    cost_cache = {}

    def _ensure_meta(pid):
        if pid in meta_cache:
            return meta_cache[pid]

        p = prods.get(pid)
        categ_id = False
        categ_name = ''
        full_name = ''
        default_code = ''
        is_cigarette = False

        if p:
            try:
                full_name = p.display_name or p.name or ''
            except Exception:
                full_name = ''
            try:
                default_code = p.default_code or ''
            except Exception:
                default_code = ''

            try:
                tmpl = p.product_tmpl_id
            except Exception:
                tmpl = False

            try:
                categ = tmpl and tmpl.categ_id or False
            except Exception:
                categ = False

            if categ:
                try:
                    categ_id = categ.id
                except Exception:
                    categ_id = False
                try:
                    categ_name = categ.complete_name or categ.name or ''
                except Exception:
                    try:
                        categ_name = categ.name or ''
                    except Exception:
                        categ_name = ''

            is_cigarette = bool(categ_id and (categ_id in CIGARETTE_CATEGORY_IDS))

        meta_cache[pid] = {
            'categ_id': categ_id,
            'categ_name': categ_name,
            'is_cigarette': is_cigarette,
            'name': full_name,
            'default_code': default_code,
        }
        return meta_cache[pid]

    def _ensure_cost(pid):
        if pid in cost_cache:
            return cost_cache[pid]

        p = prods.get(pid)
        if not p:
            cost_cache[pid] = {
                'ila_factor':0.0,'iva_compra':0.0,'iva_venta_so':0.0,
                'raw':0.0,'costo_neto_unit':0.0,'costo_oh_unit':0.0,
                'ila_compra_unit':0.0,'iva_compra_unit':0.0,
                'flag_raw_zero':True,'flag_cost_fallback':True
            }
            return cost_cache[pid]

        ila_factor   = _sum_ila_factor(p)
        iva_compra   = _iva_compra_factor(p)
        iva_venta_so = _iva_venta_so_factor(p)

        raw = 0.0
        try:
            val = p.raw_product_price
            if val:
                raw = float(val or 0.0)
        except Exception:
            pass
        if not raw:
            try:
                tmpl = p.product_tmpl_id
                if tmpl and tmpl.raw_product_price:
                    raw = float(tmpl.raw_product_price or 0.0)
            except Exception:
                pass

        flag_raw_zero = False
        flag_cost_fallback = False
        denom = 1.0 + (ila_factor or 0.0) + (iva_compra or 0.0)
        if raw and (denom > 0.0):
            costo_neto_unit = raw / denom
        else:
            try:
                costo_neto_unit = float(p.standard_price or 0.0)
            except Exception:
                costo_neto_unit = 0.0
            flag_cost_fallback = True
            if not raw:
                flag_raw_zero = True

        ila_compra_unit = costo_neto_unit * (ila_factor or 0.0)
        iva_compra_unit = costo_neto_unit * (iva_compra or 0.0)
        costo_oh_unit   = costo_neto_unit + ila_compra_unit

        cost_cache[pid] = {
            'ila_factor': ila_factor,
            'iva_compra': iva_compra,
            'iva_venta_so': iva_venta_so,
            'raw': raw,
            'costo_neto_unit': costo_neto_unit,
            'ila_compra_unit': ila_compra_unit,
            'iva_compra_unit': iva_compra_unit,
            'costo_oh_unit':  costo_oh_unit,
            'flag_raw_zero': flag_raw_zero,
            'flag_cost_fallback': flag_cost_fallback,
        }
        return cost_cache[pid]

    rows = []
    BATCH = 1000

    for (tid, pid) in keys:
        p = prods.get(pid)
        if not p:
            continue

        q_pos = float(pos_qty.get((tid, pid), 0.0) or 0.0)
        q_so  = float(so_qty.get((tid, pid), 0.0) or 0.0)
        qty   = q_pos + q_so

        net_pos = float(pos_net.get((tid, pid), 0.0) or 0.0)
        net_so  = float(so_net.get((tid, pid), 0.0) or 0.0)
        net_total = net_pos + net_so

        if abs(net_total) <= EPS:
            continue

        c = _ensure_cost(pid)
        m = _ensure_meta(pid)

        ila_factor      = c['ila_factor']
        iva_compra      = c['iva_compra']
        iva_venta_so    = c['iva_venta_so']
        raw             = c['raw']
        costo_neto_unit = c['costo_neto_unit']
        ila_compra_unit = c['ila_compra_unit']
        iva_compra_unit = c['iva_compra_unit']
        costo_oh_unit   = c['costo_oh_unit']

        costo_neto_total = qty * costo_neto_unit
        costo_oh_total   = qty * costo_oh_unit
        costo_total_unit = costo_neto_unit + ila_compra_unit + iva_compra_unit
        costo_total      = qty * costo_total_unit

        iva_factor_sale = iva_venta_so or 0.0
        ila_factor_sale = ila_factor or 0.0

        # IVA venta
        iva_pos = net_pos * iva_factor_sale
        iva_so  = net_so * iva_factor_sale
        iva_total = iva_pos + iva_so

        # ILA venta
        ila_venta_pos = 0.0
        ila_venta_so  = 0.0
        if ILA_SALES_MODE == 'all':
            ila_venta_pos = net_pos * ila_factor_sale
            ila_venta_so  = net_so * ila_factor_sale
        elif ILA_SALES_MODE == 'so':
            ila_venta_so  = net_so * ila_factor_sale

        ila_venta_total = ila_venta_pos + ila_venta_so

        venta_bruta_total = net_total + iva_total + ila_venta_total

        # Margen SIN ILA venta
        cost_total_eff = costo_oh_total
        margin_total   = net_total - cost_total_eff
        margin_pct     = (margin_total / net_total) if abs(net_total) > EPS else None
        rentab_sobre_costo = (margin_total / cost_total_eff) if abs(cost_total_eff) > EPS else None

        precio_neto_unit = (net_total / qty) if abs(qty) > EPS else 0.0
        precio_bruto_unit = (venta_bruta_total / qty) if abs(qty) > EPS else 0.0

        sem, reason, is_cigarette, exp_min, exp_max = _classify_margin(
            margin_pct=margin_pct,
            is_cigarette=m.get('is_cigarette', False),
            flag_raw_zero=c.get('flag_raw_zero', False),
            flag_cost_fallback=c.get('flag_cost_fallback', False),
        )

        vals = {
            'x_studio_compania': company.id,
            'x_studio_fecha_desde': df,
            'x_studio_fecha_hasta': dt,
            'x_studio_equipo_de_ventas': tid,
            'x_studio_producto': pid,

            'x_studio_qty': qty,
            'x_studio_net_pos': net_pos,
            'x_studio_net_so': net_so,
            'x_studio_price_net_total': net_total,

            'x_studio_ila_venta_total': ila_venta_total,
            'x_studio_iva_venta_pos': iva_pos,
            'x_studio_iva_venta_so': iva_so,
            'x_studio_venta_bruta_total': venta_bruta_total,

            'x_studio_raw_price': raw,
            'x_studio_ila_factor': ila_factor,
            'x_studio_iva_compra': iva_compra,
            'x_studio_costo_neto_unit':  costo_neto_unit,
            'x_studio_ila_compra_unit':  ila_compra_unit,
            'x_studio_iva_compra_unit':  iva_compra_unit,
            'x_studio_costo_oh_unit':    costo_oh_unit,
            'x_studio_costo_neto_total': costo_neto_total,
            'x_studio_costo_oh_total':   costo_oh_total,
            'x_studio_costo_total':      costo_total,

            'x_studio_cost_total_eff': cost_total_eff,
            'x_studio_margin_total':   margin_total,
            'x_studio_margin_pct':     margin_pct,

            'x_studio_flag_sold': bool(qty or net_total),
            'x_studio_flag_raw_zero': c.get('flag_raw_zero', False),
            'x_studio_flag_cost_fallback': c.get('flag_cost_fallback', False),
        }

        if HAS_CURRENCY_ID_FIELD:
            vals['x_studio_currency_id'] = currency.id
        if HAS_CAT_FIELD:
            vals['x_studio_categoria'] = m.get('categ_id') or False
        if HAS_IVA_VENTA_FIELD:
            vals['x_studio_iva_venta'] = iva_total
        if HAS_ILA_VENTA_SO_FIELD:
            vals['x_studio_ila_venta_so'] = ila_venta_so
        if HAS_PRECIO_NETO_UNIT:
            vals['x_studio_precio_neto_unit'] = precio_neto_unit
        if HAS_PRECIO_BRUTO_UNIT:
            vals['x_studio_precio_bruto_unit'] = precio_bruto_unit
        if HAS_RENTAB_COSTO:
            vals['x_studio_rentab_sobre_costo'] = rentab_sobre_costo
        if HAS_SEM_FIELD:
            vals['x_studio_semaforo_margen'] = sem
        if HAS_SEM_REASON_FIELD:
            vals['x_studio_motivo_semaforo'] = reason
        if HAS_EXPECT_MIN_FIELD:
            vals['x_studio_margin_expected_min'] = exp_min
        if HAS_EXPECT_MAX_FIELD:
            vals['x_studio_margin_expected_max'] = exp_max
        if HAS_IS_CIG_FIELD:
            vals['x_studio_es_cigarro'] = is_cigarette

        rows.append(vals)
        if len(rows) >= BATCH:
            Marg.create(rows)
            rows.clear()

    if rows:
        Marg.create(rows)
        rows.clear()

    total_rows = Marg.search_count([
        ('x_studio_compania','=', company.id),
        ('x_studio_fecha_desde','=', df),
        ('x_studio_fecha_hasta','=', dt),
    ])
    subt = 'Periodo %s a %s | Filas: %s | ila_sales_mode=%s | POS sin ILA venta' % (df, dt, total_rows, ILA_SALES_MODE)
    if TEAM_IDS and (not _team_col):
        subt += ' | Aviso: POS sin columna de equipo; filtro de equipo aplicado solo a SO.'
    if HAS_SEM_FIELD:
        subt += ' | Semaforo: OK'
    else:
        subt += ' | Semaforo no escrito: faltan campos Studio'

    action = {
        'type':'ir.actions.client','tag':'display_notification',
        'params': {'title':'Margen por Producto','message': subt,
                   'type':'success','sticky': False}
    }
