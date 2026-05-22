# ============================================================
# REFERENCIA — No importable desde safe_eval Server Actions.
# Usar como plantilla al refactorizar o migrar a módulo Odoo.
# ============================================================
"""
odoo_safe_eval_helpers — Utilidades genéricas para scripts bajo safe_eval.

Diseñadas para funcionar sin imports externos (solo stdlib datetime).
Todas las funciones son copy-paste friendly: no tienen dependencias entre sí
y pueden incluirse individualmente en cualquier Server Action.

Patrones incluidos:
  - Conversiones seguras de tipo
  - Parseo de contexto de server action
  - Batch create
  - Advisory lock (PostgreSQL)
  - Delete SQL directo
  - Dry-run guard
  - Notificaciones Odoo
"""


# ---------------------------------------------------------------------------
# Conversiones seguras de tipo
# ---------------------------------------------------------------------------

def _safe_float(v, default=0.0):
    """Convierte v a float. Retorna default si falla o si v es None/False."""
    if v is None or v is False:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    """Convierte v a int. Retorna default si falla."""
    if v is None or v is False:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_text(v, maxlen=255):
    """Convierte v a string y trunca a maxlen caracteres."""
    if v is None or v is False:
        return ""
    try:
        return str(v)[:maxlen]
    except Exception:
        return ""


def _safe_bool(v, default=False):
    """Convierte v a bool de forma tolerante."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "si", "sí")
    return bool(v)


def safe_div(num, den, default=0.0):
    """División segura. Retorna default si den es 0 o None."""
    if not den:
        return default
    try:
        return float(num) / float(den)
    except (TypeError, ZeroDivisionError):
        return default


# ---------------------------------------------------------------------------
# Parseo de contexto de server action
# ---------------------------------------------------------------------------

def _ctx_bool(ctx, key, default=False):
    """
    Extrae un bool del contexto de server action.
    Acepta bool, int (0/1) y strings ('true'/'false'/'1'/'0').
    """
    if key not in ctx:
        return default
    return _safe_bool(ctx[key], default)


def _to_int_list(v):
    """
    Convierte v a lista de enteros.
    Acepta: lista, tupla, string CSV '1,2,3', int único.
    Retorna [] si v es None/False/vacío.
    """
    if not v:
        return []
    if isinstance(v, (list, tuple)):
        result = []
        for x in v:
            try:
                result.append(int(x))
            except (TypeError, ValueError):
                pass
        return result
    if isinstance(v, int):
        return [v]
    if isinstance(v, str):
        result = []
        for part in v.split(","):
            part = part.strip()
            if part:
                try:
                    result.append(int(part))
                except ValueError:
                    pass
        return result
    return []


# ---------------------------------------------------------------------------
# Batch create
# ---------------------------------------------------------------------------

def batch_create(env, model_name, vals_list, batch_size=500):
    """
    Crea registros en lotes para evitar memory bloat.

    Parámetros:
      env: entorno Odoo
      model_name: string (ej: 'x_pos_week_sku_sale')
      vals_list: lista de dicts
      batch_size: tamaño de cada lote (default 500)

    Retorna: total de registros creados.
    """
    model = env[model_name]
    total = 0
    for i in range(0, len(vals_list), batch_size):
        batch = vals_list[i:i + batch_size]
        model.create(batch)
        total += len(batch)
    return total


# ---------------------------------------------------------------------------
# Advisory lock (PostgreSQL)
# ---------------------------------------------------------------------------

def acquire_advisory_lock(cr, lock_key):
    """
    Intenta obtener un advisory lock de PostgreSQL.

    Retorna True si se obtuvo el lock, False si ya está tomado (otra instancia corriendo).
    El lock es a nivel de sesión: se libera automáticamente al cerrar la conexión
    o al llamar release_advisory_lock().

    Patrón de uso:
        if not acquire_advisory_lock(env.cr, LOCK_KEY):
            raise UserError("Otro proceso está corriendo. Intente más tarde.")
        try:
            # ... lógica del script ...
        finally:
            release_advisory_lock(env.cr, LOCK_KEY)
    """
    cr.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
    return cr.fetchone()[0]


def release_advisory_lock(cr, lock_key):
    """
    Libera un advisory lock de PostgreSQL.
    Llamar siempre en bloque finally para garantizar la liberación.
    """
    cr.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))


# ---------------------------------------------------------------------------
# Delete SQL directo
# ---------------------------------------------------------------------------

def delete_range_sql(cr, table_name, date_field, date_from, date_to,
                     team_field=None, team_ids=None):
    """
    DELETE SQL directo sin ORM para borrar registros en un rango de fechas.

    Más eficiente que search+unlink para modelos Studio sin lógica de negocio.

    Parámetros:
      table_name: nombre de la tabla SQL (ej: 'x_pos_week_sku_sale')
      date_field: nombre de la columna de fecha (ej: 'x_studio_iso_week_start')
      date_from, date_to: datetime.date límites inclusivos
      team_field: columna de team_id (opcional, filtrar por equipo)
      team_ids: lista de int (requerido si team_field está presente)
    """
    if team_field and team_ids:
        team_ids_literal = ",".join(str(t) for t in team_ids)
        cr.execute(
            """
            DELETE FROM {table}
            WHERE {date_field} >= %s
              AND {date_field} <= %s
              AND {team_field} IN ({teams})
            """.format(
                table=table_name,
                date_field=date_field,
                team_field=team_field,
                teams=team_ids_literal,
            ),
            (date_from, date_to),
        )
    else:
        cr.execute(
            """
            DELETE FROM {table}
            WHERE {date_field} >= %s
              AND {date_field} <= %s
            """.format(table=table_name, date_field=date_field),
            (date_from, date_to),
        )


# ---------------------------------------------------------------------------
# Dry-run guard
# ---------------------------------------------------------------------------

def dry_run_guard(dry_run, counts):
    """
    Si dry_run=True, retorna counts sin ejecutar escrituras.
    Usar al inicio de la sección de escritura:

        if dry_run_guard(dry_run, {"to_create": len(vals)}):
            return  # o raise UserError con el resumen

    Retorna counts si dry_run=True, None si dry_run=False.
    """
    if dry_run:
        return counts
    return None


# ---------------------------------------------------------------------------
# Notificaciones Odoo
# ---------------------------------------------------------------------------

def notify_action(title, message, notify_type="success", sticky=False):
    """
    Retorna un dict de acción 'display_notification' para notificaciones Odoo.

    Uso en server action:
        action = notify_action("Proceso completado", "Se crearon 150 registros.")
        # Asignar a la variable de retorno del server action si aplica.

    notify_type: 'success' | 'warning' | 'danger' | 'info'
    """
    return {
        "type": "ir.actions.client",
        "tag": "display_notification",
        "params": {
            "title": title,
            "message": message,
            "type": notify_type,
            "sticky": sticky,
        },
    }
