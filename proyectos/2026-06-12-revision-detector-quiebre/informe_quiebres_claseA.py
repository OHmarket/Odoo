# ============================================================
# Informe gerencial de quiebres — CLASE A (read-only)
# ============================================================
# Server Action de tipo code. NO escribe en datos de negocio: solo SELECT
# agregados server-side (gaps-and-islands) + crea un ir.attachment con el CSV.
#
# Universo: x_stock_balance_daily, x_studio_abcxyz LIKE 'A%' (AX+AY+AZ),
#           x_studio_date >= 2025-01-01.
# Metricas por (sala, mes): SKUs distintos en quiebre total, dias-quiebre total,
#           Nº episodios (rachas consecutivas, mes de inicio), duracion promedio
#           de episodio, e incidencias parciales intradia (aparte).
#
# Canon: gaps-and-islands (window functions) para rachas consecutivas. Devuelve
#   ~200 filas agregadas; nunca baja filas crudas (no repite el "API completo").
# ============================================================

VERSION_ID = 'INFORME_QUIEBRE_A_v1'
FECHA_DESDE = '2025-01-01'

# 1) Episodios (quiebre TOTAL) -> agregado a (team, mes de inicio)
SQL_EPISODIOS = """
WITH base AS (
    SELECT x_studio_team_id AS team,
           x_studio_product_id AS pid,
           x_studio_date AS d
    FROM x_stock_balance_daily
    WHERE x_studio_abcxyz LIKE %(pat)s
      AND x_studio_stockout = TRUE
      AND COALESCE(x_studio_stockout_partial, FALSE) = FALSE
      AND x_studio_date >= %(desde)s
),
isl AS (
    SELECT team, pid, d,
           d - (ROW_NUMBER() OVER (PARTITION BY team, pid ORDER BY d))::int AS grp
    FROM base
),
ep AS (
    SELECT team, pid, MIN(d) AS start_d, COUNT(*) AS dur
    FROM isl
    GROUP BY team, pid, grp
)
SELECT team,
       date_trunc('month', start_d)::date AS mes,
       COUNT(*)        AS n_episodios,
       SUM(dur)        AS dias_en_episodios,
       AVG(dur)::numeric(10,2) AS dur_prom_dias,
       MAX(dur)        AS dur_max_dias
FROM ep
GROUP BY team, date_trunc('month', start_d);
"""

# 2) SKUs distintos + dias total por (team, mes), sobre dias de quiebre TOTAL
SQL_SKUS = """
SELECT x_studio_team_id AS team,
       date_trunc('month', x_studio_date)::date AS mes,
       COUNT(DISTINCT x_studio_product_id) AS skus_distintos,
       COUNT(*) AS dias_total
FROM x_stock_balance_daily
WHERE x_studio_abcxyz LIKE %(pat)s
  AND x_studio_stockout = TRUE
  AND COALESCE(x_studio_stockout_partial, FALSE) = FALSE
  AND x_studio_date >= %(desde)s
GROUP BY x_studio_team_id, date_trunc('month', x_studio_date);
"""

# 3) Incidencias parciales (intradia) por (team, mes) — reportadas aparte
SQL_PARCIAL = """
SELECT x_studio_team_id AS team,
       date_trunc('month', x_studio_date)::date AS mes,
       COUNT(*) AS inc_parciales,
       COUNT(DISTINCT x_studio_product_id) AS skus_parciales
FROM x_stock_balance_daily
WHERE x_studio_abcxyz LIKE %(pat)s
  AND COALESCE(x_studio_stockout_partial, FALSE) = TRUE
  AND x_studio_date >= %(desde)s
GROUP BY x_studio_team_id, date_trunc('month', x_studio_date);
"""

params = {'pat': 'A%', 'desde': FECHA_DESDE}

env.cr.execute(SQL_EPISODIOS, params)
ep_rows = env.cr.fetchall()    # team, mes, n_ep, dias_en_ep, dur_prom, dur_max

