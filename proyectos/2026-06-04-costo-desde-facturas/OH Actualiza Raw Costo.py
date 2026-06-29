# ============================================================
# OH - ACTUALIZA raw_product_price DESDE FACTURAS (WAC, camino simple)
#
#   Objetivo: mantener al dia el costo (raw_product_price, que esta CON IVA) con
#   PROMEDIO PONDERADO (WAC) calculado desde las FACTURAS reales de proveedor, no
#   desde las ordenes de compra (el AVCO de Odoo sale de las OC y puede divergir).
#
#   Alcance (camino simple): proveedores SIN regla de flete (x_vendor_freight_rule).
#   Productos ALMACENABLES (type='product'). Ventana movil de N dias.
#
#   raw_nuevo = sum(price_total de las lineas) / sum(unidades_base)
#             = promedio ponderado por cantidad del costo unitario CON IVA
#   (price_total ya incluye IVA -y ILA si aplica-, misma convencion que raw.)
#
#   UoM inconsistente: qty a veces viene en unidades base (GALLETA x40) y a veces
#   en packs (CHICLE). Se elige la base (qty o qty*ratio) cuyo costo unitario neto
#   quede mas cerca de standard_price (ancla de MAGNITUD, no de valor). Si ninguna
#   cuadra (>15%), la linea es DUDOSA y el producto se EXCLUYE (no se pisa).
#
#   Resguardos (conservador):
#     - dry_run: no escribe, solo reporta.            (def. True)
#     - excluye productos con lineas UoM dudosas.
#     - no pisa si |raw_nuevo - raw_actual| / raw_actual > wac_max_change (def 0.30).
#     - excluye templates con >1 variante comprada (costo por variante ambiguo).
#
#   Params de contexto:
#     wac_window_days (def 90) | wac_max_change (def 0.30) | wac_dry_run (def True)
# ============================================================

VERSION_ID = "OH_ACTUALIZA_RAW_COSTO_v1_WAC_SIMPLE"

def _ctx_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ('1', 'true', 't', 'yes', 'y', 'si', 'on'):
        return True
    if s in ('0', 'false', 'f', 'no', 'n', 'off'):
        return False
    return default

def _f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

WINDOW_DAYS = int(env.context.get('wac_window_days') or 90)
MAX_CHANGE  = _f(env.context.get('wac_max_change') or 0.30)
DRY_RUN     = _ctx_bool(env.context.get('wac_dry_run'), True)
STD_TOL     = 0.15   # tolerancia para aceptar la base contra standard_price

# proveedores con regla de flete -> se excluyen (camino landed, aparte)
freight_pids = []
for _r in env['x_vendor_freight_rule'].sudo().search([('x_studio_active', '=', True)]):
    if _r.x_studio_partner_id:
        freight_pids.append(_r.x_studio_partner_id.id)

today = datetime.date.today()
d_from = today - datetime.timedelta(days=WINDOW_DAYS)

def _base_units(qty, rat, net, std):
    # elige qty o qty*ratio (base) cuyo costo unit neto este mas cerca de std.
    if std <= 0.0 or net <= 0.0:
        return qty, True
    cands = [qty] if (not rat or rat == 1.0) else [qty, qty * rat]
    best = qty
    bestdev = None
    for bu in cands:
        if bu <= 0.0:
            continue
        dev = abs((net / bu) - std) / std
        if (bestdev is None) or (dev < bestdev):
            bestdev = dev
            best = bu
    miss = (bestdev is None) or (bestdev > STD_TOL)
    return best, miss

# ---- acumular por template ----
Line = env['account.move.line'].sudo()
dom = [
    ('parent_state', '=', 'posted'),
    ('move_id.move_type', '=', 'in_invoice'),
    ('display_type', '=', 'product'),
    ('date', '>=', d_from),
    ('company_id', '=', env.company.id),
    ('product_id', '!=', False),
]
if freight_pids:
    dom.append(('partner_id', 'not in', freight_pids))

agg = {}   # tmpl_id -> dict
seen_lines = 0
batch = 2000
offset = 0
while True:
    lines = Line.search(dom, limit=batch, offset=offset, order='id')
    if not lines:
        break
    offset += len(lines)
    for l in lines:
        seen_lines += 1
        prod = l.product_id
        if not prod or (getattr(prod, 'type', '') != 'product'):
            continue
        qty = _f(l.quantity)
        if qty <= 0.0:
            continue
        rat = 1.0
        uom = l.product_uom_id
        if uom and ('ratio' in uom._fields):
            rat = _f(uom.ratio) or 1.0
        net = _f(l.price_subtotal)
        gross = _f(l.price_total)
        std = _f(prod.standard_price)
        bu, miss = _base_units(qty, rat, net, std)
        if bu <= 0.0:
            continue
        tmpl = prod.product_tmpl_id
        tid = tmpl.id
        a = agg.get(tid)
        if a is None:
            a = {'gross': 0.0, 'units': 0.0, 'miss': 0, 'variants': set(),
                 'name': tmpl.display_name or prod.display_name or str(tid),
                 'raw_now': _f(tmpl.raw_product_price)}
            agg[tid] = a
        a['gross'] += gross
        a['units'] += bu
        a['variants'].add(prod.id)
        if miss:
            a['miss'] += 1

# ---- decidir y escribir ----
written = 0
skip_uom = 0
skip_maxchange = 0
skip_multivariant = 0
skip_no_units = 0
samples_write = []
samples_block = []

Template = env['product.template'].sudo()

for tid, a in agg.items():
    if a['units'] <= 0.0:
        skip_no_units += 1
        continue
    if a['miss'] > 0:
        skip_uom += 1
        continue
    if len(a['variants']) > 1:
        skip_multivariant += 1
        continue
    wac = a['gross'] / a['units']
    raw_now = a['raw_now']
    if raw_now > 0.0 and abs(wac - raw_now) / raw_now > MAX_CHANGE:
        skip_maxchange += 1
        if len(samples_block) < 8:
            samples_block.append("%s: raw=%.0f wac=%.0f (%+.0f%%)"
                                 % (a['name'][:32], raw_now, wac, (wac - raw_now) / raw_now * 100.0))
        continue
    new_val = round(wac)
    if not DRY_RUN:
        Template.browse(tid).write({'raw_product_price': new_val})
    written += 1
    if len(samples_write) < 8:
        chg = ((wac - raw_now) / raw_now * 100.0) if raw_now else 0.0
        samples_write.append("%s: raw=%.0f -> %.0f (%+.0f%%)" % (a['name'][:32], raw_now, new_val, chg))

msg = (
    "v=%s | DRY_RUN=%s | ventana=%sd (%s..%s) | excl_flete=%s | lineas=%s | "
    "templates=%s | ESCRIBIR=%s | skip_uom=%s | skip_cambio>%.0f%%=%s | "
    "skip_multivariante=%s | skip_sin_unidades=%s"
    % (
        VERSION_ID, int(DRY_RUN), WINDOW_DAYS, d_from, today, len(freight_pids),
        seen_lines, len(agg), written, skip_uom, MAX_CHANGE * 100.0, skip_maxchange,
        skip_multivariant, skip_no_units,
    )
)
if samples_write:
    msg += "\n-- a escribir (muestra):"
    for s in samples_write:
        msg += "\n  " + s
if samples_block:
    msg += "\n-- bloqueados por tope (muestra):"
    for s in samples_block:
        msg += "\n  " + s

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'OH Actualiza Raw Costo (WAC)',
        'message': msg,
        'type': 'success' if written or DRY_RUN else 'warning',
        'sticky': True,
    }
}
