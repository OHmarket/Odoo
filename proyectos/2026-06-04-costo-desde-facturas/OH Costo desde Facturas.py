# ============================================================
# OH - COSTO DESDE FACTURAS (LANDED COST, MULTI-PROVEEDOR, AUDITABLE)
#   Reemplaza "OH CCU Capture + Freight Alloc" (CCU-only).
#
#   Modelo: LANDED COST (SAP/Oracle). Captura account.move.line de facturas de
#   proveedor y calcula el costo unitario REAL de compra:
#
#     precio_compra_unit = ( neto x (1 + ILA) + flete_neto_asignado ) / unidades_equiv
#
#   - Base NETO + ILA, SIN IVA (IVA 19% compra es credito fiscal recuperable).
#     ILA / Especifico / Beb. Analc / Vinos / IVA No Recup. SI capitalizan.
#   - Comparable con raw_product_price (que esta BRUTO con IVA): para productos
#     sin ILA, raw / (1 + IVA) ~ este costo neto. standard_price es el neto Odoo.
#   - "La factura manda, la tarifa distribuye": el total del flete = linea(s) de
#     flete de la factura; el tarifario x_vendor_freight_rule solo da los PESOS
#     de reparto entre productos. El total SIEMPRE cuadra con la factura.
#   - Multi-proveedor: procesa todo partner con regla activa (no hard CCU).
#   - Llave tarifa por producto deducida de la factura:
#       cc_unit  = product.template.volume   (PROXY: el negocio guarda CC en volume)
#       pack_qty = product_uom_id.ratio      (ej. "x 6 Unidades" -> 6)
#
#   Escribe en x_vendor_bill_cost_lin. El costo cash queda en
#   x_studio_unit_gross_with_freight (label "Precio Compra"), que es el campo
#   que OH Analisis de Stock.py ya lee como purchase_price_cash_unit.
#
#   Params de contexto (todos opcionales):
#     date_from / vendor_bill_start, date_to / vendor_bill_end   (def. mes actual)
#     dte_code                          (def. '33')
#     vendor_bill_purge_all / purge_all (def. True -> TRUNCATE al inicio)
#     vendor_bill_dry_run / dry_run     (def. False)
#     vendor_bill_only_posted           (def. True)
# ============================================================

VERSION_ID = "OH_COSTO_FACTURAS_v3_NETO_SIN_IVA"

# ===== TOGGLE MANUAL — editar antes de correr =====
#   DRY:  True = DRY-RUN (cuenta; NO trunca, NO escribe) | False = FIRME | None = context
#   RUN_FROM/RUN_TO: rango (None = usar context / default mes actual)
#   RUN_DTE: 'all' (afectas+exentas) | '33' (solo afecta) | None = context/default '33'
DRY = True
RUN_FROM = None   # ej '2026-01-01'
RUN_TO   = None   # ej '2026-04-30'
RUN_DTE  = None   # ej 'all'

# Generaliza v1: procesa TODOS los proveedores (no solo los con regla de flete).
#   - Solo captura productos ALMACENABLES (type='product'); excluye servicios/
#     consumibles (RETENCION, articulos de oficina, recargas, fletes sin producto
#     en proveedores sin regla, etc.).
#   - Proveedor SIN regla de flete -> costo = neto (+ILA) / unidades (sin flete).
#   - Proveedor CON regla de flete  -> landed cost neto con reparto por tarifa.
#   - vendor_bill_mode: 'all' (def) | 'simple' (solo sin flete) | 'freight' (solo con flete).
#     Para "partir por lo simple" (no-ILA/no-flete): vendor_bill_mode='simple'.
#   - vendor_bill_partner_ids: lista opcional para acotar a proveedores puntuales.
#   - dte_code: '33' (def) o 'all' para no filtrar tipo de documento.

MODEL_NAME = 'x_vendor_bill_cost_lin'
DEST = env[MODEL_NAME].sudo()

