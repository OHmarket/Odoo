# ============================================================
# DIAGNOSTICO SERVER ACTION (descartable)
# Reporta para 5 PIDs especificos:
#   - Si existe el variant en product.product (active/sale_ok)
#   - Cambios de precio en ultimas 12 sem (x_price_change_event)
#   - Promos en ultimas 4 sem (x_loyalty_promo_event)
#   - Bucket ABCXYZ en x_calculo_abc_xyz
#   - Si esta alertado en x_price_coreccion
# Resultado en notification + log.
# ============================================================

PIDS = [9413, 9407, 451548, 451500, 9430]
TZ = 'America/Santiago'

env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ,))
today = env.cr.fetchone()[0]
target_week = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=1)
lb_12 = target_week - datetime.timedelta(weeks=12)
lb_4  = target_week - datetime.timedelta(weeks=4)

lines = []

Prod = env['product.product'].sudo()
prods = Prod.browse(PIDS).exists()
prod_map = {p.id: p for p in prods}

Ev = env['x_price_change_event'].sudo()
Pr = env['x_loyalty_promo_event'].sudo()
Abc = env['x_calculo_abc_xyz'].sudo()
Corr = env['x_price_coreccion'].sudo() if env.get('x_price_coreccion') else None

for pid in PIDS:
    p = prod_map.get(pid)
    name = p.display_name if p else '<no existe>'
    active = p.active if p else None
    sale_ok = p.sale_ok if p else None
    sub_cat = (p.categ_id.complete_name or '') if p else ''
    lines.append('===== PP%s  %s' % (pid, name[:60]))
    lines.append('  active=%s sale_ok=%s' % (active, sale_ok))
    lines.append('  categ: %s' % sub_cat[:80])

    # ABCXYZ
    abc_rows = Abc.search([('x_studio_product_id', '=', pid)], limit=1)
    if abc_rows:
        a = abc_rows[0]
        lines.append('  abcxyz=%s ciclo=%s regimen=%s' % (
            a.x_studio_abcxyz or '',
            getattr(a, 'x_studio_ciclo_de_vida', '') or '',
            getattr(a, 'x_studio_regimen', '') or '',
        ))
    else:
        lines.append('  NO esta en x_calculo_abc_xyz')

    # Eventos de precio
    ev_rows = Ev.search([
        ('x_studio_product_variant_id', '=', pid),
        ('x_studio_period_start', '>=', lb_12),
        ('x_studio_period_start', '<=', target_week),
    ], order='x_studio_period_start desc', limit=5)
    if ev_rows:
        for ev in ev_rows:
            lines.append('  PRICE  %s  delta=%+.1f%%  dir=%s  is_real=%s' % (
                ev.x_studio_period_start,
                (ev.x_studio_delta_pct or 0) * 100,
                ev.x_studio_direction or '',
                bool(getattr(ev, 'x_studio_is_real_change', False)),
            ))
    else:
        lines.append('  PRICE  sin eventos en ultimas 12 sem')

    # Promos
    pr_rows = Pr.search([
        ('x_studio_product_variant_id', '=', pid),
        ('x_studio_period_start', '>=', lb_4),
        ('x_studio_period_start', '<=', target_week),
    ], order='x_studio_period_start desc', limit=5)
    if pr_rows:
        for pr in pr_rows:
            lines.append('  PROMO  %s  %s  lift=%.2f  min_qty=%s' % (
                pr.x_studio_period_start,
                (pr.x_studio_program_name or '')[:30],
                pr.x_studio_lift_qty or 0,
                getattr(pr, 'x_studio_minimum_qty', '') or '',
            ))
    else:
        lines.append('  PROMO  sin promos en ultimas 4 sem')

    # Alertas existentes
    if Corr is not None:
        cr_rows = Corr.search([('x_studio_product_id', '=', pid)], limit=3)
        if cr_rows:
            for c in cr_rows:
                lines.append('  CORR   %s  tipo=%s  factor=%.3f' % (
                    c.x_studio_target_week_start,
                    c.x_studio_tipo_alerta or '',
                    c.x_studio_factor_corr or 1.0,
                ))
        else:
            lines.append('  CORR   NO alertado por el detector')

txt = '\n'.join(lines)
try:
    log(txt, level='info')
except Exception:
    pass

# Devolver via notification corta y log completo
action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'Diag 5 SKUs',
        'message': 'Diagnostico en log. Lineas: %s. Ver tail -f odoo.log' % len(lines),
        'sticky': True,
        'type': 'info',
    }
}
