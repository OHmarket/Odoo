# ============================================================
# OH - COSTO DESDE FACTURAS (Fase 1, DRY-RUN report, TODOS los proveedores)
#   READ-ONLY. Por producto, ULTIMO documento, calcula los DOS costos:
#     global_con_iva = (price_total + flete_bruto) / unidades   -> raw
#     margen_sin_iva = (neto x (1+ILA) + flete_neto) / unidades -> margen
#   Flete solo donde el proveedor tiene regla activa (x_vendor_freight_rule) y
#   la factura trae linea de flete (CCU). Proveedores sin flete: costo = neto+IVA+ILA.
#   Embonor (flete global en XML) NO se captura aca -> queda sin flete (flag).
#   Tabaco (315->no; BAT 301) excluido. Params: cf_days (60), cf_max (3000).
# ============================================================

VERSION_ID = "OH_COSTO_FACT_F1_DRYRUN_ALL"
BAT = 301

def _f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

def _norm(s):
    return (s or '').strip().lower()

DAYS = int(env.context.get('cf_days') or 60)
MAXM = int(env.context.get('cf_max') or 3000)
d_from = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()

# ---- reglas de flete por proveedor ----
RULES = {}
for r in env['x_vendor_freight_rule'].sudo().search([('x_studio_active', '=', True)]):
    if not r.x_studio_partner_id:
        continue
    rtype = _norm(r.x_studio_rule_type)
    pats = [p.strip().lower() for p in (r.x_studio_freight_patterns or '').split(',') if p.strip()]
    rates = []
    fija = 0.0
    for tl in r.x_studio_tariff_line_ids:
        cc = _f(tl.x_studio_cc_unit); pk = _f(tl.x_studio_pack_qty); tar = _f(tl.x_studio_tariff_case)
        if tar <= 0.0:
            continue
        if 'fija' in rtype:
            fija = fija or tar
            continue
        mvol = cc if ('botella' in rtype) else cc * pk
        if mvol > 0.0:
            rates.append((mvol, tar / (mvol / 1000.0)))
    RULES[r.x_studio_partner_id.id] = {
        'rtype': rtype, 'pats': pats, 'rates': rates, 'fija': fija,
        'avg': (sum(x[1] for x in rates) / len(rates)) if rates else 0.0,
    }

def _rate(rule, cc, pack):
    rates = rule['rates']
    if not rates:
        return 0.0
    key = cc if ('botella' in rule['rtype']) else cc * pack
    for mv, rr in rates:
        if abs(mv - key) < 1.0:
            return rr
    return rule['avg']

