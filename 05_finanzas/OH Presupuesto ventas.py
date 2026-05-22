# ============================================================
# OH Presupuesto de Ventas — RECALC AYER + FUTURO (HASTA 31-12-2026)
# SAFE_EVAL friendly: SIN imports, SIN global, SIN getattr
#
# VERSION_ID = "PRESU_WD_TAG_v13_HOLIDAYS_FROM_MODEL__OFFSET_POLICY_IN_CODE"
#
# CAMBIOS vs v12.4:
#  1) La fecha base del feriado YA NO está hardcodeada en HOLIDAY_SPECS.
#  2) Se lee desde x_holiday_occurrence + x_holiday_master.
#  3) Se mantiene en código solo la política de offsets P/H por código.
#  4) Se mantiene lógica especial de Año Nuevo cross-year.
# ============================================================

# ================== Parámetros ==================
TZ_NAME = 'America/Santiago'
ALPHA_BLEND = 0.25
INCLUDE_POS = True

MIN_BASE_IN_WINDOW = 30000000
ROLL_WINDOW_DAYS = 45
LONG_WINDOW_DAYS = 365

FILTERED_TEAM_IDS = [18, 16, 12, 10, 9, 8, 7, 6, 5, 17, 13, 11]
WEEKS_FOR_WD_AVG = 4

ADJ_MIN = 0.60
ADJ_MAX = 1.80

ENABLE_SHORT_CORR = True
SHORT_CORR_MIN = 0.70
SHORT_CORR_MAX = 1.60

EASTER_SHORTCORR_ONLY_IF_MONTH_CHANGES = True

# === Factor rolling robusto ===
FACTOR_NO_CROSS_YEAR = False
FACTOR_WARMUP_DAYS = 14

# === Uplift por weekday SOLO para FERIADO_ANO_ANTERIOR con LY4 ===
# wd: 0=Lun, 1=Mar, 2=Mié, 3=Jue, 4=Vie, 5=Sáb, 6=Dom
FERIADO_LY4_WD_UPLIFT = {
    0: 1.70,  # Lunes
    1: 1.28,  # Martes
    2: 1.00,  # Miércoles
    3: 0.70,  # Jueves
    4: 0.95,  # Viernes
    5: 0.96,  # Sábado
    6: 1.51,  # Domingo
}
FERIADO_LY4_WD_UPLIFT_MIN = 0.60
FERIADO_LY4_WD_UPLIFT_MAX = 2.00

# === FLOOR por LOCAL (crm.team) para matar outliers tipo 4MM ===
ENABLE_TEAM_DAILY_FLOOR = True
TEAM_DAILY_FLOOR_MULT_ROLL30 = 0.45
TEAM_DAILY_FLOOR_ABS_MIN = 300000
TEAM_DAILY_FLOOR_APPLY_PAST = True
TEAM_DAILY_FLOOR_APPLY_FUTURE = True
TEAM_DAILY_FLOOR_SCALE_MAX = 1.50

# === Override piso absoluto por team (reaperturas / sucursales especiales) ===
TEAM_DAILY_FLOOR_ABS_OVERRIDE = {
    11: 1000000,  # San José — reapertura mar-2026, media histórica ~1.57M
}

# (si no estás usando multiplicadores por clase, déjalo vacío)
mult = {}

BATCH = 1000

# === Lock para evitar doble corrida simultánea ===
LOCK_KEY = 1424122

# === Modelos de feriados ===
HOL_OCC_MODEL = 'x_holiday_occurrence'
HOL_MAS_MODEL = 'x_holiday_master'

# === Política P/H por código de feriado ===
# La FECHA sale del modelo; aquí solo se define cómo marcar días alrededor.
HOLIDAY_OFFSET_POLICY = {
    'NEWYEAR': [(0, 'H')],
    'GOOD_FRIDAY': [(-1, 'P'), (0, 'H')],
    'HOLY_SATURDAY': [(0, 'H')],
    'LABOR_DAY': [(-1, 'P'), (0, 'H')],
    'NAVY_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')],
    'INDIGENOUS_PEOPLES_DAY': [(0, 'H')],
    'SAINT_PETER_PAUL': [(0, 'H')],
    'VIRGIN_OF_CARMEN': [(0, 'H')],
    'ASSUMPTION': [(0, 'H')],
    'INDEPENDENCE_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')],
    'ARMY_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')],
    'ADDITIONAL_PATRIOTIC_HOLIDAY': [(0, 'H')],
    'ENCOUNTER_OF_TWO_WORLDS': [(0, 'H')],
    'EVANGELICAL_CHURCHES_DAY': [(-2, 'P'), (-1, 'P'), (0, 'H')],
    'ALL_SAINTS': [(0, 'H')],
    'IMMACULATE_CONCEPTION': [(0, 'H')],
    'CHRISTMAS': [(-1, 'P'), (0, 'H')],
}

