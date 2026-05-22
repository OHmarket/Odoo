# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
field_map — Introspección dinámica de campos para adaptarse a versiones de Odoo/Studio.

Contexto:
  Los scripts de OH Market corren en un entorno Studio donde los campos tienen nombres
  con prefijos x_studio_* que pueden cambiar entre instalaciones, y donde la versión
  de Odoo determina qué campos nativos existen (detailed_type vs type, crm_team_id vs team_id).

  Estas funciones permiten detectar qué campo usar sin hardcodear nombres.
"""


# ---------------------------------------------------------------------------
# Introspección de campos
# ---------------------------------------------------------------------------

def first_existing_field(model_obj, candidates):
    """
    Retorna el primer nombre de campo de candidates que existe en model_obj._fields.
    Retorna None si ninguno existe.

    Parámetros:
      model_obj: instancia del modelo Odoo (ej: env['product.template'])
      candidates: lista de strings con nombres de campo a probar en orden

    Uso:
        type_field = first_existing_field(env['product.template'], ['detailed_type', 'type'])
    """
    for fname in candidates:
        if fname in model_obj._fields:
            return fname
    return None


def first_m2o_field(model_obj, candidates, comodel_name):
    """
    Como first_existing_field pero solo acepta campos Many2one que apunten a comodel_name.

    Uso:
        team_field = first_m2o_field(env['pos.config'], ['crm_team_id', 'team_id'], 'crm.team')
    """
    for fname in candidates:
        field = model_obj._fields.get(fname)
        if field and field.type == "many2one" and field.comodel_name == comodel_name:
            return fname
    return None


def is_active_record(record):
    """
    Verifica si un registro tiene campo active y su valor es True.
    Tolerante a modelos sin campo active (retorna True en ese caso).

    Uso: filtrar registros activos sin asumir que el modelo tiene active.
    """
    if "active" in record._fields:
        return bool(record.active)
    return True


# ---------------------------------------------------------------------------
# Detección de modelos de feriados
# ---------------------------------------------------------------------------

def detect_holiday_model(env):
    """
    Detecta si existe el modelo de feriados x_holiday_occurrence en el entorno.
    Retorna el nombre del modelo si existe, None si no.

    Fallback: los scripts aceptan override manual via contexto:
      context.get('holiday_dates', [])  # lista de strings 'YYYY-MM-DD'
    """
    try:
        env["x_holiday_occurrence"]
        return "x_holiday_occurrence"
    except KeyError:
        return None


def holiday_week_counts(env, week_starts, team_ids=None, holiday_model=None,
                        manual_dates=None):
    """
    Retorna dict {week_start: {has_holiday, holiday_days, in_band_key}} para
    cada lunes en week_starts.

    Fuentes (en orden de prioridad):
      1. manual_dates: lista de strings 'YYYY-MM-DD' (override de contexto)
      2. holiday_model: nombre del modelo Studio de feriados

    Parámetros:
      week_starts: lista de datetime.date (lunes)
      team_ids: no usado actualmente (los feriados son nacionales en Chile)
      holiday_model: 'x_holiday_occurrence' u otro
      manual_dates: lista de strings 'YYYY-MM-DD'

    Retorna dict con keys = week_start (date):
      {
        'has_holiday': bool,
        'holiday_days': int,
        'in_band_key': str  # nombre del feriado más representativo de la semana
      }
    """
    from datetime import date, timedelta

    result = {ws: {"has_holiday": False, "holiday_days": 0, "in_band_key": ""} for ws in week_starts}

    # Recolectar fechas feriado
    holiday_dates_set = set()

    if manual_dates:
        for ds in manual_dates:
            try:
                parts = ds.split("-")
                holiday_dates_set.add(date(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

    elif holiday_model:
        try:
            records = env[holiday_model].search([])
            date_field = first_existing_field(records, ["x_studio_date", "x_date", "date"])
            if date_field:
                for rec in records:
                    val = getattr(rec, date_field, None)
                    if val:
                        if hasattr(val, "date"):
                            val = val.date()
                        holiday_dates_set.add(val)
        except Exception:
            pass

    # Asignar a semanas
    for ws in week_starts:
        week_end = ws + timedelta(days=6)
        count = 0
        for hd in holiday_dates_set:
            if ws <= hd <= week_end:
                count += 1
        if count > 0:
            result[ws]["has_holiday"] = True
            result[ws]["holiday_days"] = count
            result[ws]["in_band_key"] = "FERIADO"

    return result


# ---------------------------------------------------------------------------
# Put field con type checking
# ---------------------------------------------------------------------------

def put_field(vals, fields_map, fname, value, maxlen=255):
    """
    Escribe value en vals[fname] con validación de tipo según fields_map.

    fields_map: dict {fname: field_object} (ej: env['modelo']._fields)

    Si fname no está en fields_map, lo omite silenciosamente (evita error ORM).
    Si el campo es selection, normaliza a lowercase para comparación.

    Uso:
        fields_map = env['x_calculo_abc_xyz']._fields
        put_field(vals, fields_map, 'x_studio_abcxyz', 'AX')
    """
    if fname not in fields_map:
        return

    field = fields_map[fname]
    ftype = field.type

    if ftype == "char":
        vals[fname] = str(value)[:maxlen] if value is not None else False
    elif ftype == "float":
        try:
            vals[fname] = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            vals[fname] = 0.0
    elif ftype == "integer":
        try:
            vals[fname] = int(value) if value is not None else 0
        except (TypeError, ValueError):
            vals[fname] = 0
    elif ftype == "boolean":
        vals[fname] = bool(value)
    elif ftype == "date":
        vals[fname] = value  # asumir que ya es date o string 'YYYY-MM-DD'
    elif ftype == "datetime":
        vals[fname] = value
    elif ftype in ("many2one", "many2one_reference"):
        vals[fname] = int(value) if value else False
    elif ftype == "selection":
        # Normalizar: buscar valor case-insensitive en la lista de selección válida
        selection_values = [s[0] for s in (field.selection or [])]
        value_str = str(value).strip() if value is not None else ""
        matched = next((s for s in selection_values if s.lower() == value_str.lower()), None)
        vals[fname] = matched if matched else False
    else:
        vals[fname] = value
