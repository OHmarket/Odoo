# DIAGNOSTICO Server Action: SMA6/SMA12/SMA26 para los 50 SKUs Z4 mature
# que dieron forecast=0 con ventas >=5. Compara contra el mu_week que el
# motor terminó usando.

# IDs de los SKUs anomalos del backtest W17-W19 (separados por nombre primero)
# Si el ID viene como string '[xxx]', el Server Action lo parsea.

NAMES_OR_IDS = [
    'AU66-0CARA', 'AU66-0ALMO', '451523', '451420', 'AU66-0CHOC',
    'C593-6', '5128161', '102320050', '5101032', '101920061',
    '9518', '0-062', '0781', '00002', '9908',
    'PAF10', '10199613', 'H670-8WILD', '6250', '870689',
    'H670-8ORIG', '300065824', '101920061', 'S747-K0000', '300066167',
    '12298926', '5128161', '6258', '7843', '7802100501196',
    '300066348', '300055263', '964741', '447082', '9644',
    '300061947', '300054998', '12035120', '9892', '12076018',
    '12517860', '7802100002716', '798190225043', '300060148', '0704',
    '9936', 'S746-10000', '12567311', '7802100020130', '7802100010292',
    '7802100004741', '7802100003515', '965216', '504001'
]
TZ = 'America/Santiago'
HISTORY_WEEKS = 26

# Sin import: 'datetime' ya esta en el namespace de Odoo safe_eval.
env.cr.execute("SELECT (timezone(%s, now())::date)", (TZ,))
today = env.cr.fetchone()[0]
date_to = today - datetime.timedelta(days=today.weekday()) - datetime.timedelta(days=1)  # ultimo domingo
date_from = date_to - datetime.timedelta(weeks=HISTORY_WEEKS)

# Buscar pids por default_code o por id directo
pids = set()
Prod = env['product.product'].sudo()
for tag in NAMES_OR_IDS:
    try:
        if tag.isdigit():
            p = Prod.browse(int(tag)).exists()
            if p:
                pids.add(p.id)
                continue
    except Exception:
        pass
    rs = Prod.search([('default_code', '=', tag)], limit=1)
    if not rs:
        rs = Prod.search([('default_code', 'ilike', tag)], limit=3)
    for r in rs:
        pids.add(r.id)

if not pids:
    action = {'type': 'ir.actions.client', 'tag': 'display_notification',
              'params': {'title': 'Diag', 'message': 'No pids resueltos', 'sticky': True}}
else:
    # Query ventas semanales agregadas (todo team)
    env.cr.execute("""
        SELECT pp.id,
               date_trunc('week', po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS wk,
               SUM(pol.qty) AS qty
        FROM pos_order_line pol
        JOIN pos_order po ON po.id = pol.order_id
        JOIN product_product pp ON pp.id = pol.product_id
        WHERE po.state IN ('paid','done','invoiced')
          AND po.company_id = %s
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date >= %s
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date <= %s
          AND pp.id = ANY(%s)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, (TZ, env.company.id, TZ, date_from, TZ, date_to, list(pids)))

    by_pid = {}
    for pid, wk, qty in env.cr.fetchall():
        by_pid.setdefault(pid, []).append((wk, float(qty or 0.0)))

    # Construir semanas continuas
    weeks_list = []
    cur = date_from - datetime.timedelta(days=date_from.weekday())
    end = date_to - datetime.timedelta(days=date_to.weekday())
    while cur <= end:
        weeks_list.append(cur)
        cur += datetime.timedelta(weeks=1)
    weeks_list = weeks_list[-26:]  # ultimas 26 sem cerradas

    lines = []
    lines.append('%-55s %-7s %-7s %-7s %-7s %s' % (
        'producto', 'SMA6', 'SMA12', 'SMA26', 'maxOBS', 'last_8_weekly'
    ))
    lines.append('-' * 130)

    for pid in sorted(pids):
        p = Prod.browse(pid).exists()
        if not p:
            continue
        sales = dict(by_pid.get(pid, []))
        weekly = [sales.get(w, 0.0) for w in weeks_list]
        sma6 = sum(weekly[-6:]) / 6.0 if len(weekly) >= 6 else 0
        sma12 = sum(weekly[-12:]) / 12.0 if len(weekly) >= 12 else 0
        sma26 = sum(weekly) / max(len(weekly), 1) if weekly else 0
        max_obs = max(weekly) if weekly else 0
        last_8 = weekly[-8:] if len(weekly) >= 8 else weekly
        last_8_str = ' '.join('%g' % v for v in last_8)
        name = (p.display_name or '')[:53]
        lines.append('%-55s %7.2f %7.2f %7.2f %7.0f %s' % (
            name, sma6, sma12, sma26, max_obs, last_8_str
        ))

    txt = '\n'.join(lines)
    try:
        log(txt, level='info')
    except Exception:
        pass

    # Adjuntar como archivo descargable desde la interfaz.
    # Usar 'raw' (bytes directos) para no requerir import base64.
    att = env['ir.attachment'].sudo().create({
        'name': 'diag_sma_z4_anomalos_%s.txt' % date_to,
        'type': 'binary',
        'raw': txt.encode('utf-8'),
        'mimetype': 'text/plain',
        'res_model': 'product.product',
    })

    action = {
        'type': 'ir.actions.act_url',
        'url': '/web/content/%s?download=true' % att.id,
        'target': 'self',
    }
