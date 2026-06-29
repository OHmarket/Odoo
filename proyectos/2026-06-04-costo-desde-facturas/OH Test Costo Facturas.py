# ============================================================
# OH - TEST / DIAGNOSTICO Costo desde Facturas (READ-ONLY)
#
#   NO es para produccion. Evalua la CALIDAD del dato de entrada antes de
#   mejorarlo. Server-side (no carga POS). No escribe nada salvo un CSV adjunto
#   descargable.
#
#   Reporta:
#   - Resumen: total facturas, cuantas SIN DETALLE (sin lineas de producto / lump),
#     cuantas con lineas pero TODAS libres (sin product_id), cuantas con vinculo.
#   - Por producto vinculado: codigo (default_code), valor capturado (price_unit
#     neto de la ultima compra) vs raw_product_price (que esta CON IVA), y el ratio.
#
#   Params: test_date_from, test_date_to (def. ultimos 30 dias), test_max (def 4000)
# ============================================================

VERSION_ID = "OH_TEST_COSTO_FACTURAS_DIAG_v1"

def _f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0

today = datetime.date.today()
date_from = (env.context.get('test_date_from') or (today - datetime.timedelta(days=30)).isoformat()).strip()
date_to = (env.context.get('test_date_to') or today.isoformat()).strip()
MAXM = int(env.context.get('test_max') or 4000)

Move = env['account.move'].sudo()

# Si se corre desde el menu contextual de account.move con facturas
# seleccionadas, usa esas. Si no, usa el rango de fechas.
_active_ids = env.context.get('active_ids') or []
_scope = ''
if env.context.get('active_model') == 'account.move' and _active_ids:
    moves = Move.search([
        ('id', 'in', _active_ids),
        ('move_type', '=', 'in_invoice'),
        ('state', '=', 'posted'),
    ], limit=MAXM)
    _scope = "%s facturas seleccionadas" % len(moves)
else:
    moves = Move.search([
        ('move_type', '=', 'in_invoice'),
        ('state', '=', 'posted'),
        ('company_id', '=', env.company.id),
        ('invoice_date', '>=', date_from),
        ('invoice_date', '<=', date_to),
    ], limit=MAXM, order='invoice_date asc')
    _scope = "rango %s..%s" % (date_from, date_to)

n_moves = len(moves)
sin_detalle = 0          # 0 lineas de producto (lump / solo cargos)
libre_total = 0          # tiene lineas producto pero TODAS sin product_id
con_vinculo = 0          # >=1 linea con product_id
n_lineas_prod = 0
n_vinc = 0
n_libre = 0

prod = {}   # tmpl_id -> dict

for move in moves:
    doc_date = move.invoice_date or move.date
    plines = []
    for l in move.invoice_line_ids:
        if l.display_type == 'product':
            plines.append(l)
    if not plines:
        sin_detalle += 1
        continue
    linked = []
    has_freight = False
    for l in plines:
        n_lineas_prod += 1
        if 'flete' in (l.name or '').lower():
            has_freight = True
        if l.product_id:
            n_vinc += 1
            linked.append(l)
        else:
            n_libre += 1
    if not linked:
        libre_total += 1
        continue
    con_vinculo += 1
    for l in linked:
        p = l.product_id
        tmpl = p.product_tmpl_id
        qty = _f(l.quantity)
        price_unit = _f(l.price_unit)   # neto por unidad de la UoM de la linea
        raw = _f(tmpl.raw_product_price)
        std = _f(p.standard_price)
        # ratio de la UoM de la linea (cuantas unidades base por unidad de linea)
        ratio = 1.0
        if l.product_uom_id and ('ratio' in l.product_uom_id._fields):
            ratio = _f(l.product_uom_id.ratio) or 1.0
        # ANCLA UoM: el neto por unidad BASE es price_unit o price_unit/ratio,
        # el que quede mas cerca de standard_price (std fija la unidad).
        candA = price_unit
        candB = (price_unit / ratio) if ratio > 1.0 else price_unit
        uom_flag = ''
        if std > 0.0 and ratio > 1.0:
            devA = abs(candA - std) / std
            devB = abs(candB - std) / std
            if devB < devA:
                net_unit = candB
                uom_flag = '/%g' % ratio   # se dividio por el factor (multipack)
            else:
                net_unit = candA
            if min(devA, devB) > 0.15:
                uom_flag = (uom_flag + ' REVISAR').strip()
        else:
            net_unit = candA
        # impuestos: IVA y ILA (bucket no-IVA)
        vat_pct = 0.0
        ila_pct = 0.0
        for t in l.tax_ids:
            if t.amount_type == 'percent' and t.amount > 0:
                nm = (t.name or '').lower()
                if 'iva' in nm and 'no recup' not in nm:
                    vat_pct += t.amount / 100.0
                else:
                    ila_pct += t.amount / 100.0
        # VALOR A PAGAR (all-in, sin flete todavia) = neto base x (1 + IVA + ILA)
        # raw_product_price = valor a pagar = factura + impuestos + flete -> benchmark
        pagar_unit = net_unit * (1.0 + vat_pct + ila_pct)
        ratio_raw = (pagar_unit / raw) if raw else 0.0  # ~1 sin flete; <1 si falta el flete
        key = tmpl.id
        cur = prod.get(key)
        keep = (cur is None) or (not cur['date']) or (doc_date and doc_date >= cur['date'])
        if keep:
            prod[key] = {
                'code': p.default_code or '',
                'name': (tmpl.name or '')[:50],
                'date': doc_date,
                'qty': qty,
                'net_unit': net_unit,
                'ila_pct': ila_pct,
                'vat_pct': vat_pct,
                'pagar_unit': pagar_unit,
                'ratio_raw': ratio_raw,
                'flete': has_freight,
                'std': std,
                'uom_flag': uom_flag,
                'raw': raw,
                'ila': ila_pct > 0.0,
            }