# Códigos que se consideran "Pascua" para short correction especial
EASTER_SHORTCORR_CODES = set(['GOOD_FRIDAY', 'HOLY_SATURDAY'])

# ================== Lock ==================
env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
locked = env.cr.fetchone()[0]
if not locked:
    raise ValueError("Presupuesto de Ventas ya está en ejecución")

# ================== Utilidades ==================
def _year_bounds(year):
    return datetime.date(year, 1, 1), datetime.date(year, 12, 31)

def _d2s(d):
    return d and d.isoformat() or ''

def _sum_range(d2v, d_from, d_to):
    s = 0.0
    d = d_from
    while d <= d_to:
        s += d2v.get(d, 0.0)
        d += datetime.timedelta(days=1)
    return s

def _clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x

def _weekday_eq_in_base_year(d, base_year):
    # weekday equivalente LY robusto (364 días) con guard para caer dentro del año base
    x = d - datetime.timedelta(days=364)
    guard = 0
    while x.year != base_year and guard < 60:
        if x.year > base_year:
            x = x - datetime.timedelta(days=7)
        else:
            x = x + datetime.timedelta(days=7)
        guard += 1
    return x

def _avg_lastN_same_weekday_ly(daily_ly, hclass_ly, anchor_day, tid, wd, n_weeks):
    vals = []
    d = anchor_day
    steps = 0
    while (len(vals) < int(n_weeks)) and (steps < 12):
        if d.weekday() == wd and hclass_ly.get(d, 'N') == 'N':
            v = daily_ly.get((d, tid), 0.0) or 0.0
            if v > 0.0:
                vals.append(v)
        d = d - datetime.timedelta(days=7)
        steps += 1
    return (sum(vals) / float(len(vals))) if vals else 0.0

def _avg_lastN_same_weekday_ty(curr_team_map, hclass_tgt, anchor_day, wd, n_weeks, cap_day):
    vals = []
    d = anchor_day - datetime.timedelta(days=7)
    steps = 0
    while (len(vals) < int(n_weeks)) and (steps < 12):
        if d <= cap_day and d.weekday() == wd and hclass_tgt.get(d, 'N') == 'N':
            v = curr_team_map.get(d, 0.0) or 0.0
            if v > 0.0:
                vals.append(v)
        d = d - datetime.timedelta(days=7)
        steps += 1
    return (sum(vals) / float(len(vals))) if vals else 0.0

# Prioridad feriado: H > P > N
def _set_hclass(hmap, day, new_cls):
    pr = {'N': 0, 'P': 1, 'H': 2}
    old = hmap.get(day, 'N')
    if pr.get(new_cls, 0) >= pr.get(old, 0):
        hmap[day] = new_cls

def _pre_days_newyear_by_weekday(wd):
    if wd == 1:  # martes
        return 4
    if wd == 0:  # lunes
        return 3
    if wd == 3:  # jueves
        return 2
    if wd == 2 or wd == 4:  # miércoles o viernes
        return 1
    return 0

def _set_taginfo(taginfo_map, day, tag, off, cls):
    pr = {'N': 0, 'P': 1, 'H': 2}
    old = taginfo_map.get(day)
    old_pr = pr.get(old[3], 0) if old else -1
    if pr.get(cls, 0) >= old_pr:
        taginfo_map[day] = (tag, off, day, cls)

