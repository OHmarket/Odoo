# ============================================================
# INSPECCION del modelo x_demanda_normalizada (READ-ONLY)
# ------------------------------------------------------------
# Pega en Server Action 1570, model = x_demanda_normalizada.
# Devuelve la lista de campos tecnicos para confirmar antes de Fase 2.
# ============================================================

TARGET_MODEL = 'x_demanda_normalizada'

# Campos esperados (logico -> tecnico esperado)
ESPERADOS = [
    'x_studio_team_id', 'x_studio_product_id', 'x_studio_week_start',
    'x_studio_qty_obs', 'x_studio_qty_norm', 'x_studio_factor', 'x_studio_avail',
    'x_studio_n_so', 'x_studio_perfil_level', 'x_studio_metodo',
    'x_studio_run_id', 'x_studio_version_id',
]

info = env[TARGET_MODEL].fields_get()
existentes = sorted(info.keys())

# Solo campos custom (excluir id, create_date, write_date, etc.)
custom = [f for f in existentes if f.startswith('x_')]

faltantes = [f for f in ESPERADOS if f not in info]
extras    = [f for f in custom if f not in ESPERADOS]

# Detalles utiles por campo
detalles = []
for f in sorted(custom):
    d = info[f]
    line = '%s | %s' % (f, d.get('type'))
    if d.get('type') == 'many2one':
        line += ' -> ' + str(d.get('relation'))
    if d.get('type') == 'selection':
        line += ' values=' + str([v[0] for v in (d.get('selection') or [])])
    detalles.append(line)

msg = 'Modelo OK: %s campos custom | Faltantes: %s | Extras: %s' % (
    len(custom), faltantes or 'ninguno', extras or 'ninguno')

for d in detalles:
    log('FIELD ' + d, level='info')
log('FALTANTES: ' + str(faltantes), level='warning' if faltantes else 'info')
log('EXTRAS: ' + str(extras), level='info')

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'Inspect x_demanda_normalizada',
        'message': msg,
        'type': 'success' if not faltantes else 'danger',
        'sticky': True,
    },
}
