# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
stock_reader — Mapeo entre equipos (sucursales) y almacenes Odoo.

Contexto:
  En OH Market cada sucursal (crm.team) tiene un almacén asociado (stock.warehouse).
  La fuente primaria del mapeo es pos.config (campo crm_team_id o team_id → warehouse_id).
  El FALLBACK_MAP es un dict hardcoded para casos en que pos.config no tiene el mapeo.

  IDs de referencia (productivo):
    CENTRAL_WAREHOUSE_ID = 15
    CENTRAL_TEAM_ID      = 26
"""

# ---------------------------------------------------------------------------
# Fallback hardcoded (actualizar si cambian los IDs en producción)
# ---------------------------------------------------------------------------

TEAM_WAREHOUSE_MAP_FALLBACK = {
    # team_id: warehouse_id
    # Completar con los IDs reales del entorno productivo
    # Ejemplo: 18: 5, 16: 3, 17: 4, ...
}

CENTRAL_WAREHOUSE_ID = 15
CENTRAL_TEAM_ID = 26


# ---------------------------------------------------------------------------
# Construcción del mapa team → warehouse
# ---------------------------------------------------------------------------

def build_team_warehouse_map(env, team_field="crm_team_id", fallback=None):
    """
    Construye dict {team_id: warehouse_id} leyendo pos.config.

    Parámetros:
      team_field: 'crm_team_id' (v14+) o 'team_id' (v13)
      fallback: dict de fallback adicional (se fusiona; pos.config tiene prioridad)

    Retorna dict {int: int}.
    """
    result = dict(fallback or TEAM_WAREHOUSE_MAP_FALLBACK)

    configs = env["pos.config"].search([
        (team_field, "!=", False),
        ("warehouse_id", "!=", False),
    ])
    for cfg in configs:
        team_id = getattr(cfg, team_field).id
        wh_id = cfg.warehouse_id.id
        if team_id and wh_id:
            result[team_id] = wh_id

    return result


# ---------------------------------------------------------------------------
# Helpers de ubicaciones
# ---------------------------------------------------------------------------

def _get_wh(wh_id, env):
    """Retorna el browse del warehouse o raise si no existe."""
    wh = env["stock.warehouse"].browse(wh_id)
    if not wh.exists():
        raise ValueError("Warehouse ID %s no encontrado" % wh_id)
    return wh


def get_stock_loc_from_wh(wh_id, env):
    """
    Retorna el ID de la ubicación interna principal (lot_stock_id) del warehouse.
    Es la ubicación donde se cuenta el stock disponible.
    """
    return _get_wh(wh_id, env).lot_stock_id.id


def get_in_type_from_wh(wh_id, env):
    """
    Retorna el ID del picking type 'incoming' del warehouse.
    Usado para recepciones de compra.
    """
    wh = _get_wh(wh_id, env)
    for pt in env["stock.picking.type"].search([
        ("warehouse_id", "=", wh.id),
        ("code", "=", "incoming"),
    ]):
        return pt.id
    raise ValueError("Picking type incoming no encontrado para warehouse %s" % wh_id)


def get_internal_type_from_wh(wh_id, env):
    """
    Retorna el ID del picking type 'internal' del warehouse.
    Usado para traslados entre ubicaciones del mismo almacén.
    """
    wh = _get_wh(wh_id, env)
    for pt in env["stock.picking.type"].search([
        ("warehouse_id", "=", wh.id),
        ("code", "=", "internal"),
    ]):
        return pt.id
    raise ValueError("Picking type internal no encontrado para warehouse %s" % wh_id)


# ---------------------------------------------------------------------------
# Validación UoM compra (caja)
# ---------------------------------------------------------------------------

def is_purchase_uom_box(product):
    """
    Verifica que la UoM de compra del producto no sea la misma que la UoM base.
    En OH Market, la compra debe ser en cajas (UoM distinta a la unidad base).

    Retorna True si la UoM de compra es válida (no es la misma que la UoM interna).
    Retorna False si el producto usa la misma UoM para compra y venta (sin caja).
    """
    uom_po = product.uom_po_id
    uom_base = product.uom_id
    if not uom_po or not uom_base:
        return False
    return uom_po.id != uom_base.id