Move = env['account.move'].sudo()
moves = Move.search([
    ('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
    ('company_id', '=', env.company.id), ('partner_id', '!=', BAT),
    ('invoice_date', '>=', d_from),
], limit=MAXM, order='invoice_date asc')

prod = {}
con_flete_doc = 0

for move in moves:
    pid = move.partner_id.id if move.partner_id else False
    rule = RULES.get(pid)
    doc_date = move.invoice_date or move.date
    plines = []
    freight_net = 0.0
    freight_gross = 0.0
    for l in move.invoice_line_ids:
        if l.display_type != 'product':
            continue
        nm = _norm(l.name)
        # flete: cualquier linea con 'flete' (o patrones del proveedor)
        if ('flete' in nm) or (rule and any(pp in nm for pp in rule['pats'])):
            freight_net += _f(l.price_subtotal)
            freight_gross += _f(l.price_total)
            continue
        if not l.product_id:
            continue
        qty = _f(l.quantity)
        if qty <= 0.0:
            continue
        ratio = 1.0
        if l.product_uom_id and ('ratio' in l.product_uom_id._fields):
            ratio = _f(l.product_uom_id.ratio) or 1.0
        net_line = _f(l.price_subtotal)
        std_b = _f(l.product_id.standard_price)
        # ANCLA UoM: unidades base = qty o qty*ratio, la que deje el neto/unidad
        # mas cerca de standard_price (resuelve packs vs piezas).
        units = qty * ratio
        if ratio > 1.0:
            if std_b > 0.0:
                da = abs((net_line / qty) - std_b)
                db = abs((net_line / (qty * ratio)) - std_b)
                units = qty if da <= db else qty * ratio
        tmpl = l.product_id.product_tmpl_id
        vol = _f(tmpl.volume)
        liters = units * vol / 1000.0 if vol > 0.0 else 0.0
        ila_pct = 0.0
        for t in l.tax_ids:
            tn = (t.name or '').lower()
            if t.amount_type == 'percent' and t.amount > 0 and 'iva' not in tn:
                ila_pct += t.amount / 100.0
        plines.append({'units': units, 'liters': liters, 'cc': vol, 'pack': ratio,
                       'qty': qty, 'net': _f(l.price_subtotal), 'gross': _f(l.price_total),
                       'ila': ila_pct, 'tmpl': tmpl})

    has_freight = (freight_net > 0.0 or freight_gross > 0.0) and bool(plines)
    if has_freight:
        con_flete_doc += 1
        lknown = 0.0; nknown = 0.0
        for p in plines:
            if p['liters'] > 0.0:
                lknown += p['liters']; nknown += p['net']
        lpn = (lknown / nknown) if nknown > 0.0 else 0.0
        weights = []
        wsum = 0.0
        for p in plines:
            if p['ila'] <= 0.0:
                w = 0.0                       # flete SOLO a productos con ILA
            elif rule and 'fija' in rule['rtype']:
                w = rule['fija'] * p['qty']
            elif rule and rule['rates']:
                lit = p['liters'] if p['liters'] > 0.0 else p['net'] * lpn
                w = lit * _rate(rule, p['cc'], p['pack'])
            else:
                w = p['net']                  # sin tarifa -> reparte por valor neto
            weights.append(max(w, 0.0)); wsum += max(w, 0.0)
    else:
        weights = [0.0] * len(plines)
        wsum = 0.0

    for i in range(len(plines)):
        p = plines[i]
        fr_net = (freight_net * weights[i] / wsum) if wsum > 0.0 else 0.0
        fr_gross = (freight_gross * weights[i] / wsum) if wsum > 0.0 else 0.0
        units = p['units']
        global_unit = (p['gross'] + fr_gross) / units if units else 0.0
        margen_unit = (p['net'] * (1.0 + p['ila']) + fr_net) / units if units else 0.0
        tmpl = p['tmpl']; tid = tmpl.id
        cur = prod.get(tid)
        if (cur is None) or (doc_date and doc_date >= cur['date']):
            prod[tid] = {
                'code': (tmpl.default_code or ''), 'name': (tmpl.name or '')[:40],
                'date': doc_date, 'global': global_unit, 'margen': margen_unit,
                'raw': _f(tmpl.raw_product_price), 'std': _f(tmpl.standard_price),
                'flete': fr_gross > 0.0,
            }

# ---- salida ----
def _n(x):
    return ("%.2f" % x).replace('.', ',')

rows = sorted(prod.values(), key=lambda r: -r['raw'])
ok = 0; sin_raw = 0; medida = 0
buf = ["RESUMEN COSTO (Fase1 dryrun, todos);%s..hoy" % d_from]
buf.append("facturas;%s" % len(moves))
buf.append("docs con flete;%s" % con_flete_doc)
buf.append("productos (ultimo doc);%s" % len(prod))
buf.append("")
buf.append("codigo;producto;fecha;global_con_iva(->raw);margen_sin_iva;raw_actual;ratio_global/raw;flete;std")
for r in rows:
    ratio = (r['global'] / r['raw']) if r['raw'] else 0.0
    if not r['raw']:
        sin_raw += 1
    elif 0.9 <= ratio <= 1.1:
        ok += 1
    elif ratio > 1.5 or ratio < 0.5:
        medida += 1
    buf.append("%s;%s;%s;%s;%s;%s;%s;%s;%s" % (
        r['code'], (r['name'] or '').replace(';', ','), r['date'] or '',
        _n(r['global']), _n(r['margen']), _n(r['raw']), _n(ratio),
        'SI' if r['flete'] else '', _n(r['std'])))

csv_text = "\n".join(buf)
att = env['ir.attachment'].sudo().create({
    'name': 'costo_facturas_dryrun.csv', 'type': 'binary',
    'raw': csv_text.encode('utf-8-sig'), 'mimetype': 'text/csv'})

msg = "%s..hoy | facturas=%s | docs_flete=%s | productos=%s\n" % (d_from, len(moves), con_flete_doc, len(prod))
msg += "ratio global/raw: OK(0.9-1.1)=%s | error_medida(>1.5 o <0.5)=%s | sin_raw=%s\n" % (ok, medida, sin_raw)
msg += "global=con IVA(->raw) | margen=sin IVA | ULTIMO doc\n"
msg += "CSV: /web/content/%s?download=true\n\nTop 20 por raw:" % att.id
i = 0
for r in rows:
    ratio = (r['global'] / r['raw']) if r['raw'] else 0.0
    msg += "\n  %-9s g %8s m %8s raw %8s %.2f%s %s" % (
        r['code'], _n(r['global']), _n(r['margen']), _n(r['raw']), ratio,
        ' FLE' if r['flete'] else '', (r['name'] or '')[:18])
    i += 1
    if i >= 20:
        break

action = {'type': 'ir.actions.client', 'tag': 'display_notification',
          'params': {'title': 'OH Costo Facturas (F1 dryrun, todos)', 'message': msg,
                     'type': 'success' if ok else 'warning', 'sticky': True}}