# ---------------- helpers ----------------
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

def _norm(s):
    return (s or '').strip().lower()

def _digits_only(s):
    out = ''
    for ch in (s or ''):
        if ('0' <= ch) and (ch <= '9'):
            out += ch
    return out

def _clean_vals(vals):
    out = {}
    for k in vals:
        if k in DEST._fields:
            out[k] = vals[k]
    return out

# ---------------- clasificacion de impuestos ----------------
# Recuperable (NO capitaliza): IVA credito fiscal (name contiene 'iva' y no
# 'no recup'). Costo (SI capitaliza, bucket ILA): cualquier otro % positivo
# (Especifico, Beb. Analc, Vinos, ILA, IVA No Recup.). Retenciones (negativas)
# se ignoran.
def _is_recoverable_iva(tax):
    nm = _norm(tax.name or tax.display_name or '')
    if 'iva' not in nm:
        return False
    if 'no recup' in nm or 'no rec.' in nm:
        return False
    return True

def _split_tax_pcts(taxes):
    vat = 0.0
    ila = 0.0
    for t in taxes:
        if (t.amount_type or '') != 'percent':
            continue
        amt = _f(t.amount)
        if amt <= 0.0:
            continue
        if _is_recoverable_iva(t):
            vat += amt / 100.0
        else:
            ila += amt / 100.0
    return vat, ila

def _tax_desc_from_taxes(taxes):
    parts = []
    for t in taxes:
        nm = (t.name or t.display_name or '').strip()
        if nm:
            parts.append("%s (%s)" % (nm, _f(t.amount)))
    s = " | ".join(parts).strip()
    if len(s) > 250:
        s = s[:247] + "..."
    return s

# ---------------- tarifario de flete ----------------
# Reparto del flete: "la factura manda, la tarifa distribuye". El peso de cada
# linea = litros x tarifa-por-litro de su tipo de caja (escala consistente).
#   - Tipo de Caja : match por volumen de caja (cc_linea * uom_ratio = product.volume * pack)
#   - CC Botella   : match por cc de la botella
#   - Tarifa Fija  : flat -> tarifa_fija * n_cajas
# Lineas sin volumen (product.volume=0) imputan litros con la densidad L/$ de la
# factura, para no romper la escala. La tarifa solo da pesos: el total SIEMPRE
# cuadra con la linea de flete de la factura (normalizacion por wsum).
RULES = {}
_rule_recs = env['x_vendor_freight_rule'].sudo().search([('x_studio_active', '=', True)])
for _r in _rule_recs:
    if not _r.x_studio_partner_id:
        continue
    _rtype = _norm(_r.x_studio_rule_type)
    _pats = [p.strip().lower() for p in (_r.x_studio_freight_patterns or '').split(',') if p.strip()]
    _rates = []   # [(match_vol_cc, rate_$_por_L)]
    _fija = 0.0
    for _tl in _r.x_studio_tariff_line_ids:
        _cc = _f(_tl.x_studio_cc_unit)
        _pack = _f(_tl.x_studio_pack_qty)
        _t = _f(_tl.x_studio_tariff_case)
        if _t <= 0.0:
            continue
        if 'fija' in _rtype:
            if _fija <= 0.0:
                _fija = _t
            continue
        _mvol = _cc if ('botella' in _rtype) else (_cc * _pack)
        if _mvol > 0.0:
            _rates.append((_mvol, _t / (_mvol / 1000.0)))
    RULES[_r.x_studio_partner_id.id] = {
        'rtype': _rtype,
        'patterns': _pats,
        'rates': _rates,
        'avg_rate': (sum(x[1] for x in _rates) / len(_rates)) if _rates else 0.0,
        'fija_tar': _fija,
    }

def _line_is_freight(partner_id, label):
    rule = RULES.get(partner_id) or {}
    lab = _norm(label)
    if not lab:
        return False
    for p in (rule.get('patterns') or []):
        if p and p in lab:
            return True
    return False

