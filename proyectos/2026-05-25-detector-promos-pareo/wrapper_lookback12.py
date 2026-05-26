# ============================================================
# SA Wrapper: Detector v5.9 con lookback_promo = 12 sem
# ------------------------------------------------------------
# El feed x_loyalty_promo_event esta cerrado en 2026-04-27 (no hay
# eventos en mayo). Para validar que v5.9 emite PROMO_PAREO_MODERADO,
# ampliamos el lookback temporalmente a 12 semanas (captura mar-abr).
#
# Settings -> Technical -> Server Actions -> New
# Model: res.users (cualquiera). Type: Execute Python Code.
# Pega este codigo. Action -> Run.
# ============================================================

# Busca el detector por nombre (sin hardcodear ID)
act = env['ir.actions.server'].sudo().search([
    ('name', 'ilike', 'Price Correccion'),
], limit=2)

if not act:
    raise ValueError("No se encontro SA 'Price Correccion'")
if len(act) > 1:
    raise ValueError("Multiples SAs 'Price Correccion': %s" % act.ids)

# Ejecutar con lookback 12 semanas
action = act.with_context(lookback_promo_weeks=12).run()

if not action:
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'Detector v5.9 - lookback 12 sem',
            'message': 'Detector corrido con lookback_promo=12 (captura mar-abr).',
            'type': 'success',
            'sticky': True,
        },
    }
