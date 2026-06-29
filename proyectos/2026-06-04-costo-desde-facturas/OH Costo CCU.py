# ============================================================
# OH - COSTO CCU (Fase 1, DRY-RUN report) — READ-ONLY
#
#   Por producto CCU, toma el ULTIMO documento (factura) y calcula los DOS costos
#   landed con flete, y los compara con raw_product_price. NO escribe nada.
#
#     global_unit (con IVA)  = (price_total + flete_bruto_asignado) / unidades   -> raw
#     margen_unit (sin IVA)  = (neto x (1+ILA) + flete_neto_asignado) / unidades -> margen
#
#   Flete CCU = linea "Flete de Mercaderias"; reparto por litros x tarifa-$/L
#   (x_vendor_freight_rule). Unidades = qty x uom.ratio (CCU viene en packs).
#
#   Params: ccu_days (def 60), ccu_max (def 400)
# ============================================================

VERSION_ID = "OH_COSTO_CCU_F1_DRYRUN"
CCU = 315

def _f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

DAYS = int(env.context.get('ccu_days') or 60)
MAXM = int(env.context.get('ccu_max') or 400)
d_from = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()

# ---- tarifa CCU: rates ($/L) por volumen de caja (cc*pack) ----
patterns = ['flete']
rates = []          # (case_vol_cc, rate_$_por_L)
rule = env['x_vendor_freight_rule'].sudo().search(
    [('x_studio_partner_id', '=', CCU), ('x_studio_active', '=', True)], limit=1)
if rule:
    patterns = [p.strip().lower() for p in (rule.x_studio_freight_patterns or 'flete').split(',') if p.strip()]
    for tl in rule.x_studio_tariff_line_ids:
        cv = _f(tl.x_studio_cc_unit) * _f(tl.x_studio_pack_qty)
        tar = _f(tl.x_studio_tariff_case)
        if cv > 0.0 and tar > 0.0:
            rates.append((cv, tar / (cv / 1000.0)))
avg_rate = (sum(r for _, r in rates) / len(rates)) if rates else 0.0

def _rate(case_vol):
    for mv, r in rates:
        if abs(mv - case_vol) < 1.0:
            return r
    return avg_rate

Move = env['account.move'].sudo()
moves = Move.search([
    ('partner_id', '=', CCU), ('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
    ('invoice_date', '>=', d_from),
], limit=MAXM, order='invoice_date asc')

prod = {}   # tmpl_id -> latest dict

for move in moves:
    doc_date = move.invoice_date or move.date
    plines = []
    freight_net = 0.0
    freight_gross = 0.0
    for l in move.invoice_line_ids:
        if l.display_type != 'product':
            continue
        nm = (l.name or '').lower()
        if any(p in nm for p in patterns):
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
        units = qty * ratio
        tmpl = l.product_id.product_tmpl_id
        vol = _f(tmpl.volume)
        liters = units * vol / 1000.0 if vol > 0.0 else 0.0
        # ILA% (impuestos % que no son IVA)
        ila_pct = 0.0
        for t in l.tax_ids:
            tn = (t.name or '').lower()
            if t.amount_type == 'percent' and t.amount > 0 and 'iva' not in tn:
                ila_pct += t.amount / 100.0
        plines.append({
            'units': units, 'liters': liters, 'rate': _rate(vol * ratio),
            'net': _f(l.price_subtotal), 'gross': _f(l.price_total),
            'ila': ila_pct, 'tmpl': tmpl, 'name': l.name or '',
        })

    # reparto del flete por litros x rate (imputa litros si vol=0)
    wsum = 0.0
    lknown = 0.0
    nknown = 0.0
    for p in plines:
        if p['liters'] > 0.0:
            lknown += p['liters']
            nknown += p['net']
    lpn = (lknown / nknown) if nknown > 0.0 else 0.0
    weights = []
    for p in plines:
        lit = p['liters'] if p['liters'] > 0.0 else p['net'] * lpn
        w = lit * p['rate']
        weights.append(w)
        wsum += w

    for i in range(len(plines)):
        p = plines[i]
        w = weights[i]
        fr_net = (freight_net * w / wsum) if wsum > 0.0 else 0.0
        fr_gross = (freight_gross * w / wsum) if wsum > 0.0 else 0.0
        units = p['units']
        global_unit = (p['gross'] + fr_gross) / units if units else 0.0
        margen_unit = (p['net'] * (1.0 + p['ila']) + fr_net) / units if units else 0.0
        tmpl = p['tmpl']
        tid = tmpl.id
        cur = prod.get(tid)
        if (cur is None) or (doc_date and doc_date >= cur['date']):
            prod[tid] = {
                'code': (tmpl.default_code or ''),
                'name': (tmpl.name or '')[:40],
                'date': doc_date,
                'global': global_unit,
                'margen': margen_unit,
                'raw': _f(tmpl.raw_product_price),
                'std': _f(tmpl.standard_price),
            }

# ---- CSV ----
buf = ["RESUMEN CCU costo (Fase1 dry-run);%s..%s" % (d_from, datetime.date.today().isoformat())]
buf.append("facturas;%s" % len(moves))
buf.append("productos (ultimo doc c/u);%s" % len(prod))
buf.append("")
buf.append("codigo;producto;fecha;global_con_iva(->raw);margen_sin_iva;raw_actual;ratio_global/raw;std")

def _n(x):
    return ("%.2f" % x).replace('.', ',')

rows = sorted(prod.values(), key=lambda r: -r['raw'])
ok = 0
for r in rows:
    ratio = (r['global'] / r['raw']) if r['raw'] else 0.0
    if r['raw'] and 0.9 <= ratio <= 1.1:
        ok += 1
    buf.append("%s;%s;%s;%s;%s;%s;%s;%s" % (
        r['code'], (r['name'] or '').replace(';', ','), r['date'] or '',
        _n(r['global']), _n(r['margen']), _n(r['raw']), _n(ratio), _n(r['std'])))

csv_text = "\n".join(buf)
att = env['ir.attachment'].sudo().create({
    'name': 'costo_ccu_dryrun.csv', 'type': 'binary',
    'raw': csv_text.encode('utf-8-sig'), 'mimetype': 'text/csv',
})

msg = "CCU %s..%s | facturas=%s | productos=%s | ratio global/raw en 0.9-1.1: %s/%s\n" % (
    d_from, datetime.date.today().isoformat(), len(moves), len(prod), ok, len(rows))
msg += "global=con IVA (->raw) | margen=sin IVA | ULTIMO doc por producto\n"
msg += "CSV: /web/content/%s?download=true\n\nTop 20 (cod | global | margen | raw | ratio):" % att.id
i = 0
for r in rows:
    ratio = (r['global'] / r['raw']) if r['raw'] else 0.0
    msg += "\n  %-9s g %8s | m %8s | raw %8s | %.2f | %s" % (
        r['code'], _n(r['global']), _n(r['margen']), _n(r['raw']), ratio, (r['name'] or '')[:20])
    i += 1
    if i >= 20:
        break

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {'title': 'OH Costo CCU (Fase1 dry-run)', 'message': msg,
               'type': 'success' if ok else 'warning', 'sticky': True},
}