# Cargo global capitalizable que viene como LINEA sin product_id (no como tarifa):
# Embonor factura el flete como linea "RECARGO". Se detecta por nombre y se reparte
# entre los productos del move por VALOR neto (cargo % proporcional al precio).
_CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')
def _line_is_charge(label):
    lab = _norm(label)
    if not lab:
        return False
    for w in _CHARGE_WORDS:
        if w in lab:
            return True
    return False

def _line_rate(partner_id, cc, pack):
    # retorna (rate_$_por_L, basis, miss). basis: 'L' (litros x rate),
    # 'flat' (tarifa fija x n_cajas), 'none' (sin tarifa).
    rule = RULES.get(partner_id) or {}
    rtype = rule.get('rtype') or ''
    if 'fija' in rtype:
        ft = rule.get('fija_tar') or 0.0
        return ft, 'flat', (ft <= 0.0)
    rates = rule.get('rates') or []
    if not rates:
        return 0.0, 'none', True
    key = cc if ('botella' in rtype) else (cc * pack)
    for mv, r in rates:
        if abs(mv - key) < 1.0:
            return r, 'L', False
    return (rule.get('avg_rate') or 0.0), 'L', True

# ---------------- params ----------------
# RUN_FROM/RUN_TO/RUN_DTE (toggles manuales arriba) mandan; si None, cae al context.
date_from = (RUN_FROM or env.context.get('vendor_bill_start') or env.context.get('date_from') or '').strip()
date_to   = (RUN_TO   or env.context.get('vendor_bill_end')   or env.context.get('date_to')   or '').strip()
if not date_from or not date_to:
    _today = datetime.date.today()
    date_from = _today.replace(day=1).isoformat()
    date_to = _today.isoformat()

DTE_CODE = (RUN_DTE or env.context.get('dte_code') or '33').strip()   # '' / 'all' -> sin filtro DTE

# MODE: 'all' (todos), 'simple' (solo proveedores SIN regla de flete -> costo neto+ILA),
#       'freight' (solo proveedores CON regla de flete). Para "partir por lo simple"
#       (no-ILA/no-flete) usar mode='simple'.
MODE = (env.context.get('vendor_bill_mode') or 'all').strip().lower()
# filtro explicito opcional de proveedores
_explicit_partners = env.context.get('vendor_bill_partner_ids') or None

ONLY_POSTED = _ctx_bool(env.context.get('vendor_bill_only_posted'), True)
ALLOW_DRAFT = (not ONLY_POSTED) and _ctx_bool(env.context.get('allow_draft'), False)

PURGE_ALL_AT_START = _ctx_bool(env.context.get('vendor_bill_purge_all'), None)
if PURGE_ALL_AT_START is None:
    PURGE_ALL_AT_START = _ctx_bool(env.context.get('purge_all'), True)

# El toggle manual DRY (arriba) manda; si se deja en None, cae al context.
if DRY is None:
    DRY_RUN = _ctx_bool(env.context.get('vendor_bill_dry_run') or env.context.get('dry_run'), False)
else:
    DRY_RUN = bool(DRY)

MAX_MOVES_TOTAL = int(env.context.get('max_moves_total') or 999999999)
MOVE_BATCH      = int(env.context.get('vendor_bill_batch') or env.context.get('move_batch') or 500)
BATCH_CREATE_N  = int(env.context.get('batch_create_n') or 800)

states = ['posted'] + (['draft'] if ALLOW_DRAFT else [])
Move = env['account.move'].sudo()

_rule_partner_ids = list(RULES.keys())

