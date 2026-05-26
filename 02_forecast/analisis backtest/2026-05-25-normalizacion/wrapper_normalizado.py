# ============================================================
# SA Wrapper: ejecutar OH Forecast Backtest con normalizacion
# ------------------------------------------------------------
# Crea este Server Action en Odoo (Settings -> Technical -> Server
# Actions -> New). Asociado a cualquier modelo (ej: res.users).
#
# Permite correr el Backtest con flag use_demand_normalization=True
# sin necesidad de pasar context manual via UI.
#
# Busca el SA "OH Forecast Backtest" por nombre, no por ID.
# ============================================================

act = env['ir.actions.server'].sudo().search([
    ('name', 'ilike', 'OH Forecast Backtest'),
], limit=2)

if not act:
    raise ValueError("No se encontro Server Action con nombre 'OH Forecast Backtest'")
if len(act) > 1:
    raise ValueError("Hay %s Server Actions con nombre similar a 'OH Forecast Backtest'. Ambiguo. IDs=%s" % (
        len(act), act.ids))

action = act.with_context(use_demand_normalization=True).run()

# El backtest ya devuelve su propia notificacion. Si no, le ponemos una.
if not action:
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'Backtest NORMALIZADO disparado',
            'message': 'OH Forecast Backtest corrio con use_demand_normalization=True',
            'type': 'success',
            'sticky': True,
        },
    }
