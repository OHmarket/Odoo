# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
calendar_rules — Reglas del calendario OH Market.

Estándares:
- Semana: lunes (weekday 0) → domingo (weekday 6).
- LY comparable: d - 364 días (52 semanas exactas, mismo weekday).
- ISO week: número de semana ISO 1-53 calculado desde el lunes de semana.

Bandas estacionales definidas por semana ISO (uso en OH Analisis Ventas SKU):
  VERANO_ALTO     semanas 1-3, 52-53
  VERANO_MEDIO    semanas 4-8
  VERANO_BAJO     semanas 9-12
  FIESTAS_PATRIAS semanas 37-38
  HALLOWEEN       semanas 43-44
  FIN_ANIO        semanas 49-51
  BASE            resto
"""

from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SEASONAL_BANDS = {
    "VERANO_ALTO":     list(range(1, 4)) + list(range(52, 54)),
    "VERANO_MEDIO":    list(range(4, 9)),
    "VERANO_BAJO":     list(range(9, 13)),
    "FIESTAS_PATRIAS": list(range(37, 39)),
    "HALLOWEEN":       list(range(43, 45)),
    "FIN_ANIO":        list(range(49, 52)),
}


# ---------------------------------------------------------------------------
# Semana OH (lunes-domingo)
# ---------------------------------------------------------------------------

def oh_week_start(d):
    """Retorna el lunes de la semana de d."""
    return d - timedelta(days=d.weekday())


def oh_week_end(d):
    """Retorna el domingo de la semana de d."""
    return oh_week_start(d) + timedelta(days=6)


def oh_iso_week(week_start):
    """
    Retorna el número de semana ISO (1-53) a partir del lunes de semana.
    Usa la definición ISO 8601: la semana que contiene el primer jueves del año.
    """
    return week_start.isocalendar()[1]


def oh_iso_year(week_start):
    """Retorna el año ISO de la semana (puede diferir del año calendario en semana 1/53)."""
    return week_start.isocalendar()[0]


# ---------------------------------------------------------------------------
# LY comparable
# ---------------------------------------------------------------------------

def ly_364(d):
    """
    Retorna d - 364 días (52 semanas exactas).
    Garantiza el mismo weekday que d, sin desplazamiento.
    Estándar OH para comparar períodos equivalentes YoY.
    """
    return d - timedelta(days=364)


def ly_week_start(week_start):
    """Retorna el lunes de la semana equivalente LY (week_start - 364 días)."""
    return ly_364(week_start)


def ly_month_approx(month_start):
    """
    Retorna el inicio aproximado del mes equivalente LY.
    Usa -364 días como aproximación del mismo weekday.
    Para análisis mensual exacto, comparar por nombre de mes en año anterior.
    """
    return ly_364(month_start)


# ---------------------------------------------------------------------------
# Iteradores
# ---------------------------------------------------------------------------

def iter_week_starts(d1, d2):
    """
    Genera todos los lunes en el rango [d1, d2].
    d1 se ajusta al lunes de su semana si no es lunes.
    """
    current = oh_week_start(d1)
    while current <= d2:
        yield current
        current += timedelta(weeks=1)


def iter_month_starts(d1, d2):
    """Genera todos los primeros días de mes en el rango [d1, d2]."""
    current = d1.replace(day=1)
    while current <= d2:
        yield current
        year = current.year + (current.month // 12)
        month = (current.month % 12) + 1
        current = current.replace(year=year, month=month, day=1)


# ---------------------------------------------------------------------------
# Mes
# ---------------------------------------------------------------------------

def month_start(d):
    """Retorna el primer día del mes de d."""
    return d.replace(day=1)


def month_end(d):
    """Retorna el último día del mes de d."""
    next_month = month_start(d).replace(month=d.month % 12 + 1) if d.month < 12 \
        else date(d.year + 1, 1, 1)
    return next_month - timedelta(days=1)


# ---------------------------------------------------------------------------
# Bandas estacionales
# ---------------------------------------------------------------------------

def seasonal_band(week_start):
    """
    Retorna la banda estacional para la semana dada.
    Retorna 'BASE' si no coincide con ninguna banda especial.
    """
    iso_w = oh_iso_week(week_start)
    for band, weeks in SEASONAL_BANDS.items():
        if iso_w in weeks:
            return band
    return "BASE"


def is_base_week(week_start):
    """True si la semana no pertenece a ninguna banda estacional especial."""
    return seasonal_band(week_start) == "BASE"