dom_moves = [
    ('move_type', '=', 'in_invoice'),
    ('state', 'in', states),
    ('company_id', '=', env.company.id),
    '|',
        '&', ('invoice_date', '>=', date_from), ('invoice_date', '<=', date_to),
        '&', ('date',         '>=', date_from), ('date',         '<=', date_to),
]
if DTE_CODE and DTE_CODE.lower() not in ('all', '*'):
    dom_moves.append(('l10n_latam_document_type_id.code', '=', DTE_CODE))
if _explicit_partners:
    dom_moves.append(('partner_id', 'in', list(_explicit_partners)))
elif MODE == 'freight':
    dom_moves.append(('partner_id', 'in', _rule_partner_ids))
# MODE == 'simple' se filtra por-move (skip partners con regla); 'all' no filtra

# ---------------- PURGE ----------------
if PURGE_ALL_AT_START:
    if DRY_RUN:
        purge_msg = "PURGE_ALL=1 pero DRY_RUN=1 (no borre)"
    else:
        env.cr.execute('TRUNCATE TABLE "%s" RESTART IDENTITY CASCADE' % (DEST._table,))
        purge_msg = "TRUNCATE OK (%s)" % (DEST._table,)
else:
    purge_msg = "PURGE_ALL=0 (no borre)"

# ---------------- batch create ----------------
state = {'buf': [], 'created': 0}

def _flush():
    if DRY_RUN or (not state['buf']):
        state['buf'] = []
        return
    DEST.create(state['buf'])
    state['created'] += len(state['buf'])
    state['buf'] = []

# ---------------- main loop ----------------
seen_moves = 0
ok_moves = 0
seen_lines = 0
inserted_lines = 0
skipped_qty = 0
moves_with_freight = 0
tariff_miss_lines = 0
skipped = []

