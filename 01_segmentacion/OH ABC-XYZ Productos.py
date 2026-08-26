# === ABC/XYZ → product.template (SOLO UI: ABC, XYZ, Rank, Actualizado) ===
# Fuente: x_calculo_abc_xyz   (una fila por VARIANTE product.product)
# Destino: product.template
# - GLOBAL (sin team; el modelo no tiene x_studio_team_id)
# - Escribe SOLO si cambia; RESET total de templates fuera del calculo
# - Normaliza ABC/XYZ a A/B/C y X/Y/Z
# - SAFE_EVAL friendly: NO usa getattr
#
# v2 (2026-08-26): corrige el writer de Rank ABC/XYZ.
#   [1] variante->template: x_studio_product_id es product.product (VARIANTE).
#       Antes se usaba pid[0] (id de variante) como id de template -> los ranks
#       caian en el template equivocado. Ahora se mapea variante->product_tmpl_id.
#   [2] rank: se lee x_studio_rank_abcxyz (Ranking ABCXYZ), no x_studio_sequence
#       (hoy coinciden 1..N, pero el campo semantico correcto es rank_abcxyz).
#   [3] ABC: el campo destino real es x_studio_categora_abc_1 (typo Studio, sin
#       'i'). El nombre 'categoria_abc_1' no existe -> antes ABC nunca se escribia.
#   [4] reset total: templates con abc/xyz/rank seteado que ya NO estan en el
#       calculo vigente se limpian (abc/xyz=False, rank=0, updated_on=False).

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

cal_recs = Cal.search(dom, order=order)

# [2] Fuente del rank: Ranking ABCXYZ real; fallback a la secuencia.
rank_src = None
for cand in ('x_studio_rank_abcxyz', 'x_studio_sequence'):
    if cand in cal_fields:
        rank_src = cand
        break

to_read = ['x_studio_product_id']
if 'x_studio_abc' in cal_fields:
    to_read.append('x_studio_abc')
if 'x_studio_xyz' in cal_fields:
    to_read.append('x_studio_xyz')
if rank_src:
    to_read.append(rank_src)

rows = cal_recs.read(to_read)

# --- [1] map variante (product.product) -> template (product.template) -------
PP = env['product.product'].sudo()
variant_ids = []
for r in rows:
    pid = r.get('x_studio_product_id')
    if pid:
        variant_ids.append(pid[0])
variant_ids = list(set(variant_ids))

v2t = {}
if variant_ids:
    for p in PP.browse(variant_ids).exists().read(['product_tmpl_id']):
        t = p.get('product_tmpl_id')
        if t:
            v2t[p['id']] = t[0]

# best por template: si un template tuviera >1 variante, gana el de menor rank.
best = {}  # tid -> {'abc','xyz','rank'}
for r in rows:
    pid = r.get('x_studio_product_id')
    if not pid:
        continue
    tid = v2t.get(pid[0])
    if not tid:
        continue
    rank = int(r.get(rank_src) or 0) if rank_src else 0
    prev = best.get(tid)
    if prev is None or (rank > 0 and (prev['rank'] == 0 or rank < prev['rank'])):
        best[tid] = {
            'abc': r.get('x_studio_abc'),
            'xyz': r.get('x_studio_xyz'),
            'rank': rank,
        }

PT = env['product.template'].sudo()
pt_fields = PT._fields

# [3] destino ABC: campo real con typo Studio 'categora' (sin 'i').
fname_abc = None
for cand in ('x_studio_categora_abc_1', 'x_studio_categoria_abc_1'):
    if cand in pt_fields:
        fname_abc = cand
        break

fname_xyz        = 'x_studio_xyz_company'    if 'x_studio_xyz_company'    in pt_fields else None
fname_updated_on = 'x_studio_abc_updated_on' if 'x_studio_abc_updated_on' in pt_fields else None

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

# --- [4] RESET total: limpiar templates fuera del calculo vigente ------------
reset_count = 0
ors = []
if fname_rank: ors.append((fname_rank, '!=', 0))
if fname_abc:  ors.append((fname_abc, '!=', False))
if fname_xyz:  ors.append((fname_xyz, '!=', False))
if ors:
    reset_domain = (['|'] * (len(ors) - 1)) + ors
    # active_test=False: alcanzar tambien templates archivados con valor stale.
    candidates = PT.with_context(active_test=False).search(reset_domain)
    reset_ids = [t for t in candidates.ids if t not in best]
    if reset_ids:
        reset_vals = {}
        if fname_abc:        reset_vals[fname_abc]        = False
        if fname_xyz:        reset_vals[fname_xyz]        = False
        if fname_rank:       reset_vals[fname_rank]       = 0
        if fname_updated_on: reset_vals[fname_updated_on] = False
        PT.browse(reset_ids).write(reset_vals)
        reset_count = len(reset_ids)

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'ABC/XYZ → Productos',
        'message': "Escritos %s | Reseteados %s | Omitidos %s." % (written, reset_count, skipped),
        'sticky': False,
        'type': 'success' if (written or reset_count) else 'warning',
    }
}
