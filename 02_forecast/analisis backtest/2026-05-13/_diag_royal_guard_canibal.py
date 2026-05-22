# Diagnostico Royal Guard / Cristal Ultra / Budweiser / Stella / Quilmes:
# por que canibal pasivo agarra a Cristal pero no a Royal Guard.

PIDS = [451500, 451548, 9413, 9407, 9430, 1726, 9958]

lines = []

for pid in PIDS:
    Prod = env['product.product'].sudo().browse(pid).exists()
    if not Prod:
        lines.append('PP%s <no existe>' % pid)
        continue
    name = (Prod.display_name or '')[:50]
    active = Prod.active
    sale_ok = Prod.sale_ok
    categ_complete = Prod.categ_id.complete_name or ''
    lines.append('===== PP%s  %s' % (pid, name))
    lines.append('  active=%s sale_ok=%s' % (active, sale_ok))
    lines.append('  categ: %s' % categ_complete[:80])

    # parts del complete name
    parts = categ_complete.split(' / ')
    cat_l2 = parts[1] if len(parts) >= 2 else ''
    cat_l3 = parts[2] if len(parts) >= 3 else (parts[-1] if parts else '')
    lines.append('  L2="%s"  L3="%s"' % (cat_l2, cat_l3))

    # x_calculo_abc_xyz
    Abc = env['x_calculo_abc_xyz'].sudo().search([('x_studio_product_id', '=', pid)], limit=1)
    if Abc:
        lines.append('  ABCXYZ: abcxyz=%s lifecycle=%s regimen=%s active=%s' % (
            Abc.x_studio_abcxyz or '',
            getattr(Abc, 'x_studio_ciclo_de_vida', '') or '',
            getattr(Abc, 'x_studio_regimen', '') or '',
            getattr(Abc, 'x_studio_active', getattr(Abc, 'active', '?'))
        ))
    else:
        lines.append('  NO esta en x_calculo_abc_xyz')

    # Alerta en x_price_coreccion
    Corr = env['x_price_coreccion'].sudo().search([('x_studio_product_id', '=', pid)])
    if Corr:
        for c in Corr:
            lines.append('  CORR  target=%s  tipo=%s  factor=%.3f  source=%s  razon=%s' % (
                c.x_studio_target_week_start,
                c.x_studio_tipo_alerta or '',
                c.x_studio_factor_corr or 1.0,
                getattr(c, 'x_studio_source', '') or '',
                (c.x_studio_razon or '')[:80],
            ))
    else:
        lines.append('  NO alertado en x_price_coreccion')

# Tambien: cuantos SKUs por sub-cat L3 tienen eventos
lines.append('\n--- Otros SKUs con cambio de precio en sub-cat de Royal Guard ---')
# Cervezas Tradicionales / Promocion - cualquiera con evento
import datetime as dt
env.cr.execute("SELECT (timezone('America/Santiago', now())::date)")
today = env.cr.fetchone()[0]
target = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=1)
lookback = target - dt.timedelta(weeks=52)

Ev = env['x_price_change_event'].sudo()
ev_rows = Ev.search([('x_studio_period_start', '>=', lookback)], limit=200)
sub_cat_counts = {}
for ev in ev_rows:
    try:
        pp = ev.x_studio_product_variant_id
        if not pp:
            continue
        cat_complete = pp.categ_id.complete_name or ''
        parts = cat_complete.split(' / ')
        l3 = parts[2] if len(parts) >= 3 else ''
        if l3:
            sub_cat_counts.setdefault(l3, []).append(pp.id)
    except Exception:
        pass

for l3, pids_list in sorted(sub_cat_counts.items(), key=lambda x: -len(x[1])):
    if 'Cervez' in l3:
        lines.append('  sub_cat="%s": %s SKUs con evento, ej: %s' % (l3, len(pids_list), pids_list[:5]))

try:
    log('\n'.join(lines), level='info')
except Exception:
    pass

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'Diag Cervezas Canibal',
        'message': 'Reporte en log (%s lineas)' % len(lines),
        'sticky': True,
        'type': 'info',
    }
}