offset = 0
skipped_mode = 0
skipped_non_product = 0
while True:
    if seen_moves >= MAX_MOVES_TOTAL:
        break
    limit = MOVE_BATCH
    if (seen_moves + limit) > MAX_MOVES_TOTAL:
        limit = MAX_MOVES_TOTAL - seen_moves
        if limit <= 0:
            break

    moves = Move.search(dom_moves, order='date asc, id asc', limit=limit, offset=offset)
    if not moves:
        break
    seen_moves += len(moves)
    offset += len(moves)

    for move in moves:
        try:
            partner = move.partner_id
            partner_id = partner.id if partner else False

            _has_rule = partner_id in RULES
            if MODE == 'simple' and _has_rule:
                skipped_mode += 1
                continue
            if MODE == 'freight' and not _has_rule:
                skipped_mode += 1
                continue

            doc_type = move.l10n_latam_document_type_id
            dte_code = (doc_type.code or '') if doc_type else ''
            doc_num = _digits_only(move.l10n_latam_document_number or '')

            doc_key = "MOVE-%s" % (move.id,)
            if dte_code and doc_num:
                doc_key = "%s-%s" % (dte_code, doc_num)

            doc_date = move.invoice_date or move.date

            snap_lines = []
            prod_idx = []
            freight_idx = []

            for l in move.invoice_line_ids:
                seen_lines += 1
                qty = _f(l.quantity)
                if qty <= 0.0:
                    skipped_qty += 1
                    continue

                line_label = (l.name or '').strip()
                # cargo global sin product_id (ej. Embonor "RECARGO") -> tratar como
                # flete a repartir. Exigir SIN product_id evita capturar un producto
                # cuyo nombre contenga la palabra.
                is_charge = (not l.product_id) and _line_is_charge(line_label)
                is_freight = _line_is_freight(partner_id, line_label) or is_charge

                # solo costear productos ALMACENABLES (type='product'); excluye
                # servicios/consumibles genericos (RETENCION, articulos de oficina,
                # recargas, etc.). Las lineas de flete (sin producto) se mantienen.
                is_product = bool(l.product_id) and ('type' in l.product_id._fields) and (l.product_id.type == 'product')
                if (not is_freight) and (not is_product):
                    skipped_non_product += 1
                    continue

                uom = l.product_uom_id
                uom_ratio = 1.0
                if uom and ('ratio' in uom._fields):
                    uom_ratio = _f(uom.ratio) or 1.0

                # ---- ancla de UoM a standard_price ----
                # La factura a veces trae qty en piezas y a veces en packs; qty*ratio
                # rompe en un caso, qty solo en el otro. Se elige la base (qty o
                # qty*ratio) cuyo NETO unitario quede mas cerca de standard_price (el
                # std fija la UNIDAD, la factura el VALOR). Si ni asi cuadra (>15% vs
                # std) la linea queda marcada uom_dudosa (dato de origen sucio, ej.
                # ratio de UoM inconsistente entre facturas). Flete no se ancla.
                _net_line = _f(l.price_subtotal)
                std_b = _f(l.product_id.standard_price) if l.product_id else 0.0
                units_equiv = qty * uom_ratio
                uom_dudosa = False
                if (not is_freight) and std_b > 0.0 and qty > 0.0:
                    _unit_pack = (_net_line / (qty * uom_ratio)) if uom_ratio else 0.0
                    _unit_unit = _net_line / qty
                    if abs(_unit_unit - std_b) <= abs(_unit_pack - std_b):
                        units_equiv = qty
                        _best = _unit_unit
                    else:
                        units_equiv = qty * uom_ratio
                        _best = _unit_pack
                    if abs(_best - std_b) / std_b > 0.15:
                        uom_dudosa = True

                cc_unit = 0.0
                if l.product_id and l.product_id.product_tmpl_id:
                    tmpl = l.product_id.product_tmpl_id
                    if 'volume' in tmpl._fields:
                        cc_unit = _f(tmpl.volume)
                line_liters = (units_equiv * (cc_unit / 1000.0)) if cc_unit > 0.0 else 0.0

                line_net = _f(l.price_subtotal)
                taxes = l.tax_ids or env['account.tax'].browse([])
                vat_pct, ila_pct = _split_tax_pcts(taxes)
                vat_amount = line_net * vat_pct
                ila_amount = line_net * ila_pct
                gross_no_freight = line_net + vat_amount + ila_amount

                # snapshot del costo maestro para comparar en el modelo
                raw_snap = 0.0
                std_snap = 0.0
                if l.product_id:
                    raw_snap = _f(l.product_id.product_tmpl_id.raw_product_price)
                    std_snap = _f(l.product_id.standard_price)

                vals = {
                    'name': "%s | line %s" % (doc_key, l.id),
                    'x_name': "%s | %s" % (doc_key, line_label),
                    'x_studio_doc_date': doc_date or False,
                    'x_studio_l10n_latam_document_number': doc_num,
                    'x_studio_partner_id': partner_id,
                    'x_studio_company_id': move.company_id.id if move.company_id else False,
                    'x_studio_currency_id': move.currency_id.id if move.currency_id else False,
                    'x_studio_line_label': line_label,
                    'x_studio_product_id': l.product_id.id if l.product_id else False,
                    'x_studio_default_code': (l.product_id.default_code or '') if l.product_id else '',
                    'x_studio_uom_id': uom.id if uom else False,
                    'x_studio_qty_invoice': qty,
                    'x_studio_units_per_uom': uom_ratio,
                    'x_studio_qty_units_equiv': units_equiv,
                    'x_studio_cc_unit': cc_unit,
                    'x_studio_line_liters': line_liters,
                    'x_studio_line_net': line_net,
                    'x_studio_vat_pct': vat_pct,
                    'x_studio_ila_pct': ila_pct,
                    'x_studio_vat_amount': vat_amount,
                    'x_studio_ila_amount': ila_amount,
                    'x_studio_odoo_line_total': gross_no_freight,
                    'x_studio_gross_no_freight_total': gross_no_freight,
                    'x_studio_unit_gross_no_freight': (gross_no_freight / units_equiv) if units_equiv else 0.0,
                    'x_studio_unit_net': (line_net / units_equiv) if units_equiv else 0.0,
                    'x_studio_tax_desc': _tax_desc_from_taxes(taxes),
                    # snapshot del maestro para comparar costo capturado vs raw/std
                    'x_studio_raw_snapshot': raw_snap,
                    'x_studio_std_snapshot': std_snap,
                    'x_studio_uom_dudosa': uom_dudosa,
                    # se completan abajo (flete / costo cash)
                    'x_studio_unit_gross_with_freight': 0.0,
                }
                snap_lines.append(vals)
                idx = len(snap_lines) - 1

                if is_freight:
                    freight_idx.append(idx)
                else:
                    prod_idx.append(idx)   # garantizado storable por el filtro de arriba

            # ---- flete total de la factura (neto = verdad a repartir) ----
            freight_net = 0.0
            freight_gross = 0.0
            for ix in freight_idx:
                fn = _f(snap_lines[ix].get('x_studio_line_net'))
                fv = _f(snap_lines[ix].get('x_studio_vat_amount'))
                fi = _f(snap_lines[ix].get('x_studio_ila_amount'))
                freight_net += fn
                freight_gross += fn + fv + fi

            # ---- litros totales del move (auditoria) ----
            move_liters_total = 0.0
            for ix in prod_idx:
                move_liters_total += _f(snap_lines[ix].get('x_studio_line_liters'))
            move_freight_per_liter = (freight_gross / move_liters_total) if move_liters_total else 0.0

            for ix in range(len(snap_lines)):
                snap_lines[ix]['x_studio_move_liters_total'] = move_liters_total
                snap_lines[ix]['x_studio_move_freight_per_liter'] = move_freight_per_liter
                snap_lines[ix]['x_studio_freight_invoice_net'] = freight_net
                snap_lines[ix]['x_studio_freight_invoice_gross'] = freight_gross

            # ---- pesos de tarifa por linea producto (litros x $/L; imputa volume=0) ----
            # Solo si la factura trae flete. Proveedores sin flete (camino simple):
            # weights=0 -> alloc=0 -> costo = neto x (1+ILA) / unidades.
            has_freight = bool(freight_idx) and bool(prod_idx) and (freight_net > 0.0 or freight_gross > 0.0)
            weights = []
            wsum = 0.0
            if has_freight:
                moves_with_freight += 1
                known_l = 0.0
                known_net = 0.0
                for ix in prod_idx:
                    ll = _f(snap_lines[ix].get('x_studio_line_liters'))
                    if ll > 0.0:
                        known_l += ll
                        known_net += _f(snap_lines[ix].get('x_studio_line_net'))
                l_per_net = (known_l / known_net) if known_net > 0.0 else 0.0
                for ix in prod_idx:
                    cc = _f(snap_lines[ix].get('x_studio_cc_unit'))
                    pack = _f(snap_lines[ix].get('x_studio_units_per_uom'))
                    qinv = _f(snap_lines[ix].get('x_studio_qty_invoice'))
                    ueq = _f(snap_lines[ix].get('x_studio_qty_units_equiv'))
                    ll = _f(snap_lines[ix].get('x_studio_line_liters'))
                    rate, basis, miss = _line_rate(partner_id, cc, pack)
                    if basis == 'flat':
                        w = rate * max(qinv, 0.0)
                    elif basis == 'none':
                        # sin tarifa (ej. Embonor RECARGO global): repartir por VALOR
                        # neto -> el cargo se aplica proporcional al precio del producto.
                        w = _f(snap_lines[ix].get('x_studio_line_net'))
                    else:  # 'L'
                        lit = ll if ll > 0.0 else (_f(snap_lines[ix].get('x_studio_line_net')) * l_per_net)
                        if ll <= 0.0:
                            miss = True
                        w = lit * rate
                    if miss:
                        tariff_miss_lines += 1
                    if w < 0.0:
                        w = 0.0
                    weights.append((ix, w))
                    wsum += w
            else:
                weights = [(ix, 0.0) for ix in prod_idx]

            # ---- reparto del flete (residual en ultima linea); costo cash por linea ----
            for i, (ix, w) in enumerate(weights):
                if (not has_freight) or wsum <= 0.0:
                    alloc_net = 0.0
                    alloc_gross = 0.0
                elif i == len(weights) - 1:
                    used_net = 0.0
                    used_gross = 0.0
                    for j in range(len(weights) - 1):
                        used_net += freight_net * (weights[j][1] / wsum)
                        used_gross += freight_gross * (weights[j][1] / wsum)
                    alloc_net = freight_net - used_net
                    alloc_gross = freight_gross - used_gross
                else:
                    alloc_net = freight_net * (w / wsum)
                    alloc_gross = freight_gross * (w / wsum)

                base_net = _f(snap_lines[ix].get('x_studio_line_net'))
                ila_pct = _f(snap_lines[ix].get('x_studio_ila_pct'))
                units_equiv = _f(snap_lines[ix].get('x_studio_qty_units_equiv'))
                gross_no_freight = _f(snap_lines[ix].get('x_studio_odoo_line_total'))

                total_net_wf = base_net + alloc_net
                total_gross_wf = gross_no_freight + alloc_gross

                # "Precio Compra" = NETO + ILA + flete neto, por unidad (SIN IVA,
                # recuperable). Para productos sin ILA queda comparable con
                # raw_product_price sin IVA: raw / (1 + IVA) ~ este costo.
                unit_cost = (base_net * (1.0 + ila_pct) + alloc_net) / units_equiv if units_equiv else 0.0

                snap_lines[ix]['x_studio_freight_basis_qty'] = w
                snap_lines[ix]['x_studio_freight_alloc_net'] = alloc_net
                snap_lines[ix]['x_studio_freight_alloc_gross'] = alloc_gross
                snap_lines[ix]['x_studio_total_net_with_freight'] = total_net_wf
                snap_lines[ix]['x_studio_total_gross_with_freight'] = total_gross_wf
                snap_lines[ix]['x_studio_unit_freight_gross'] = (alloc_net / units_equiv) if units_equiv else 0.0
                # campo que lee Stock como "Precio Compra" = neto + ILA + flete (sin IVA)
                snap_lines[ix]['x_studio_unit_gross_with_freight'] = unit_cost

            for vals in snap_lines:
                state['buf'].append(_clean_vals(vals))
                inserted_lines += 1
                if len(state['buf']) >= BATCH_CREATE_N:
                    _flush()

            ok_moves += 1

        except Exception as e:
            skipped.append("move_id=%s err=%s" % (move.id, (str(e) or '')[:180]))

_flush()

msg = (
    "v=%s | %s | MODE=%s | reglas_flete=%s | DTE=%s | rango=%s..%s | moves=%s | OK=%s | "
    "skip_mode=%s | moves_with_freight=%s | seen_lines=%s | inserted=%s | "
    "skip_qty<=0=%s | skip_no_product=%s | tariff_miss=%s | created=%s | DRY_RUN=%s"
    % (
        VERSION_ID, purge_msg, MODE, len(_rule_partner_ids), DTE_CODE, date_from, date_to,
        seen_moves, ok_moves, skipped_mode, moves_with_freight, seen_lines, inserted_lines,
        skipped_qty, skipped_non_product, tariff_miss_lines, state['created'], int(DRY_RUN)
    )
)
if skipped:
    msg += "\nSKIPPED (muestra):"
    for s in skipped[:5]:
        msg += "\n- " + s
    if len(skipped) > 5:
        msg += "\n(+%s mas)" % (len(skipped) - 5)

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'OH Costo desde Facturas',
        'message': msg,
        'type': 'success' if ok_moves else 'warning',
        'sticky': False,
    }
}
