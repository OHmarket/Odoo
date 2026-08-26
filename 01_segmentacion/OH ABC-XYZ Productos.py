# === ABC/XYZ → product.template (SOLO UI: ABC, XYZ, Rank, Actualizado) ===
# Fuente: x_calculo_abc_xyz
# Destino: product.template
# - GLOBAL (sin team; tu modelo no tiene x_studio_team_id)
# - Escribe SOLO si cambia
# - Normaliza ABC/XYZ a A/B/C y X/Y/Z
# - SAFE_EVAL friendly: NO usa getattr

ONLY_SALE_OK_DEFAULT = True
ONLY_ACTIVE_DEFAULT  = True

CTX = env.context or {}
ONLY_SALE_OK = CTX.get('only_sale_ok', ONLY_SALE_OK_DEFAULT) is True
ONLY_ACTIVE  = CTX.get('only_active',  ONLY_ACTIVE_DEFAULT)  is True

company = env.company

# Now UTC
env.cr.execute("SELECT (NOW() AT TIME ZONE 'UTC')::timestamp")
_now_utc = env.cr.fetchone()[0]

Cal = env['x_calculo_abc_xyz'].sudo()
cal_fields = Cal._fields

dom = [('x_studio_company_id', '=', company.id)]
if 'x_active' in cal_fields:
    dom.append(('x_active', '=', True))

order = 'id asc'
if 'x_studio_sequence' in cal_fields:
    order = 'x_studio_sequence asc, id asc'

# Leemos registros
cal_recs = Cal.search(dom, order=order)

# Campos que vamos a leer desde el modelo (solo los que existan)
to_read = ['x_studio_product_id']
if 'x_studio_abc' in cal_fields:
    to_read.append('x_studio_abc')
if 'x_studio_xyz' in cal_fields:
    to_read.append('x_studio_xyz')
if 'x_studio_sequence' in cal_fields:
    to_read.append('x_studio_sequence')

rows = cal_recs.read(to_read)

# best por template: como ya vienen ordenados por sequence asc, el primero que aparece gana
best = {}  # tid -> {'abc':..,'xyz':..,'rank':..}
for r in rows:
    pid = r.get('x_studio_product_id')
    if not pid:
        continue
    tid = pid[0]
    if tid in best:
        continue

    best[tid] = {
        'abc': r.get('x_studio_abc'),
        'xyz': r.get('x_studio_xyz'),
        'rank': r.get('x_studio_sequence') or 0,
    }

PT = env['product.template'].sudo()
pt_fields = PT._fields

fname_abc        = 'x_studio_categoria_abc_1' if 'x_studio_categoria_abc_1' in pt_fields else None
fname_xyz        = 'x_studio_xyz_company'     if 'x_studio_xyz_company'     in pt_fields else None
fname_updated_on = 'x_studio_abc_updated_on'  if 'x_studio_abc_updated_on'  in pt_fields else None

fname_rank = None
for cand in (
    'x_studio_abcxyz_company_rank',
    'x_studio_abcyz_company_rank',
    'x_studio_top_abcxyz',
    'x_studio_top_abcyz',
    'x_studio_company_rank',
    'x_studio_rank',
):
    if cand in pt_fields:
        fname_rank = cand
        break

written = 0
skipped = 0

for tid, info in best.items():
    pt = PT.browse(tid)
    if not pt.exists():
        skipped += 1
        continue

    if ONLY_ACTIVE and (not pt.active):
        skipped += 1
        continue

    if ONLY_SALE_OK and ('sale_ok' in pt_fields) and (not pt.sale_ok):
        skipped += 1
        continue

    abc = (info.get('abc') or '')
    xyz = (info.get('xyz') or '')

    abc = (abc.strip().upper()) if isinstance(abc, str) else ''
    xyz = (xyz.strip().upper()) if isinstance(xyz, str) else ''

    if abc not in ('A', 'B', 'C'):
        abc = False
    if xyz not in ('X', 'Y', 'Z'):
        xyz = False

    vals = {}
    if fname_abc:        vals[fname_abc]        = abc
    if fname_xyz:        vals[fname_xyz]        = xyz
    if fname_rank:       vals[fname_rank]       = int(info.get('rank') or 0)
    if fname_updated_on: vals[fname_updated_on] = _now_utc

    changed = {}
    for k, v in vals.items():
        if pt[k] != v:
            changed[k] = v

    if changed:
        pt.write(changed)
        written += 1
    else:
        skipped += 1

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'ABC/XYZ → Productos',
        'message': "Actualizados %s productos (omitidos %s)." % (written, skipped),
        'sticky': False,
        'type': 'success' if written else 'warning',
    }
}