env.cr.execute(SQL_SKUS, params)
sku_rows = env.cr.fetchall()   # team, mes, skus_distintos, dias_total

env.cr.execute(SQL_PARCIAL, params)
par_rows = env.cr.fetchall()   # team, mes, inc_parciales, skus_parciales

# Mapeo team_id -> nombre real de sala (pos.config.name; crm.team todos = 'Sales')
team_name = {}
for pc in env['pos.config'].sudo().search_read(
        [('crm_team_id', '!=', False)], ['crm_team_id', 'name']):
    t = pc['crm_team_id'][0]
    team_name.setdefault(t, pc['name'])

# Merge a dict por (team, mes)
data = {}


def _slot(team, mes):
    k = (team, str(mes))
    r = data.get(k)
    if r is None:
        r = {'skus_distintos': 0, 'dias_total': 0, 'n_episodios': 0,
              'dias_en_episodios': 0, 'dur_prom_dias': 0.0, 'dur_max_dias': 0,
              'inc_parciales': 0, 'skus_parciales': 0}
        data[k] = r
    return r


for team, mes, n_ep, dias_ep, dur_prom, dur_max in ep_rows:
    r = _slot(team, mes)
    r['n_episodios'] = int(n_ep or 0)
    r['dias_en_episodios'] = int(dias_ep or 0)
    r['dur_prom_dias'] = float(dur_prom or 0.0)
    r['dur_max_dias'] = int(dur_max or 0)

for team, mes, skus, dias in sku_rows:
    r = _slot(team, mes)
    r['skus_distintos'] = int(skus or 0)
    r['dias_total'] = int(dias or 0)

for team, mes, inc, skus_p in par_rows:
    r = _slot(team, mes)
    r['inc_parciales'] = int(inc or 0)
    r['skus_parciales'] = int(skus_p or 0)

# CSV Excel-CL (sep ';', decimal ',', utf-8-sig)
cols = ['sala', 'team_id', 'mes', 'skus_distintos', 'dias_quiebre_total',
        'n_episodios', 'dur_prom_dias', 'dur_max_dias',
        'inc_parciales', 'skus_parciales']


def _num(v):
    return str(v).replace('.', ',')


lines = [';'.join(cols)]
for (team, mes) in sorted(data.keys(), key=lambda x: (team_name.get(x[0], 'zzz%s' % x[0]), x[1])):
    r = data[(team, mes)]
    sala = team_name.get(team, 'Team %s' % team)
    lines.append(';'.join([
        sala, str(team), mes,
        str(r['skus_distintos']), str(r['dias_total']),
        str(r['n_episodios']), _num(r['dur_prom_dias']), str(r['dur_max_dias']),
        str(r['inc_parciales']), str(r['skus_parciales']),
    ]))

csv_text = '\r\n'.join(lines)

att = env['ir.attachment'].sudo().create({
    'name': 'informe_quiebres_claseA.csv',
    'type': 'binary',
    'raw': csv_text.encode('utf-8-sig'),
    'mimetype': 'text/csv',
})

# Resumen al log (fallback si la descarga es incomoda)
total_dias = sum(r['dias_total'] for r in data.values())
total_ep = sum(r['n_episodios'] for r in data.values())
meses = sorted({m for (_, m) in data.keys()})
log('INFORME %s OK: filas=%s salas=%s meses=[%s..%s] dias_quiebre_A=%s episodios=%s attach_id=%s' % (
    VERSION_ID, len(data), len(team_name), meses[0] if meses else '-',
    meses[-1] if meses else '-', total_dias, total_ep, att.id), level='info')
log('INFORME %s CSV:\n%s' % (VERSION_ID, csv_text), level='info')

action = {
    'type': 'ir.actions.act_url',
    'url': '/web/content/%s?download=true' % att.id,
    'target': 'self',
}
