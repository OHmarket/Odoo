# ============================================================
# OH - FIX default_code (formato DTE proveedor)  [camino NORKOSHE]
#
#   Las facturas de proveedor vinculan por  product.default_code == <VlrCodigo>
#   del DTE (EXACTO, espacio incluido). A un subconjunto de SKU NORKOSHE se les
#   creo el default_code SIN el espacio (ej. "87910") mientras el DTE manda
#   "8791 0" -> nunca vinculan (la linea queda como texto libre y el costo no se
#   captura). Otros SKU del mismo proveedor se crearon CON espacio y vinculan ok.
#
#   Este script corrige el default_code al formato del DTE (le pone el espacio).
#   El mapa es explicito porque la posicion del espacio varia (sufijo 1 o 2
#   digitos: "87910"->"8791 0", "700219"->"7002 19").
#
#   Efecto: las facturas FUTURAS de esos SKU vinculan solas. Las lineas libres
#   historicas NO se re-vinculan (eso es un reproceso aparte).
#
#   Resguardos: dry_run (def True); no toca si el default_code destino ya existe
#   (colision) o si el origen no existe / esta duplicado.
#
#   Params: fix_dry_run (def True)
# ============================================================

VERSION_ID = "OH_FIX_DEFAULT_CODE_v1_NORKOSHE"

def _ctx_bool(v, default=False):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ('1', 'true', 't', 'yes', 'y', 'si', 'on'):
        return True
    if s in ('0', 'false', 'f', 'no', 'n', 'off'):
        return False
    return default

DRY_RUN = _ctx_bool(env.context.get('fix_dry_run'), True)

# (default_code_actual, default_code_correcto)  -- formato DTE con espacio
MAP = [
    ('35720', '3572 0'),   # GALLETA ALTEZA FRUTILLA MCKAY 140
    ('36290', '3629 0'),   # GALLETA TRENCITO CHOCOBISCUIT 78 G
    ('36310', '3631 0'),   # GALLETA MCKAY CRIOLLITAS 80 G
    ('36760', '3676 0'),   # GALLETA TRITON VAINILLA MCKAY 116
    ('36800', '3680 0'),   # GALLETA TRITON CHOCOLATE MCKAY 116
    ('36960', '3696 0'),   # GALLETA MCKAY ALTEZA CHOCOLATE VAI
    ('41120', '4112 0'),   # GALLETA KUKY CHIP CHIPERS CHOCOLAT
    ('59010', '5901 0'),   # GALLETA MCKAY GRILL CLASICA 140 G
    ('700219', '7002 19'), # ESPUMANTE VINAMAR ROSE 750 CC
    ('70220', '7022 0'),   # CHOCOLATE SAHNE NUSS TRADICIONAL
    ('7410', '741 0'),     # CHOCOLATE CAPRI FRUTILLA 30 G
    ('7560', '756 0'),     # CHOCOLATE CAPRI ALMENDRA 30 G
    ('7570', '757 0'),     # CHOCOLATE TRENCITO 24 G
    ('8030', '803 0'),     # GALLETA MCKAY CRIOLLITAS 120 G
    ('81160', '8116 0'),   # GALLETA KUKY CLASICA 120 G
    ('81170', '8117 0'),   # GALLETA KUKY CHOCOLATE 120 G
    ('81990', '8199 0'),   # GALLETA MCKAY NIZA 150 G
    ('83840', '8384 0'),   # GALLETA MCKAY DE VINO 155 G
    ('83950', '8395 0'),   # GALLETA MCKAY MANTEQUILLA 140 G
    ('8410', '841 0'),     # GALLETA TRENCITO 130 G
    ('86640', '8664 0'),   # GALLETA MCKAY SODA CLASICA 180 G
    ('87870', '8787 0'),   # CHOCOLATE PRESTIGIO 35 G
    ('87890', '8789 0'),   # CHOCOLATE SAHNE NUSS 14 G
    ('87910', '8791 0'),   # OBLEA SUPER 8 29 G
    ('89180', '8918 0'),   # GALLETA MCKAY GRILL 35 G
    ('94480', '9448 0'),   # OBLEA KIT KAT CHOCOLATE DE LECHE
    ('96050', '9605 0'),   # OBLEA CHOKITA 30 G
]

Product = env['product.product'].sudo()

changed = []
skipped = []

for old, new in MAP:
    prods = Product.search([('default_code', '=', old)])
    if not prods:
        skipped.append("%s: origen no existe" % old)
        continue
    if len(prods) > 1:
        skipped.append("%s: %s productos con ese codigo (ambiguo)" % (old, len(prods)))
        continue
    coll = Product.search([('default_code', '=', new)])
    if coll:
        skipped.append("%s -> %s: destino ya existe (colision)" % (old, new))
        continue
    p = prods[0]
    if not DRY_RUN:
        p.write({'default_code': new})
    changed.append("%s -> %s | %s" % (old, new, (p.display_name or '')[:40]))

msg = "v=%s | DRY_RUN=%s | a corregir=%s | omitidos=%s" % (
    VERSION_ID, int(DRY_RUN), len(changed), len(skipped))
if changed:
    msg += "\n-- CAMBIOS:"
    for c in changed:
        msg += "\n  " + c
if skipped:
    msg += "\n-- OMITIDOS:"
    for s in skipped:
        msg += "\n  " + s

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'OH Fix default_code (NORKOSHE)',
        'message': msg,
        'type': 'success' if changed else 'warning',
        'sticky': True,
    }
}
