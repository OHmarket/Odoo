# ============================================================
# ABCXYZ OH Market — PRODUCT.PRODUCT + ABCXYZ + REGIMEN + GMROI + ADI/CV2
# ============================================================
# VERSION_ID = "ABCXYZ_OH_MARGIN_v19_4_SERIES_SHORT"
# v19.4 (2026-05-12): vista corta de series_type (Syntetos-Boylan sobre
#   ultimas 12 semanas) ademas de la larga (52 sem).
#   - x_studio_series_type:        largo (52 sem), comportamiento existente.
#   - x_studio_series_type_short:  corto (12 sem), nuevo.
#   - x_studio_series_type_active: el corto si difiere del largo (y no es
#     no_signal); si no, el largo. Es el que consume el motor HM-SI.
#   - regimen ahora se calcula con series_type_active.
#   - Motivo: SKUs en ramp-up tienen comportamiento corto distinto al largo.
#     Caso real: Cerveza Coors 620 BX smooth (largo) pero en ult. 12 sem
#     vende 121/sem (era 29 promedio anual) -> es smooth con mu alto.
# v19.3 (anterior):
# Cambios respecto a v19.2:
#   - GMROI ahora lee inventario directamente de stock.quant (primario Odoo)
#     en lugar de x_analisis_de_stock (modelo derivado).
#     · Filtro: location_id.usage='internal', quantity>0, company_id.
#     · Costo: usa el cost_unit que ABCXYZ ya calcula por producto
#       (COST_MODEL con fallback a standard_price).
#     · Cobertura: incluye TODO el catálogo con stock real, sin depender de
#       que x_analisis_de_stock haya corrido o filtre por team activo.
#   - Sigue siendo SNAPSHOT (al momento de correr ABCXYZ).
#   - Fase 2 TODO: convertir a PROMEDIO histórico sobre 26w leyendo
#     x_stock_balance_daily.
#
# Cambios respecto a v19.1:
#   - Eliminada la separación de semanas BASE vs ALL (bandas estacionales).
#   - HM-SI descuenta estacionalidad con SI → ABCXYZ no necesita pre-filtrar.
#
# Objetivo:
#   Refactor del ABCXYZ para que sea la única fuente de verdad de la
#   segmentación de productos. Añade tres dimensiones nuevas:
#
#   A) ADI + CV² (Syntetos-Boylan)
#      ADI = total_weeks / weeks_with_demand (intervalo promedio de demanda).
#      CV² = (sigma/mu)² sobre periodos POSITIVOS únicamente.
#      Reemplazan la inferencia de series_type vía letra XYZ (que mezclaba
#      intermittent con lumpy). La matriz ADI×CV² distingue 4 patrones:
#        smooth | erratic | intermittent | lumpy.
#
#   B) REGIMEN de forecast (REG-0..REG-8)
#      Reemplaza las zonas Z1-Z4 (calculadas hoy en HM-SI con caps P6).
#      Triplete: (abcxyz_letter_volumen, series_type, ciclo_de_vida).
#      HM-SI lee x_studio_regimen y aplica la regla directamente.
#
#   C) GMROI + GMROI_CLASS (G_A/G_B/G_C/G_D)
#      Dimensión financiera paralela. Mide retorno sobre inversión en stock.
#      Cuartiles empíricos sobre el catálogo activo.
#      Decide CUÁNTO invertir en stock (no afecta la regla de forecast).
#
# Cambios respecto a v18.3:
#   + _classify_series_type(): matriz Syntetos-Boylan (ADI x CV2)
#   + _assign_regimen():  asigna REG-0..8 sobre el triplete
#   + _load_inv_valor_by_product(): lee stock.quant (primario Odoo) best-effort
#   + _compute_gmroi():   GMROI anualizado por producto
#   + _classify_gmroi_by_quartiles(): asigna G_A/G_B/G_C/G_D
#   + sum_qty_pos, sum_sq_pos: acumuladores nuevos en el loop XYZ
#   + Nuevas columnas escritas:
#       x_studio_adi           (float, intervalo promedio de demanda)
#       x_studio_cv2           (float, CV² sobre periodos con qty>0)
#       x_studio_series_type   (smooth/erratic/intermittent/lumpy/no_signal)
#       x_studio_regimen       (REG-0..REG-8)
#       x_studio_gmroi         (float, margen anual / inv promedio)
#       x_studio_gmroi_class   (G_A/G_B/G_C/G_D)
#       x_studio_inv_valor_avg (float, $ inventario agregado sobre locales)
#
# Mantiene de v18.3:
#   1) Usar x_studio_product_id como product.product.
#   2) ABC, XYZ, ranking, ciclo de vida y eliminación.
#   3) Letra XYZ y x_studio_cv (CV sobre todos los periodos) intactos.
#   4) NO escribe campos de forecast / cobertura / safety / compra.
#   5) Compatibilidad con _filter_vals: si el campo nuevo no existe
#      en Odoo Studio, se omite del write sin error.
#
# Alcance:
#   - Solo ventas POS para ABC/XYZ.
#   - GMROI lee inventario SNAPSHOT desde stock.quant.
#     Si stock.quant no es accesible, GMROI=0 → G_D.
#
# Requiere que x_studio_product_id sea Many2one a product.product.
# ============================================================

VERSION_ID = "ABCXYZ_OH_MARGIN_v19_4_SERIES_SHORT"

TZ_NAME = 'America/Santiago'
LOCK_KEY = 99009431

# ----------------------
# Parámetros
# ----------------------
ABC_WEEKS_DEFAULT = 26
XYZ_WEEKS_DEFAULT = 26
HISTORY_MONTHS_DEFAULT = 24

ABC_THRESHOLDS = (0.80, 0.95)
XYZ_THRESHOLDS = (0.45, 0.90)

# Syntetos-Boylan classification (ADI x CV2 sobre periodos positivos)
#   ADI  < 1.32 AND CV2 < 0.49  → smooth
#   ADI  < 1.32 AND CV2 ≥ 0.49  → erratic
#   ADI  ≥ 1.32 AND CV2 < 0.49  → intermittent
#   ADI  ≥ 1.32 AND CV2 ≥ 0.49  → lumpy
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49

HARD_RESET_DEFAULT = True

MU_ELIM = 0.15
SCORE_ELIM = 3.2
PUNTOS_ABC_C = 1.5
PUNTOS_XYZ_Z = 1.2
PUNTOS_MU_BAJA = 1.0
PUNTOS_Q_POCA = 1.0
PUNTOS_ULT_Q0 = 1.0
PUNTOS_SIN_VENTA = 1.4

# ----------------------
# Parámetros ajuste de tendencia para promedio histórico semanal
# Nota: esto sigue siendo estadística histórica para clasificación,
# no forecast operativo de compra.
# ----------------------
MU_TREND_R2_MIN     = 0.15
MU_TREND_EXTRAP_CAP = 0.40
MU_TREND_F8V8_CAP   = 1.30
MU_TREND_F8V8_FLOOR = 0.77
MU_TREND_N_MIN      = 16
MU_TREND_SLOPE_CAP  = 0.05

MIN_ACTIVE_WEEKS_DEFAULT = 4
MIN_MU_WEEK_DEFAULT = 0.2

BATCH_SIZE = 500

# ----------------------
# Origen costo histórico OH
# ----------------------
COST_MODEL = 'x_margen_por_producto_'
COST_FIELD = 'x_studio_costo_oh_unit'
PRODUCT_FIELD = 'x_studio_producto'
COST_DATE_FROM_FIELD = 'x_studio_fecha_desde'
COST_DATE_TO_FIELD = 'x_studio_fecha_hasta'

