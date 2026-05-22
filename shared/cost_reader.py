# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
cost_reader — Lectura de costo real del producto con manejo de impuestos.

Contexto OH Market:
- raw_product_price: campo Studio con el precio de costo neto operativo.
  Si es 0 o no existe, se usa standard_price como fallback.
- ILA (Impuesto de Lujo/Adicional): impuesto de compra que se suma al costo.
- IVA compra (19%): impuesto de compra recuperable (no se suma al costo OH).
- El costo OH = costo_neto × (1 + factor_ILA).

Nota sobre cigarrillos:
  Los productos cigarrillo tienen reglas de ILA especiales con tasas distintas.
  Detectar via product.category antes de calcular.
"""


# ---------------------------------------------------------------------------
# Flatten de impuestos (recursivo)
# ---------------------------------------------------------------------------

def flatten_taxes(tax_record):
    """
    Descompone recursivamente un account.tax en lista plana de impuestos leaf.
    Maneja grupos de impuestos (type_tax_use='none' que agrupan otros).

    Retorna lista de dicts:
      [{id, name, amount, amount_type, price_include, type_tax_use}, ...]
    """
    result = []
    if not tax_record:
        return result

    if tax_record.amount_type == "group" and tax_record.children_tax_ids:
        for child in tax_record.children_tax_ids:
            result.extend(flatten_taxes(child))
    else:
        result.append({
            "id": tax_record.id,
            "name": tax_record.name or "",
            "amount": tax_record.amount,
            "amount_type": tax_record.amount_type,
            "price_include": tax_record.price_include,
            "type_tax_use": tax_record.type_tax_use,
        })
    return result


# ---------------------------------------------------------------------------
# Detección IVA / ILA
# ---------------------------------------------------------------------------

_ILA_KEYWORDS = ("ila", "adicional", "lujo", "específico")
_NO_RECUPERABLE_KEYWORDS = ("no recuperable", "uso común", "uso comun", "parcial")


def is_ila_tax(tax_dict):
    """True si el impuesto es tipo ILA (impuesto adicional/lujo)."""
    name_lower = (tax_dict.get("name") or "").lower()
    return any(kw in name_lower for kw in _ILA_KEYWORDS)


def is_no_recuperable(tax_dict):
    """True si el impuesto es de uso común/no recuperable."""
    name_lower = (tax_dict.get("name") or "").lower()
    return any(kw in name_lower for kw in _NO_RECUPERABLE_KEYWORDS)


def iva_compra_factor(product):
    """
    Detecta el factor multiplicador de IVA en supplier_taxes_id del producto.
    Retorna el factor (ej: 1.19 para IVA 19%) o 1.0 si no hay IVA compra.
    Solo considera impuestos tipo 'percent' no-ILA.
    """
    factor = 1.0
    for tax in product.supplier_taxes_id:
        for t in flatten_taxes(tax):
            if (t["amount_type"] == "percent"
                    and not is_ila_tax(t)
                    and not is_no_recuperable(t)
                    and t["amount"] > 0):
                factor *= 1.0 + t["amount"] / 100.0
    return factor


def sum_ila_factor(product):
    """
    Suma los factores ILA en supplier_taxes_id del producto.
    Retorna el factor multiplicador acumulado (ej: 1.27 si ILA=27%).
    Retorna 1.0 si no hay ILA.
    """
    factor = 1.0
    for tax in product.supplier_taxes_id:
        for t in flatten_taxes(tax):
            if is_ila_tax(t) and t["amount_type"] == "percent" and t["amount"] > 0:
                factor *= 1.0 + t["amount"] / 100.0
    return factor


# ---------------------------------------------------------------------------
# Costo OH
# ---------------------------------------------------------------------------

def raw_to_cost_net(product, fallback_to_standard=True):
    """
    Lee raw_product_price del producto.
    Si es 0 o el campo no existe, usa standard_price como fallback.

    Retorna (cost_net, flag_raw_zero, flag_fallback):
      cost_net: costo neto por unidad
      flag_raw_zero: True si raw_product_price era 0
      flag_fallback: True si se usó standard_price
    """
    raw = getattr(product, "x_studio_raw_product_price", 0.0) or 0.0
    flag_raw_zero = raw == 0.0
    flag_fallback = False

    if flag_raw_zero and fallback_to_standard:
        raw = product.standard_price or 0.0
        flag_fallback = True

    return raw, flag_raw_zero, flag_fallback


def cost_oh_unit(product, fallback_to_standard=True):
    """
    Calcula el costo OH por unidad:
      costo_neto × factor_ILA

    El IVA de compra es recuperable para OH Market, por lo que no se suma al costo.

    Retorna dict con todos los componentes:
      {cost_net, ila_factor, cost_oh, flag_raw_zero, flag_fallback}
    """
    cost_net, flag_raw_zero, flag_fallback = raw_to_cost_net(product, fallback_to_standard)
    ila = sum_ila_factor(product)

    return {
        "cost_net": cost_net,
        "ila_factor": ila,
        "cost_oh": cost_net * ila,
        "flag_raw_zero": flag_raw_zero,
        "flag_fallback": flag_fallback,
    }