def _apply_newyear_crossyear_pre(hmap, year, date_from, date_to):
    try:
        d31 = datetime.date(year, 12, 31)
    except Exception:
        d31 = False

    if d31 and (date_from <= d31 <= date_to):
        _set_hclass(hmap, d31, 'P')
        try:
            jan1_next = datetime.date(year + 1, 1, 1)
            pre_days = _pre_days_newyear_by_weekday(jan1_next.weekday())
        except Exception:
            pre_days = 0
        k = 1
        while k < int(pre_days or 0):
            x = d31 - datetime.timedelta(days=k)
            if date_from <= x <= date_to:
                _set_hclass(hmap, x, 'P')
            k += 1

def _load_holiday_bases(years):
    Occ = env[HOL_OCC_MODEL].sudo()
    Mas = env[HOL_MAS_MODEL].sudo()

    years_list = []
    for y in list(years):
        try:
            years_list.append(int(y))
        except Exception:
            pass

    base_main = {}
    for y in years_list:
        base_main[y] = {}

    occs = Occ.search([
        ('x_studio_active', '=', True),
        ('x_studio_year', 'in', years_list),
        ('x_studio_holiday_id', '!=', False),
        ('x_studio_holiday_date', '!=', False),
    ])

    occ_rows = occs.read(['x_studio_year', 'x_studio_holiday_id', 'x_studio_holiday_date'])
    master_ids = []
    for r in occ_rows:
        h = r.get('x_studio_holiday_id')
        hid = h and h[0] or False
        if hid:
            master_ids.append(hid)

    master_ids = list(set(master_ids))
    code_by_id = {}
    if master_ids:
        mrows = Mas.browse(master_ids).read(['x_studio_code'])
        for r in mrows:
            code_by_id[r['id']] = (r.get('x_studio_code') or '').strip().upper()

    for r in occ_rows:
        yy = r.get('x_studio_year')
        h = r.get('x_studio_holiday_id')
        dt = r.get('x_studio_holiday_date')
        hid = h and h[0] or False
        code = code_by_id.get(hid)
        if yy and dt and code:
            if yy not in base_main:
                base_main[yy] = {}
            base_main[yy][code] = dt

    return base_main

def _apply_holidays_from_model(hclass_map, taginfo_map, year, date_from, date_to, base_main_by_tag_by_year):
    base_map = base_main_by_tag_by_year.get(year, {})
    for code in base_map:
        base = base_map.get(code)
        if not base:
            continue
        offsets = HOLIDAY_OFFSET_POLICY.get(code)
        if not offsets:
            offsets = [(0, 'H')]
        for off, cls in offsets:
            x = base + datetime.timedelta(days=int(off))
            if date_from <= x <= date_to:
                _set_hclass(hclass_map, x, cls)
                _set_taginfo(taginfo_map, x, code, int(off), cls)

# ================== Setup (HOY en TZ Chile vía SQL) ==================
env.cr.execute("SELECT (now() AT TIME ZONE %s)::date", (TZ_NAME,))
today_real = env.cr.fetchone()[0]
calc_today = today_real - datetime.timedelta(days=1)  # día cerrado = AYER

# ================== RANGO NUEVO: AYER -> FIN 2026 ==================
date_from_target = calc_today
horizon_end = datetime.date(2026, 12, 31)

# ================== Años involucrados ==================
target_years = set()
yy = date_from_target.year
while yy <= horizon_end.year:
    target_years.add(yy)
    yy += 1

base_years = set()
for yy in list(target_years):
    base_years.add(yy - 1)

# Si el rolling cruza años, necesito el año -2 para el denominador del factor
if not FACTOR_NO_CROSS_YEAR:
    extra = set()
    for yy in list(base_years):
        extra.add(yy - 1)
    for yy in list(extra):
        base_years.add(yy)

all_years_sales = set()
for yy in target_years:
    all_years_sales.add(yy)
for yy in base_years:
    all_years_sales.add(yy)

min_year = min(list(all_years_sales)) if all_years_sales else today_real.year
max_year = max(list(all_years_sales)) if all_years_sales else today_real.year

# Necesitamos historia para rolling 365: ampliamos ventana de extracción hacia atrás
dt_utc_from = datetime.datetime(min_year, 1, 1, 0, 0, 0)
dt_utc_to = datetime.datetime(max_year + 1, 1, 1, 0, 0, 0)

team_filter_set = set()
for _id in FILTERED_TEAM_IDS:
    try:
        team_filter_set.add(int(_id))
    except Exception:
        pass
teams_iter = list(team_filter_set)