# ---- CSV ----
EOL = "\n"
buf = []
buf.append("RESUMEN;%s..%s" % (date_from, date_to))
buf.append("total_facturas;%s" % n_moves)
buf.append("sin_detalle (lump, 0 lineas producto);%s" % sin_detalle)
buf.append("con lineas pero TODAS libres (sin product_id);%s" % libre_total)
buf.append("con vinculo (>=1 producto);%s" % con_vinculo)
buf.append("lineas producto total;%s" % n_lineas_prod)
buf.append("  vinculadas;%s" % n_vinc)
buf.append("  libres (texto);%s" % n_libre)
buf.append("productos distintos vinculados;%s" % len(prod))
# cuantos productos quedan fuera de rango vs standard_price (posible dato malo)
n_revisar = 0
for r in prod.values():
    if 'REVISAR' in (r['uom_flag'] or ''):
        n_revisar += 1
buf.append("productos con costo fuera de rango vs std (REVISAR);%s" % n_revisar)
n_con_flete = 0
for r in prod.values():
    if r['flete']:
        n_con_flete += 1
buf.append("productos con FLETE en la factura (ratio<1 = ese es el gap);%s" % n_con_flete)
buf.append("")
buf.append("raw = valor a pagar = factura + IVA + ILA + flete (benchmark). pagar = neto+IVA+ILA (sin flete).")
buf.append("ratio pagar/raw ~1 = raw al dia ; <1 = falta flete o raw alto ; >>1 o <<1 = error de medida")
buf.append("codigo;producto;fecha;neto_base;IVA%;ILA%;pagar_unit(s/flete);raw(valor_a_pagar);ratio_pagar/raw;flete;std;uom_ajuste")

def _num(x):
    return ("%.2f" % x).replace('.', ',')

rows = sorted(prod.values(), key=lambda r: -r['raw'])
for r in rows:
    buf.append("%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s;%s" % (
        r['code'], (r['name'] or '').replace(';', ','), r['date'] or '',
        _num(r['net_unit']), _num(r['vat_pct'] * 100.0), _num(r['ila_pct'] * 100.0),
        _num(r['pagar_unit']), _num(r['raw']), _num(r['ratio_raw']),
        'SI' if r['flete'] else '', _num(r['std']), (r['uom_flag'] or '')))

csv_text = EOL.join(buf)

att = env['ir.attachment'].sudo().create({
    'name': 'test_costo_facturas.csv',
    'type': 'binary',
    'raw': csv_text.encode('utf-8-sig'),
    'mimetype': 'text/csv',
})

# --- resumen legible en pantalla (sticky) ---
msg = "Alcance: %s\n" % _scope
msg += "Facturas: %s\n" % n_moves
msg += "  SIN DETALLE (lump, 0 lineas prod): %s\n" % sin_detalle
msg += "  con lineas pero TODAS libres:      %s\n" % libre_total
msg += "  con vinculo (>=1 producto):        %s\n" % con_vinculo
msg += "Lineas producto: %s  (vinculadas %s | libres %s)\n" % (n_lineas_prod, n_vinc, n_libre)
msg += "Productos distintos vinculados: %s\n" % len(prod)
msg += "  fuera de rango vs std (error medida/raw viejo): %s\n" % n_revisar
msg += "  con FLETE en factura (ratio<1 = ese es el gap): %s\n" % n_con_flete
msg += "raw = valor a pagar (factura+IVA+ILA+flete). ratio pagar/raw ~1 = OK\n"
msg += "Descargar CSV detalle: /web/content/%s?download=true\n" % att.id
msg += "\nTop 20 (codigo | pagar s/flete | raw | ratio | flete):"
i = 0
for r in rows:
    msg += "\n  %-8s %9s | raw %9s | %.2f%s%s | %s" % (
        r['code'], _num(r['pagar_unit']), _num(r['raw']), r['ratio_raw'],
        ' FLE' if r['flete'] else '', (' ' + r['uom_flag']) if r['uom_flag'] else '',
        (r['name'] or '')[:22])
    i += 1
    if i >= 20:
        break

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'TEST Costo desde Facturas (diagnostico)',
        'message': msg,
        'type': 'success' if con_vinculo else 'warning',
        'sticky': True,
    }
}