# ----------------------
# Origen stock para GMROI — lectura directa de stock.quant (primario Odoo).
# Suma qty sobre locations internas y multiplica por el costo unitario que ya
# calcula ABCXYZ por producto (COST_MODEL con fallback a standard_price).
#
# Fase actual: SNAPSHOT del inventario al momento de correr ABCXYZ.
# Fase 2 (TODO): convertir a PROMEDIO histórico sobre 26 semanas leyendo
#                x_stock_balance_daily y promediando qty * costo por día.
# ----------------------
STOCK_QUANT_MODEL = 'stock.quant'

# Anualizador para extrapolar margen del periodo ABCXYZ a 52 semanas.
# Con ABC_WEEKS=26 esto da factor 2. Si ABC_WEEKS cambia se ajusta solo.
GMROI_ANNUAL_WEEKS = 52

# ----------------------
# Helpers base
# ----------------------
def _safe_int(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v, default=0.0):
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def _week_range(dfrom, dto):
    start = _week_start(dfrom)
    end = _week_start(dto)
    weeks = []
    cur = start
    while cur <= end:
        weeks.append(cur)
        cur += datetime.timedelta(weeks=1)
    return weeks or [start]


def _quarter_abs(d):
    return d.year * 4 + ((d.month - 1) // 3) + 1


def _xyz_and_cv(mu, sigma, t1, t2, min_mu, min_active_weeks, active_weeks):
    mu = mu or 0.0
    sigma = sigma or 0.0
    if mu < (min_mu or 0.0) or (active_weeks or 0) < (min_active_weeks or 0):
        return 'Z', (sigma / mu) if mu > 0 else 999.0
    cv = (sigma / mu) if mu > 0 else 999.0
    if cv <= t1:
        return 'X', cv
    if cv <= t2:
        return 'Y', cv
    return 'Z', cv


def _infer_lifecycle(u_q0, u_q1, u_q2, u_q3, u_q4, u_q5, u_q6, u_q7, p_q8, xyz):
    """Lifecycle PLC inferido por presencia trimestral — PROXY, no canónico.

    Canónico: Levitt PLC (introduction/growth/maturity/decline) basado en
    rate-of-change de ventas, no solo presencia/ausencia por trimestre.
    Esta función usa heurísticas simples sobre 8 trimestres que en algunos
    casos colapsan growth con ramp_up, o marcan declining a productos que
    solo tuvieron quiebre. Ver AGENTS.md → Referencias Canonicas → PLC.
    """
    u_rest = u_q1 + u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7
    u8 = u_q0 + u_rest

    if u8 <= 0:
        return 'dead'
    if p_q8 <= 2 and u_q1 <= 0:
        return 'intermittent'
    if u_q0 > 0 and u_rest <= 0:
        return 'new'
    if u_q0 <= 0 and (u_q1 + u_q2 + u_q3) > 0:
        return 'declining'
    if xyz == 'Z' and p_q8 <= 5:
        return 'seasonal'
    if u_q0 > 0 and u_q1 <= 0 and (u_q2 + u_q3 + u_q4 + u_q5 + u_q6 + u_q7) > 0:
        return 'ramp_up'
    return 'mature'


# ----------------------------------------------------------------------
# Segmentación por régimen de forecast (REG-0..8)
#
# Reemplaza la segmentación por zonas Z1-Z4 (que se calcula en HM-SI con caps
# arbitrarios) por una matriz de reglas explícitas sobre el triplete
# (abcxyz_letter, series_type, ciclo_de_vida).
#
# Política por régimen:
#   REG-0  no_forecast        : dead/declining o C+no_signal → forecast = 0
#   REG-1  smooth_full        : A × smooth × mature → mu + SI completo
#   REG-2  smooth_moderado    : B × smooth × mature
#   REG-3  smooth_conservador : C × smooth
#   REG-4  erratic_cap_120    : any × erratic → cap ±20% sobre mu
#   REG-5  lumpy_proteccion   : A/B × lumpy → mu sin cap inferior
#   REG-6  lumpy_C_floor      : C × lumpy → max(mu, 0.3)
#   REG-7  intermittent_floor : intermittent/no_signal → mu × 0.5
#   REG-8  seasonal_amplif    : seasonal con lifecycle especial
#
# series_type se infiere de la letra XYZ (X→smooth, Y→erratic, Z→lumpy)
# salvo cuando lifecycle marca un caso especial (no_signal / intermittent).
# ----------------------------------------------------------------------

def _classify_series_type(adi, cv2, active_weeks, min_active_weeks,
                          adi_threshold=ADI_THRESHOLD, cv2_threshold=CV2_THRESHOLD):
    """Clasifica series_type por la matriz Syntetos-Boylan (ADI x CV2).

      ADI  = total_weeks / weeks_with_demand    (intervalo promedio de demanda)
      CV2  = (sigma / mu)² SOLO sobre periodos con qty > 0

    Reglas:
      - active_weeks < min_active_weeks → 'no_signal'
      - ADI=0 (sin demanda en el periodo) → 'no_signal'
      - ADI < 1.32 AND CV2 < 0.49 → 'smooth'
      - ADI < 1.32 AND CV2 ≥ 0.49 → 'erratic'
      - ADI ≥ 1.32 AND CV2 < 0.49 → 'intermittent'
      - ADI ≥ 1.32 AND CV2 ≥ 0.49 → 'lumpy'

    Esta clasificación distingue 'intermittent' (esporádico-estable) de
    'lumpy' (esporádico-variable) — distinción que la letra XYZ pierde
    porque agrupa ambos como Z por CV alto sobre todos los periodos.
    """
    if (active_weeks or 0) < (min_active_weeks or 0):
        return 'no_signal'
    if not adi or adi <= 0:
        return 'no_signal'
    intermittent_zone = adi >= adi_threshold
    high_variance = (cv2 or 0.0) >= cv2_threshold
    if intermittent_zone:
        return 'lumpy' if high_variance else 'intermittent'
    return 'erratic' if high_variance else 'smooth'


def _assign_regimen(abcxyz, series_type, ciclo_de_vida):
    """Asigna régimen de forecast desde el triplete.

    PROXY: la matriz de 9 regímenes y las reglas asociadas son una propuesta
    de este proyecto. Tiene fundamento en Syntetos-Boylan (series_type) +
    ABC clásico, pero las políticas concretas por régimen (REG-1 mu×1.00,
    REG-4 cap ±20%, etc.) NO vienen de literatura. Para Fase 2 se debe:
      - REG-7 intermittent → reemplazar mu×0.5 por Croston/SBA real
      - REG-8 seasonal → reemplazar mu×1.10 por Holt-Winters con SI
      - REG-1 a REG-5 → validar factores contra backtest extendido (>13 sem)
    Referencia: AGENTS.md → Referencias Canonicas → Forecast operativo.

    Retorna uno de: 'REG-0' .. 'REG-8'.
    """
    abc_letter = (abcxyz or '')[:1].upper()
    s = (series_type or '').strip().lower()
    c = (ciclo_de_vida or '').strip().lower()

    # 1. Terminal: sin pronóstico
    if c in ('dead', 'declining'):
        return 'REG-0'
    if s == 'no_signal' and abc_letter == 'C':
        return 'REG-0'

    # 2. Lifecycles especiales (precedencia sobre series)
    if c == 'seasonal':
        return 'REG-8'
    if c == 'ramp_up':
        return 'REG-1'   # tratar como smooth durante el ramp

    # 3. Smooth segmentado por importancia ABC
    if s == 'smooth':
        if abc_letter == 'A':
            return 'REG-1'
        if abc_letter == 'B':
            return 'REG-2'
        return 'REG-3'

    # 4. Erratic — política uniforme con cap suave
    if s == 'erratic':
        return 'REG-4'

    # 5. Lumpy segmentado por importancia ABC
    if s == 'lumpy':
        if abc_letter in ('A', 'B'):
            return 'REG-5'
        return 'REG-6'

    # 6. Residual: intermittent / no_signal no-C
    if s in ('intermittent', 'no_signal'):
        return 'REG-7'

    return 'REG-0'


# ----------------------------------------------------------------------
# GMROI — clasificación financiera independiente del régimen de forecast
#
# GMROI = Margen Bruto Anual / Inventario Promedio en Valor
#
# Dimensión paralela a ABC/XYZ:
#   - ABC/XYZ/Régimen → cuánto y cómo pronosticar (forecast)
#   - GMROI (G_A/G_B/G_C/G_D) → cuánto invertir en stock (capital de trabajo)
#
# Cuartiles empíricos sobre el catálogo activo (top 25% → G_A, etc.).
# Productos con inventario=0 o margen<=0 → G_D (clase residual).
# ----------------------------------------------------------------------

def _load_inv_valor_by_product(env, product_ids, cost_by_product, company_id=None):
    """Lee inventario primario desde stock.quant.

    Suma qty sobre ubicaciones internas y multiplica por el costo unitario
    que ya calculó ABCXYZ por producto. Devuelve {product_id: inv_valor_total}.

    SNAPSHOT al momento de la corrida (no promedio histórico).
    TODO Fase 2: convertir a promedio histórico sobre 26w usando
    x_stock_balance_daily.

    Falla silenciosa: si stock.quant no es accesible retorna {} y los
    productos quedan sin inventario calculado (GMROI=0 → G_D).
    """
    if not product_ids:
        return {}
    try:
        Quant = env[STOCK_QUANT_MODEL].sudo()
        domain = [
            ('product_id', 'in', list(product_ids)),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ]
        if company_id:
            domain.append(('company_id', '=', company_id))
        rows = Quant.search_read(domain, ['product_id', 'quantity'])
    except Exception:
        return {}

    qty_by_pid = {}
    for r in rows:
        pv = r.get('product_id')
        if not pv:
            continue
        pid = pv[0] if isinstance(pv, (list, tuple)) else pv
        qty = _safe_float(r.get('quantity'), 0.0)
        if qty > 0:
            qty_by_pid[pid] = qty_by_pid.get(pid, 0.0) + qty

    out = {}
    for pid, qty in qty_by_pid.items():
        cost = _safe_float(cost_by_product.get(pid), 0.0)
        if cost > 0 and qty > 0:
            out[pid] = qty * cost
    return out


def _compute_gmroi(margin_period, n_weeks_period, inv_valor):
    """GMROI — PROXY actual, no canónico.

    PROXY (a corregir en Fase 2 cuando esté el lector de stock con quiebres):
      - Margen: extrapolación lineal margen_26w × (52/26).
        Canónico: rolling 12 meses real, ajustado por seasonality.
      - Inventario: snapshot de stock.quant.
        Canónico: average inventory at cost (promedio mensual 13w o 12m).
      - Anualización lineal asume demanda estacionaria.
        Canónico para seasonal/ramp_up: usar SI ajustado o ciclo completo.

    Referencia: ver AGENTS.md → Referencias Canonicas → Rentabilidad sobre
    inventario. Umbrales retail >3.0 sano / 2.0-3.0 vigilar / <2.0 problema.

    margin_period: margen sumado del periodo (ABC_WEEKS, típicamente 26 sem).
    n_weeks_period: semanas reales del periodo.
    inv_valor: inventario en valor (CLP) — hoy snapshot, futuro promedio.

    Returns float (0.0 si no se puede calcular).
    """
    if inv_valor <= 0 or n_weeks_period <= 0 or margin_period <= 0:
        return 0.0
    margin_annual = margin_period * (GMROI_ANNUAL_WEEKS / float(n_weeks_period))
    return margin_annual / inv_valor


def _classify_gmroi_by_quartiles(items, key='gmroi'):
    """Asigna 'gmroi_class' ∈ {G_A, G_B, G_C, G_D} a cada item por cuartiles.

    PROXY (no canónico): retail estándar usa umbrales fijos (>3.0 sano,
    2.0-3.0 vigilar, <2.0 problema) y/o matriz GMROI×turnover (Hax-Wig)
    en lugar de cuartiles empíricos del catálogo. Los cuartiles actuales
    se mantienen como clasificación relativa hasta que se valide la
    distribución contra benchmarks de retail chileno.

    - Productos con gmroi <= 0 → G_D (cola sin retorno)
    - Sobre los que tienen gmroi > 0: cuartiles empíricos (Q1 / mediana / Q3)
    """
    valid = [it.get(key, 0.0) for it in items if (it.get(key, 0.0) or 0.0) > 0.0]
    if not valid:
        for it in items:
            it['gmroi_class'] = 'G_D'
            it['gmroi_quartile_thresholds'] = (0.0, 0.0, 0.0)
        return (0.0, 0.0, 0.0)

    valid.sort(reverse=True)   # descendente: mayor GMROI primero
    n = len(valid)
    # Top 25% → G_A, 25-50 → G_B, 50-75 → G_C, 75-100 → G_D
    q_a = valid[max(0, n // 4 - 1)] if n >= 4 else valid[0]
    q_b = valid[max(0, n // 2 - 1)] if n >= 2 else valid[-1]
    q_c = valid[max(0, (3 * n) // 4 - 1)] if n >= 4 else valid[-1]

    for it in items:
        g = it.get(key, 0.0) or 0.0
        if g <= 0:
            cls = 'G_D'
        elif g >= q_a:
            cls = 'G_A'
        elif g >= q_b:
            cls = 'G_B'
        elif g >= q_c:
            cls = 'G_C'
        else:
            cls = 'G_D'
        it['gmroi_class'] = cls
        it['gmroi_quartile_thresholds'] = (q_a, q_b, q_c)
    return (q_a, q_b, q_c)


_IMPORTANCE_THRESHOLDS = ((0.05, 'critico'), (0.20, 'alto'), (0.50, 'medio'))

def _importance_from_rank(rank_global, total_items):
    if not total_items or total_items <= 0:
        return 'bajo'
    pct = rank_global / total_items
    for threshold, label in _IMPORTANCE_THRESHOLDS:
        if pct <= threshold:
            return label
    return 'bajo'


def _calc_mu_trend(qty_series, n_weeks, ciclo_de_vida,
                   r2_min, extrap_cap, f8v8_cap, f8v8_floor, n_min, slope_cap):
    """Ajusta promedio histórico semanal incorporando tendencia.

    Retorna (mu_ajustado, method_label).
    Esto NO es forecast operativo; solo es señal histórica para clasificación.
    """
    n = n_weeks
    if n < 4:
        return None, 'fallback_sin_historia'

    xm = (n - 1) / 2.0
    _sum = 0.0
    ss_xy = 0.0
    ss_xx = 0.0
    for _i in range(n):
        _q = qty_series[_i]
        _sum += _q
        _dx = _i - xm
        ss_xy += _dx * _q
        ss_xx += _dx * _dx

    mu_sma = _sum / n

    if ciclo_de_vida == 'dead':
        return mu_sma, 'sma_dead'

    if ss_xx <= 0:
        return mu_sma, 'sma_ss_zero'

    b1 = ss_xy / ss_xx
    b0 = mu_sma - b1 * xm

    ss_res = 0.0
    ss_tot = 0.0
    for _i in range(n):
        _q = qty_series[_i]
        _pred = b0 + b1 * _i
        _err = _q - _pred
        ss_res += _err * _err
        _d = _q - mu_sma
        ss_tot += _d * _d

    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    if r2 < 0.0:
        r2 = 0.0

    _f8v8_mu = None
    _f8v8_factor = None
    _f8v8_f_raw = None
    _f8v8_status = None
    if n >= n_min:
        _sum_rec = 0.0
        for _q in qty_series[-8:]:
            _sum_rec += _q
        _sma_rec = _sum_rec / 8.0
        _sum_ant = 0.0
        for _q in qty_series[-16:-8]:
            _sum_ant += _q
        _sma_ant = _sum_ant / 8.0
        if _sma_ant > 0:
            _f8v8_f_raw = _sma_rec / _sma_ant
            if _f8v8_f_raw < f8v8_floor:
                _f8v8_factor = f8v8_floor
            elif _f8v8_f_raw > f8v8_cap:
                _f8v8_factor = f8v8_cap
            else:
                _f8v8_factor = _f8v8_f_raw
            _f8v8_mu = mu_sma * _f8v8_factor
            _f8v8_status = 'capped' if abs(_f8v8_factor - _f8v8_f_raw) > 0.001 else 'ok'

    _extrap_mu = b0 + b1 * n
    if _extrap_mu < 0.0:
        _extrap_mu = 0.0
    _cap_hi = mu_sma * (1.0 + extrap_cap)
    _cap_lo = mu_sma * (1.0 - extrap_cap)
    if _cap_lo < 0.0:
        _cap_lo = 0.0
    if _extrap_mu < _cap_lo:
        _extrap_adj = _cap_lo
        _extrap_st = 'capped'
    elif _extrap_mu > _cap_hi:
        _extrap_adj = _cap_hi
        _extrap_st = 'capped'
    else:
        _extrap_adj = _extrap_mu
        _extrap_st = 'ok'

    if ciclo_de_vida == 'declining':
        if r2 >= r2_min and b1 < 0:
            pend_rel = abs(b1) / mu_sma if mu_sma > 0 else 0.0
            if pend_rel > slope_cap:
                return mu_sma, 'sma_declining_slope_guard_' + str(round(pend_rel * 100, 1)) + 'pct'
            return _extrap_adj, 'linreg_declining_' + _extrap_st + '_R2=' + str(round(r2, 2)) + '_b1=' + str(round(b1, 3))
        return mu_sma, 'sma_declining_R2=' + str(round(r2, 2))

    if r2 >= r2_min:
        if b1 < 0:
            pend_rel = abs(b1) / mu_sma if mu_sma > 0 else 0.0
            if pend_rel > slope_cap:
                if _f8v8_mu is not None:
                    return _f8v8_mu, 'f8v8_slope_guard_' + _f8v8_status + '_' + str(round(pend_rel * 100, 1)) + 'pct_f=' + str(round(_f8v8_factor, 3))
                return mu_sma, 'sma_slope_guard_' + str(round(pend_rel * 100, 1)) + 'pct'
        return _extrap_adj, 'linreg_' + _extrap_st + '_R2=' + str(round(r2, 2)) + '_b1=' + str(round(b1, 3))

    if _f8v8_mu is not None:
        return _f8v8_mu, 'f8v8_' + _f8v8_status + '_f=' + str(round(_f8v8_factor, 3)) + '_raw=' + str(round(_f8v8_f_raw, 3))

    return mu_sma, 'sma_puro_R2=' + str(round(r2, 2))


# ----------------------
def _filter_vals(vals, fields_map):
    return {k: v for k, v in vals.items() if fields_map.get(k)}


def _to_date(v):
    if not v:
        return False
    if isinstance(v, datetime.date):
        return v
    try:
        return fields.Date.to_date(v)
    except Exception:
        try:
            return datetime.datetime.fromisoformat(str(v)).date()
        except Exception:
            return False


def _pick_best_cost(candidates, target_date):
    if not candidates:
        return 0.0

    best = None
    best_priority = 3

    for c in candidates:
        dfrom = c.get('date_from')
        dto = c.get('date_to')

        if dfrom and dfrom <= target_date and (not dto or dto >= target_date):
            priority = 0
        elif dfrom and dfrom <= target_date:
            priority = 1
        else:
            priority = 2

        if priority < best_priority:
            best_priority = priority
            best = c
        elif priority == best_priority:
            best_dfrom = best.get('date_from') or datetime.date(1900, 1, 1)
            c_dfrom = dfrom or datetime.date(1900, 1, 1)
            if c_dfrom > best_dfrom:
                best = c

    return _safe_float(best.get('cost'), 0.0) if best else 0.0


# ----------------------
# Context
# ----------------------
CTX = env.context or {}

HARD_RESET = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))

ABC_WEEKS = int(CTX.get('abc_weeks', ABC_WEEKS_DEFAULT))
XYZ_WEEKS = int(CTX.get('xyz_weeks', XYZ_WEEKS_DEFAULT))
HIST_MONTHS = int(CTX.get('history_months', HISTORY_MONTHS_DEFAULT))

MIN_ACTIVE_WEEKS = int(CTX.get('min_active_weeks', MIN_ACTIVE_WEEKS_DEFAULT))
MIN_MU_WEEK = float(CTX.get('min_mu_week', MIN_MU_WEEK_DEFAULT))

ABC_T1, ABC_T2 = ABC_THRESHOLDS
XYZ_T1, XYZ_T2 = XYZ_THRESHOLDS

company = env.company
Cal = env['x_calculo_abc_xyz'].sudo()
ProductProduct = env['product.product'].sudo()
ProductTmpl = env['product.template'].sudo()
fields_map = Cal._fields or {}
pt_fields = ProductTmpl._fields or {}

# Validación crítica: x_studio_product_id debe ser product.product
_prod_field = fields_map.get('x_studio_product_id')
if _prod_field:
    try:
        if _prod_field.comodel_name != 'product.product':
            raise ValueError('x_studio_product_id debe apuntar a product.product; hoy apunta a %s' % _prod_field.comodel_name)
    except Exception as _e:
        raise ValueError(str(_e))

# ----------------------
# Lock
# ----------------------
env.cr.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,))
locked = env.cr.fetchone()[0]

if not locked:
    action = {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': 'ABC/XYZ',
            'message': 'Otro proceso está ejecutándose. Reintenta.',
            'type': 'warning',
            'sticky': False,
        }
    }
else:
    warning_msgs = []
    purge_count = 0

    try:
        # ----------------------
        # PURGE INICIAL
        # ----------------------
        if HARD_RESET:
            # Seguridad: nunca purgar con domain vacío.
            # ABCXYZ es company-dependent; si el campo no existe, aborta en vez de borrar todo.
            if not fields_map.get('x_studio_company_id'):
                raise ValueError('HARD_RESET abortado: falta campo x_studio_company_id en x_calculo_abc_xyz')
            old = Cal.search([('x_studio_company_id', '=', company.id)])
            purge_count = len(old)
            if old:
                old.unlink()

        # ----------------------
        # Fechas: por defecto usa última semana cerrada para evitar semana parcial
        # ----------------------
        env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
        today_local = env.cr.fetchone()[0]

        current_week_start = _week_start(today_local)
        last_closed_week_end = current_week_start - datetime.timedelta(days=1)

        date_to_ctx = CTX.get('date_to')
        if date_to_ctx:
            try:
                date_to_raw = datetime.datetime.fromisoformat(str(date_to_ctx)).date()
                date_to = _week_start(date_to_raw) + datetime.timedelta(days=6)
                if date_to >= current_week_start:
                    date_to = last_closed_week_end
            except Exception:
                date_to = last_closed_week_end
        else:
            date_to = last_closed_week_end

        env.cr.execute(
            "SELECT (date_trunc('month', %s::date)::date - (%s || ' months')::interval)::date",
            (date_to, HIST_MONTHS)
        )
        history_from = env.cr.fetchone()[0]

        abc_from = date_to - datetime.timedelta(weeks=ABC_WEEKS)
        xyz_from = date_to - datetime.timedelta(weeks=XYZ_WEEKS)

        abc_weeks_list = _week_range(abc_from, date_to)
        xyz_weeks_list = _week_range(xyz_from, date_to)
        all_weeks_list = _week_range(history_from, date_to)

        q_now_abs = _quarter_abs(date_to)

        _week_to_q_offset = {}
        for _wk in all_weeks_list:
            _wk_q_abs = _quarter_abs(_wk)
            _offset = q_now_abs - _wk_q_abs
            if 0 <= _offset <= 7:
                _week_to_q_offset[_wk] = _offset

        # ----------------------
        # Universo maestro base: product.product vendible activo
        # ----------------------
        dtype_sql = 'pt.detailed_type' if pt_fields.get('detailed_type') else 'pt.type'

        excluded_dtype_sql = "COALESCE(%s, '') NOT IN ('service', 'combo')" % dtype_sql

        env.cr.execute("""
            SELECT
                pp.id AS product_id,
                pp.product_tmpl_id AS tmpl_id,
                pt.name AS tmpl_name,
                pt.categ_id AS categ_id,
                (pt.create_date AT TIME ZONE 'UTC' AT TIME ZONE %s)::date AS create_date_local,
                pp.default_code AS default_code
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pp.active = TRUE
              AND pt.active = TRUE
              AND pt.sale_ok = TRUE
              AND """ + excluded_dtype_sql + """
        """, (TZ_NAME,))

        active_product_ids = set()
        product_to_tmpl = {}
        product_to_categ = {}
        product_to_name = {}
        product_to_code = {}
        product_create_date = {}
        tmpl_to_product_ids = {}
        active_tmpl_ids = set()

        for product_id, tmpl_id, tmpl_name, categ_id, create_date_local, default_code in env.cr.fetchall():
            pid = _safe_int(product_id)
            tid = _safe_int(tmpl_id)
            if not pid or not tid:
                continue
            active_product_ids.add(pid)
            active_tmpl_ids.add(tid)
            product_to_tmpl[pid] = tid
            product_to_categ[pid] = categ_id or False
            product_to_name[pid] = tmpl_name or ''
            product_to_code[pid] = default_code or ''
            product_create_date[pid] = create_date_local or False
            lst = tmpl_to_product_ids.get(tid)
            if lst:
                lst.append(pid)
            else:
                tmpl_to_product_ids[tid] = [pid]

        all_product_ids = list(active_product_ids)
        all_tmpl_ids = list(active_tmpl_ids)

        if not all_product_ids:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'ABC/XYZ',
                    'message': 'No hay variantes activas/vendibles para procesar.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        else:
            product_tuple = tuple(all_product_ids)
            tmpl_tuple = tuple(all_tmpl_ids)

            # ----------------------
            # Ventas POS históricas por product.product
            # ----------------------
            sales_product_ids = set()
            data = {}

            sql_sales = """
                WITH base AS (
                    SELECT
                        pol.id AS line_id,
                        pol.combo_parent_id,
                        pp.id AS product_id,
                        pt.id AS tmpl_id,
                        __DTYPE_SQL__ AS dtype,
                        date_trunc('week', po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date AS week,
                        COALESCE(pol.qty, 0.0) AS qty,
                        COALESCE(pol.price_subtotal, 0.0) AS line_rev
                    FROM pos_order_line pol
                    JOIN pos_order po ON po.id = pol.order_id
                    JOIN product_product pp ON pp.id = pol.product_id
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    WHERE po.company_id = %(company_id)s
                      AND po.state IN ('paid','done','invoiced')
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date >= %(history_from)s
                      AND (po.date_order AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date <= %(date_to)s
                      AND pp.active = TRUE
                      AND pt.sale_ok = TRUE
                      AND pt.active = TRUE
                      AND COALESCE(__DTYPE_SQL__, '') <> 'service'
                ),
                standalone AS (
                    SELECT product_id, week,
                           SUM(line_rev) AS net_revenue,
                           SUM(qty) AS units
                    FROM base
                    WHERE combo_parent_id IS NULL
                      AND COALESCE(dtype, '') <> 'combo'
                    GROUP BY 1, 2
                ),
                combo_child_pre AS (
                    SELECT
                        c.line_id, c.combo_parent_id, c.product_id, c.week, c.qty,
                        c.line_rev AS child_rev,
                        p.line_rev AS parent_rev,
                        CASE
                            WHEN ABS(COALESCE(c.line_rev, 0.0)) > 0.00001 THEN ABS(c.line_rev)
                            WHEN COALESCE(c.qty, 0.0) > 0 THEN c.qty
                            ELSE 0.0
                        END AS weight_value
                    FROM base c
                    JOIN base p ON p.line_id = c.combo_parent_id
                    WHERE c.combo_parent_id IS NOT NULL
                      AND COALESCE(c.dtype, '') <> 'service'
                ),
                combo_parent_stats AS (
                    SELECT combo_parent_id,
                           SUM(weight_value) AS weight_sum,
                           COUNT(*) AS child_count,
                           SUM(CASE WHEN ABS(child_rev) > 0.00001 THEN 1 ELSE 0 END) AS priced_child_count
                    FROM combo_child_pre
                    GROUP BY 1
                ),
                combo_children AS (
                    SELECT c.product_id, c.week,
                           SUM(CASE
                               WHEN s.priced_child_count > 0 THEN c.child_rev
                               WHEN ABS(c.parent_rev) <= 0.00001 THEN 0.0
                               WHEN COALESCE(s.weight_sum, 0.0) > 0.00001
                                   THEN c.parent_rev * (c.weight_value / s.weight_sum)
                               WHEN COALESCE(s.child_count, 0) > 0
                                   THEN c.parent_rev / s.child_count
                               ELSE 0.0
                           END) AS net_revenue,
                           SUM(c.qty) AS units
                    FROM combo_child_pre c
                    JOIN combo_parent_stats s ON s.combo_parent_id = c.combo_parent_id
                    GROUP BY 1, 2
                )
                SELECT product_id, week,
                       SUM(net_revenue) AS net_revenue,
                       SUM(units) AS units
                FROM (
                    SELECT * FROM standalone
                    UNION ALL
                    SELECT * FROM combo_children
                ) su
                GROUP BY 1, 2
            """.replace('__DTYPE_SQL__', dtype_sql)

            env.cr.execute(sql_sales, {
                'company_id': company.id,
                'history_from': history_from,
                'date_to': date_to,
                'tz': TZ_NAME,
            })

            for product_id, wk, rev, qty in env.cr.fetchall():
                pid = _safe_int(product_id)
                if pid not in active_product_ids:
                    continue

                bucket = data.get(pid)
                if not bucket:
                    bucket = {}
                    data[pid] = bucket

                w = bucket.get(wk)
                if w:
                    w[0] += _safe_float(rev)
                    w[1] += _safe_float(qty)
                else:
                    bucket[wk] = [_safe_float(rev), _safe_float(qty)]

                sales_product_ids.add(pid)

            # ----------------------
            # standard_price por product.product
            # ----------------------
            standard_price_map = {}
            _sp_loaded = False

            try:
                env.cr.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'product_product'
                      AND column_name = 'standard_price'
                """)
                _has_sp_col = bool(env.cr.fetchone())
            except Exception:
                _has_sp_col = False

            if _has_sp_col:
                try:
                    env.cr.execute("""
                        SELECT pp.id, pp.standard_price
                        FROM product_product pp
                        WHERE pp.id IN %s
                    """, (product_tuple,))
                    for _pid, _sp in env.cr.fetchall():
                        standard_price_map[_safe_int(_pid)] = _safe_float(_sp, 0.0)
                    _sp_loaded = True
                except Exception:
                    _sp_loaded = False

            if not _sp_loaded:
                for chunk_start in range(0, len(all_product_ids), BATCH_SIZE):
                    chunk = all_product_ids[chunk_start:chunk_start + BATCH_SIZE]
                    for r in ProductProduct.browse(chunk).read(['standard_price']):
                        standard_price_map[r['id']] = _safe_float(r.get('standard_price'), 0.0)

            # ----------------------
            # Costo histórico OH por product.product, con fallback desde template
            # ----------------------
            cost_candidates = {}
            try:
                m = env[COST_MODEL].sudo()
                fields_m = m._fields or {}

                product_field_def = fields_m.get(PRODUCT_FIELD)
                cost_has_date_from = bool(fields_m.get(COST_DATE_FROM_FIELD))
                cost_has_date_to = bool(fields_m.get(COST_DATE_TO_FIELD))
                comodel = product_field_def.comodel_name if (product_field_def and product_field_def.type == 'many2one') else ''

                read_fields = [PRODUCT_FIELD, COST_FIELD]
                if cost_has_date_from:
                    read_fields.append(COST_DATE_FROM_FIELD)
                if cost_has_date_to:
                    read_fields.append(COST_DATE_TO_FIELD)

                if comodel == 'product.product':
                    vals_cost = m.search([(PRODUCT_FIELD, 'in', all_product_ids)]).read(read_fields)
                    for r in vals_cost:
                        product_val = r.get(PRODUCT_FIELD)
                        if not product_val:
                            continue
                        pid = _safe_int(product_val[0])
                        if pid not in active_product_ids:
                            continue
                        candidate = {
                            'date_from': _to_date(r.get(COST_DATE_FROM_FIELD)) if cost_has_date_from else False,
                            'date_to': _to_date(r.get(COST_DATE_TO_FIELD)) if cost_has_date_to else False,
                            'cost': _safe_float(r.get(COST_FIELD), 0.0),
                        }
                        lst = cost_candidates.get(pid)
                        if lst:
                            lst.append(candidate)
                        else:
                            cost_candidates[pid] = [candidate]

                elif comodel == 'product.template':
                    vals_cost = m.search([(PRODUCT_FIELD, 'in', all_tmpl_ids)]).read(read_fields)
                    for r in vals_cost:
                        product_val = r.get(PRODUCT_FIELD)
                        if not product_val:
                            continue
                        tmpl_id = _safe_int(product_val[0])
                        pids = tmpl_to_product_ids.get(tmpl_id) or []
                        if not pids:
                            continue
                        candidate = {
                            'date_from': _to_date(r.get(COST_DATE_FROM_FIELD)) if cost_has_date_from else False,
                            'date_to': _to_date(r.get(COST_DATE_TO_FIELD)) if cost_has_date_to else False,
                            'cost': _safe_float(r.get(COST_FIELD), 0.0),
                        }
                        for pid in pids:
                            lst = cost_candidates.get(pid)
                            if lst:
                                lst.append(candidate)
                            else:
                                cost_candidates[pid] = [candidate]
                else:
                    warning_msgs.append('Modelo de costo sin many2one válido en x_studio_producto')
            except Exception:
                warning_msgs.append('No se pudo leer costo histórico OH; usando standard_price')

            # ----------------------
            # Construcción items
            # ----------------------
            items = []

            for product_id in active_product_ids:
                wkmap = data.get(product_id) or {}

                create_date_local = product_create_date.get(product_id) or date_to

                first_sale_week = None
                for wk0 in all_weeks_list:
                    row0 = wkmap.get(wk0)
                    if row0 and (row0[1] > 0.0 or abs(row0[0]) > 0.00001):
                        first_sale_week = wk0
                        break

                age_anchor = create_date_local
                if first_sale_week and first_sale_week < age_anchor:
                    age_anchor = first_sale_week

                age_days = (date_to - age_anchor).days if age_anchor else 0
                age_weeks = max(age_days // 7 + 1, 1)

                # ABC por margen últimos ABC_WEEKS
                total_rev_abc = 0.0
                total_qty_abc = 0.0
                for wk in abc_weeks_list:
                    row = wkmap.get(wk)
                    if row:
                        total_rev_abc += row[0]
                        total_qty_abc += row[1]

                cost_unit = _pick_best_cost(cost_candidates.get(product_id) or [], date_to)
                if cost_unit <= 0.0:
                    cost_unit = standard_price_map.get(product_id, 0.0)

                total_margin_abc = total_rev_abc - cost_unit * total_qty_abc

                # XYZ histórico sobre TODAS las semanas del periodo
                # (la estacionalidad se descuenta en HM-SI vía seasonal index;
                #  ABCXYZ ya no excluye semanas "atípicas").
                sum_qty_all = 0.0
                sum_sq_all = 0.0
                sum_qty_pos = 0.0   # ADI/CV2 (Syntetos-Boylan): solo periodos con qty>0
                sum_sq_pos = 0.0
                active_wks = 0
                qty_all_vals = []

                weeks_for_xyz = max(min(XYZ_WEEKS, age_weeks), 1)

                for wk in xyz_weeks_list:
                    row = wkmap.get(wk)
                    q = row[1] if row else 0.0
                    qty_all_vals.append(q)
                    sum_qty_all += q
                    sum_sq_all += q * q
                    if q > 0:
                        active_wks += 1
                        sum_qty_pos += q
                        sum_sq_pos += q * q

                if weeks_for_xyz > 0:
                    mu_sma = sum_qty_all / weeks_for_xyz
                    variance = (sum_sq_all / weeks_for_xyz) - mu_sma * mu_sma
                    if variance < 0.0:
                        variance = 0.0
                else:
                    mu_sma = 0.0
                    variance = 0.0

                sigma_week = variance ** 0.5

                xyz, cv = _xyz_and_cv(mu_sma, sigma_week, XYZ_T1, XYZ_T2,
                                      MIN_MU_WEEK, MIN_ACTIVE_WEEKS, active_wks)

                # ADI = intervalo promedio de demanda (sobre periodo XYZ completo).
                # CV² = varianza relativa de las CANTIDADES cuando hay demanda.
                # Ambos son los inputs canónicos de la matriz Syntetos-Boylan.
                adi = (weeks_for_xyz / active_wks) if active_wks > 0 else 0.0
                if active_wks > 0:
                    mu_pos = sum_qty_pos / active_wks
                    var_pos = (sum_sq_pos / active_wks) - mu_pos * mu_pos
                    if var_pos < 0.0:
                        var_pos = 0.0
                    cv2_pos = (var_pos / (mu_pos * mu_pos)) if mu_pos > 0 else 0.0
                else:
                    cv2_pos = 0.0

                # v19.4: VISTA CORTA (ultimas 12 semanas) - calcular adi/cv2 short
                # para detectar cambios estructurales recientes que la vista larga
                # (52w) no captura. Caso real: SKUs en ramp-up clasificados como
                # smooth/intermittent por historia larga pero que en el corto son
                # erratic/lumpy o smooth con mu_week alto.
                SHORT_WEEKS = 12
                qty_short_vals = qty_all_vals[-SHORT_WEEKS:] if len(qty_all_vals) >= 1 else []
                active_wks_short = 0
                sum_qty_pos_short = 0.0
                sum_sq_pos_short = 0.0
                for _q_s in qty_short_vals:
                    if _q_s > 0:
                        active_wks_short += 1
                        sum_qty_pos_short += _q_s
                        sum_sq_pos_short += _q_s * _q_s
                weeks_for_xyz_short = len(qty_short_vals)
                adi_short = (weeks_for_xyz_short / active_wks_short) if active_wks_short > 0 else 0.0
                if active_wks_short > 0:
                    mu_pos_short = sum_qty_pos_short / active_wks_short
                    var_pos_short = (sum_sq_pos_short / active_wks_short) - mu_pos_short * mu_pos_short
                    if var_pos_short < 0.0:
                        var_pos_short = 0.0
                    cv2_pos_short = (var_pos_short / (mu_pos_short * mu_pos_short)) if mu_pos_short > 0 else 0.0
                else:
                    cv2_pos_short = 0.0

                # Trimestres activos últimos 8 trimestres
                u_total_hist = 0.0
                _u_q = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

                last_sale_week = False
                for _wk, _row in wkmap.items():
                    _qty_val = _safe_float(_row[1], 0.0)
                    u_total_hist += _qty_val
                    if _qty_val > 0.0:
                        if (not last_sale_week) or (_wk > last_sale_week):
                            last_sale_week = _wk
                        _off = _week_to_q_offset.get(_wk)
                        if _off is not None:
                            _u_q[_off] += _qty_val

                if last_sale_week:
                    weeks_since_last_sale = ((_week_start(date_to) - last_sale_week).days // 7)
                else:
                    weeks_since_last_sale = len(all_weeks_list)

                _p_q8 = 0
                for _u in _u_q:
                    if _u > 0:
                        _p_q8 += 1

                pres = [1 if _u_q[_i] > 0 else 0 for _i in range(8)]
                p_q7 = 0
                p_q4 = 0
                for _i in range(7):
                    p_q7 += pres[_i]
                for _i in range(4):
                    p_q4 += pres[_i]

                _ciclo_pre = _infer_lifecycle(
                    _u_q[0], _u_q[1], _u_q[2], _u_q[3],
                    _u_q[4], _u_q[5], _u_q[6], _u_q[7],
                    _p_q8, xyz
                )

                _mu_adj, _mu_trend_method = _calc_mu_trend(
                    qty_all_vals,
                    weeks_for_xyz,
                    _ciclo_pre,
                    MU_TREND_R2_MIN,
                    MU_TREND_EXTRAP_CAP,
                    MU_TREND_F8V8_CAP,
                    MU_TREND_F8V8_FLOOR,
                    MU_TREND_N_MIN,
                    MU_TREND_SLOPE_CAP,
                )
                mu_week = _mu_adj if _mu_adj is not None else mu_sma

                items.append({
                    'product_id': product_id,
                    'tmpl_id': product_to_tmpl.get(product_id),
                    'total_margin_abc': total_margin_abc,
                    'total_rev_abc': total_rev_abc,
                    'total_qty_abc': total_qty_abc,
                    'cost_unit': cost_unit,
                    'mu_week': mu_week,
                    'mu_sma': mu_sma,
                    'mu_trend_method': _mu_trend_method,
                    'sigma_week': sigma_week,
                    'cv': cv,
                    'adi': adi,
                    'cv2_pos': cv2_pos,
                    # v19.4: vista corta (12 sem)
                    'adi_short': adi_short,
                    'cv2_pos_short': cv2_pos_short,
                    'active_weeks_short': active_wks_short,
                    'weeks_for_xyz_short': weeks_for_xyz_short,
                    'n_weeks': weeks_for_xyz,
                    'active_weeks': active_wks,
                    'create_date_local': create_date_local,
                    'age_weeks': age_weeks,
                    'u_total_hist': u_total_hist,
                    'last_sale_week': last_sale_week,
                    'weeks_since_last_sale': weeks_since_last_sale,
                    'u_q': _u_q,
                    'p_q4': p_q4,
                    'p_q7': p_q7,
                    'p_q8': _p_q8,
                    'xyz': xyz,
                    '_ciclo_pre': _ciclo_pre,
                })

            # ----------------------
            # GMROI — dimensión financiera paralela al ABCXYZ.
            # Lee stock.quant (primario Odoo), agrega qty sobre ubicaciones
            # internas y multiplica por el costo unitario que ya calculó
            # ABCXYZ por producto. Luego clasifica por cuartiles.
            # ----------------------
            cost_by_product_map = {it['product_id']: it.get('cost_unit', 0.0) for it in items}
            inv_valor_by_product = _load_inv_valor_by_product(
                env,
                [_it['product_id'] for _it in items],
                cost_by_product_map,
                company_id=company.id,
            )
            for _it in items:
                _inv = _safe_float(inv_valor_by_product.get(_it['product_id']), 0.0)
                _it['inv_valor_avg'] = _inv
                _it['gmroi'] = _compute_gmroi(
                    _it.get('total_margin_abc', 0.0),
                    _it.get('n_weeks', 0),
                    _inv,
                )

            gmroi_q_thresholds = _classify_gmroi_by_quartiles(items, key='gmroi')

            # ----------------------
            # Ranking ABC — sin stock como criterio de desempate
            # ----------------------
            for _it in items:
                _it['_sort_key'] = (
                    _it['total_margin_abc'],
                    _it['total_rev_abc'],
                    _it['mu_week'],
                )

            items.sort(key=lambda _it: _it['_sort_key'], reverse=True)

            total_items = len(items)
            grand = 0.0
            for _it in items:
                if _it['total_margin_abc'] > 0.0:
                    grand += _it['total_margin_abc']

            batch = []
            total_created = 0
            log_lines = []
            cum = 0.0

            _cal_create = Cal.with_context(
                tracking_disable=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notrack=True
            ).create

            for rank, it in enumerate(items, 1):
                product_id = it['product_id']
                total_margin_abc = it['total_margin_abc']
                abc_base = total_margin_abc if total_margin_abc > 0.0 else 0.0

                if grand <= 0.0:
                    abc = 'C'
                else:
                    cum += abc_base / grand
                    if abc_base <= 0.0:
                        abc = 'C'
                    elif cum <= ABC_T1:
                        abc = 'A'
                    elif cum <= ABC_T2:
                        abc = 'B'
                    else:
                        abc = 'C'

                xyz = it['xyz']
                abcxyz = abc + xyz
                u_q = it['u_q']

                ciclo_de_vida = it['_ciclo_pre']

                # Series type por matriz Syntetos-Boylan (ADI × CV² sobre positivos).
                # Régimen de forecast: triplete (abcxyz, series_type, ciclo) → REG-0..8.
                # Esto sustituye la segmentación por zonas Z1-Z4 de HM-SI.
                series_type = _classify_series_type(
                    it.get('adi', 0.0),
                    it.get('cv2_pos', 0.0),
                    it.get('active_weeks', 0),
                    MIN_ACTIVE_WEEKS_DEFAULT,
                )

                # v19.4: vista corta (12 semanas). Para el corto pedimos
                # min_active_weeks=2 (en lugar del default que aplica al largo)
                # asi un SKU con 2+ semanas activas en las ultimas 12 es
                # clasificable. Si tiene <2 sem activas en el corto, no_signal.
                series_type_short = _classify_series_type(
                    it.get('adi_short', 0.0),
                    it.get('cv2_pos_short', 0.0),
                    it.get('active_weeks_short', 0),
                    2,
                )

                # Si el corto difiere del largo Y NO es no_signal, usar corto.
                # Si corto es no_signal (SKU sin actividad reciente), mantener largo.
                if series_type_short and series_type_short != 'no_signal' and series_type_short != series_type:
                    series_type_active = series_type_short
                else:
                    series_type_active = series_type

                regimen = _assign_regimen(abcxyz, series_type_active, ciclo_de_vida)

                # Score de eliminación / revisión de surtido
                puntaje = 0.0
                motivos = []

                if abc == 'C':
                    puntaje += PUNTOS_ABC_C
                    motivos.append('ABC=C')
                if xyz == 'Z':
                    puntaje += PUNTOS_XYZ_Z
                    motivos.append('XYZ=Z')
                if it['mu_week'] <= MU_ELIM:
                    puntaje += PUNTOS_MU_BAJA
                    motivos.append('promedio histórico bajo')
                if it['p_q8'] <= 2:
                    puntaje += PUNTOS_Q_POCA
                    motivos.append('poca presencia trimestral')
                if u_q[1] <= 0:
                    puntaje += PUNTOS_ULT_Q0
                    motivos.append('último trimestre=0')

                zero_sales_hist = it['u_total_hist'] <= 0.0
                if zero_sales_hist:
                    puntaje += PUNTOS_SIN_VENTA
                    motivos.append('sin venta histórica')

                eliminar_sino = puntaje >= SCORE_ELIM
                if it.get('age_weeks', 0) < 8:
                    eliminar_sino = False
                    motivos.append('sku_nuevo_lt_8w')

                importancia = _importance_from_rank(rank, total_items)

                if eliminar_sino:
                    if zero_sales_hist:
                        motivo_grupo = 'Sin venta histórica'
                    elif ciclo_de_vida == 'dead':
                        motivo_grupo = 'Sin movimiento reciente'
                    elif ciclo_de_vida == 'intermittent':
                        motivo_grupo = 'Intermitente / baja presencia'
                    elif abc == 'C' and xyz == 'Z':
                        motivo_grupo = 'Baja contribución y alta variabilidad'
                    else:
                        motivo_grupo = 'Baja rotación / revisar'
                    motivo_eliminar = '; '.join(motivos)[:240]
                else:
                    motivo_eliminar = ''
                    motivo_grupo = ''

                # Estado surtido opcional si existe el campo
                assortment_status = 'mantener'
                if it.get('age_weeks', 0) < 8:
                    assortment_status = 'observar_nuevo'
                elif eliminar_sino:
                    if zero_sales_hist or ciclo_de_vida == 'dead':
                        assortment_status = 'desactivar'
                    else:
                        assortment_status = 'revisar'
                elif ciclo_de_vida == 'seasonal':
                    assortment_status = 'seasonal'

                in_sales = product_id in sales_product_ids
                origin_label = 'master+sales' if in_sales else 'master'

                vals = {
                    'x_active': True,
                    'x_name': 'ABC/XYZ GLOBAL · PP%s' % product_id,
                    'x_studio_company_id': company.id,
                    'x_studio_product_id': product_id,
                    'x_studio_team_id': False,
                    'x_studio_categ_id': product_to_categ.get(product_id),
                    'x_studio_abc': abc,
                    'x_studio_xyz': xyz,
                    'x_studio_abcxyz': abcxyz,
                    'x_studio_rank_abcxyz': rank,
                    'x_studio_sequence': rank,
                    'x_studio_create_date': it.get('create_date_local'),
                    'x_studio_age_weeks': it.get('age_weeks'),
                    'x_studio_n_weeks': it['n_weeks'],
                    'x_studio_mu_week': it['mu_week'],
                    'x_studio_sigma_week': it['sigma_week'],
                    'x_studio_cv': it['cv'],
                    'x_studio_adi': it.get('adi', 0.0),
                    'x_studio_cv2': it.get('cv2_pos', 0.0),
                    'x_studio_p_q4': it['p_q4'],
                    'x_studio_p_q7': it['p_q7'],
                    'x_studio_p_q8': it['p_q8'],
                    'x_studio_trimestres_activos': it['p_q8'],
                    'x_studio_uni_ltimo_trimestre': u_q[1],
                    'x_studio_uni_trimestre_ly': u_q[5],
                    'x_studio_importancia': importancia,
                    'x_studio_puntaje': puntaje,
                    'x_studio_eliminar_sino': eliminar_sino,
                    'x_studio_motivo_eliminar': motivo_eliminar,
                    'x_studio_motivo_eliminar_grupo': motivo_grupo,
                    'x_studio_ciclo_de_vida': ciclo_de_vida,
                    'x_studio_series_type': series_type,
                    'x_studio_series_type_short': series_type_short,
                    'x_studio_series_type_active': series_type_active,
                    'x_studio_regimen': regimen,
                    'x_studio_gmroi': it.get('gmroi', 0.0),
                    'x_studio_gmroi_class': it.get('gmroi_class', 'G_D'),
                    'x_studio_inv_valor_avg': it.get('inv_valor_avg', 0.0),
                    'x_studio_notes': (
                        'ABCXYZ limpio | lifecycle=%s | rank=%s | margin=%.2f | rev=%.2f | qty=%.2f | mu=%.3f | sigma=%.3f | cv=%.3f | trend=%s | origin=%s'
                        % (
                            ciclo_de_vida,
                            rank,
                            total_margin_abc,
                            it['total_rev_abc'],
                            it['total_qty_abc'],
                            it['mu_week'],
                            it['sigma_week'],
                            it['cv'],
                            it.get('mu_trend_method', '-'),
                            origin_label,
                        )
                    ),
                    'x_studio_trazabilidad_corta': (
                        'rank=%s | %s | %s | age_w=%.0f | margin=%.2f | rev=%.2f | qty=%.2f | mu=%.3f | sigma=%.3f | cv=%.3f | p_q8=%s | elim=%s | %s'
                        % (
                            rank,
                            abcxyz,
                            ciclo_de_vida,
                            it.get('age_weeks', 0),
                            total_margin_abc,
                            it['total_rev_abc'],
                            it['total_qty_abc'],
                            it['mu_week'],
                            it['sigma_week'],
                            it['cv'],
                            it['p_q8'],
                            eliminar_sino,
                            motivo_grupo,
                        )
                    ),
                    'x_studio_updated_on': datetime.datetime.utcnow(),
                }

                # Campos nuevos opcionales si ya fueron creados
                if fields_map.get('x_studio_period_end'):
                    vals['x_studio_period_end'] = date_to
                if fields_map.get('x_studio_calc_version'):
                    vals['x_studio_calc_version'] = VERSION_ID
                if fields_map.get('x_studio_assortment_status'):
                    vals['x_studio_assortment_status'] = assortment_status
                if fields_map.get('x_studio_zero_sales_24m'):
                    vals['x_studio_zero_sales_24m'] = zero_sales_hist
                if fields_map.get('x_studio_last_sale_week'):
                    vals['x_studio_last_sale_week'] = it.get('last_sale_week') or False
                if fields_map.get('x_studio_weeks_since_last_sale'):
                    vals['x_studio_weeks_since_last_sale'] = it.get('weeks_since_last_sale', len(all_weeks_list))
                if fields_map.get('x_studio_mu_trend_method'):
                    vals['x_studio_mu_trend_method'] = it.get('mu_trend_method', '')[:120]

                # Compatibilidad: estos campos existen en tu modelo actual, pero quedan sin escribir:
                # x_studio_demanda_semanal, x_studio_peso_dinmico,
                # x_studio_stock, x_studio_stock_effective, x_studio_share_of_pool,
                # x_studio_cover_weeks, x_studio_cover_label,
                # x_studio_lead_weeks, x_studio_moq,
                # x_studio_safety_stock_units, x_studio_target_units,
                # x_studio_factor_estacional.

                vals = _filter_vals(vals, fields_map)
                batch.append(vals)

                if len(log_lines) < 20:
                    label = product_to_code.get(product_id) or ('PP%s' % product_id)
                    log_lines.append(
                        '%s | %s | rank=%s | %s | %s | margin=%.2f | mu=%.3f | cv=%.3f | elim=%s | %s'
                        % (
                            label,
                            product_to_name.get(product_id, ''),
                            rank,
                            abcxyz,
                            ciclo_de_vida,
                            total_margin_abc,
                            it['mu_week'],
                            it['cv'],
                            eliminar_sino,
                            motivo_grupo,
                        )
                    )

                if len(batch) >= BATCH_SIZE:
                    _cal_create(batch)
                    total_created += len(batch)
                    batch = []

            if batch:
                _cal_create(batch)
                total_created += len(batch)

            try:
                log(
                    'ABCXYZ v18.3 PRODUCT.PRODUCT CLEAN SAFE | purged=%s | creados=%s | products=%s | sales=%s | hist=%s→%s | bucket=GLOBAL'
                    % (
                        purge_count,
                        total_created,
                        len(active_product_ids),
                        len(sales_product_ids),
                        history_from,
                        date_to,
                    ),
                    level='info'
                )
                for line in log_lines:
                    log(line, level='info')
            except Exception:
                pass

            msg = (
                'OK | v18.3 CLEAN SAFE | purged=%s | procesados=%s | products=%s | sales=%s | hist=%s→%s | ABC=%sw XYZ=%sw | product_id=product.product'
                % (
                    purge_count,
                    total_created,
                    len(active_product_ids),
                    len(sales_product_ids),
                    history_from,
                    date_to,
                    ABC_WEEKS,
                    XYZ_WEEKS,
                )
            )

            if warning_msgs:
                msg += ' | warnings=' + ' / '.join(warning_msgs[:3])

            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'ABC/XYZ v18.3 CLEAN SAFE',
                    'message': msg,
                    'sticky': False,
                    'type': 'success',
                }
            }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