Presu = env['x_presupuesto_de_venta'].sudo()
company = env.company
currency = company.currency_id

has_ly_cal_date = 'x_studio_ly_calendar_date' in Presu._fields
has_ly_cal_amt = 'x_studio_ly_calendar_2024' in Presu._fields

# ================== PURGA (SOLO AYER -> FIN 2026) ==================
env.cr.execute("""
    DELETE FROM x_presupuesto_de_venta
    WHERE x_company_id = %s
      AND x_date_2025_eq >= %s
      AND x_date_2025_eq <= %s
""", (company.id, date_from_target, horizon_end))

# ================== 1) Ventas por día LOCAL Chile (SQL, CORTADO EN AYER) ==================
daily_sales = {}

sql_sale = """
    SELECT
        (so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS day_local,
        so.team_id AS team_id,
        SUM(so.amount_total) AS amt
    FROM sale_order so
    WHERE so.company_id = %s
      AND so.state IN ('sale','done')
      AND so.team_id = ANY(%s::int[])
      AND so.date_order >= %s
      AND so.date_order <  %s
      AND (so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date <= %s
    GROUP BY day_local, team_id
"""
env.cr.execute(
    sql_sale,
    (TZ_NAME, company.id, list(team_filter_set), dt_utc_from, dt_utc_to, TZ_NAME, calc_today)
)
for day_local, tid, amt in env.cr.fetchall():
    if day_local and tid in team_filter_set:
        key = (day_local, tid)
        daily_sales[key] = daily_sales.get(key, 0.0) + (amt or 0.0)

if INCLUDE_POS:
    sql_pos = """
        SELECT
            (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS day_local,
            pc.crm_team_id AS team_id,
            SUM(po.amount_total) AS amt
        FROM pos_order po
        JOIN pos_config pc ON pc.id = po.config_id
        WHERE po.company_id = %s
          AND po.state IN ('paid','invoiced','done')
          AND pc.crm_team_id IS NOT NULL
          AND pc.crm_team_id = ANY(%s::int[])
          AND po.date_order >= %s
          AND po.date_order <  %s
          AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)::date <= %s
        GROUP BY day_local, pc.crm_team_id
    """
    env.cr.execute(
        sql_pos,
        (TZ_NAME, company.id, list(team_filter_set), dt_utc_from, dt_utc_to, TZ_NAME, calc_today)
    )
    for day_local, tid, amt in env.cr.fetchall():
        if day_local and tid in team_filter_set:
            key = (day_local, tid)
            daily_sales[key] = daily_sales.get(key, 0.0) + (amt or 0.0)

# ================== 2) Mapas por team ==================
sales_by_team = {}
for tid in teams_iter:
    sales_by_team[tid] = {}
for (d0, tid), v in daily_sales.items():
    if tid in sales_by_team:
        sales_by_team[tid][d0] = sales_by_team[tid].get(d0, 0.0) + (v or 0.0)

# ================== 2.1) Clases feriado/pre por año ==================
holiday_class_by_year = {}
taginfo_by_year = {}
base_main_by_tag_by_year = _load_holiday_bases(all_years_sales)

def _build_holiday_maps_for_year(yy):
    date_from_y, date_to_y = _year_bounds(yy)
    hmap = {}
    tmap = {}
    d0 = date_from_y
    while d0 <= date_to_y:
        hmap[d0] = 'N'
        d0 += datetime.timedelta(days=1)

    _apply_holidays_from_model(hmap, tmap, yy, date_from_y, date_to_y, base_main_by_tag_by_year)
    _apply_newyear_crossyear_pre(hmap, yy, date_from_y, date_to_y)

    holiday_class_by_year[yy] = hmap
    taginfo_by_year[yy] = tmap

for yy in list(target_years):
    _build_holiday_maps_for_year(yy)
for yy in list(base_years):
    _build_holiday_maps_for_year(yy)

def _base_equiv_date_for_target_day(d_tgt):
    tgt_year = d_tgt.year
    base_year = tgt_year - 1
    info = taginfo_by_year.get(tgt_year, {}).get(d_tgt)
    if not info:
        return False
    tag = info[0]
    off = info[1]
    base_main = base_main_by_tag_by_year.get(base_year, {}).get(tag)
    if not base_main:
        return False
    return base_main + datetime.timedelta(days=int(off))

