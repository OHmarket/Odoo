"""Conciliacion de completitud Odoo <-> RCV del SII. Funcion pura."""


def clave(rut, tipo, folio):
    """Normaliza identidad: rut solo digitos (cuerpo+DV), tipo str, folio sin ceros."""
    r = ''.join(c for c in str(rut) if c.isdigit())
    t = str(tipo).strip()
    f = str(folio).strip().lstrip('0') or '0'
    return (r, t, f)


def conciliar(sii_keys, odoo_keys):
    s = set(sii_keys)
    o = set(odoo_keys)
    return {
        'faltan_en_odoo': sorted(s - o),  # en SII, no en Odoo -> ROJO completitud
        'sobran_en_odoo': sorted(o - s),  # en Odoo, no en SII -> revisar
    }