# ================== 3) Factor Rolling — OPT con prefix sums ==================
factor_day_by_team = {}
factor_today_by_team = {}

fac_end = calc_today
fac_start = fac_end - datetime.timedelta(days=LONG_WINDOW_DAYS - 1)

fac_dates = []
d0 = fac_start
while d0 <= fac_end:
    fac_dates.append(d0)
    d0 += datetime.timedelta(days=1)

fac_idx = {}
i = 0
while i < len(fac_dates):
    fac_idx[fac_dates[i]] = i
    i += 1

base_eq_by_date = {}

def _base_equiv_for_factor(d0):
    tgt_year = d0.year
    base_year = tgt_year - 1
    tgt_cls = holiday_class_by_year.get(tgt_year, {}).get(d0, 'N')
    if tgt_cls != 'N':
        bd = _base_equiv_date_for_target_day(d0)
        if bd:
            return bd
        try:
            return datetime.date(base_year, d0.month, d0.day)
        except Exception:
            return _weekday_eq_in_base_year(d0, base_year)
    return _weekday_eq_in_base_year(d0, base_year)

i = 0
while i < len(fac_dates):
    dd = fac_dates[i]
    base_eq_by_date[dd] = _base_equiv_for_factor(dd)
    i += 1

year_start_idx_by_i = []
i = 0
while i < len(fac_dates):
    dd = fac_dates[i]
    ys = datetime.date(dd.year, 1, 1)
    ysi = fac_idx.get(ys)
    if ysi is None:
        ysi = 0
    year_start_idx_by_i.append(ysi)
    i += 1

def _psum(arr):
    ps = [0.0]
    s = 0.0
    i = 0
    while i < len(arr):
        s += (arr[i] or 0.0)
        ps.append(s)
        i += 1
    return ps

def _range_sum(ps, i0, i1):
    if i0 < 0:
        i0 = 0
    if i1 < 0:
        return 0.0
    if i1 >= (len(ps) - 1):
        i1 = (len(ps) - 2)
    if i0 > i1:
        return 0.0
    return ps[i1 + 1] - ps[i0]

for tid in teams_iter:
    factor_day_by_team[tid] = {}
    last_fac = 1.0

    team_map = sales_by_team.get(tid, {})
    curr_arr = []
    base_arr = []

    i = 0
    while i < len(fac_dates):
        dd = fac_dates[i]
        curr_v = team_map.get(dd, 0.0) or 0.0
        bd = base_eq_by_date.get(dd)
        base_v = team_map.get(bd, 0.0) if bd else 0.0
        base_v = base_v or 0.0
        curr_arr.append(curr_v)
        base_arr.append(base_v)
        i += 1

    ps_curr = _psum(curr_arr)
    ps_base = _psum(base_arr)

    i = 0
    while i < len(fac_dates):
        dd = fac_dates[i]

        long_i0 = i - (LONG_WINDOW_DAYS - 1)
        short_i0 = i - (ROLL_WINDOW_DAYS - 1)

        if FACTOR_NO_CROSS_YEAR:
            ys_i0 = year_start_idx_by_i[i]
            if long_i0 < ys_i0:
                long_i0 = ys_i0
            if short_i0 < ys_i0:
                short_i0 = ys_i0

        if long_i0 < 0:
            long_i0 = 0
        if short_i0 < 0:
            short_i0 = 0

        curr_long = _range_sum(ps_curr, long_i0, i)
        base_long = _range_sum(ps_base, long_i0, i)
        long_fac = (curr_long / base_long) if base_long > 0.0 else 1.0

        curr_short = _range_sum(ps_curr, short_i0, i)
        base_short = _range_sum(ps_base, short_i0, i)

        if base_short >= (MIN_BASE_IN_WINDOW or 0):
            short_fac = (curr_short / base_short) if base_short > 0.0 else long_fac
            fac = ALPHA_BLEND * long_fac + (1.0 - ALPHA_BLEND) * short_fac
        else:
            fac = long_fac

        if (FACTOR_WARMUP_DAYS or 0) > 0:
            win_days = (i - long_i0) + 1
            if win_days < int(FACTOR_WARMUP_DAYS):
                fac = 1.0

        factor_day_by_team[tid][dd] = fac
        last_fac = fac
        i += 1

    factor_today_by_team[tid] = last_fac or 1.0

# ================== 3.1) Rolling30 fallback ==================
avg_rolling30_by_team = {}
roll30_start = calc_today - datetime.timedelta(days=29)
roll30_days = (calc_today - roll30_start).days + 1 if calc_today >= roll30_start else 0
for tid in teams_iter:
    if roll30_days > 0:
        total30 = _sum_range(sales_by_team[tid], roll30_start, calc_today)
        avg_rolling30_by_team[tid] = total30 / roll30_days
    else:
        avg_rolling30_by_team[tid] = 0.0

# ================== 4) Cache equipos ==================
team_name_cache = {}
for t in env['crm.team'].sudo().browse(teams_iter):
    team_name_cache[t.id] = t.display_name or t.name or ('Equipo %s' % t.id)

# ================== 5) Crear AYER -> FIN 2026 ==================
rows = []
ty4_cache = {}

d = date_from_target
while d <= horizon_end:
    wd = d.weekday()
    tgt_year = d.year
    base_year = tgt_year - 1

    tgt_cls = holiday_class_by_year.get(tgt_year, {}).get(d, 'N')

    d_base_eq = _weekday_eq_in_base_year(d, base_year)
    baseeq_cls = holiday_class_by_year.get(base_year, {}).get(d_base_eq, 'N')

    d_base_cal = False
    if tgt_cls != 'N':
        d_base_cal = _base_equiv_date_for_target_day(d)
    if not d_base_cal:
        try:
            d_base_cal = datetime.date(base_year, d.month, d.day)
        except Exception:
            d_base_cal = False

    info_tgt = taginfo_by_year.get(tgt_year, {}).get(d)
    day_tag = info_tgt and info_tgt[0] or False

    for tid in teams_iter:
        v_base_show = sales_by_team[tid].get(d_base_eq, 0.0) or 0.0
        v_curr = sales_by_team[tid].get(d, 0.0) or 0.0

        # fac del día (futuro usa último fac)
        fac = factor_day_by_team[tid].get(d, factor_today_by_team.get(tid, 1.0))

        v_base_cal = (sales_by_team[tid].get(d_base_cal, 0.0) or 0.0) if d_base_cal else 0.0

        base_mode = 'WD'
        adj = 1.0
        proj_raw = 0.0
        v_base_clean = 0.0

        if (tgt_cls != 'N') and d_base_cal and (v_base_cal > 0.0):
            base_mode = 'CAL'
            proj_raw = v_base_cal * fac
            adj = 1.0
        else:
            base_cls_eq = holiday_class_by_year.get(base_year, {}).get(d_base_eq, 'N')

            # === Caso: FERIADO ANO ANTERIOR (weekday-eq LY cae en P/H) ===
            if (tgt_cls == 'N') and (base_cls_eq != 'N'):
                v_base_clean = _avg_lastN_same_weekday_ly(daily_sales, holiday_class_by_year.get(base_year, {}), d_base_eq, tid, wd, WEEKS_FOR_WD_AVG)
                if v_base_clean > 0.0:
                    base_mode = 'LY4'
                    proj_raw = v_base_clean * fac

                    upl = FERIADO_LY4_WD_UPLIFT.get(wd, 1.0) or 1.0
                    upl = _clamp(upl, FERIADO_LY4_WD_UPLIFT_MIN, FERIADO_LY4_WD_UPLIFT_MAX)
                    proj_raw = proj_raw * upl

                    adj = 1.0
                else:
                    base_mode = 'TY4'
                    proj_raw = 0.0
                    adj = 1.0
            else:
                if v_base_show > 0.0:
                    proj_raw = v_base_show * fac
                    base_mode = 'WD'
                else:
                    base_mode = 'TY4'
                    proj_raw = 0.0

                if base_mode == 'WD':
                    base_cls = holiday_class_by_year.get(base_year, {}).get(d_base_eq, 'N')
                    m_base = mult.get((tid, wd, base_cls), 1.0) or 1.0
                    m_tgt = mult.get((tid, wd, tgt_cls), 1.0) or 1.0
                    adj = (m_tgt / m_base) if m_base > 0 else 1.0
                    adj = _clamp(adj, ADJ_MIN, ADJ_MAX)
                else:
                    adj = 1.0

        if base_mode == 'TY4':
            cap_day = d - datetime.timedelta(days=1)
            keyc = (tid, d)
            ty4 = ty4_cache.get(keyc)
            if ty4 is None:
                ty4 = _avg_lastN_same_weekday_ty(sales_by_team[tid], holiday_class_by_year.get(tgt_year, {}), d, wd, WEEKS_FOR_WD_AVG, cap_day)
                if ty4 <= 0.0:
                    ty4 = avg_rolling30_by_team.get(tid, 0.0) or 0.0
                ty4_cache[keyc] = ty4
            proj_raw = ty4
            adj = 1.0

        proj = proj_raw * adj

        # === short correction (solo cuando aplica) ===
        apply_sc = False
        if base_mode == 'LY4':
            apply_sc = True
        if (not apply_sc) and (base_mode == 'CAL') and (tgt_cls in ('P', 'H')) and d_base_cal and (day_tag in EASTER_SHORTCORR_CODES):
            if (not EASTER_SHORTCORR_ONLY_IF_MONTH_CHANGES) or (d.month != d_base_cal.month):
                apply_sc = True

        if ENABLE_SHORT_CORR and apply_sc:
            cap_day = d - datetime.timedelta(days=1)

            keyc = (tid, d)
            ty4 = ty4_cache.get(keyc)
            if ty4 is None:
                ty4 = _avg_lastN_same_weekday_ty(sales_by_team[tid], holiday_class_by_year.get(tgt_year, {}), d, wd, WEEKS_FOR_WD_AVG, cap_day)
                if ty4 <= 0.0:
                    ty4 = avg_rolling30_by_team.get(tid, 0.0) or 0.0
                ty4_cache[keyc] = ty4

            ly4 = v_base_clean
            if ly4 <= 0.0:
                anchor_ly = d_base_eq
                if (base_mode == 'CAL') and d_base_cal:
                    anchor_ly = d_base_cal
                ly4 = _avg_lastN_same_weekday_ly(daily_sales, holiday_class_by_year.get(base_year, {}), anchor_ly, tid, wd, WEEKS_FOR_WD_AVG)

            if (ty4 > 0.0) and (ly4 > 0.0):
                corr = ty4 / ly4
                corr = _clamp(corr, SHORT_CORR_MIN, SHORT_CORR_MAX)
                proj = proj * corr

        # ================== FLOOR por LOCAL (crm.team) ==================
        floor_team_applied = False
        if ENABLE_TEAM_DAILY_FLOOR:
            apply_floor = False
            if (d <= calc_today and TEAM_DAILY_FLOOR_APPLY_PAST) or (d > calc_today and TEAM_DAILY_FLOOR_APPLY_FUTURE):
                apply_floor = True

            if apply_floor:
                abs_min = TEAM_DAILY_FLOOR_ABS_OVERRIDE.get(tid, TEAM_DAILY_FLOOR_ABS_MIN) or 0
                roll30 = avg_rolling30_by_team.get(tid, 0.0) or 0.0
                floor_team = (TEAM_DAILY_FLOOR_MULT_ROLL30 or 0.0) * roll30
                if floor_team < abs_min:
                    floor_team = float(abs_min)

                if floor_team > 0.0 and proj < floor_team:
                    if proj > 0.0 and proj >= abs_min:
                        scale = floor_team / proj
                        if scale > (TEAM_DAILY_FLOOR_SCALE_MAX or 1.0):
                            floor_team = proj * (TEAM_DAILY_FLOOR_SCALE_MAX or 1.0)
                    if proj < floor_team:
                        proj = floor_team
                        floor_team_applied = True

        # === métricas vs real: solo hasta AYER ===
        if d <= calc_today:
            bruto_curr = v_curr
            dev = v_curr - proj
            variacion_anual = v_curr - v_base_show
        else:
            bruto_curr = 0.0
            dev = 0.0
            variacion_anual = 0.0

        tname = team_name_cache.get(tid, ('Equipo %s' % tid))
        label = '%s -> %s | %s' % (_d2s(d_base_eq), _d2s(d), tname)

        _trat = 'NORMAL'
        if (tgt_cls != 'N') and (base_mode == 'CAL'):
            _trat = 'FERIADO_ANO_ACTUAL'
        else:
            if (tgt_cls == 'N') and (baseeq_cls != 'N') and (base_mode in ('LY4', 'TY4')):
                _trat = 'FERIADO_ANO_ANTERIOR' if base_mode == 'LY4' else 'PROM_4_SEMANAS'
            elif base_mode == 'TY4':
                _trat = 'PROM_4_SEMANAS'
            else:
                _trat = 'NORMAL'

        vals = {
            'x_name': label,
            'x_company_id': company.id,
            'x_currency_id': currency.id,

            'x_date_2024': d_base_eq,
            'x_bruto_2024': v_base_show,

            'x_date_2025_eq': d,
            'x_weekday': str(wd),
            'x_team_id': tid,

            'x_bruto_2025': bruto_curr,
            'x_proj_2025': proj,
            'x_deviation': dev,
            'x_factor_day': fac,
        }

        # Error ABS / Error %
        _err_abs = dev
        if _err_abs < 0:
            _err_abs = -_err_abs
        if d <= calc_today:
            if v_curr > 0.0:
                _err_pct = _err_abs / v_curr
            else:
                _err_pct = 0.0 if (_err_abs <= 0.0) else 1.0
        else:
            _err_pct = 0.0

        if 'x_studio_error_abs' in Presu._fields:
            vals['x_studio_error_abs'] = _err_abs
        if 'x_studio_error_pct' in Presu._fields:
            vals['x_studio_error_pct'] = _err_pct

        # ================== Tratamiento (Selection safe, SIN getattr) ==================
        trat_field = Presu._fields.get('x_studio_tratamiento')
        trat_is_selection = False
        trat_allowed = False
        if trat_field:
            ftype = ''
            try:
                ftype = trat_field.type
            except Exception:
                ftype = ''
            if ftype == 'selection':
                trat_is_selection = True
                try:
                    trat_allowed = set([k for k, v in (trat_field.selection or [])])
                except Exception:
                    trat_allowed = False

        if 'x_studio_tratamiento' in Presu._fields:
            trat_val = _trat
            if trat_is_selection:
                if trat_allowed and (trat_val not in trat_allowed):
                    if 'NORMAL' in trat_allowed:
                        trat_val = 'NORMAL'
                    else:
                        try:
                            trat_val = list(trat_allowed)[0]
                        except Exception:
                            trat_val = 'NORMAL'
                vals['x_studio_tratamiento'] = trat_val
            else:
                vals['x_studio_tratamiento'] = (trat_val + '|FLOOR_TEAM') if floor_team_applied else trat_val

        # Flag visible en nombre
        if floor_team_applied:
            vals['x_name'] = (vals.get('x_name') or label) + ' [FLOOR]'

        # Si existe boolean para floor aplicado
        for _fname in ('x_studio_floor_team', 'x_floor_team', 'x_studio_floor_applied', 'x_floor_applied'):
            if _fname in Presu._fields:
                vals[_fname] = bool(floor_team_applied)
                break

        # ================== presupuesto_actualizado ==================
        budget_updated = v_curr if (d <= calc_today) else proj
        if 'x_studio_presupuesto_actualizado' in Presu._fields:
            vals['x_studio_presupuesto_actualizado'] = budget_updated

        if 'x_studio_variacin_anual' in Presu._fields:
            vals['x_studio_variacin_anual'] = variacion_anual

        if has_ly_cal_date:
            vals['x_studio_ly_calendar_date'] = d_base_cal or False
        if has_ly_cal_amt:
            vals['x_studio_ly_calendar_2024'] = v_base_cal or 0.0

        rows.append(vals)
        if len(rows) >= BATCH:
            Presu.create(rows)
            rows = []

    d += datetime.timedelta(days=1)

if rows:
    Presu.create(rows)
    rows = []

total = Presu.search_count([
    ('x_date_2025_eq', '>=', date_from_target),
    ('x_date_2025_eq', '<=', horizon_end),
    ('x_company_id', '=', company.id),
])

action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'title': 'Presupuesto de Ventas',
        'message': 'OK | v13 | HolidaysFromModel | Desde %s a %s | Hoy=%s | Ayer=%s | Registros=%s'
                   % (_d2s(date_from_target), _d2s(horizon_end), _d2s(today_real), _d2s(calc_today), total),
        'type': 'success',
        'sticky': False,
    }
}
