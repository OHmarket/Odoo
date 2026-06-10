# OH Analisis de Stock LOCAL + Bodega Central
# ============================================================
#
# Version activa: v9.2.0 (ver CHANGELOG.md para historial completo)
#
# v9.2.0 (2026-06-09): CD pass-through diferencial. solo_bodega: la sala SOLO
#   transfiere desde CD; el faltante se consolida en UNA compra_cd en la fila CD
#   (id 26) = max(0, Σ necesidad_salas − stock_CD). Elimina (a) el orphan de salas
#   'compra_cd' cuyo traslado nunca se generaba y (b) el doble conteo del antiguo
#   solo_bodega_cd_replenish (target forward del CD). Ver
#   proyectos/2026-06-09-diag-li450701/diseno.md
#
# Objetivo:
#   - Calcular analisis de stock por Sucursal (crm.team) y Bodega Central.
#   - Leer demanda local desde x_forecast_weekly_data (fallback a "General OH"
#     solo si falta forecast local).
#   - Calcular stock fisico por sucursal desde ubicaciones directas (sin pos.config).
#   - Reservar stock de Bodega Central entre sucursales para un mismo SKU
#     usando prioridad operativa local:
#       1) sin_stock  2) critico  3) bajo  4) menor cover_weeks
#       5) mayor mu_week  6) mayor gap_target
#
# Reglas vivas (resumen operativo, no cronologia):
#   - Sala usa period_weeks por SKU como horizonte (fwd['lead_weeks']);
#     fallback PURCHASE_CYCLE_WEEKS si missing. lead_weeks operativo = 0.
#   - CD reposicion solo_bodega usa el MISMO period_weeks por SKU (v9.1.85).
#   - Safety stock: z * sigma * sqrt(period_weeks). Z segun ABCXYZ:
#     AX/BX=1.68, AY=1.28, BY=1.04, AZ=1.04, CX=0.84, BZ/CY=0.35, CZ=0.0;
#     default fallback 0.84. Top cash sube a 1.65 (piso, display reserve).
#     Cigarros (categ 1628): multiplicador 0.778 sobre Z; display_mult=0.
#   - MOQ: politica caja-o-esperar (SMART_MOQ_ROUNDING). Bloquea cajas
#     cuyo post-stock supere target * 1.35. Para AX/AY/AZ/BX/BY/BZ en estado
#     critico/sin_stock se fuerza ceil de caja.
#   - Routing sala -> CD: si solo_bodega -> CD. Si categoria padre in
#     [Cafeteria, Cigarrillos, Congelados, Esenciales Hogar, Impulso,
#     Snack y Coctel] -> SALA siempre. Si cobertura_caja = moq/demanda_semanal
#     > COVER_WEEKS_THRESHOLD_FOR_CD (4.286 sem) -> CD. Resto -> SALA.
#   - Phantom kits: padre absorbe demanda del pool (mu_padre + mu_hijo/qty_per_parent).
#     Hijos visibles, no compran. PHANTOM_PROCUREMENT_MODE define la direccion:
#     buy_parent_block_children (default) compra el PADRE y bloquea el hijo, tanto
#     en sala como en la reposicion CD solo_bodega (v9.1.87 hizo ese loop mode-aware;
#     antes saltaba al padre e invertia la regla). block_parent = legacy inverso.
#   - Techo financiero por proveedor: lee res.partner payment_term
#     (FINANCIAL_CEILING_WEEKS = payment_days / 7).
#   - sigma_week NO se escala por share cuando fwd_source='local' (ya es local).
#     Solo se escala por sqrt(share) si fwd_source='global'.
#   - compra_mensual_estimada = compra_w1 + gap_residual operativo (no presupuesto
#     teorico de target). Forzada a 0 para no_disponible/phantom_block/retorno/
#     liquidar y para lineas locales con buy_action='compra_cd' (se calcula
#     UNA vez en la fila CD).
#   - stock_pedido_compra/transfer expone OC y pickings en x_studio_oc_pendientes
#     (si el campo existe en Studio).
#
# Detalles, fixes historicos y metricas de snapshots: ver CHANGELOG.md.
# ------------------------------------------------------------

VERSION_ID = 'OH_STOCK_ANALYSIS_v9_1_87_PHANTOM_CD_REPLENISH_PADRE'

TZ_NAME  = 'America/Santiago'
LOCK_KEY = 99009441
GLOBAL_TEAM_NAME = 'General OH'

ANALYSIS_MODEL = 'x_analisis_de_stock'
ABC_MODEL      = 'x_calculo_abc_xyz'
FWD_MODEL      = 'x_hm_si_forecast'
# v3.35 (S5) escribe team con x_studio_team_id, no x_studio_local.
FWD_TEAM_FIELD = 'x_studio_team_id'

SNAPSHOT_FIELD = 'x_studio_fecha_1'
COMPANY_FIELD  = 'x_studio_company_id'

FILTERED_TEAM_IDS_DEFAULT = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]

# Mapa fallback correcto team_id -> stock.warehouse.id
TEAM_WAREHOUSE_MAP_FALLBACK = {
    5:  1,    # Panguipulli 790  -> PA790/Stock
    6:  4,    # Los Lagos        -> LL200/Stock
    7:  2,    # Futrono          -> FU120/Stock
    8:  3,    # Panguipulli 645  -> PA645/Stock
    9:  16,   # Panguipulli 763  -> PA763/Stock
    10: 8,    # Lautaro          -> LA812/Stock
    11: 5,    # San José         -> SJ121/Stock
    12: 9,    # Paillaco         -> PA706/Stock
    13: 10,   # Mehuin Express   -> MEHEX/Stock
    16: 12,   # Coñaripe         -> CO899/Stock
    17: 14,   # Nueva Imperial   -> IM495/Stock
    18: 13,   # Malalhue         -> ML402/Stock
}

# Configuración Bodega Central
CENTRAL_WAREHOUSE_ID_DEFAULT      = 15
CENTRAL_ROOT_LOCATION_IDS_DEFAULT = []
CENTRAL_LOCATION_IDS_DEFAULT      = []
CENTRAL_RESERVE_PCT_DEFAULT       = 0.0   # 0.10 => reserva 10% del stock central

USE_DYNAMIC_POS_CONFIG_DEFAULT    = False

BATCH_SIZE         = 500
HARD_RESET_DEFAULT = True

PAYMENT_DAYS_DEFAULT        = 30.0
CD_ELIGIBLE_ABCXYZ_DEFAULT  = ('AX', 'AY', 'AZ', 'BX', 'BY', 'BZ')
PURCHASE_CYCLE_DAYS_DEFAULT = 7.0
DEMAND_FLOOR_WEEK           = 1.0 / 4.345  # ~0.23
MOQ_COVER_GUARD_DEFAULT      = 2.5
SMART_MOQ_ROUNDING_DEFAULT    = True
MOQ_MAX_POST_FACTOR_DEFAULT   = 1.35   # max post-compra vs target_weeks antes de bloquear caja extra
MOQ_CRITICAL_FACTOR_DEFAULT   = 0.50   # critico si cobertura < periodo * este factor
RETURN_HOLD_WEEKS_DEFAULT    = 8.0
RETURN_TRIGGER_WEEKS_DEFAULT = 8.0
CD_DELIVERY_EXTRA_DAYS_DEFAULT = 2.0  # buffer logistico CD->sala (atraso camion, ej. martes en vez de lunes)
CENTRAL_TEAM_ID_DEFAULT = 26

# Politica de descentralizacion sala vs CD: COBERTURA DE CAJA + EXCLUSION POR CATEGORIA.
#
# Regla operativa:
#   1) solo_bodega=True manda primero (negociacion comercial).
#   2) Si la categoria del SKU pertenece a una de las categorias padre
#      excluidas (recursivamente, incluye todos los hijos), va a SALA
#      siempre. Estas categorias son productos de picking lento o muy
#      baratos por unidad donde consolidar en CD destruye eficiencia.
#   3) Si no es solo_bodega y la categoria NO esta excluida, se calcula
#      cobertura_caja = moq / demanda_semanal. Si cobertura > umbral
#      (default 30 dias = 4.286 semanas), se fuerza compra_cd para
#      consolidar entre sucursales. Si no, queda en compra_sala.
#
# COVER_WEEKS_THRESHOLD_FOR_CD: umbral en semanas. Si la caja deja mas de
# este horizonte de stock en sala, se manda a CD. Default 30/7 = 4.286.
COVER_WEEKS_THRESHOLD_FOR_CD_DEFAULT = 30.0 / 7.0  # ~4.286 sem (30 dias)

# NO_CD_PARENT_CATEGORY_IDS: lista de IDs padre en product.category.
# Se expanden recursivamente via child_of para incluir todas las
# subcategorias. SKUs de estas categorias nunca caen al check de cobertura
# (siempre van a compra_sala salvo que solo_bodega=True).
# IDs corresponden a OH Market (Mayo 2026):
#   1715 = Cafeteria
#   1719 = Cigarrillos y Tabacos
#   1717 = Congelados
#   1716 = Esenciales Hogar
#   1718 = Impulso
#   1653 = Snack y Coctel
NO_CD_PARENT_CATEGORY_IDS_DEFAULT = [1715, 1716, 1717, 1718, 1719, 1653]

# Politica de exhibicion + top caja
# Reserva comercial que se suma al target operativo (no a la demanda).
DISPLAY_STOCK_ENABLED_DEFAULT = False
DISPLAY_MIN_DEMAND_WEEK_DEFAULT = 1.0
DISPLAY_MAX_UNITS_DEFAULT = 6.0
DISPLAY_PCT_DEFAULT = 0.0
DISPLAY_PCT_TOP_CASH_DEFAULT = 0.30
DISPLAY_PCT_BY_ABCXYZ = {
    'AX': 0.20, 'AY': 0.20,
    'BX': 0.15, 'BY': 0.15,
    'AZ': 0.10, 'BZ': 0.10,
    'CX': 0.0,  'CY': 0.0,
    'CZ': 0.0,
}
TOP_CASH_WEEKLY_MIN_DEFAULT = 25000.0
TOP_CASH_RANK_MAX_DEFAULT = 300
TOP_CASH_SAFETY_FACTOR_DEFAULT = 1.65
TOP_CASH_ABCXYZ_ALLOWED = ('AX', 'AY', 'BX', 'BY')

# Ajuste de estimacion para cigarros (categ_id=1628):
# multiplicador 0.778 sobre el safety factor global (baja AX/AY de z=1.645 a z=1.28).
CIGARROS_CATEGORY_IDS_DEFAULT = [1628]
CIGARROS_SAFETY_MULT_DEFAULT = 0.778
CIGARROS_DISPLAY_MULT_DEFAULT = 0.0

# Valoracion de packs/kit phantom.
# component_first: costo pack = suma(componentes * cantidad BOM); fallback a costo propio.
# product_first: usa costo propio del pack; fallback a componentes si viene en cero.
# value_phantom_kits=False: valor stock = 0 para pool=phantom.
VALUE_PHANTOM_KITS_DEFAULT = True
PHANTOM_COST_SOURCE_DEFAULT = 'product_first'
PHANTOM_PROCUREMENT_MODE_DEFAULT = 'buy_parent_block_children'  # block_parent | allow_parent | buy_parent_block_children

_SAFETY_FACTOR = {
    'AX': 1.68, 'BX': 1.68,   # 2026-06-04: bajado de 2.05 (98%->95% servicio, sobre-protegido)
    'AY': 1.28, 'BY': 1.04,   # 2026-06-10: bajado de 1.68/1.28 (diag_z_ay_az_by: libera ~$5.9M target, svc teorico 90%/85%; curva quiebre-vs-z plana en Y)
    'AZ': 1.04, 'BZ': 0.35,   # 2026-06-02: bajado de 0.84 (sobre-protegido)
    'CX': 0.84, 'CY': 0.35,   # 2026-06-02: bajado de 0.52 (sobre-protegido)
    'CZ': 0.0,
}
# Calibracion BZ/CY (2026-06-02): el test de safety factor mostro que en estos
# segmentos de baja rotacion la curva quiebre vs z es plana (el colchon casi no
# compra servicio: los quiebres vienen de spikes que ni z=0.84 alcanza). Con z=0.35
# el quiebre sube <1pp y ambos quedan muy bajo su tolerancia (BZ 20%, CY 30%),
# liberando ~58%/33% del safety. Ver proyectos/2026-06-02-test-safety-factor/.
# Calibracion A/B-X (2026-06-04): AX/AY/BX bajados de 2.05 a 1.68 (servicio 98%->95%,
# sigue alto). El 2.05 sobre-protegia el VOLUMEN: simulacion mostro -12M de inventario
# objetivo, 0 SKUs nuevos bajo 90% servicio. Confirma el test 2026-06-02 (A/B-X en
# 2.05 = ~+10M de stock muerto). El sobrestock vivia en el z, NO en el sigma (el
# proxy sigma-demanda 4sem si acaso subestima; ver proyectos/2026-06-04-revision-target-cobertura/).
_SAFETY_FACTOR_DEFAULT = 0.84

# Sala solo_bodega usa la misma regla que proveedor->CD con H=1.0 sem:
# safety stock = Z * sigma * sqrt(H), Z desde _SAFETY_FACTOR por ABCXYZ.


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


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def _financial_ceiling_weeks(payment_days):
    return max(_safe_float(payment_days, 0.0), 0.0) / 7.0


def _payment_days_from_term(term, default_days):
    # Deriva dias de pago efectivos desde un account.payment.term.
    # OH (Mayo 2026): 1 linea por term con value='percent' y nb_days=X (no usan balance).
    # Si hay line con value='balance' la usamos (caso estandar Odoo); sino max(nb_days).
    # Fallback al default global si nada da dias > 0.
    if not term:
        return default_days
    lines = term.line_ids or []
    balance = [l for l in lines if (l.value or '') == 'balance']
    if balance:
        d = _safe_int(balance[0].nb_days, 0)
        return float(d) if d > 0 else default_days
    if lines:
        d = max([_safe_int(l.nb_days, 0) for l in lines] + [0])
        return float(d) if d > 0 else default_days
    return default_days


def _is_top_cash_sku(abcxyz, rank_abcxyz, venta_bruta_week):
    abc = (abcxyz or '').strip()
    if abc not in TOP_CASH_ABCXYZ_ALLOWED:
        return False
    rank = _safe_int(rank_abcxyz, 0)
    venta = _safe_float(venta_bruta_week, 0.0)
    if rank > 0 and rank <= TOP_CASH_RANK_MAX:
        return True
    if venta >= TOP_CASH_WEEKLY_MIN:
        return True
    return False


def _safety_factor_for(abcxyz, is_top_cash=False, is_cigarros=False):
    abc = (abcxyz or '').strip()
    base = _safe_float(_SAFETY_FACTOR.get(abc, _SAFETY_FACTOR_DEFAULT), _SAFETY_FACTOR_DEFAULT)

    # Política global/top cash.
    if is_top_cash and abc in TOP_CASH_ABCXYZ_ALLOWED:
        base = max(base, TOP_CASH_SAFETY_FACTOR)

    # Cigarros mantiene el mismo modelo estadistico, pero reduce exposicion.
    # Se aplica despues de top_cash para evitar que top_cash vuelva a inflar el z.
    if is_cigarros:
        base = base * CIGARROS_SAFETY_MULT

    return base


def _display_pct_for(abcxyz, is_top_cash=False, is_cigarros=False):
    if not DISPLAY_STOCK_ENABLED:
        return 0.0
    abc = (abcxyz or '').strip()
    pct = _safe_float(DISPLAY_PCT_BY_ABCXYZ.get(abc, DISPLAY_PCT_DEFAULT), DISPLAY_PCT_DEFAULT)
    if is_top_cash:
        pct = max(pct, DISPLAY_PCT_TOP_CASH)
    if is_cigarros:
        pct = pct * CIGARROS_DISPLAY_MULT
    return _clamp(pct, 0.0, 1.0)


def _calc_display_stock_units(abcxyz, mu_week, is_top_cash=False, is_cigarros=False):
    mu = max(_safe_float(mu_week, 0.0), 0.0)
    if (not DISPLAY_STOCK_ENABLED) or mu < DISPLAY_MIN_DEMAND_WEEK:
        return 0.0
    pct = _display_pct_for(abcxyz, is_top_cash, is_cigarros)
    units = mu * pct
    if DISPLAY_MAX_UNITS > 0.0:
        units = min(units, DISPLAY_MAX_UNITS)
    return max(units, 0.0)


def _calc_target_units(abcxyz, mu, sigma, protection_weeks, moq, financial_ceiling_weeks, is_top_cash=False, is_cigarros=False):
    mu    = max(_safe_float(mu,               0.0), 0.0)
    sigma = max(_safe_float(sigma,            0.0), 0.0)
    H     = max(_safe_float(protection_weeks, 0.5), 0.5)
    fcw   = max(_safe_float(financial_ceiling_weeks, 4.0), 0.5)

    if abcxyz == 'CZ':
        raw_units = min(2.0, H) * max(mu, DEMAND_FLOOR_WEEK)
        safety    = 0.0
    else:
        z         = _safety_factor_for(abcxyz, is_top_cash, is_cigarros)
        safety    = z * sigma * (H ** 0.5)
        raw_units = mu * H + safety

    eff_mu       = mu if mu > DEMAND_FLOOR_WEEK else DEMAND_FLOOR_WEEK
    target_weeks = _clamp(raw_units / eff_mu, 0.0, fcw)
    target_units = target_weeks * eff_mu

    return target_units, safety, target_weeks


def _cover_label(cover_weeks, mu_real, financial_ceiling_weeks):
    if mu_real <= DEMAND_FLOOR_WEEK:
        return 'sin_salida'
    if cover_weeks <= 0.0:
        return 'sin_stock'
    if cover_weeks < 1.5:
        return 'critico'
    if cover_weeks < financial_ceiling_weeks * 0.5:
        return 'bajo'
    if cover_weeks <= financial_ceiling_weeks:
        return 'normal'
    if cover_weeks <= financial_ceiling_weeks * 1.5:
        return 'alto'
    return 'exceso'


def _buy_action_from_cover(stock_effective, cover_label):
    if stock_effective <= 0.0:
        return 'reponer_ahora', 'sin_stock'
    if cover_label in ('critico', 'bajo'):
        return 'reponer_ahora', 'bajo_cobertura'
    if cover_label == 'normal':
        return 'no_comprar_esta_semana', 'cobertura_normal'
    if cover_label == 'alto':
        return 'congelar_compra', 'cobertura_alta'
    if cover_label == 'exceso':
        return 'liquidar', 'sobrestock'
    if cover_label == 'sin_salida':
        return 'congelar_compra', 'sin_salida'
    return 'no_comprar_esta_semana', 'default'


def _severity_from_cover(cover_label):
    if cover_label == 'sin_stock':  return 100
    if cover_label == 'critico':    return 90
    if cover_label == 'bajo':       return 70
    if cover_label == 'normal':     return 40
    if cover_label == 'alto':       return 20
    if cover_label == 'exceso':     return 10
    if cover_label == 'sin_salida': return 5
    return 0


def _rango_sobrestock(w):
    if w <= 0.0:  return 'sin_exceso'
    if w < 4.0:   return 'menos_1_mes'
    if w < 8.0:   return '1_2_meses'
    if w < 13.0:  return '2_3_meses'
    if w < 26.0:  return '3_6_meses'
    if w < 52.0:  return '6_12_meses'
    if w < 104.0: return '1_2_anios'
    return 'mas_2_anios'


def _ceil_moq(qty, moq):
    moq = max(_safe_float(moq, 1.0), 1.0)
    qty = max(_safe_float(qty, 0.0), 0.0)
    if qty <= 0.0:
        return qty
    if moq <= 1.0:
        result = float(int(qty + 0.9999999))
        return result if result > 0.0 else 1.0
    n = int(qty / moq)
    if (n * moq) < qty - 0.0000001:
        n += 1
    if n == 0:
        n = 1
    return float(n * moq)


def _round_moq_nearest(qty, moq, force_min=False):
    # Fallback simple: redondeo al multiplo MOQ/caja mas cercano.
    moq = max(_safe_float(moq, 1.0), 1.0)
    qty = max(_safe_float(qty, 0.0), 0.0)
    if qty <= 0.0:
        return 0.0
    if moq <= 1.0:
        return _ceil_units(qty) if force_min else _round_units(qty)
    n_floor = int(qty / moq)
    q_floor = float(n_floor * moq)
    q_ceil = q_floor
    if q_ceil < qty - 0.0000001:
        q_ceil += moq
    if force_min and q_floor <= 0.0:
        return q_ceil if q_ceil > 0.0 else moq
    diff_floor = qty - q_floor
    diff_ceil = q_ceil - qty
    if q_floor > 0.0 and diff_floor <= diff_ceil + 0.0000001:
        return q_floor
    return q_ceil


def _smart_moq_box_or_wait(qty_need, moq, stock_base, mu_week, target_units, target_weeks, cover_label, force_min=False, abcxyz=None, display_stock_units=0.0):
    # Politica global caja-o-esperar para evitar sobrecompra sistematica por MOQ.
    # Regla:
    #   - Calcula floor y ceil de la necesidad exacta.
    #   - Si floor deja el stock post-compra a menos de 1 caja del target tecnico, se acepta floor.
    #   - Si la necesidad exacta es menor que 1 caja y no hay quiebre/critico, se espera.
    #   - Si hay quiebre/critico, se permite caja minima.
    #   - Ceil se permite si no supera target_weeks * MOQ_MAX_POST_FACTOR.
    moq = max(_safe_float(moq, 1.0), 1.0)
    need = max(_safe_float(qty_need, 0.0), 0.0)
    stock = max(_safe_float(stock_base, 0.0), 0.0)
    mu = max(_safe_float(mu_week, 0.0), 0.0)
    target = max(_safe_float(target_units, 0.0), 0.0)
    H = max(_safe_float(target_weeks, 1.0), 0.5)
    display_units = max(_safe_float(display_stock_units, 0.0), 0.0)

    if need <= 0.0:
        return 0.0

    if moq <= 1.0:
        return _ceil_units(need) if force_min else _round_units(need)

    n_floor = int(need / moq)
    q_floor = float(n_floor * moq)
    q_ceil = q_floor
    if q_ceil < need - 0.0000001:
        q_ceil += moq
    if q_ceil <= 0.0:
        q_ceil = moq

    cover_label_norm = cover_label or ''
    abcxyz_safe = (abcxyz or '').strip()
    critical_moq_allowed = abcxyz_safe in ('AX', 'AY', 'AZ', 'BX', 'BY', 'BZ')

    current_cover = (stock / mu) if mu > DEMAND_FLOOR_WEEK else 999.0
    critical_cover = max(0.25, H * MOQ_CRITICAL_FACTOR)
    cover_is_critical = bool(cover_label_norm in ('sin_stock', 'critico') or current_cover < critical_cover)
    is_critical = bool(force_min or cover_is_critical)

    # Si la brecha es menor que una caja, solo forzar caja minima por criticidad
    # cuando el SKU pertenece a grupos ABCXYZ relevantes.
    # Excepcion: force_min operacional sin cover critico se mantiene para redondeos CD.
    operational_force_min = bool(force_min and cover_label_norm not in ('sin_stock', 'critico'))

    if q_floor <= 0.0:
        if operational_force_min:
            return q_ceil
        if cover_is_critical and critical_moq_allowed:
            return q_ceil
        return 0.0

    # Excepcion critica segmentada por ABCXYZ:
    # En sin_stock/critico, no aceptar floor si deja una cobertura post-compra
    # menor a la cobertura minima critica o si todavia queda bajo el target tecnico.
    # Aplica solo a AX/AY/AZ/BX/BY/BZ; CX/CY/CZ mantienen caja-o-esperar.
    # Ejemplo: need 7.7, MOQ 4, stock 2, mu 8.12, AX => floor 4 deja 0.74 semanas; usar ceil 8.
    post_floor = stock + q_floor
    gap_after_floor = max(target - post_floor, 0.0)
    if cover_is_critical and critical_moq_allowed and mu > DEMAND_FLOOR_WEEK:
        # No basta mirar stock total; para no vaciar la exhibicion,
        # evaluamos cobertura vendible descontando display_stock_units.
        sellable_post_floor = max(post_floor - display_units, 0.0)
        cover_floor = sellable_post_floor / mu
        min_critical_post_cover = max(0.75, min(H, 1.0))
        if post_floor < target - 0.0000001 and cover_floor < min_critical_post_cover - 0.0000001:
            return q_ceil

    # Si comprando floor quedamos a menos de una caja del target, aceptar floor.
    # Esta regla aplica principalmente a SKU no criticos o casos donde floor ya deja cobertura suficiente.
    if gap_after_floor <= moq + 0.0000001:
        return q_floor

    # Si floor todavia queda demasiado corto, probar ceil, pero con limite de cobertura post-compra.
    if mu > DEMAND_FLOOR_WEEK:
        cover_ceil = (stock + q_ceil) / mu
        max_post_cover = max(H, H * MOQ_MAX_POST_FACTOR)
        if cover_ceil <= max_post_cover + 0.0000001:
            return q_ceil
        if operational_force_min or (cover_is_critical and critical_moq_allowed):
            return q_ceil
        return q_floor

    return q_ceil if (operational_force_min or (cover_is_critical and critical_moq_allowed)) else q_floor

def _ceil_units(qty):
    qty = max(_safe_float(qty, 0.0), 0.0)
    if qty <= 0.0:
        return 0.0
    return float(int(qty + 0.9999999))


def _round_units(qty):
    qty = max(_safe_float(qty, 0.0), 0.0)
    if qty <= 0.0:
        return 0.0
    return float(int(qty + 0.5))


def _normalize_banda_actual(banda):
    # Se eliminan bandas verano del analisis operativo.
    # Si FWD entrega VERANO_*, el analisis lo trata como BASE.
    b = (banda or 'BASE').strip()
    if b in ('VERANO_BAJO', 'VERANO_MEDIO', 'VERANO_ALTO'):
        return 'BASE'
    return b or 'BASE'


def _filter_vals(vals, fields_map):
    out = {}
    for k, v in vals.items():
        if fields_map.get(k):
            out[k] = v
    return out


def _to_int_list(val):
    out = []
    if not val:
        return out
    try:
        for x in val:
            try:
                out.append(int(x))
            except Exception:
                pass
        return out
    except Exception:
        try:
            return [int(val)]
        except Exception:
            return []


def _to_str_list(val):
    out = []
    if not val:
        return out
    try:
        if isinstance(val, str):
            src = val.replace(';', ',').split(',')
        else:
            src = val
        for x in src:
            try:
                s = str(x or '').strip().upper()
                if s:
                    out.append(s)
            except Exception:
                pass
        return out
    except Exception:
        try:
            s = str(val or '').strip().upper()
            return [s] if s else []
        except Exception:
            return []


def _priority_tuple(rec):
    cover_label = rec.get('cover_label') or ''
    if cover_label == 'sin_stock':
        sev_rank = 0
    elif cover_label == 'critico':
        sev_rank = 1
    elif cover_label == 'bajo':
        sev_rank = 2
    else:
        sev_rank = 9

    cover_weeks = _safe_float(rec.get('cover_weeks'), 999.0)
    mu_week     = _safe_float(rec.get('mu_week'), 0.0)
    gap_target  = _safe_float(rec.get('qty_neta_pre_central'), 0.0)
    team_id     = _safe_int(rec.get('team_id'), 0)

    return (
        sev_rank,
        cover_weeks,
        -mu_week,
        -gap_target,
        team_id,
    )


# ----------------------
# Context
# ----------------------
CTX = env.context or {}

HARD_RESET          = bool(CTX.get('hard_reset', HARD_RESET_DEFAULT))
PAYMENT_DAYS        = _safe_float(CTX.get('payment_days',        PAYMENT_DAYS_DEFAULT),        PAYMENT_DAYS_DEFAULT)
PURCHASE_CYCLE_DAYS = _safe_float(CTX.get('purchase_cycle_days', PURCHASE_CYCLE_DAYS_DEFAULT), PURCHASE_CYCLE_DAYS_DEFAULT)
MOQ_COVER_GUARD     = _safe_float(CTX.get('moq_cover_guard',     MOQ_COVER_GUARD_DEFAULT),     MOQ_COVER_GUARD_DEFAULT)
SMART_MOQ_ROUNDING = bool(CTX.get('smart_moq_rounding', SMART_MOQ_ROUNDING_DEFAULT))
MOQ_MAX_POST_FACTOR = _safe_float(CTX.get('moq_max_post_factor', MOQ_MAX_POST_FACTOR_DEFAULT), MOQ_MAX_POST_FACTOR_DEFAULT)
MOQ_CRITICAL_FACTOR = _safe_float(CTX.get('moq_critical_factor', MOQ_CRITICAL_FACTOR_DEFAULT), MOQ_CRITICAL_FACTOR_DEFAULT)
CENTRAL_RESERVE_PCT = _safe_float(CTX.get('central_reserve_pct', CENTRAL_RESERVE_PCT_DEFAULT), CENTRAL_RESERVE_PCT_DEFAULT)
RETURN_HOLD_WEEKS   = _safe_float(CTX.get('return_hold_weeks', RETURN_HOLD_WEEKS_DEFAULT), RETURN_HOLD_WEEKS_DEFAULT)
RETURN_TRIGGER_WEEKS = _safe_float(CTX.get('return_trigger_weeks', RETURN_TRIGGER_WEEKS_DEFAULT), RETURN_TRIGGER_WEEKS_DEFAULT)
CD_DELIVERY_EXTRA_DAYS = _safe_float(CTX.get('cd_delivery_extra_days', CD_DELIVERY_EXTRA_DAYS_DEFAULT), CD_DELIVERY_EXTRA_DAYS_DEFAULT)
CENTRAL_TEAM_ID = _safe_int(CTX.get('central_team_id', CENTRAL_TEAM_ID_DEFAULT), CENTRAL_TEAM_ID_DEFAULT)
CD_ELIGIBLE_ABCXYZ = tuple(_to_str_list(CTX.get('cd_eligible_abcxyz')) or list(CD_ELIGIBLE_ABCXYZ_DEFAULT))
# Parametros de la regla cobertura + categoria (routing sala vs CD).
COVER_WEEKS_THRESHOLD_FOR_CD = _safe_float(
    CTX.get('cover_weeks_threshold_for_cd', COVER_WEEKS_THRESHOLD_FOR_CD_DEFAULT),
    COVER_WEEKS_THRESHOLD_FOR_CD_DEFAULT
)
NO_CD_PARENT_CATEGORY_IDS = _to_int_list(CTX.get('no_cd_parent_category_ids')) or list(NO_CD_PARENT_CATEGORY_IDS_DEFAULT)

DISPLAY_STOCK_ENABLED = bool(CTX.get('display_stock_enabled', DISPLAY_STOCK_ENABLED_DEFAULT))
DISPLAY_MIN_DEMAND_WEEK = _safe_float(CTX.get('display_min_demand_week', DISPLAY_MIN_DEMAND_WEEK_DEFAULT), DISPLAY_MIN_DEMAND_WEEK_DEFAULT)
DISPLAY_MAX_UNITS = _safe_float(CTX.get('display_max_units', DISPLAY_MAX_UNITS_DEFAULT), DISPLAY_MAX_UNITS_DEFAULT)
DISPLAY_PCT_TOP_CASH = _safe_float(CTX.get('display_pct_top_cash', DISPLAY_PCT_TOP_CASH_DEFAULT), DISPLAY_PCT_TOP_CASH_DEFAULT)
TOP_CASH_WEEKLY_MIN = _safe_float(CTX.get('top_cash_weekly_min', TOP_CASH_WEEKLY_MIN_DEFAULT), TOP_CASH_WEEKLY_MIN_DEFAULT)
TOP_CASH_RANK_MAX = _safe_int(CTX.get('top_cash_rank_max', TOP_CASH_RANK_MAX_DEFAULT), TOP_CASH_RANK_MAX_DEFAULT)
TOP_CASH_SAFETY_FACTOR = _safe_float(CTX.get('top_cash_safety_factor', TOP_CASH_SAFETY_FACTOR_DEFAULT), TOP_CASH_SAFETY_FACTOR_DEFAULT)

# XYZ local por team: si esta activo, el Z del safety se elige por
# ABC_global + XYZ_local (cuando viene poblado desde el forecast).
# is_top_cash y display reserve siguen con ABCXYZ global (importancia comercial).
# Default False para primer despliegue; activar tras validar Fase 0.
ENABLE_XYZ_LOCAL = bool(CTX.get('enable_xyz_local', False))

# Parametros testeables por contexto para cigarros.
# Ejemplo:
#   env['ir.actions.server'].browse(ID).with_context(
#       cigarros_category_ids=[1628],
#       cigarros_safety_mult=0.778,
#   ).run()
CIGARROS_CATEGORY_IDS = _to_int_list(CTX.get('cigarros_category_ids')) or list(CIGARROS_CATEGORY_IDS_DEFAULT)
CIGARROS_SAFETY_MULT = _safe_float(CTX.get('cigarros_safety_mult', CIGARROS_SAFETY_MULT_DEFAULT), CIGARROS_SAFETY_MULT_DEFAULT)
CIGARROS_SAFETY_MULT = _clamp(CIGARROS_SAFETY_MULT, 0.0, 1.0)
CIGARROS_DISPLAY_MULT = _safe_float(CTX.get('cigarros_display_mult', CIGARROS_DISPLAY_MULT_DEFAULT), CIGARROS_DISPLAY_MULT_DEFAULT)
CIGARROS_DISPLAY_MULT = _clamp(CIGARROS_DISPLAY_MULT, 0.0, 1.0)

VALUE_PHANTOM_KITS = bool(CTX.get('value_phantom_kits', VALUE_PHANTOM_KITS_DEFAULT))
PHANTOM_COST_SOURCE = CTX.get('phantom_cost_source', PHANTOM_COST_SOURCE_DEFAULT) or PHANTOM_COST_SOURCE_DEFAULT
if PHANTOM_COST_SOURCE not in ('component_first', 'product_first'):
    PHANTOM_COST_SOURCE = PHANTOM_COST_SOURCE_DEFAULT

PHANTOM_PROCUREMENT_MODE = CTX.get('phantom_procurement_mode', PHANTOM_PROCUREMENT_MODE_DEFAULT) or PHANTOM_PROCUREMENT_MODE_DEFAULT
if PHANTOM_PROCUREMENT_MODE not in ('block_parent', 'allow_parent', 'buy_parent_block_children'):
    PHANTOM_PROCUREMENT_MODE = PHANTOM_PROCUREMENT_MODE_DEFAULT

TEAM_IDS_CTX = _to_int_list(CTX.get('team_ids'))
FILTERED_TEAM_IDS = TEAM_IDS_CTX if TEAM_IDS_CTX else list(FILTERED_TEAM_IDS_DEFAULT)

CENTRAL_LOCATION_IDS = _to_int_list(CTX.get('central_location_ids')) or list(CENTRAL_LOCATION_IDS_DEFAULT)
CENTRAL_ROOT_LOCATION_IDS = _to_int_list(CTX.get('central_root_location_ids')) or list(CENTRAL_ROOT_LOCATION_IDS_DEFAULT)
CENTRAL_WAREHOUSE_ID = _safe_int(CTX.get('central_warehouse_id', CENTRAL_WAREHOUSE_ID_DEFAULT), CENTRAL_WAREHOUSE_ID_DEFAULT)
USE_DYNAMIC_POS_CONFIG = bool(CTX.get('use_dynamic_pos_config', USE_DYNAMIC_POS_CONFIG_DEFAULT))

PURCHASE_CYCLE_WEEKS    = max(PURCHASE_CYCLE_DAYS / 7.0, 0.5)
FINANCIAL_CEILING_WEEKS = _financial_ceiling_weeks(PAYMENT_DAYS)
CD_DELIVERY_EXTRA_WEEKS = max(CD_DELIVERY_EXTRA_DAYS, 0.0) / 7.0

company     = env.company
currency    = company.currency_id

Anal        = env[ANALYSIS_MODEL].sudo()
Abc         = env[ABC_MODEL].sudo()
Fwd         = env[FWD_MODEL].sudo()
ProductTmpl = env['product.template'].sudo()
Team        = env['crm.team'].sudo()
StockLoc    = env['stock.location'].sudo()
StockWh     = env['stock.warehouse'].sudo()
PosConfig   = env['pos.config'].sudo()

fields_map  = Anal._fields or {}
pt_fields   = ProductTmpl._fields or {}
abc_fields  = Abc._fields or {}
fwd_fields  = Fwd._fields or {}

global_team = Team.search([('name', '=', GLOBAL_TEAM_NAME)], limit=1)
GLOBAL_TEAM_ID = global_team.id if global_team else False

NO_DISP_ACTION = 'no_disponible_de_compra'
NO_DISP_ACTION_ENABLED = False
try:
    _buy_action_field = fields_map.get('x_studio_buy_action')
    _selection = _buy_action_field and _buy_action_field.selection or []
    for _opt in (_selection or []):
        _key = False
        try:
            if isinstance(_opt, (list, tuple)) and _opt:
                _key = _opt[0]
        except Exception:
            _key = False
        if _key == NO_DISP_ACTION:
            NO_DISP_ACTION_ENABLED = True
            break
except Exception:
    NO_DISP_ACTION_ENABLED = False

NO_DISP_ACTION_SAFE = NO_DISP_ACTION if NO_DISP_ACTION_ENABLED else 'no_comprar_esta_semana'

RETURN_TO_CD_ACTION = 'retorno_a_cd'
RETURN_TO_CD_ACTION_ENABLED = False
try:
    _buy_action_field = fields_map.get('x_studio_buy_action')
    _selection = _buy_action_field and _buy_action_field.selection or []
    for _opt in (_selection or []):
        _key = False
        try:
            if isinstance(_opt, (list, tuple)) and _opt:
                _key = _opt[0]
        except Exception:
            _key = False
        if _key == RETURN_TO_CD_ACTION:
            RETURN_TO_CD_ACTION_ENABLED = True
            break
except Exception:
    RETURN_TO_CD_ACTION_ENABLED = False

RETURN_TO_CD_ACTION_SAFE = RETURN_TO_CD_ACTION if RETURN_TO_CD_ACTION_ENABLED else 'congelar_compra'

SUPPLY_RETURN_CD_VALUE = 'retorno_a_cd'
SUPPLY_RETURN_CD_ENABLED = False
SUPPLY_TRANSFER_CD_ENABLED = False
try:
    _supply_field = fields_map.get('x_studio_supply_source')
    _supply_selection = _supply_field and _supply_field.selection or []
    for _opt in (_supply_selection or []):
        _key = False
        try:
            if isinstance(_opt, (list, tuple)) and _opt:
                _key = _opt[0]
        except Exception:
            _key = False
        if _key == SUPPLY_RETURN_CD_VALUE:
            SUPPLY_RETURN_CD_ENABLED = True
        if _key == 'transferir_desde_cd':
            SUPPLY_TRANSFER_CD_ENABLED = True
except Exception:
    SUPPLY_RETURN_CD_ENABLED = False
    SUPPLY_TRANSFER_CD_ENABLED = False

if SUPPLY_RETURN_CD_ENABLED:
    SUPPLY_RETURN_CD_SAFE = SUPPLY_RETURN_CD_VALUE
elif SUPPLY_TRANSFER_CD_ENABLED:
    SUPPLY_RETURN_CD_SAFE = 'transferir_desde_cd'
else:
    SUPPLY_RETURN_CD_SAFE = 'no_action'


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
            'title': 'OH Analisis de Stock LOCAL',
            'message': 'Otro proceso esta ejecutandose. Reintenta.',
            'type': 'warning',
            'sticky': False,
        }
    }
else:
    try:
        # ----------------------
        # Fecha snapshot
        # ----------------------
        env.cr.execute('SELECT (timezone(%s, now())::date)', (TZ_NAME,))
        today_local = env.cr.fetchone()[0]

        snapshot_ctx = CTX.get('snapshot_date')
        if snapshot_ctx:
            try:
                snapshot_date = fields.Date.to_date(snapshot_ctx)
            except Exception:
                snapshot_date = today_local
        else:
            snapshot_date = today_local

        # ----------------------
        # Factor dinámico hasta fin de mes — ponderado por día de semana
        # ----------------------
        # Suma ponderada DOW para semanas restantes del mes (vs conteo uniforme).
        # Pesos calibrados desde x_presupuesto_de_venta (dias NORMAL 2026).
        # Sum = 7.0 → consistente con demanda_semanal del FWD.
        # Excluye snapshot_date (hoy ya ocurrió); suma desde mañana hasta fin de mes.
        # Fallback: 30/7 si falla el cálculo de fecha.
        #
        # Fuente de calibración:
        #   normal = presupuesto.search([tratamiento = 'NORMAL'])
        #   dow_avg = mean(proyeccion) group by dayofweek
        #   DOW_DEMAND_WEIGHTS = dow_avg / dow_avg.mean()  → sum = 7.0
        # Pesos DOW calibrados desde x_presupuesto_de_venta (dias NORMAL 2026).
        # DOW PostgreSQL: 0=domingo, 1=lunes, ..., 6=sabado.
        # Nota: EXTRACT(DOW) en PG usa 0=domingo, distinto de Python (0=lunes).
        # Sum pesos = 7.0 -> consistente con demanda_semanal del FWD.
        # Se usa generate_series en SQL para evitar imports prohibidos en safe_eval.
        # Excluye snapshot_date (hoy ya ocurrio); suma desde manana hasta fin de mes.
        # Fallback: 30/7 si falla la query.
        try:
            env.cr.execute("""
                SELECT COALESCE(SUM(
                    CASE EXTRACT(DOW FROM d)::int
                        WHEN 0 THEN 1.1039
                        WHEN 1 THEN 0.6370
                        WHEN 2 THEN 0.6845
                        WHEN 3 THEN 0.7477
                        WHEN 4 THEN 0.8104
                        WHEN 5 THEN 1.3166
                        WHEN 6 THEN 1.6998
                        ELSE 1.0
                    END
                ), 0.0)
                FROM generate_series(
                    %s::date + interval '1 day',
                    date_trunc('month', %s::date) + interval '1 month - 1 day',
                    interval '1 day'
                ) AS gs(d)
            """, (snapshot_date, snapshot_date))
            _weighted_days = _safe_float(env.cr.fetchone()[0], 0.0)
            MONTH_REMAINING_WEEKS = max(_weighted_days / 7.0, 0.0)
        except Exception:
            MONTH_REMAINING_WEEKS = 30.0 / 7.0

        # ----------------------
        # Purga total
        # ----------------------
        purge_count = 0
        if HARD_RESET:
            old = Anal.search([])
            purge_count = len(old)
            if old:
                i = 0
                while i < len(old):
                    old[i:i + 1000].unlink()
                    i += 1000

        # ----------------------
        # Universo maestro
        # ----------------------
        master_domain = [('sale_ok', '=', True), ('active', '=', True)]
        if pt_fields.get('detailed_type'):
            master_domain.append(('detailed_type', 'not in', ['service', 'combo']))
        elif pt_fields.get('type'):
            master_domain.append(('type', '!=', 'service'))

        tmpl_recs = ProductTmpl.search(master_domain)
        if not tmpl_recs:
            action = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'OH Analisis de Stock LOCAL',
                    'message': 'No hay productos activos/vendibles para procesar.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
        else:
            tmpl_ids   = tmpl_recs.ids
            tmpl_tuple = tuple(tmpl_ids)

            # ----------------------
            # Metadata template
            # ----------------------
            tmpl_meta = {}
            read_fields = ['name', 'categ_id', 'standard_price', 'list_price', 'purchase_ok']
            if pt_fields.get('raw_product_price'):
                read_fields.append('raw_product_price')
            if pt_fields.get('x_studio_comprar_solo_en_bodega'):
                read_fields.append('x_studio_comprar_solo_en_bodega')

            for r in tmpl_recs.read(read_fields):
                tid   = r['id']
                categ = r.get('categ_id')
                tmpl_meta[tid] = {
                    'name':                   r.get('name') or '',
                    'categ_id':               categ and categ[0] or False,
                    'standard_price':         _safe_float(r.get('standard_price'), 0.0),
                    'list_price':             _safe_float(r.get('list_price'), 0.0),
                    'raw_product_price':      _safe_float(r.get('raw_product_price'), 0.0),
                    'solo_bodega':            bool(r.get('x_studio_comprar_solo_en_bodega')),
                    'purchase_ok':            bool(r.get('purchase_ok')),
                }

            # Derivar set de category IDs excluidos del check de CD.
            # Recibe IDs padre en NO_CD_PARENT_CATEGORY_IDS y expande via
            # product.category child_of para incluir todas las subcategorias.
            no_cd_category_set = set()
            if NO_CD_PARENT_CATEGORY_IDS:
                try:
                    _no_cd_cats = env['product.category'].sudo().search([
                        ('id', 'child_of', NO_CD_PARENT_CATEGORY_IDS)
                    ])
                    no_cd_category_set = set(_no_cd_cats.ids)
                except Exception:
                    # Fallback defensivo: usar IDs padre sin expandir hijos.
                    no_cd_category_set = set(int(x) for x in NO_CD_PARENT_CATEGORY_IDS if x)

            # product_product map
            env.cr.execute("""
                SELECT id, product_tmpl_id
                FROM product_product
                WHERE product_tmpl_id IN %s
            """, (tmpl_tuple,))
            pp_to_tmpl = {}
            tmpl_to_pp = {}
            for pp_id, tmpl_id in env.cr.fetchall():
                pp_to_tmpl[_safe_int(pp_id)] = _safe_int(tmpl_id)
                if _safe_int(tmpl_id) not in tmpl_to_pp:
                    tmpl_to_pp[_safe_int(tmpl_id)] = _safe_int(pp_id)

            # ----------------------
            # Team -> root locations
            # ----------------------
            pc_fields = PosConfig._fields or {}

            team_to_root_ids = {}
            team_warehouse_id = {}
            team_root_location_id = {}
            team_source_mode = {}
            team_location_name = {}

            for t_id, wh_id in TEAM_WAREHOUSE_MAP_FALLBACK.items():
                if t_id not in FILTERED_TEAM_IDS:
                    continue
                try:
                    wh_rec = StockWh.browse(wh_id)
                except Exception:
                    wh_rec = False
                if not wh_rec or not wh_rec.exists() or not wh_rec.lot_stock_id:
                    continue

                loc_id = wh_rec.lot_stock_id.id
                team_to_root_ids[t_id] = [loc_id]
                team_root_location_id[t_id] = loc_id
                team_source_mode[t_id] = 'fallback_map'
                team_warehouse_id[t_id] = wh_rec.id

                try:
                    loc_rec = wh_rec.lot_stock_id
                    team_location_name[t_id] = loc_rec.complete_name or loc_rec.name or ('wh:%s' % wh_rec.id)
                except Exception:
                    team_location_name[t_id] = 'wh:%s' % wh_rec.id

            if USE_DYNAMIC_POS_CONFIG:
                team_field_pc = False
                for fname in ['crm_team_id', 'x_studio_team_id', 'team_id']:
                    f = pc_fields.get(fname)
                    if not f:
                        continue
                    try:
                        is_m2o = (f.type == 'many2one')
                        is_team = (f.comodel_name == 'crm.team')
                        if is_m2o and is_team:
                            team_field_pc = fname
                            break
                    except Exception:
                        pass

                if team_field_pc and pc_fields.get('picking_type_id'):
                    pc_read = ['picking_type_id', team_field_pc]
                    for cfg in PosConfig.search([]).read(pc_read):
                        t = cfg.get(team_field_pc)
                        team_id = t and t[0] or False
                        if not team_id or team_id not in FILTERED_TEAM_IDS:
                            continue
                        if team_to_root_ids.get(team_id):
                            continue

                        pt = cfg.get('picking_type_id')
                        pt_id = pt and pt[0] or False
                        if not pt_id:
                            continue
                        try:
                            pt_rec = env['stock.picking.type'].sudo().browse(pt_id)
                            loc = pt_rec.default_location_src_id
                            if loc and loc.id and loc.usage == 'internal':
                                arr = team_to_root_ids.get(team_id) or []
                                if loc.id not in arr:
                                    arr.append(loc.id)
                                team_to_root_ids[team_id] = arr
                                team_root_location_id[team_id] = loc.id
                                team_location_name[team_id] = loc.complete_name or loc.name or ''
                                team_source_mode[team_id] = 'dynamic_pos_config'

                                wh_id = False
                                try:
                                    if getattr(pt_rec, 'warehouse_id', False):
                                        wh_id = pt_rec.warehouse_id.id or False
                                except Exception:
                                    wh_id = False
                                if not wh_id:
                                    try:
                                        wh_rec = StockWh.search([('lot_stock_id', '=', loc.id), ('company_id', '=', company.id)], limit=1)
                                        wh_id = wh_rec.id if wh_rec else False
                                    except Exception:
                                        wh_id = False
                                team_warehouse_id[team_id] = wh_id or False
                        except Exception:
                            pass

            valid_team_ids = [t for t in FILTERED_TEAM_IDS if team_to_root_ids.get(t)]

            if not valid_team_ids:
                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'OH Analisis de Stock LOCAL',
                        'message': 'No se pudieron derivar ubicaciones desde mapa fijo ni POS dinámico.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }
            else:
                def _expand_internal_locations(root_ids, direct_ids):
                    if direct_ids:
                        loc_ids = []
                        try:
                            loc_ids = StockLoc.search([('id', 'in', direct_ids), ('usage', '=', 'internal')]).ids
                        except Exception:
                            loc_ids = list(direct_ids)
                        return loc_ids
                    if root_ids:
                        loc_ids = []
                        try:
                            loc_ids = StockLoc.search([('id', 'child_of', root_ids), ('usage', '=', 'internal')]).ids
                        except Exception:
                            loc_ids = list(root_ids)
                        return loc_ids
                    return []

                def _build_stock_maps(loc_ids):
                    stock_direct_map = {}
                    variant_stock_map = {}
                    stock_real_map = {}
                    if not loc_ids:
                        return stock_direct_map, variant_stock_map, stock_real_map

                    env.cr.execute("""
                        SELECT sq.product_id,
                               SUM(COALESCE(sq.quantity,0.0) - COALESCE(sq.reserved_quantity,0.0)) AS qty
                        FROM stock_quant sq
                        JOIN stock_location sl ON sl.id = sq.location_id
                        WHERE sl.usage = 'internal'
                          AND sq.company_id = %s
                          AND sq.location_id IN %s
                        GROUP BY sq.product_id
                        HAVING ABS(SUM(COALESCE(sq.quantity,0.0) - COALESCE(sq.reserved_quantity,0.0))) > 0.00001
                    """, (company.id, tuple(loc_ids)))

                    for pid_r, qty_r in env.cr.fetchall():
                        pid_i = _safe_int(pid_r)
                        qty_i = _safe_float(qty_r, 0.0)
                        if not pid_i:
                            continue
                        variant_stock_map[pid_i] = qty_i
                        tmpl_id = pp_to_tmpl.get(pid_i)
                        if tmpl_id:
                            stock_direct_map[tmpl_id] = stock_direct_map.get(tmpl_id, 0.0) + qty_i

                    return stock_direct_map, variant_stock_map, stock_real_map

                # ----------------------
                # Kit phantom global definition
                # ----------------------
                kit_components_tmpl = {}
                env.cr.execute("""
                    SELECT
                        bom.product_tmpl_id, bom.product_id,
                        line.product_id AS comp_pp_id,
                        line.product_qty AS comp_qty
                    FROM mrp_bom bom
                    JOIN mrp_bom_line line ON line.bom_id = bom.id
                    WHERE bom.type = 'phantom'
                      AND line.product_qty > 0
                      AND (
                          bom.product_tmpl_id IN %s
                          OR bom.product_id IN (
                              SELECT id FROM product_product
                              WHERE product_tmpl_id IN %s
                          )
                      )
                    ORDER BY bom.id, line.sequence, line.id
                """, (tmpl_tuple, tmpl_tuple))

                for kit_tmpl_id, kit_variant_id, comp_pp_id, comp_qty in env.cr.fetchall():
                    if kit_tmpl_id:
                        t_kit = _safe_int(kit_tmpl_id)
                    elif kit_variant_id:
                        env.cr.execute(
                            "SELECT product_tmpl_id FROM product_product WHERE id = %s",
                            (_safe_int(kit_variant_id),)
                        )
                        row = env.cr.fetchone()
                        t_kit = _safe_int(row[0]) if row else 0
                    else:
                        continue
                    if not t_kit or t_kit not in tmpl_ids:
                        continue
                    comp_pid = _safe_int(comp_pp_id)
                    comp_q   = _safe_float(comp_qty, 0.0)
                    if comp_pid <= 0 or comp_q <= 0.0:
                        continue
                    arr = kit_components_tmpl.get(t_kit) or []
                    arr.append((comp_pid, comp_q))
                    kit_components_tmpl[t_kit] = arr

                # ----------------------
                # Mapa inverso pool hijo -> padre comprable
                # ----------------------
                # En OH, el producto padre phantom representa la unidad de compra/abastecimiento
                # y los hijos/componentes pueden ser unidades de venta.
                #
                # Ejemplo:
                #   Padre: [450336] Pack 6x355
                #   Hijo : [7802100505538] Unidad 355
                #
                # Regla:
                #   - La venta del hijo aporta demanda al padre en equivalente de compra.
                #   - El hijo queda visible, pero bloqueado para compra/transferencia documental.
                #   - El padre concentra compra, proveedor, MOQ y presupuesto mensual.
                component_parent_tmpl = {}
                for _parent_tid, _comps in kit_components_tmpl.items():
                    _parent_meta = tmpl_meta.get(_parent_tid) or {}

                    # Solo redirigimos abastecimiento hacia padres realmente comprables.
                    # Si el padre no es comprable, se mantiene comportamiento normal del hijo.
                    if not bool(_parent_meta.get('purchase_ok')):
                        continue

                    for _comp_pid, _comp_qty in (_comps or []):
                        _child_tid = pp_to_tmpl.get(_safe_int(_comp_pid))
                        if not _child_tid or _child_tid == _parent_tid:
                            continue

                        # Si un hijo participa en más de un padre comprable, tomamos el primero.
                        # En una siguiente capa se puede resolver por proveedor/categoría/código principal.
                        if _child_tid not in component_parent_tmpl:
                            component_parent_tmpl[_child_tid] = {
                                'parent_tmpl_id': _parent_tid,
                                'qty_per_parent': max(_safe_float(_comp_qty, 1.0), 1.0),
                            }

                def _apply_kit_stock(direct_map, variant_map):
                    stock_real_map = {}
                    for tmpl_id in tmpl_ids:
                        comps = kit_components_tmpl.get(tmpl_id)
                        if not comps:
                            qty = direct_map.get(tmpl_id, 0.0)
                            if abs(qty) > 0.00001:
                                stock_real_map[tmpl_id] = qty
                        else:
                            min_kits = None
                            for comp_pid, comp_qty in comps:
                                comp_stock = _safe_float(variant_map.get(comp_pid, 0.0), 0.0)
                                kits_from_comp = comp_stock / comp_qty if comp_qty > 0.0 else 0.0
                                if min_kits is None or kits_from_comp < min_kits:
                                    min_kits = kits_from_comp
                            kits_available = max(min_kits or 0.0, 0.0)
                            if kits_available > 0.00001:
                                stock_real_map[tmpl_id] = kits_available
                    return stock_real_map

                # ----------------------
                # Stock directo por sucursal
                # ----------------------
                stock_direct_by_team = {}
                variant_stock_by_team = {}
                stock_real_by_team = {}
                team_loc_ids_by_team = {}

                for team_id in valid_team_ids:
                    root_ids = team_to_root_ids.get(team_id) or []
                    loc_ids = _expand_internal_locations(root_ids, [])
                    if not loc_ids:
                        continue
                    team_loc_ids_by_team[team_id] = list(loc_ids)
                    direct_map, variant_map, _dummy = _build_stock_maps(loc_ids)
                    stock_direct_by_team[team_id] = direct_map
                    variant_stock_by_team[team_id] = variant_map
                    stock_real_by_team[team_id] = _apply_kit_stock(direct_map, variant_map)

                def _build_open_incoming_maps(loc_ids):
                    purchase_open_map = {}
                    transfer_open_map = {}
                    # Nombres de OC y pickings que originan el stock_pedido,
                    # para trazabilidad en x_studio_oc_pendientes.
                    purchase_names_map = {}
                    transfer_names_map = {}
                    if not loc_ids:
                        return purchase_open_map, transfer_open_map, purchase_names_map, transfer_names_map

                    loc_tuple = tuple(loc_ids)

                    # IMPORTANTE v9.1.52:
                    # sm.product_uom_qty esta expresado en la UoM del movimiento.
                    # Si la OC fue creada en cajas, sumar directo product_uom_qty subcuenta el stock entrante.
                    # Convertimos a la UoM base del producto:
                    # qty_base = qty_move / uom_move.factor * uom_product.factor
                    env.cr.execute("""
                        SELECT sm.product_id,
                               SUM(
                                   CASE
                                       WHEN um.category_id = up.category_id
                                            AND COALESCE(um.factor, 0.0) <> 0.0
                                       THEN COALESCE(sm.product_uom_qty, 0.0) / um.factor * up.factor
                                       ELSE COALESCE(sm.product_uom_qty, 0.0)
                                   END
                               ) AS qty
                        FROM stock_move sm
                        JOIN stock_location src ON src.id = sm.location_id
                        JOIN stock_location dst ON dst.id = sm.location_dest_id
                        JOIN product_product pp ON pp.id = sm.product_id
                        JOIN product_template pt ON pt.id = pp.product_tmpl_id
                        JOIN uom_uom um ON um.id = sm.product_uom
                        JOIN uom_uom up ON up.id = pt.uom_id
                        WHERE sm.company_id = %s
                          AND sm.state NOT IN ('done', 'cancel')
                          AND sm.purchase_line_id IS NOT NULL
                          AND dst.usage = 'internal'
                          AND sm.location_dest_id IN %s
                        GROUP BY sm.product_id
                        HAVING ABS(
                            SUM(
                                CASE
                                    WHEN um.category_id = up.category_id
                                         AND COALESCE(um.factor, 0.0) <> 0.0
                                    THEN COALESCE(sm.product_uom_qty, 0.0) / um.factor * up.factor
                                    ELSE COALESCE(sm.product_uom_qty, 0.0)
                                END
                            )
                        ) > 0.00001
                    """, (company.id, loc_tuple))
                    for pid_r, qty_r in env.cr.fetchall():
                        pid_i = _safe_int(pid_r)
                        qty_i = _safe_float(qty_r, 0.0)
                        tmpl_id = pp_to_tmpl.get(pid_i)
                        if tmpl_id and qty_i > 0.0:
                            purchase_open_map[tmpl_id] = purchase_open_map.get(tmpl_id, 0.0) + qty_i

                    env.cr.execute("""
                        SELECT sm.product_id,
                               SUM(
                                   CASE
                                       WHEN um.category_id = up.category_id
                                            AND COALESCE(um.factor, 0.0) <> 0.0
                                       THEN COALESCE(sm.product_uom_qty, 0.0) / um.factor * up.factor
                                       ELSE COALESCE(sm.product_uom_qty, 0.0)
                                   END
                               ) AS qty
                        FROM stock_move sm
                        JOIN stock_location src ON src.id = sm.location_id
                        JOIN stock_location dst ON dst.id = sm.location_dest_id
                        JOIN product_product pp ON pp.id = sm.product_id
                        JOIN product_template pt ON pt.id = pp.product_tmpl_id
                        JOIN uom_uom um ON um.id = sm.product_uom
                        JOIN uom_uom up ON up.id = pt.uom_id
                        WHERE sm.company_id = %s
                          -- Solo guias aceptadas: excluye borrador y cancelada.
                          -- 'draft' es intencion, no compromiso: contarlo infla el transito.
                          AND sm.state NOT IN ('done', 'cancel', 'draft')
                          AND sm.purchase_line_id IS NULL
                          AND src.usage = 'internal'
                          AND dst.usage = 'internal'
                          AND sm.location_dest_id IN %s
                          AND sm.location_id NOT IN %s
                        GROUP BY sm.product_id
                        HAVING ABS(
                            SUM(
                                CASE
                                    WHEN um.category_id = up.category_id
                                         AND COALESCE(um.factor, 0.0) <> 0.0
                                    THEN COALESCE(sm.product_uom_qty, 0.0) / um.factor * up.factor
                                    ELSE COALESCE(sm.product_uom_qty, 0.0)
                                END
                            )
                        ) > 0.00001
                    """, (company.id, loc_tuple, loc_tuple))
                    for pid_r, qty_r in env.cr.fetchall():
                        pid_i = _safe_int(pid_r)
                        qty_i = _safe_float(qty_r, 0.0)
                        tmpl_id = pp_to_tmpl.get(pid_i)
                        if tmpl_id and qty_i > 0.0:
                            transfer_open_map[tmpl_id] = transfer_open_map.get(tmpl_id, 0.0) + qty_i

                    # Nombres de OC pendientes que disparan stock_pedido_compra.
                    # Se listan sin qty para la trazabilidad simple del usuario.
                    env.cr.execute("""
                        SELECT DISTINCT pp.product_tmpl_id, po.name
                          FROM stock_move sm
                          JOIN stock_location dst ON dst.id = sm.location_dest_id
                          JOIN product_product pp ON pp.id = sm.product_id
                          JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
                          JOIN purchase_order po ON po.id = pol.order_id
                         WHERE sm.company_id = %s
                           AND sm.state NOT IN ('done', 'cancel')
                           AND sm.purchase_line_id IS NOT NULL
                           AND dst.usage = 'internal'
                           AND sm.location_dest_id IN %s
                    """, (company.id, loc_tuple))
                    for tid_r, name_r in env.cr.fetchall():
                        tmpl_id = _safe_int(tid_r)
                        if tmpl_id and name_r:
                            purchase_names_map.setdefault(tmpl_id, set()).add(name_r)

                    # Nombres de pickings internos pendientes (transfers sin OC).
                    env.cr.execute("""
                        SELECT DISTINCT pp.product_tmpl_id, sp.name
                          FROM stock_move sm
                          JOIN stock_location src ON src.id = sm.location_id
                          JOIN stock_location dst ON dst.id = sm.location_dest_id
                          JOIN product_product pp ON pp.id = sm.product_id
                          JOIN stock_picking sp ON sp.id = sm.picking_id
                         WHERE sm.company_id = %s
                           -- Solo guias aceptadas: excluye borrador y cancelada.
                           AND sm.state NOT IN ('done', 'cancel', 'draft')
                           AND sm.purchase_line_id IS NULL
                           AND src.usage = 'internal'
                           AND dst.usage = 'internal'
                           AND sm.location_dest_id IN %s
                           AND sm.location_id NOT IN %s
                    """, (company.id, loc_tuple, loc_tuple))
                    for tid_r, name_r in env.cr.fetchall():
                        tmpl_id = _safe_int(tid_r)
                        if tmpl_id and name_r:
                            transfer_names_map.setdefault(tmpl_id, set()).add(name_r)

                    return purchase_open_map, transfer_open_map, purchase_names_map, transfer_names_map

                stock_pedido_compra_by_team = {}
                stock_pedido_transfer_by_team = {}
                stock_pedido_total_by_team = {}
                # Maps de nombres OC/picking por team (trazabilidad).
                purchase_names_by_team = {}
                transfer_names_by_team = {}

                for team_id in valid_team_ids:
                    loc_ids = team_loc_ids_by_team.get(team_id) or []
                    po_map, tr_map, po_names_map, tr_names_map = _build_open_incoming_maps(loc_ids)
                    stock_pedido_compra_by_team[team_id] = po_map
                    stock_pedido_transfer_by_team[team_id] = tr_map
                    purchase_names_by_team[team_id] = po_names_map
                    transfer_names_by_team[team_id] = tr_names_map

                    total_map = {}
                    for _tid, _qty in po_map.items():
                        total_map[_tid] = total_map.get(_tid, 0.0) + _safe_float(_qty, 0.0)
                    for _tid, _qty in tr_map.items():
                        total_map[_tid] = total_map.get(_tid, 0.0) + _safe_float(_qty, 0.0)
                    stock_pedido_total_by_team[team_id] = total_map

                # ----------------------
                # Bodega central
                # ----------------------
                central_root_ids = []
                central_loc_ids  = list(CENTRAL_LOCATION_IDS)
                central_wh_id = False

                try:
                    central_wh = StockWh.browse(CENTRAL_WAREHOUSE_ID)
                    if central_wh and central_wh.exists():
                        central_wh_id = central_wh.id
                        if central_wh.lot_stock_id:
                            central_root_ids = [central_wh.lot_stock_id.id]
                except Exception:
                    central_wh_id = False
                    central_root_ids = []

                if not central_root_ids:
                    central_root_ids = list(CENTRAL_ROOT_LOCATION_IDS)

                central_expanded_loc_ids = _expand_internal_locations(central_root_ids, central_loc_ids)
                central_direct_map = {}
                central_variant_map = {}
                central_stock_real_map = {}
                if central_expanded_loc_ids:
                    central_direct_map, central_variant_map, _dummy = _build_stock_maps(central_expanded_loc_ids)
                    central_stock_real_map = _apply_kit_stock(central_direct_map, central_variant_map)

                # Entradas abiertas hacia Bodega Central.
                # Se usan para mostrar stock_pedido/proyectado del CD.
                # No se usan para asignar transferencias inmediatas: la reserva CD sigue usando stock fisico.
                central_stock_pedido_compra_map = {}
                central_stock_pedido_transfer_map = {}
                central_stock_pedido_total_map = {}
                # Nombres OC/picking pendientes hacia CD (trazabilidad).
                central_purchase_names_map = {}
                central_transfer_names_map = {}
                if central_expanded_loc_ids:
                    _cd_po_map, _cd_tr_map, _cd_po_names, _cd_tr_names = _build_open_incoming_maps(central_expanded_loc_ids)
                    central_stock_pedido_compra_map = _cd_po_map or {}
                    central_stock_pedido_transfer_map = _cd_tr_map or {}
                    central_purchase_names_map = _cd_po_names or {}
                    central_transfer_names_map = _cd_tr_names or {}
                    for _tid, _qty in central_stock_pedido_compra_map.items():
                        central_stock_pedido_total_map[_tid] = central_stock_pedido_total_map.get(_tid, 0.0) + _safe_float(_qty, 0.0)
                    for _tid, _qty in central_stock_pedido_transfer_map.items():
                        central_stock_pedido_total_map[_tid] = central_stock_pedido_total_map.get(_tid, 0.0) + _safe_float(_qty, 0.0)

                # ----------------------
                # Mapas auxiliares de compra (lead, moq, supplier, uom_po)
                # Se leen directos de Odoo en lugar de pasar por el modelo FWD.
                # S5 (HM-SI) solo escribe mu/sigma/xyz; el resto lo resolvemos aqui.
                # ----------------------
                _tmpl_ids_universe = tuple(set(pp_to_tmpl.values())) or (0,)

                env.cr.execute("""
                    SELECT DISTINCT ON (si.product_tmpl_id)
                           si.product_tmpl_id,
                           COALESCE(si.delay, 7.0) / 7.0   AS lead_weeks,
                           GREATEST(COALESCE(si.min_qty, 1.0), 1.0) AS moq,
                           si.partner_id
                      FROM product_supplierinfo si
                     WHERE si.product_tmpl_id IN %s
                     ORDER BY si.product_tmpl_id, si.sequence, si.min_qty, si.id
                """, (_tmpl_ids_universe,))
                supplier_lead_map    = {}
                supplier_moq_map     = {}
                supplier_partner_map = {}
                for _tid, _lw, _mq, _pid in env.cr.fetchall():
                    supplier_lead_map[_safe_int(_tid)]    = max(_safe_float(_lw, 1.0), 0.5)
                    supplier_moq_map[_safe_int(_tid)]     = _safe_float(_mq, 1.0)
                    supplier_partner_map[_safe_int(_tid)] = _safe_int(_pid, 0) or False

                env.cr.execute("""
                    SELECT pt.id, COALESCE(uom.factor, 1.0), COALESCE(uom.uom_type, '')
                      FROM product_template pt
                      LEFT JOIN uom_uom uom ON uom.id = pt.uom_po_id
                     WHERE pt.id IN %s
                """, (_tmpl_ids_universe,))
                uom_po_factor_map = {}
                for _tid, _factor, _utype in env.cr.fetchall():
                    _factor = _safe_float(_factor, 1.0)
                    if _utype == 'bigger' and _factor > 0:
                        uom_po_factor_map[_safe_int(_tid)] = round(_factor) if _factor >= 1.0 else round(1.0 / _factor)
                    else:
                        uom_po_factor_map[_safe_int(_tid)] = 1.0

                # ----------------------
                # Leer FWD local + global
                # ----------------------
                local_fwd_map  = {}
                global_fwd_map = {}

                fwd_read_fields = [
                    'x_studio_product_id',
                    FWD_TEAM_FIELD,
                    'x_studio_mu_week',
                    'x_studio_mu_week_adjusted',   # capa demand sensing (COALESCE, ver OH Demand Sensing)
                    'x_studio_sigma_week',
                    'x_studio_xyz_local',
                ]
                fwd_read_fields = [f for f in fwd_read_fields if fwd_fields.get(f)]

                fwd_domain = [(FWD_TEAM_FIELD, 'in', valid_team_ids)]
                if GLOBAL_TEAM_ID:
                    fwd_domain = ['|', (FWD_TEAM_FIELD, '=', GLOBAL_TEAM_ID), (FWD_TEAM_FIELD, 'in', valid_team_ids)]

                for r in Fwd.search(fwd_domain, order='id desc').read(fwd_read_fields):
                    prod = r.get('x_studio_product_id')
                    if not prod:
                        continue
                    pp_id = prod[0]
                    tmpl_id = pp_to_tmpl.get(pp_id)
                    if not tmpl_id:
                        env.cr.execute("SELECT product_tmpl_id FROM product_product WHERE id = %s", (pp_id,))
                        row = env.cr.fetchone()
                        if row:
                            tmpl_id = _safe_int(row[0])
                            pp_to_tmpl[pp_id] = tmpl_id
                    if not tmpl_id:
                        continue

                    loc = r.get(FWD_TEAM_FIELD)
                    team_id = loc and loc[0] or False

                    payload = {
                        # COALESCE: si la capa demand sensing escribio un ajuste, usarlo; si no, base
                        'mu_week':       _safe_float(r.get('x_studio_mu_week_adjusted') or r.get('x_studio_mu_week'), 0.0),
                        'sigma_week':    _safe_float(r.get('x_studio_sigma_week'), 0.0),
                        'lead_weeks':    supplier_lead_map.get(tmpl_id, PURCHASE_CYCLE_WEEKS),
                        'moq':           max(uom_po_factor_map.get(tmpl_id, 1.0),
                                             supplier_moq_map.get(tmpl_id, 1.0)),
                        'share_of_pool': 1.0,
                        'banda_actual':  'BASE',
                        'supplier_id':   supplier_partner_map.get(tmpl_id, False),
                        'xyz_local':     (r.get('x_studio_xyz_local') or '').strip().upper(),
                    }

                    if GLOBAL_TEAM_ID and team_id == GLOBAL_TEAM_ID:
                        if tmpl_id not in global_fwd_map:
                            global_fwd_map[tmpl_id] = payload
                    elif team_id and team_id in valid_team_ids:
                        key = (team_id, tmpl_id)
                        if key not in local_fwd_map:
                            local_fwd_map[key] = payload

                # ----------------------
                # Consolidar demanda pool hacia SKU padre comprable
                # ----------------------
                # Importante:
                #   - NO eliminamos el FWD del hijo. El hijo sigue visible para análisis.
                #   - Sí agregamos su demanda convertida al padre para abastecimiento.
                #   - Para compra, el padre debe usar share_of_pool=1.0, porque compra contra
                #     el pool completo, no contra su participación aislada.
                def _clone_fwd_payload(_p):
                    _p = _p or {}
                    return {
                        'mu_week':       _safe_float(_p.get('mu_week'), 0.0),
                        'sigma_week':    _safe_float(_p.get('sigma_week'), 0.0),
                        'lead_weeks':    _safe_float(_p.get('lead_weeks'), PURCHASE_CYCLE_WEEKS),
                        'moq':           _safe_float(_p.get('moq'), 1.0),
                        'share_of_pool': _safe_float(_p.get('share_of_pool'), 1.0),
                        'banda_actual':  _normalize_banda_actual(_p.get('banda_actual')),
                        'supplier_id':   _p.get('supplier_id') or False,
                        'xyz_local':     (_p.get('xyz_local') or ''),
                    }

                def _merge_pool_child_into_parent(_map, _parent_key, _child_payload, _qty_per_parent, _seed_payload=None):
                    _qty = max(_safe_float(_qty_per_parent, 1.0), 1.0)
                    _child_mu = _safe_float((_child_payload or {}).get('mu_week'), 0.0)
                    _child_sigma = _safe_float((_child_payload or {}).get('sigma_week'), 0.0)

                    _mu_parent_equiv = _child_mu / _qty
                    _sigma_parent_equiv = _child_sigma / _qty

                    _current = _map.get(_parent_key)
                    if not _current:
                        # Si no existe FWD propio del padre, creamos uno solo con demanda convertida del hijo.
                        # No inyectamos demanda global del padre para evitar duplicar o asignar demanda de red completa.
                        _current = _clone_fwd_payload(_seed_payload or _child_payload)
                        _current['mu_week'] = 0.0
                        _current['sigma_week'] = 0.0

                    _old_mu = _safe_float(_current.get('mu_week'), 0.0)
                    _old_sigma = _safe_float(_current.get('sigma_week'), 0.0)

                    _current['mu_week'] = _old_mu + _mu_parent_equiv
                    _current['sigma_week'] = ((_old_sigma ** 2.0) + (_sigma_parent_equiv ** 2.0)) ** 0.5

                    # Clave: el SKU padre compra para el pool completo.
                    # Si dejamos share_of_pool < 1, el padre compraría mirando solo una fracción del stock.
                    _current['share_of_pool'] = 1.0
                    _current['pool_parent_demand'] = True
                    _current['pool_child_qty_per_parent'] = _qty

                    _map[_parent_key] = _current

                # 4.1) Local: hijo local -> padre local
                for (_team_id_pool, _child_tid_pool), _child_fwd_pool in list(local_fwd_map.items()):
                    _parent_info_pool = component_parent_tmpl.get(_child_tid_pool)
                    if not _parent_info_pool:
                        continue

                    _parent_tid_pool = _safe_int(_parent_info_pool.get('parent_tmpl_id'), 0)
                    _qty_per_parent_pool = _safe_float(_parent_info_pool.get('qty_per_parent'), 1.0)
                    if not _parent_tid_pool:
                        continue

                    _parent_key_pool = (_team_id_pool, _parent_tid_pool)
                    _seed_parent_pool = local_fwd_map.get(_parent_key_pool) or global_fwd_map.get(_parent_tid_pool) or {}

                    _merge_pool_child_into_parent(
                        local_fwd_map,
                        _parent_key_pool,
                        _child_fwd_pool,
                        _qty_per_parent_pool,
                        _seed_parent_pool,
                    )

                # 4.2) Global: hijo global -> padre global
                if GLOBAL_TEAM_ID:
                    for _child_tid_pool, _child_fwd_pool in list(global_fwd_map.items()):
                        _parent_info_pool = component_parent_tmpl.get(_child_tid_pool)
                        if not _parent_info_pool:
                            continue

                        _parent_tid_pool = _safe_int(_parent_info_pool.get('parent_tmpl_id'), 0)
                        _qty_per_parent_pool = _safe_float(_parent_info_pool.get('qty_per_parent'), 1.0)
                        if not _parent_tid_pool:
                            continue

                        _seed_parent_pool = global_fwd_map.get(_parent_tid_pool) or {}

                        _merge_pool_child_into_parent(
                            global_fwd_map,
                            _parent_tid_pool,
                            _child_fwd_pool,
                            _qty_per_parent_pool,
                            _seed_parent_pool,
                        )

                # 4.3) Todo padre phantom comprable compra contra el pool completo.
                for _key_pool, _payload_pool in list(local_fwd_map.items()):
                    try:
                        _tid_pool = _key_pool[1]
                    except Exception:
                        _tid_pool = False
                    if _tid_pool and kit_components_tmpl.get(_tid_pool):
                        _payload_pool['share_of_pool'] = 1.0

                for _tid_pool, _payload_pool in list(global_fwd_map.items()):
                    if _tid_pool and kit_components_tmpl.get(_tid_pool):
                        _payload_pool['share_of_pool'] = 1.0

                # ----------------------
                # Leer ABC/XYZ global
                # ----------------------
                # x_studio_product_id es many2one a product.product
                # (variant), no a product.template. Convertir variant_id -> tmpl_id
                # antes de indexar abc_map, identico al bloque FWD de mas arriba.
                abc_map = {}
                abc_domain = [('x_studio_company_id', '=', company.id)]
                if 'x_studio_team_id' in abc_fields:
                    abc_domain.append(('x_studio_team_id', '=', False))

                abc_read_fields = [
                    'x_studio_product_id',
                    'x_studio_abcxyz',
                    'x_studio_rank_abcxyz',
                    'x_studio_importancia',
                    'x_studio_motivo_eliminar',
                ]

                for r in Abc.search(abc_domain, order='id desc').read(abc_read_fields):
                    prod = r.get('x_studio_product_id')
                    if not prod:
                        continue
                    pp_id = prod[0]
                    tmpl_id = pp_to_tmpl.get(pp_id)
                    if not tmpl_id:
                        env.cr.execute("SELECT product_tmpl_id FROM product_product WHERE id = %s", (pp_id,))
                        row = env.cr.fetchone()
                        if row:
                            tmpl_id = _safe_int(row[0])
                            pp_to_tmpl[pp_id] = tmpl_id
                    if not tmpl_id or tmpl_id in abc_map:
                        continue
                    abc_map[tmpl_id] = {
                        'abcxyz':          r.get('x_studio_abcxyz') or '',
                        'rank_abcxyz':     _safe_int(r.get('x_studio_rank_abcxyz'), 0),
                        'importancia_abc': r.get('x_studio_importancia') or False,
                        'motivo_eliminar': r.get('x_studio_motivo_eliminar') or '',
                    }

                # ----------------------
                # Último costo compra con flete
                # ----------------------
                purchase_map = {}
                try:
                    env.cr.execute("""
                        SELECT DISTINCT ON (pp.product_tmpl_id)
                            pp.product_tmpl_id,
                            vb.x_studio_partner_id,
                            vb.x_studio_unit_gross_with_freight,
                            vb.x_studio_doc_date
                        FROM x_vendor_bill_cost_lin vb
                        JOIN product_product pp ON pp.id = vb.x_studio_product_id
                        WHERE vb.x_studio_company_id = %s
                          AND vb.x_studio_product_id IS NOT NULL
                          AND pp.product_tmpl_id IN %s
                          AND (vb.x_studio_doc_date IS NULL OR vb.x_studio_doc_date <= %s)
                        ORDER BY pp.product_tmpl_id,
                                 vb.x_studio_doc_date DESC NULLS LAST,
                                 vb.id DESC
                    """, (company.id, tmpl_tuple, snapshot_date))
                    for tid, partner_id, unit_price, doc_date in env.cr.fetchall():
                        purchase_map[_safe_int(tid)] = {
                            'partner_id': _safe_int(partner_id, 0) or False,
                            'purchase_price_cash_unit': _safe_float(unit_price, 0.0),
                        }
                except Exception:
                    purchase_map = {}

                # ----------------------
                # Mapa supplier_id -> payment_days (techo financiero por proveedor)
                # ----------------------
                # Lee res.partner.property_supplier_payment_term_id por proveedor
                # y deriva dias efectivos via _payment_days_from_term().
                # Partner property es company-dependent (ir.property), por eso
                # se usa ORM en lugar de SQL crudo.
                # Fallback global PAYMENT_DAYS si el partner no tiene term.
                supplier_payment_days_map = {}
                _supplier_ids_seen = set()
                for _row in purchase_map.values():
                    _pid = _row.get('partner_id')
                    if _pid:
                        _supplier_ids_seen.add(_safe_int(_pid, 0))
                for _payload in local_fwd_map.values():
                    _pid = _payload.get('supplier_id')
                    if _pid:
                        _supplier_ids_seen.add(_safe_int(_pid, 0))
                for _payload in global_fwd_map.values():
                    _pid = _payload.get('supplier_id')
                    if _pid:
                        _supplier_ids_seen.add(_safe_int(_pid, 0))
                _supplier_ids_seen.discard(0)
                if _supplier_ids_seen:
                    try:
                        Partner = env['res.partner'].sudo()
                        for _p in Partner.browse(list(_supplier_ids_seen)):
                            _term = _p.property_supplier_payment_term_id
                            supplier_payment_days_map[_p.id] = _payment_days_from_term(_term, PAYMENT_DAYS)
                    except Exception:
                        supplier_payment_days_map = {}

                def _purchase_price_for_tmpl(_tid, _supplier_fallback=False):
                    _meta = tmpl_meta.get(_tid) or {}
                    _prow = purchase_map.get(_tid) or {}
                    _raw = _safe_float(_meta.get('raw_product_price'), 0.0)
                    _vendor = _safe_float(_prow.get('purchase_price_cash_unit'), 0.0)
                    _std = _safe_float(_meta.get('standard_price'), 0.0)
                    _vendor_supplier = _prow.get('partner_id') or False
                    if _raw > 0.0:
                        return _raw, 'raw_product_price', (_supplier_fallback or _vendor_supplier or False)
                    if _vendor > 0.0:
                        return _vendor, 'vendor_bill', (_vendor_supplier or _supplier_fallback or False)
                    if _std > 0.0:
                        return _std, 'standard_price', (_supplier_fallback or _vendor_supplier or False)
                    return 0.0, 'none', (_supplier_fallback or _vendor_supplier or False)

                def _kit_component_cost_for_tmpl(_kit_tid):
                    _comps = kit_components_tmpl.get(_kit_tid) or []
                    if not _comps:
                        return 0.0, ''
                    _total = 0.0
                    _missing = 0
                    for _comp_pid, _comp_qty in _comps:
                        _comp_tmpl = pp_to_tmpl.get(_safe_int(_comp_pid))
                        _comp_price = 0.0
                        if _comp_tmpl:
                            _comp_price, _src, _sup = _purchase_price_for_tmpl(_comp_tmpl, False)
                        if _comp_price <= 0.0:
                            _missing += 1
                        _total += max(_safe_float(_comp_qty, 0.0), 0.0) * max(_comp_price, 0.0)
                    if _total > 0.0:
                        if _missing > 0:
                            return _total, 'kit_components_partial'
                        return _total, 'kit_components'
                    return 0.0, 'kit_components_missing'

                # ----------------------
                # [NUEVO v9.1.39+GMROI]
                # Costo OH + precio neto unit desde x_margen_por_producto_
                # Se lee el registro más reciente por producto (fecha_hasta DESC).
                # Usado para calcular gmroi_reponer y margen_unit con el costo real
                # (incluyendo ILA compra), en lugar del purchase_price_cash_unit.
                # Fallback silencioso si el modelo no tiene datos para el SKU.
                # ----------------------
                costo_oh_map   = {}   # tmpl_id -> x_studio_costo_oh_unit
                pvp_neto_map   = {}   # tmpl_id -> x_studio_precio_neto_unit
                margin_pct_map = {}   # tmpl_id -> x_studio_margin_pct
                try:
                    env.cr.execute("""
                        SELECT DISTINCT ON (pp.product_tmpl_id)
                            pp.product_tmpl_id,
                            m.x_studio_costo_oh_unit,
                            m.x_studio_precio_neto_unit,
                            m.x_studio_margin_pct
                        FROM x_margen_por_producto_ m
                        JOIN product_product pp ON pp.id = m.x_studio_producto
                        WHERE m.x_studio_compania = %s
                          AND m.x_studio_costo_oh_unit > 0
                          AND pp.product_tmpl_id IN %s
                        ORDER BY pp.product_tmpl_id,
                                 m.x_studio_fecha_hasta DESC NULLS LAST,
                                 m.id DESC
                    """, (company.id, tmpl_tuple))
                    for _tmpl_id, _costo, _pvp, _mpct in env.cr.fetchall():
                        _t = _safe_int(_tmpl_id)
                        if _t:
                            costo_oh_map[_t]   = _safe_float(_costo, 0.0)
                            pvp_neto_map[_t]   = _safe_float(_pvp,   0.0)
                            margin_pct_map[_t] = _safe_float(_mpct,  0.0)
                except Exception:
                    costo_oh_map   = {}
                    pvp_neto_map   = {}
                    margin_pct_map = {}

                # ----------------------
                # Pre-calcular mu_total por SKU en la red local
                # ----------------------
                mu_total_by_tmpl = {}
                for (_tid_key, _tmpl_key), _fwd_val in local_fwd_map.items():
                    _mu = _safe_float(_fwd_val.get('mu_week'), 0.0)
                    if _mu > 0.0:
                        mu_total_by_tmpl[_tmpl_key] = mu_total_by_tmpl.get(_tmpl_key, 0.0) + _mu

                # ----------------------
                # Cálculo provisional local
                # ----------------------
                records = []
                local_hit  = 0
                global_hit = 0
                fwd_miss   = 0

                for team_id in valid_team_ids:
                    stock_real_map = stock_real_by_team.get(team_id) or {}
                    stock_pedido_compra_map = stock_pedido_compra_by_team.get(team_id) or {}
                    stock_pedido_transfer_map = stock_pedido_transfer_by_team.get(team_id) or {}
                    stock_pedido_total_map = stock_pedido_total_by_team.get(team_id) or {}
                    # Nombres OC/picking pendientes hacia este team.
                    purchase_names_map = purchase_names_by_team.get(team_id) or {}
                    transfer_names_map = transfer_names_by_team.get(team_id) or {}

                    final_tmpl_ids = set()
                    for tid, v in stock_real_map.items():
                        if abs(v) > 0.00001:
                            final_tmpl_ids.add(tid)
                    for tid, v in stock_pedido_total_map.items():
                        if abs(v) > 0.00001:
                            final_tmpl_ids.add(tid)
                    for _k, _r in local_fwd_map.items():
                        if _k[0] == team_id and _safe_float(_r.get('mu_week'), 0.0) > 0.0:
                            final_tmpl_ids.add(_k[1])
                    if not final_tmpl_ids:
                        final_tmpl_ids = set(tmpl_ids)

                    for tid in sorted(final_tmpl_ids):
                        meta = tmpl_meta.get(tid)
                        if not meta:
                            continue

                        # Categoria Cigarros (categ_id=1628).
                        # Se usa categ_id exacto para no afectar Tabacos, Accesorios o Electronicos.
                        is_cigarros = _safe_int(meta.get('categ_id'), 0) in CIGARROS_CATEGORY_IDS

                        fwd = local_fwd_map.get((team_id, tid))
                        fwd_source = 'local'
                        if fwd:
                            local_hit += 1
                        else:
                            fwd = global_fwd_map.get(tid) or {}
                            fwd_source = 'global' if fwd else 'missing'
                            if fwd:
                                global_hit += 1
                            else:
                                fwd_miss += 1

                        mu_week       = _safe_float(fwd.get('mu_week'),       0.0)
                        sigma_week    = _safe_float(fwd.get('sigma_week'),    0.0)
                        period_weeks  = _safe_float(fwd.get('lead_weeks'),    PURCHASE_CYCLE_WEEKS)
                        if period_weeks <= 0.0:
                            period_weeks = PURCHASE_CYCLE_WEEKS
                        lead_weeks    = 0.0
                        protection_weeks = period_weeks
                        moq           = _safe_float(fwd.get('moq'),           1.0)
                        share_of_pool = _safe_float(fwd.get('share_of_pool'), 1.0)
                        banda_actual  = _normalize_banda_actual(fwd.get('banda_actual'))
                        fwd_supplier  = fwd.get('supplier_id') or False

                        _mu_total_red = mu_total_by_tmpl.get(tid, mu_week)
                        _share_demanda = (mu_week / _mu_total_red) if _mu_total_red > 0.0 else 1.0
                        _share_demanda = _clamp(_share_demanda, 0.0, 1.0)
                        # Escala sigma por sqrt(share_demanda) SOLO si el FWD es global.
                        # El FWD local ya tiene sigma a nivel sucursal; escalarlo lo subdividiria
                        # incorrectamente. Para FWD global, sigma representa la variabilidad de la
                        # red completa y debe prorratearse por share.
                        if fwd_source != 'local':
                            sigma_week = sigma_week * (_share_demanda ** 0.5)

                        demanda_semanal = mu_week

                        abc             = abc_map.get(tid) or {}
                        abcxyz          = abc.get('abcxyz') or ''
                        importancia_abc = abc.get('importancia_abc') or False
                        rank_abcxyz     = _safe_int(abc.get('rank_abcxyz'), 0)
                        motivo_eliminar = abc.get('motivo_eliminar') or ''

                        # XYZ siempre desde forecast (xyz_local viene ya con
                        # herencia incorporada: si el calculo local cayo a fallback,
                        # archivo 6 ya copio el XYZ global del producto). Archivo 3
                        # solo compone ABC_global + XYZ_forecast sin re-implementar
                        # herencia. Si falta algun input valido, forzar a 'CZ' como
                        # tratamiento conservador (alta variabilidad + baja
                        # importancia = no comprar mucho hasta que llegue senal).
                        # is_top_cash y display reserve siguen con abcxyz global.
                        xyz_local = (fwd.get('xyz_local') or '').strip().upper()
                        _abc_letter = abcxyz[0] if (len(abcxyz) == 2 and abcxyz[0] in ('A', 'B', 'C')) else ''
                        if ENABLE_XYZ_LOCAL:
                            # XYZ desde forecast, ABC desde producto
                            if _abc_letter and xyz_local in ('X', 'Y', 'Z'):
                                abcxyz_efectivo = _abc_letter + xyz_local
                            else:
                                abcxyz_efectivo = 'CZ'
                        else:
                            # Toggle off: comportamiento original con abcxyz global completo
                            if _abc_letter and len(abcxyz) == 2 and abcxyz[1] in ('X', 'Y', 'Z'):
                                abcxyz_efectivo = abcxyz
                            else:
                                abcxyz_efectivo = 'CZ'

                        # Top caja / venta estimada semanal.
                        # Se calcula temprano porque afecta factor de seguridad y exhibicion.
                        _pvp_bruto_for_top = _safe_float(meta.get('list_price'), 0.0)
                        _venta_bruta_week_est_raw = _pvp_bruto_for_top * max(demanda_semanal, 0.0)
                        is_top_cash = _is_top_cash_sku(abcxyz, rank_abcxyz, _venta_bruta_week_est_raw)
                        safety_factor_used = _safety_factor_for(abcxyz_efectivo, is_top_cash, is_cigarros)

                        stock_real = _safe_float(stock_real_map.get(tid), 0.0)
                        is_phantom_pool = bool(kit_components_tmpl.get(tid))
                        phantom_child_info = component_parent_tmpl.get(tid) or {}
                        is_phantom_child = bool(phantom_child_info)
                        phantom_parent_tmpl_id = _safe_int(phantom_child_info.get('parent_tmpl_id'), 0)
                        phantom_qty_per_parent = _safe_float(phantom_child_info.get('qty_per_parent'), 1.0)
                        phantom_block_procurement = bool(
                            (is_phantom_pool and PHANTOM_PROCUREMENT_MODE == 'block_parent')
                            or
                            (is_phantom_child and PHANTOM_PROCUREMENT_MODE == 'buy_parent_block_children')
                        )

                        if share_of_pool < 0.9999:
                            stock_effective = stock_real * share_of_pool
                        else:
                            stock_effective = stock_real

                        stock_pedido_compra = _safe_float(stock_pedido_compra_map.get(tid), 0.0)
                        stock_pedido_transfer = _safe_float(stock_pedido_transfer_map.get(tid), 0.0)
                        stock_pedido_total = _safe_float(stock_pedido_total_map.get(tid), 0.0)
                        stock_proyectado = stock_effective + stock_pedido_total
                        # Nombres de OC y pickings que originan el stock_pedido
                        # de esta linea (team, tid). Se concatenan en oc_pendientes_txt.
                        _po_names_set = purchase_names_map.get(tid) or set()
                        _tr_names_set = transfer_names_map.get(tid) or set()
                        _oc_pendientes_names = sorted(set(_po_names_set) | set(_tr_names_set))
                        oc_pendientes_txt = ', '.join(_oc_pendientes_names) if _oc_pendientes_names else ''

                        purchase_price_cash_unit, price_cash_source, supplier_id = _purchase_price_for_tmpl(tid, fwd_supplier)
                        kit_component_cost_unit = 0.0
                        kit_component_cost_source = ''

                        if is_phantom_pool:
                            kit_component_cost_unit, kit_component_cost_source = _kit_component_cost_for_tmpl(tid)
                            if PHANTOM_COST_SOURCE == 'component_first' and kit_component_cost_unit > 0.0:
                                purchase_price_cash_unit = kit_component_cost_unit
                                price_cash_source = kit_component_cost_source
                            elif purchase_price_cash_unit <= 0.0 and kit_component_cost_unit > 0.0:
                                purchase_price_cash_unit = kit_component_cost_unit
                                price_cash_source = kit_component_cost_source

                        solo_bodega = bool(meta.get('solo_bodega'))
                        # Sala solo_bodega usa la misma regla que proveedor->CD.
                        # Horizonte = 1 sem (CD entrega 1 vez por semana) + buffer.
                        # Safety stock = Z * sigma * sqrt(H), Z desde _SAFETY_FACTOR por ABCXYZ.
                        sala_H = (1.0 + CD_DELIVERY_EXTRA_WEEKS) if solo_bodega else 0.0

                        if solo_bodega:
                            financial_ceiling_sku = max(1.5, sala_H * 2.0)
                            payment_days_sku = PAYMENT_DAYS
                        else:
                            # Techo financiero por proveedor: si el supplier tiene
                            # payment_term en Odoo, usar sus dias efectivos. Sino fallback global.
                            payment_days_sku = supplier_payment_days_map.get(supplier_id, PAYMENT_DAYS) if supplier_id else PAYMENT_DAYS
                            _fcw_sku = _financial_ceiling_weeks(payment_days_sku)
                            financial_ceiling_sku = max(_fcw_sku, period_weeks * 2.0)

                        mu_for_target = mu_week if mu_week > DEMAND_FLOOR_WEEK else demanda_semanal
                        if solo_bodega:
                            if mu_for_target > DEMAND_FLOOR_WEEK:
                                z_sala = _safety_factor_for(abcxyz_efectivo, is_top_cash, is_cigarros)
                                safety_stock_units = z_sala * max(sigma_week, 0.0) * (sala_H ** 0.5)
                                target_units = mu_for_target * sala_H + safety_stock_units
                                reorder_target_weeks = target_units / mu_for_target
                            else:
                                target_units = 0.0
                                safety_stock_units = 0.0
                                reorder_target_weeks = sala_H
                        elif mu_for_target > DEMAND_FLOOR_WEEK and sigma_week >= 0.0 and protection_weeks > 0.0:
                            target_units, safety_stock_units, reorder_target_weeks = _calc_target_units(
                                abcxyz_efectivo, mu_for_target, sigma_week, protection_weeks, moq, financial_ceiling_sku, is_top_cash, is_cigarros
                            )
                        else:
                            z_fb                 = _safety_factor_for(abcxyz_efectivo, is_top_cash, is_cigarros)
                            H_fb                 = PURCHASE_CYCLE_WEEKS
                            safety_stock_units   = z_fb * max(demanda_semanal, 0.0) * (H_fb ** 0.5)
                            target_units         = demanda_semanal * H_fb + safety_stock_units
                            reorder_target_weeks = (target_units / demanda_semanal if demanda_semanal > DEMAND_FLOOR_WEEK else H_fb)
                            reorder_target_weeks = _clamp(reorder_target_weeks, 0.0, financial_ceiling_sku)

                        # Reserva comercial de exhibicion.
                        # No es demanda adicional; es stock que no queremos consumir antes de reponer.
                        target_units_stat = target_units
                        display_stock_units = _calc_display_stock_units(abcxyz, mu_for_target, is_top_cash, is_cigarros)
                        if display_stock_units > 0.0:
                            target_units = target_units + display_stock_units
                            if mu_for_target > DEMAND_FLOOR_WEEK:
                                reorder_target_weeks = _clamp(target_units / mu_for_target, 0.0, financial_ceiling_sku)

                        over_target_units = max(stock_proyectado - target_units, 0.0)

                        if stock_effective <= 0.0:
                            cover_weeks = 0.0
                            cover_label = 'sin_salida' if demanda_semanal <= DEMAND_FLOOR_WEEK else 'sin_stock'
                        elif demanda_semanal <= 0.0:
                            cover_weeks = 999.0
                            cover_label = 'sin_salida'
                        else:
                            cover_weeks = stock_effective / demanda_semanal
                            cover_label = _cover_label(cover_weeks, demanda_semanal, financial_ceiling_sku)

                        if demanda_semanal <= 0.0:
                            projected_cover_weeks = 999.0
                        else:
                            projected_cover_weeks = stock_proyectado / demanda_semanal

                        cob_extra_weeks  = max(projected_cover_weeks - reorder_target_weeks, 0.0)
                        rango_sobrestock = _rango_sobrestock(cob_extra_weeks)
                        if stock_real <= 0.0:
                            rango_sobrestock = 'quiebre'

                        qty_retorno_cd = 0.0
                        if solo_bodega and demanda_semanal > DEMAND_FLOOR_WEEK and projected_cover_weeks > RETURN_TRIGGER_WEEKS:
                            _hold_units_return = demanda_semanal * max(RETURN_HOLD_WEEKS, 0.0)
                            qty_retorno_cd = max(stock_proyectado - _hold_units_return, 0.0)

                        qty_neta_pre = max(target_units - stock_proyectado, 0.0)
                        qty_buy_pre  = (_smart_moq_box_or_wait(qty_neta_pre, moq, stock_proyectado, demanda_semanal, target_units, reorder_target_weeks, cover_label, False, abcxyz, display_stock_units) if SMART_MOQ_ROUNDING else _ceil_moq(qty_neta_pre, moq))

                        if qty_buy_pre > 0.0:
                            _denom = max(demanda_semanal, DEMAND_FLOOR_WEEK)
                            cover_after_buy = (stock_proyectado + qty_buy_pre) / _denom
                            if cover_after_buy > financial_ceiling_sku * MOQ_COVER_GUARD:
                                qty_buy_pre = 0.0

                        buy_action, decision_reason = _buy_action_from_cover(stock_effective, cover_label)

                        if buy_action == 'reponer_ahora' and stock_proyectado >= target_units and target_units > 0.0:
                            buy_action = 'no_comprar_esta_semana'
                            if stock_pedido_total > 0.0:
                                decision_reason = 'stock_pedido_cubre_target'
                            else:
                                decision_reason = 'stock_cubre_target'

                        purchase_ok          = bool(meta.get('purchase_ok'))
                        no_disponible_compra = (not purchase_ok) and (not solo_bodega)
                        _es_compra_cd        = False

                        if phantom_block_procurement:
                            # Politica OH: comprar padre y bloquear hijos/componentes.
                            # (Alternativa antigua via context: bloquear padre phantom.)
                            if is_phantom_pool and PHANTOM_PROCUREMENT_MODE == 'block_parent':
                                decision_reason = 'policy_phantom_parent_no_procurement'
                            elif is_phantom_child and PHANTOM_PROCUREMENT_MODE == 'buy_parent_block_children':
                                decision_reason = (
                                    'policy_phantom_child_no_procurement_buy_parent'
                                    + ' | buy_parent_tmpl=' + str(phantom_parent_tmpl_id)
                                    + ' | qty_per_parent=' + str(round(phantom_qty_per_parent, 4))
                                )
                            else:
                                decision_reason = 'policy_phantom_no_procurement'
                            buy_action      = 'no_comprar_esta_semana'
                            qty_retorno_cd  = 0.0
                            qty_neta_pre    = 0.0
                            qty_buy_pre     = 0.0
                        elif solo_bodega and qty_retorno_cd > 0.0:
                            buy_action      = RETURN_TO_CD_ACTION_SAFE
                            decision_reason = 'sobrestock_retorno_cd'
                            qty_neta_pre    = 0.0
                            qty_buy_pre     = 0.0
                        elif solo_bodega and qty_neta_pre > 0.0 and buy_action == 'reponer_ahora':
                            buy_action      = 'transferir_desde_cd'
                            decision_reason = 'policy_solo_bodega_sala'
                        elif no_disponible_compra:
                            buy_action      = NO_DISP_ACTION_SAFE
                            decision_reason = 'policy_no_disponible_compra_purchase_ok_false'
                            qty_neta_pre    = 0.0
                            qty_buy_pre     = 0.0

                        # ── [v9.1.83] Regla de descentralizacion por COBERTURA DE CAJA ────
                        # Reemplaza la v9.1.74 (capital atascado = monto x tiempo) que
                        # inflaba productos chicos baratos de baja rotacion (Halls,
                        # chicles, caramelos), mandandolos a CD donde destruian picking.
                        #
                        # Regla nueva:
                        #   - solo_bodega=True: manda primero (no aplica esta regla).
                        #   - Categoria padre excluida (Cafeteria, Cigarrillos, Congelados,
                        #     Esenciales Hogar, Impulso, Snack y Coctel): SALA siempre.
                        #   - cobertura_caja = moq/demanda_semanal > umbral (30 dias por
                        #     default): CD para consolidar entre sucursales.
                        #   - Resto: SALA.
                        #
                        # Ejemplos validados:
                        #   * Royal Guard 710cc (Panguipulli, demanda 187 u/sem, moq 24):
                        #     cobertura 0.13 sem < 4.286 -> SALA (varias cajas llegan directo).
                        #   * Blue Label (demanda 0.08 u/sem, moq 1): cobertura ~12 sem >
                        #     4.286 -> CD (1 caja dura meses).
                        #   * Halls $4.464 caja (categoria Impulso): SALA siempre.
                        if (not solo_bodega) and (not _es_compra_cd) and buy_action == 'reponer_ahora' and demanda_semanal > DEMAND_FLOOR_WEEK:
                            categ_id_local = _safe_int(meta.get('categ_id'), 0)
                            # Solo evaluar cobertura si la categoria NO esta excluida.
                            if categ_id_local not in no_cd_category_set:
                                cobertura_caja_local = moq / demanda_semanal
                                if cobertura_caja_local > COVER_WEEKS_THRESHOLD_FOR_CD:
                                    buy_action      = 'compra_cd'
                                    decision_reason = ('cobertura_caja_alta_cd'
                                                       ' | cobertura_w=' + str(round(cobertura_caja_local, 2))
                                                       + ' | umbral_w=' + str(round(COVER_WEEKS_THRESHOLD_FOR_CD, 2))
                                                       + ' | moq=' + str(int(moq))
                                                       + ' | mu_w=' + str(round(demanda_semanal, 3)))
                                    _es_compra_cd   = True
                        # ── fin regla descentralizacion v9.1.83 ───────────────────────────

                        severity    = _severity_from_cover(cover_label)
                        short_state = ('quiebre_ya' if cover_label in ('sin_stock', 'critico')
                                       else ('riesgo_t3' if cover_label == 'bajo' else 'ok'))

                        if is_phantom_pool and not VALUE_PHANTOM_KITS:
                            stock_value_cash_physical  = 0.0
                            stock_value_cash_effective = 0.0
                            over_target_value_cash     = 0.0
                        else:
                            stock_value_cash_physical  = stock_real * purchase_price_cash_unit
                            stock_value_cash_effective = stock_effective * purchase_price_cash_unit
                            over_target_value_cash     = over_target_units * purchase_price_cash_unit

                        rec = {
                            'team_id': team_id,
                            'tmpl_id': tid,
                            'meta': meta,
                            'fwd_source': fwd_source,
                            'es_compra_cd': _es_compra_cd,
                            'no_disponible_compra': no_disponible_compra,
                            'qty_compra_cd': 0.0,
                            'mu_week': mu_week,
                            'sigma_week': sigma_week,
                            'period_weeks': period_weeks,
                            'lead_weeks': lead_weeks,
                            'protection_weeks': protection_weeks,
                            'sala_target_weeks': sala_H,
                            'cd_delivery_extra_weeks': CD_DELIVERY_EXTRA_WEEKS if solo_bodega else 0.0,
                            'moq': moq,
                            'share_of_pool': share_of_pool,
                            'is_phantom_pool': is_phantom_pool,
                            'is_phantom_child': is_phantom_child,
                            'phantom_parent_tmpl_id': phantom_parent_tmpl_id,
                            'phantom_qty_per_parent': phantom_qty_per_parent,
                            'phantom_block_procurement': phantom_block_procurement,
                            'pool_parent_demand': bool(fwd.get('pool_parent_demand')),
                            'kit_component_cost_unit': kit_component_cost_unit,
                            'kit_component_cost_source': kit_component_cost_source,
                            'banda_actual': banda_actual,
                            'fwd_supplier': fwd_supplier,
                            'abcxyz': abcxyz,
                            'importancia_abc': importancia_abc,
                            'rank_abcxyz': rank_abcxyz,
                            'motivo_eliminar': motivo_eliminar,
                            'stock_real': stock_real,
                            'stock_effective': stock_effective,
                            'stock_pedido_compra': stock_pedido_compra,
                            'stock_pedido_transfer': stock_pedido_transfer,
                            'stock_pedido_total': stock_pedido_total,
                            'stock_proyectado': stock_proyectado,
                            'oc_pendientes_txt': oc_pendientes_txt,
                            'purchase_price_cash_unit': purchase_price_cash_unit,
                            'price_cash_source': price_cash_source,
                            'supplier_id': supplier_id,
                            'financial_ceiling_sku': financial_ceiling_sku,
                            'payment_days_sku': payment_days_sku,
                            'target_units': target_units,
                            'target_units_stat': target_units_stat,
                            'display_stock_units': display_stock_units,
                            'is_top_cash': is_top_cash,
                            'is_cigarros': is_cigarros,
                            'venta_bruta_week_est_raw': _venta_bruta_week_est_raw,
                            'safety_factor_used': safety_factor_used,
                            'safety_stock_units': safety_stock_units,
                            'reorder_target_weeks': reorder_target_weeks,
                            'over_target_units': over_target_units,
                            'cover_weeks': cover_weeks,
                            'cover_label': cover_label,
                            'cob_extra_weeks': cob_extra_weeks,
                            'rango_sobrestock': rango_sobrestock,
                            'buy_action_pre': buy_action,
                            'decision_reason_pre': decision_reason,
                            'severity': severity,
                            'short_state': short_state,
                            'qty_neta_pre_central': qty_neta_pre,
                            'qty_buy_pre_central': qty_buy_pre,
                            'qty_retorno_cd': qty_retorno_cd,
                            'demanda_semanal': demanda_semanal,
                            'stock_value_cash_physical': stock_value_cash_physical,
                            'stock_value_cash_effective': stock_value_cash_effective,
                            'over_target_value_cash': over_target_value_cash,
                            'purchase_row': purchase_map.get(tid) or {},
                            'warehouse_id': team_warehouse_id.get(team_id) or False,
                            'root_location_id': team_root_location_id.get(team_id) or False,
                            'stock_source_mode': team_source_mode.get(team_id) or '',
                            'warehouse_nombre': team_location_name.get(team_id) or '',
                        }
                        records.append(rec)

                # ----------------------
                # Preparar compra_cd por SKU
                # ----------------------
                compra_cd_gaps = {}
                for rec in records:
                    rec['qty_compra_cd'] = 0.0
                    if rec.get('es_compra_cd'):
                        arr = compra_cd_gaps.get(rec['tmpl_id']) or []
                        arr.append(rec)
                        compra_cd_gaps[rec['tmpl_id']] = arr

                # ----------------------
                # Reserva bodega central por SKU
                # ----------------------
                alloc_records_by_tmpl = {}
                for rec in records:
                    rec['central_stock_total']      = _safe_float(central_stock_real_map.get(rec['tmpl_id']), 0.0)
                    rec['transfer_qty']             = 0.0
                    rec['purchase_qty_net']         = 0.0
                    rec['purchase_qty_need_exact']  = 0.0
                    rec['purchase_qty_need_units']  = 0.0
                    rec['supply_source']            = 'no_action'
                    rec['buy_action_final']         = rec.get('buy_action_pre') or 'no_comprar_esta_semana'
                    rec['solo_cd']                  = False

                    if rec.get('phantom_block_procurement'):
                        rec['transfer_qty']             = 0.0
                        rec['purchase_qty_net']         = 0.0
                        rec['purchase_qty_need_exact']  = 0.0
                        rec['purchase_qty_need_units']  = 0.0
                        rec['supply_source']            = 'no_action'
                        rec['buy_action_final']         = 'no_comprar_esta_semana'
                        rec['solo_cd']                  = False
                        continue

                    if rec.get('no_disponible_compra'):
                        rec['transfer_qty']     = 0.0
                        rec['purchase_qty_net'] = 0.0
                        rec['supply_source']    = 'no_action'
                        rec['buy_action_final'] = NO_DISP_ACTION_SAFE
                        continue

                    need = _safe_float(rec.get('qty_neta_pre_central'), 0.0)
                    if need <= 0.0:
                        continue

                    if rec.get('es_compra_cd'):
                        qty_need_units = _ceil_units(need)
                        qty_buy_moq    = (_smart_moq_box_or_wait(need, rec.get('moq'), rec.get('stock_proyectado'), rec.get('demanda_semanal'), rec.get('target_units'), rec.get('reorder_target_weeks'), rec.get('cover_label'), rec.get('cover_label') in ('sin_stock', 'critico'), rec.get('abcxyz'), rec.get('display_stock_units')) if SMART_MOQ_ROUNDING else _ceil_moq(qty_need_units, rec.get('moq')))
                        rec['purchase_qty_need_exact'] = need
                        rec['purchase_qty_need_units'] = qty_need_units
                        rec['purchase_qty_net']        = qty_buy_moq
                        rec['transfer_qty']            = 0.0
                        rec['supply_source']           = 'buy_only'
                        rec['buy_action_final']        = 'compra_cd'
                        rec['solo_cd']                 = False
                        continue

                    arr = alloc_records_by_tmpl.get(rec['tmpl_id']) or []
                    arr.append(rec)
                    alloc_records_by_tmpl[rec['tmpl_id']] = arr

                central_alloc_units = 0.0
                central_alloc_lines = 0
                central_transfer_only_lines = 0
                central_enabled = bool(central_expanded_loc_ids)

                for tmpl_id, arr in alloc_records_by_tmpl.items():
                    available = _safe_float(central_stock_real_map.get(tmpl_id), 0.0)
                    if CENTRAL_RESERVE_PCT > 0.0 and available > 0.0:
                        available = max(available * (1.0 - CENTRAL_RESERVE_PCT), 0.0)
                    arr_sorted = sorted(arr, key=_priority_tuple)
                    for rec in arr_sorted:
                        need = _safe_float(rec.get('qty_neta_pre_central'), 0.0)
                        need_units = _round_units(need)
                        available_units = _round_units(available)
                        if available_units > 0.0 and need_units > 0.0:
                            transfer_qty = min(need_units, available_units)
                        else:
                            transfer_qty = 0.0
                        available -= transfer_qty
                        if available < 0.0:
                            available = 0.0
                        rec['transfer_qty'] = transfer_qty
                        if transfer_qty > 0.0:
                            central_alloc_units += transfer_qty
                            central_alloc_lines += 1

                        qty_net = max(need - transfer_qty, 0.0)
                        qty_need_units = _ceil_units(qty_net)
                        qty_buy = (_smart_moq_box_or_wait(qty_net, rec.get('moq'), _safe_float(rec.get('stock_proyectado'), 0.0) + transfer_qty, rec.get('demanda_semanal'), rec.get('target_units'), rec.get('reorder_target_weeks'), rec.get('cover_label'), rec.get('cover_label') in ('sin_stock', 'critico'), rec.get('abcxyz'), rec.get('display_stock_units')) if SMART_MOQ_ROUNDING else _ceil_moq(qty_need_units, rec.get('moq')))
                        if qty_buy > 0.0:
                            _dem = max(_safe_float(rec.get('demanda_semanal'), 0.0), DEMAND_FLOOR_WEEK)
                            cover_after_supply = (
                                _safe_float(rec.get('stock_effective'), 0.0) + transfer_qty + qty_buy
                            ) / _dem
                            if cover_after_supply > _safe_float(rec.get('financial_ceiling_sku'), 0.5) * MOQ_COVER_GUARD:
                                qty_buy = 0.0
                        rec['purchase_qty_net'] = qty_buy

                        gap_cubierto = transfer_qty >= need - 0.00001

                        # ── [2026-06-09] Modelo CD pass-through diferencial ──────────────
                        # solo_bodega: el CD es consolidador puro. La sala SOLO transfiere lo
                        # que el CD ya tiene; el faltante (qty_net) se consolida en UNA sola
                        # compra_cd en la pseudo-fila CD (id 26), no por sala. Esto elimina:
                        #   (a) el orphan (sala 'compra_cd' con traslado que nunca se generaba), y
                        #   (b) el doble conteo del antiguo solo_bodega_cd_replenish (target
                        #       forward del CD sin restar stock de salas).
                        # compra_cd(id 26) = max(0, Σ necesidad_salas − stock_CD), MOQ una vez.
                        # Ver proyectos/2026-06-09-diag-li450701/diseno.md
                        if bool(rec.get('meta', {}).get('solo_bodega')):
                            rec['purchase_qty_net'] = 0.0        # la compra vive en el CD, no en la sala
                            if qty_net > 0.0:
                                rec['purchase_qty_need_exact'] = qty_net
                                _cc = compra_cd_gaps.get(rec['tmpl_id']) or []
                                _cc.append(rec)
                                compra_cd_gaps[rec['tmpl_id']] = _cc
                            if transfer_qty > 0.0:
                                rec['supply_source']    = 'transferir_desde_cd'
                                rec['solo_cd']          = True
                                rec['buy_action_final'] = 'transferir_desde_cd'
                                central_transfer_only_lines += 1
                            else:
                                rec['supply_source']    = 'no_action'
                                rec['solo_cd']          = False
                                rec['buy_action_final'] = 'no_comprar_esta_semana'
                            continue
                        # ── fin modelo CD pass-through (resto = no solo_bodega) ───────────

                        if transfer_qty > 0.0 and gap_cubierto and qty_buy == 0.0:
                            rec['supply_source']    = 'transferir_desde_cd'
                            rec['solo_cd']          = True
                            rec['buy_action_final'] = 'transferir_desde_cd'
                            central_transfer_only_lines += 1
                        elif transfer_qty > 0.0 and qty_buy > 0.0:
                            rec['supply_source']    = 'central+buy'
                            rec['solo_cd']          = False
                            rec['buy_action_final'] = 'reponer_ahora'
                        elif transfer_qty > 0.0:
                            rec['supply_source']    = 'transferir_desde_cd'
                            rec['solo_cd']          = True
                            rec['buy_action_final'] = 'transferir_desde_cd'
                            central_transfer_only_lines += 1
                        elif qty_buy > 0.0:
                            rec['supply_source']    = 'buy_only'
                            rec['solo_cd']          = False
                            rec['buy_action_final'] = rec.get('buy_action_pre')
                        else:
                            rec['supply_source']    = 'no_action'
                            rec['solo_cd']          = False
                            rec['buy_action_final'] = rec.get('buy_action_pre')

                # ----------------------
                # Consolidar compra CD por SKU
                # ----------------------
                # Para compra_cd NO se debe aplicar MOQ por local.
                # Primero sumamos la necesidad tecnica exacta de todos los locales por SKU
                # y recien despues aplicamos caja/MOQ una sola vez en Bodega Central.
                for tmpl_id, arr in compra_cd_gaps.items():
                    if not arr:
                        continue

                    exact_need_sum = 0.0
                    stock_sum = 0.0
                    demand_sum = 0.0
                    target_sum = 0.0
                    display_sum = 0.0
                    moq_sku = 1.0
                    any_critical = False
                    worst_cover_label = ''
                    worst_abcxyz = ''

                    for rec in arr:
                        _need = _safe_float(rec.get('purchase_qty_need_exact', rec.get('qty_neta_pre_central', 0.0)), 0.0)
                        if _need <= 0.0:
                            _need = _safe_float(rec.get('qty_neta_pre_central', 0.0), 0.0)
                        exact_need_sum += max(_need, 0.0)
                        stock_sum += _safe_float(rec.get('stock_proyectado'), 0.0)
                        demand_sum += _safe_float(rec.get('demanda_semanal'), 0.0)
                        target_sum += _safe_float(rec.get('target_units'), 0.0)
                        display_sum += _safe_float(rec.get('display_stock_units'), 0.0)
                        if _safe_float(rec.get('moq'), 0.0) > 0.0:
                            moq_sku = _safe_float(rec.get('moq'), 1.0)
                        _cl = rec.get('cover_label') or ''
                        _abc = (rec.get('abcxyz') or '').strip()
                        if _cl in ('sin_stock', 'critico'):
                            any_critical = True
                            worst_cover_label = _cl
                            if (not worst_abcxyz) and _abc in ('AX', 'AY', 'AZ', 'BX', 'BY', 'BZ'):
                                worst_abcxyz = _abc

                    target_weeks_agg = (target_sum / demand_sum) if demand_sum > DEMAND_FLOOR_WEEK else 1.0

                    if exact_need_sum > 0.0:
                        if SMART_MOQ_ROUNDING:
                            qty_order_cd = _smart_moq_box_or_wait(
                                exact_need_sum, moq_sku, stock_sum, demand_sum,
                                target_sum, target_weeks_agg, worst_cover_label, any_critical, worst_abcxyz, display_sum
                            )
                        else:
                            qty_order_cd = _ceil_moq(_ceil_units(exact_need_sum), moq_sku)
                    else:
                        qty_order_cd = 0.0

                    for rec in arr:
                        rec['qty_compra_cd'] = 0.0
                        rec['compra_cd_need_sku_exact'] = exact_need_sum
                        rec['compra_cd_qty_sku_order'] = qty_order_cd
                        rec['compra_cd_origin_lines'] = len(arr)

                    if qty_order_cd > 0.0:
                        # Solo una linea representativa carga la compra CD consolidada.
                        # La pseudo-fila CD la sumará una sola vez.
                        arr[0]['qty_compra_cd'] = qty_order_cd
                    else:
                        # Si la politica caja-o-esperar decide no comprar el SKU consolidado,
                        # apagamos la accion para no dejar lineas compra_cd sin cantidad.
                        # PERO preservamos las salas que SI tienen traslado (transferir_desde_cd):
                        # su movimiento es real aunque la compra consolidada del CD sea 0.
                        for rec in arr:
                            if _safe_float(rec.get('transfer_qty'), 0.0) > 0.0:
                                continue
                            rec['buy_action_final'] = 'no_comprar_esta_semana'
                            rec['supply_source'] = 'no_action'

                # ----------------------
                # Consolidar pseudo-sucursal CD (team analitico)
                # ----------------------
                central_team_map = {}
                records_by_tmpl = {}
                records_tmpl_set = set()
                for rec in records:
                    _rtid = rec['tmpl_id']
                    records_tmpl_set.add(_rtid)
                    _arr = records_by_tmpl.get(_rtid) or []
                    _arr.append(rec)
                    records_by_tmpl[_rtid] = _arr

                central_tmpl_ids = set(central_stock_real_map.keys())
                for _tid in records_tmpl_set:
                    central_tmpl_ids.add(_tid)
                for _tid in central_stock_pedido_total_map.keys():
                    central_tmpl_ids.add(_tid)

                for tid in sorted(central_tmpl_ids):
                    stock_cd = _safe_float(central_stock_real_map.get(tid), 0.0)
                    stock_cd_pedido_compra = _safe_float(central_stock_pedido_compra_map.get(tid), 0.0)
                    stock_cd_pedido_transfer = _safe_float(central_stock_pedido_transfer_map.get(tid), 0.0)
                    stock_cd_pedido_total = _safe_float(central_stock_pedido_total_map.get(tid), 0.0)
                    stock_cd_proyectado = stock_cd + stock_cd_pedido_total
                    if abs(stock_cd) <= 0.00001 and abs(stock_cd_pedido_total) <= 0.00001 and tid not in records_tmpl_set:
                        continue
                    # Nombres de OC y pickings que originan stock_pedido en CD.
                    _cd_po_names_set = central_purchase_names_map.get(tid) or set()
                    _cd_tr_names_set = central_transfer_names_map.get(tid) or set()
                    _cd_oc_pendientes_names = sorted(set(_cd_po_names_set) | set(_cd_tr_names_set))
                    _cd_oc_pendientes_txt = ', '.join(_cd_oc_pendientes_names) if _cd_oc_pendientes_names else ''
                    base = {
                        'tmpl_id': tid,
                        'stock_real': stock_cd,
                        'stock_effective': stock_cd,
                        'stock_pedido_compra': stock_cd_pedido_compra,
                        'stock_pedido_transfer': stock_cd_pedido_transfer,
                        'stock_pedido_total': stock_cd_pedido_total,
                        'stock_proyectado': stock_cd_proyectado,
                        'oc_pendientes_txt': _cd_oc_pendientes_txt,
                        'qty_a_pedir': 0.0,
                        'qty_transferir': 0.0,
                        'qty_retorno_cd': 0.0,
                        'moq': 1.0,
                        'supplier_id': False,
                        'purchase_price_cash_unit': 0.0,
                        'price_cash_source': 'none',
                        'abcxyz': '',
                        'rank_abcxyz': 0,
                        'importancia_abc': False,
                        'banda_actual': 'BASE',
                        'period_weeks': 0.0,
                        'lead_weeks': 0.0,
                        'protection_weeks': 0.0,
                        'sala_target_weeks': 0.0,
                        'cd_delivery_extra_weeks': 0.0,
                        'stock_source_mode': 'central',
                        'demanda_estimada_entera': 0.0,
                        'venta_bruta_estimada': 0.0,
                        'demanda_semanal_origen_cd': 0.0,
                        'stock_proyectado_origen_cd': 0.0,
                    }
                    abc = abc_map.get(tid) or {}
                    if abc:
                        base['abcxyz'] = abc.get('abcxyz') or ''
                        base['rank_abcxyz'] = _safe_int(abc.get('rank_abcxyz'), 0)
                        base['importancia_abc'] = abc.get('importancia_abc') or False
                    meta = tmpl_meta.get(tid) or {}
                    _base_price, _base_src, _base_supplier = _purchase_price_for_tmpl(tid, False)
                    _central_is_phantom = bool(kit_components_tmpl.get(tid))
                    _central_kit_cost = 0.0
                    _central_kit_src = ''
                    if _central_is_phantom:
                        _central_kit_cost, _central_kit_src = _kit_component_cost_for_tmpl(tid)
                        if PHANTOM_COST_SOURCE == 'component_first' and _central_kit_cost > 0.0:
                            _base_price = _central_kit_cost
                            _base_src = _central_kit_src
                        elif _base_price <= 0.0 and _central_kit_cost > 0.0:
                            _base_price = _central_kit_cost
                            _base_src = _central_kit_src
                    base['purchase_price_cash_unit'] = _base_price
                    base['price_cash_source'] = _base_src
                    base['supplier_id'] = _base_supplier or False

                    moq_found = False
                    for rec in records_by_tmpl.get(tid, []):
                        if not moq_found and _safe_float(rec.get('moq'), 0.0) > 0.0:
                            base['moq'] = _safe_float(rec.get('moq'), 1.0)
                            moq_found = True
                        if (not base['supplier_id']) and rec.get('supplier_id'):
                            base['supplier_id'] = rec.get('supplier_id')
                        if (not base['abcxyz']) and rec.get('abcxyz'):
                            base['abcxyz'] = rec.get('abcxyz') or ''
                            base['rank_abcxyz'] = _safe_int(rec.get('rank_abcxyz'), 0)
                            base['importancia_abc'] = rec.get('importancia_abc') or False
                        if rec.get('banda_actual'):
                            base['banda_actual'] = rec.get('banda_actual')
                        base['qty_transferir'] += _safe_float(rec.get('transfer_qty'), 0.0)
                        base['qty_retorno_cd'] += _safe_float(rec.get('qty_retorno_cd'), 0.0)
                        # Consolida por qty_compra_cd>0, NO por etiqueta: con el modelo
                        # pass-through (2026-06-09) la fila que carga la compra del SKU queda
                        # etiquetada 'transferir_desde_cd' (la sala transfiere; el CD compra).
                        _q = _safe_float(rec.get('qty_compra_cd', 0.0), 0.0)
                        if _q > 0.0:
                            base['qty_a_pedir'] += _q

                            # Venta estimada de las lineas locales que explican esta compra CD.
                            # Se acumula aunque solo una linea representativa cargue qty_compra_cd,
                            # porque la demanda pertenece a todos los locales origen.
                            _dem_ent = _round_units(_safe_float(rec.get('demanda_semanal'), 0.0))
                            _pvp_b = _safe_float((rec.get('meta') or {}).get('list_price'), 0.0)
                            base['demanda_estimada_entera'] += _dem_ent
                            base['venta_bruta_estimada'] += _dem_ent * _pvp_b
                            base['demanda_semanal_origen_cd'] += _safe_float(rec.get('demanda_semanal'), 0.0)
                            # Agregar stock proyectado de los locales que originan esta compra_cd,
                            # para presupuestar mensual a nivel SKU-red sin double counting por local.
                            base['stock_proyectado_origen_cd'] += _safe_float(rec.get('stock_proyectado'), 0.0)
                    central_team_map[tid] = base

                # ----------------------
                # Reposicion automatica CD para solo_bodega  [DESACTIVADO 2026-06-09]
                # ----------------------
                # El target forward del CD (demanda_red*periodo + safety, SIN restar stock
                # de salas) causaba doble conteo y sobre-compra (~-$78,7M en simulacion).
                # Reemplazado por el modelo CD pass-through: la compra del CD se consolida
                # en compra_cd_gaps = max(0, Σ necesidad_salas − stock_CD), MOQ una vez.
                # El loop queda inalcanzable (continue) como referencia/rollback.
                # Ver proyectos/2026-06-09-diag-li450701/diseno.md
                for tid, base in central_team_map.items():
                    continue
                    meta = tmpl_meta.get(tid) or {}
                    if not bool(meta.get('solo_bodega')):
                        continue
                    # Phantom: la direccion de compra depende del modo.
                    #   buy_parent_block_children -> repone el PADRE, bloquea el HIJO.
                    #   block_parent (legacy)      -> bloquea el PADRE, repone el HIJO.
                    #   allow_parent               -> ninguno se salta.
                    # Bug previo (<=v9.1.86): saltaba SIEMPRE al padre phantom y nunca
                    # al hijo, invirtiendo la regla bajo buy_parent_block_children
                    # (compraba la lata, no el pack). v9.1.87 lo hace mode-aware.
                    _ph_parent = bool(kit_components_tmpl.get(tid))
                    _ph_child  = bool(component_parent_tmpl.get(tid))
                    if PHANTOM_PROCUREMENT_MODE == 'buy_parent_block_children':
                        if _ph_child:
                            continue
                    elif PHANTOM_PROCUREMENT_MODE == 'block_parent':
                        if _ph_parent:
                            continue
                    if _safe_float(base.get('qty_a_pedir'), 0.0) > 0.0:
                        continue

                    abcxyz_cd = (base.get('abcxyz') or '').strip()
                    if abcxyz_cd not in CD_ELIGIBLE_ABCXYZ:
                        continue

                    mu_red = 0.0
                    sigma_sq_red = 0.0
                    moq_sku = _safe_float(base.get('moq'), 1.0)
                    # Horizonte CD = period_weeks por SKU (igual que sala), tomado del primer rec
                    # con valor valido. Todos los rec del mismo tid comparten FWD.
                    period_weeks_sku = 0.0
                    for rec in records_by_tmpl.get(tid, []):
                        mu_i = _safe_float(rec.get('mu_week'), 0.0)
                        sigma_i = _safe_float(rec.get('sigma_week'), 0.0)
                        if mu_i > 0.0:
                            mu_red += mu_i
                        if sigma_i > 0.0:
                            sigma_sq_red += sigma_i ** 2.0
                        if _safe_float(rec.get('moq'), 0.0) > 0.0:
                            moq_sku = _safe_float(rec.get('moq'), moq_sku)
                        if period_weeks_sku <= 0.0:
                            pw = _safe_float(rec.get('period_weeks'), 0.0)
                            if pw > 0.0:
                                period_weeks_sku = pw

                    if mu_red <= DEMAND_FLOOR_WEEK:
                        continue

                    if period_weeks_sku <= 0.0:
                        period_weeks_sku = PURCHASE_CYCLE_WEEKS

                    sigma_red = sigma_sq_red ** 0.5
                    z_cd = _safe_float(_SAFETY_FACTOR.get(abcxyz_cd, _SAFETY_FACTOR_DEFAULT), _SAFETY_FACTOR_DEFAULT)
                    safety_cd = z_cd * sigma_red * (period_weeks_sku ** 0.5)
                    target_cd = (mu_red * period_weeks_sku) + safety_cd
                    stock_proy_cd = _safe_float(base.get('stock_proyectado'), 0.0)
                    qty_neta_cd = max(target_cd - stock_proy_cd, 0.0)
                    if qty_neta_cd <= 0.0:
                        continue

                    cover_cd = (stock_proy_cd / mu_red) if mu_red > DEMAND_FLOOR_WEEK else 999.0
                    if stock_proy_cd <= 0.0:
                        cover_label_cd = 'sin_stock'
                    elif cover_cd < 1.5:
                        cover_label_cd = 'critico'
                    elif cover_cd < period_weeks_sku:
                        cover_label_cd = 'bajo'
                    else:
                        cover_label_cd = 'normal'

                    if SMART_MOQ_ROUNDING:
                        qty_compra_cd = _smart_moq_box_or_wait(
                            qty_neta_cd,
                            moq_sku,
                            stock_proy_cd,
                            mu_red,
                            target_cd,
                            period_weeks_sku,
                            cover_label_cd,
                            cover_label_cd in ('sin_stock', 'critico'),
                            abcxyz_cd,
                            0.0,
                        )
                    else:
                        qty_compra_cd = _ceil_moq(_ceil_units(qty_neta_cd), moq_sku)

                    if qty_compra_cd <= 0.0:
                        continue

                    base['qty_a_pedir'] = _safe_float(base.get('qty_a_pedir'), 0.0) + qty_compra_cd
                    base['moq'] = moq_sku
                    base['solo_bodega_cd_replenish'] = True
                    base['cd_target_weeks'] = period_weeks_sku
                    base['cd_target_units'] = target_cd
                    base['cd_mu_red'] = mu_red
                    base['cd_sigma_red'] = sigma_red
                    base['cd_safety_units'] = safety_cd
                    base['cd_z'] = z_cd
                    base['cd_qty_neta'] = qty_neta_cd

                # ----------------------
                # Construcción final + create
                # ----------------------
                batch   = []
                created = 0
                _anal_create = Anal.with_context(
                    tracking_disable=True,
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                    mail_notrack=True,
                ).create

                for rec in records:
                    tid     = rec['tmpl_id']
                    team_id = rec['team_id']
                    meta    = rec['meta']
                    stock_real               = _safe_float(rec['stock_real'], 0.0)
                    stock_effective          = _safe_float(rec['stock_effective'], 0.0)
                    stock_pedido_compra      = _safe_float(rec.get('stock_pedido_compra', 0.0), 0.0)
                    stock_pedido_transfer    = _safe_float(rec.get('stock_pedido_transfer', 0.0), 0.0)
                    stock_pedido_total       = _safe_float(rec.get('stock_pedido_total', 0.0), 0.0)
                    stock_proyectado         = _safe_float(rec.get('stock_proyectado', stock_effective + stock_pedido_total), 0.0)
                    target_units             = _safe_float(rec['target_units'], 0.0)
                    over_target_units        = _safe_float(rec['over_target_units'], 0.0)
                    qty_a_pedir              = _safe_float(rec.get('purchase_qty_net', 0.0), 0.0)
                    qty_retorno_cd           = _safe_float(rec.get('qty_retorno_cd', 0.0), 0.0)
                    transfer_qty             = _safe_float(rec.get('transfer_qty', 0.0), 0.0)
                    central_stock_total      = _safe_float(rec.get('central_stock_total', 0.0), 0.0)
                    moq                      = _safe_float(rec['moq'], 1.0)
                    demanda_semanal          = _safe_float(rec['demanda_semanal'], 0.0)
                    purchase_price_cash_unit = _safe_float(rec['purchase_price_cash_unit'], 0.0)

                    buy_action  = rec.get('buy_action_final') or rec.get('buy_action_pre') or 'no_comprar_esta_semana'
                    supply_src  = rec.get('supply_source') or 'no_action'
                    solo_cd     = rec.get('solo_cd', False)
                    _zero_qty_action_cleanup = False

                    if rec.get('phantom_block_procurement'):
                        buy_action     = 'no_comprar_esta_semana'
                        supply_src     = 'no_action'
                        qty_a_pedir    = 0.0
                        transfer_qty   = 0.0
                        qty_retorno_cd = 0.0
                        solo_cd        = False
                    elif rec.get('no_disponible_compra'):
                        buy_action   = NO_DISP_ACTION_SAFE
                        supply_src   = 'no_action'
                        qty_a_pedir  = 0.0
                        transfer_qty = 0.0
                        solo_cd      = False
                    elif buy_action == 'compra_cd':
                        qty_a_pedir  = _safe_float(rec.get('qty_compra_cd', 0.0), 0.0)
                        if qty_a_pedir <= 0.0:
                            qty_a_pedir = _safe_float(rec.get('purchase_qty_net', 0.0), 0.0)
                        if _safe_float(rec.get('transfer_qty', 0.0), 0.0) <= 0.0:
                            transfer_qty = 0.0
                        if not supply_src or supply_src == 'no_action':
                            supply_src   = 'buy_only'
                        rec['qty_compra_cd_consolidada_local'] = qty_a_pedir
                        qty_a_pedir  = 0.0
                        solo_cd      = False
                    elif buy_action == 'transferir_desde_cd':
                        qty_a_pedir = 0.0
                    elif buy_action == RETURN_TO_CD_ACTION_SAFE:
                        qty_a_pedir  = 0.0
                        # Retorno a CD usa el mismo campo operativo de documentos:
                        # x_studio_qty_transferir. No se usa x_studio_qty_retorno_cd.
                        transfer_qty = qty_retorno_cd
                        if not supply_src or supply_src == 'no_action':
                            supply_src = SUPPLY_RETURN_CD_SAFE
                    elif buy_action != 'reponer_ahora':
                        qty_a_pedir  = 0.0
                        transfer_qty = 0.0

                    transfer_qty = _round_units(transfer_qty)
                    qty_a_pedir  = _ceil_units(qty_a_pedir)
                    qty_retorno_cd = _round_units(qty_retorno_cd)

                    # Si el motor detecto bajo stock pero la politica caja-o-esperar
                    # decidio no comprar nada, no debe quedar como reponer_ahora.
                    # Esto evita lineas operativas tipo "compra_sala" con qty=0.
                    if buy_action == 'reponer_ahora' and qty_a_pedir <= 0.0 and transfer_qty <= 0.0:
                        buy_action = 'no_comprar_esta_semana'
                        supply_src = 'no_action'
                        solo_cd = False
                        _zero_qty_action_cleanup = True

                    qty_a_pedir_cajas = (qty_a_pedir / moq) if moq and moq > 0.0 else 0.0

                    sobrestock_moq       = max(qty_a_pedir - max(_safe_float(rec.get('qty_neta_pre_central'), 0.0) - transfer_qty, 0.0), 0.0)
                    valor_reponer        = qty_a_pedir * purchase_price_cash_unit
                    valor_orden_compra   = qty_a_pedir * purchase_price_cash_unit
                    valor_sobrestock_moq = sobrestock_moq * purchase_price_cash_unit

                    if buy_action == 'transferir_desde_cd':
                        valor_orden_compra   = 0.0
                        sobrestock_moq       = 0.0
                        valor_sobrestock_moq = 0.0
                    elif buy_action == RETURN_TO_CD_ACTION_SAFE:
                        valor_orden_compra   = 0.0
                        sobrestock_moq       = 0.0
                        valor_reponer        = 0.0
                        valor_sobrestock_moq = 0.0
                    elif buy_action != 'reponer_ahora' and buy_action != 'compra_cd':
                        sobrestock_moq       = 0.0
                        valor_reponer        = 0.0
                        valor_orden_compra   = 0.0
                        valor_sobrestock_moq = 0.0

                    decision_parts = []
                    if buy_action == 'compra_cd':
                        decision_parts.append('compra_cd_consolidada_team=%s' % CENTRAL_TEAM_ID)
                        if _safe_float(rec.get('compra_cd_qty_sku_order', 0.0), 0.0) > 0.0:
                            decision_parts.append('compra_cd_sku_order=' + str(round(_safe_float(rec.get('compra_cd_qty_sku_order', 0.0), 0.0), 2)))
                        if _safe_float(rec.get('compra_cd_need_sku_exact', 0.0), 0.0) > 0.0:
                            decision_parts.append('compra_cd_need_exact=' + str(round(_safe_float(rec.get('compra_cd_need_sku_exact', 0.0), 0.0), 2)))
                        if _safe_int(rec.get('compra_cd_origin_lines'), 0) > 0:
                            decision_parts.append('compra_cd_origin_lines=' + str(_safe_int(rec.get('compra_cd_origin_lines'), 0)))
                    if rec.get('decision_reason_pre'):
                        decision_parts.append(rec.get('decision_reason_pre'))
                    if _zero_qty_action_cleanup:
                        decision_parts.append('box_or_wait_no_qty')
                    if rec.get('no_disponible_compra'):
                        decision_parts.append('policy=no_disponible_compra')
                    if meta.get('solo_bodega'):
                        decision_parts.append('policy=solo_bodega')
                    if rec.get('is_phantom_pool'):
                        decision_parts.append('pool=phantom')
                        decision_parts.append('phantom_value=' + ('on' if VALUE_PHANTOM_KITS else 'off'))
                        if rec.get('phantom_block_procurement'):
                            decision_parts.append('phantom_procurement=blocked_parent')
                        if rec.get('kit_component_cost_source'):
                            decision_parts.append('kit_cost_source=' + rec.get('kit_component_cost_source'))
                        if _safe_float(rec.get('kit_component_cost_unit'), 0.0) > 0.0:
                            decision_parts.append('kit_cost=' + str(round(_safe_float(rec.get('kit_component_cost_unit'), 0.0), 2)))
                    if rec.get('is_phantom_child'):
                        decision_parts.append('pool_child=1')
                        decision_parts.append('buy_parent_tmpl=' + str(_safe_int(rec.get('phantom_parent_tmpl_id'), 0)))
                        decision_parts.append('qty_per_parent=' + str(round(_safe_float(rec.get('phantom_qty_per_parent'), 1.0), 4)))
                        if rec.get('phantom_block_procurement'):
                            decision_parts.append('phantom_procurement=blocked_child_buy_parent')
                    if rec.get('pool_parent_demand'):
                        decision_parts.append('pool_parent_demand=1')
                        decision_parts.append('share_for_purchase=1.0')
                    if rec.get('motivo_eliminar'):
                        decision_parts.append('abc_motivo=' + rec.get('motivo_eliminar'))
                    if rec.get('is_top_cash'):
                        decision_parts.append('top_cash=1')
                    if rec.get('is_cigarros'):
                        decision_parts.append('cat=cigarros')
                        decision_parts.append('cigar_safety_mult=' + str(round(CIGARROS_SAFETY_MULT, 3)))
                        decision_parts.append('cigar_display_mult=' + str(round(CIGARROS_DISPLAY_MULT, 3)))
                    if _safe_float(rec.get('display_stock_units'), 0.0) > 0.0:
                        decision_parts.append('display_stock=' + str(round(_safe_float(rec.get('display_stock_units'), 0.0), 2)))
                    if _safe_float(rec.get('safety_factor_used'), 0.0) > 0.0:
                        decision_parts.append('z=' + str(round(_safe_float(rec.get('safety_factor_used'), 0.0), 2)))
                        decision_parts.append('sigma=' + str(round(_safe_float(rec.get('sigma_week'), 0.0), 3)))
                    # Auditoria payment_term por proveedor.
                    # Solo loguear cuando el techo del SKU difiere del global.
                    if (not meta.get('solo_bodega')):
                        _pds = _safe_float(rec.get('payment_days_sku'), PAYMENT_DAYS)
                        if abs(_pds - PAYMENT_DAYS) > 0.1:
                            decision_parts.append('pay_days_supplier=' + str(int(_pds)))
                            decision_parts.append('fcw=' + str(round(_safe_float(rec.get('financial_ceiling_sku'), 0.0), 2)))
                    decision_parts.append('fwd=' + (rec.get('fwd_source') or 'missing'))
                    decision_parts.append('period_w=' + str(round(_safe_float(rec.get('period_weeks'), 0.0), 2)))
                    decision_parts.append('lead_w=' + str(round(_safe_float(rec.get('lead_weeks'), 0.0), 2)))
                    if SMART_MOQ_ROUNDING:
                        decision_parts.append('rounding=box_or_wait_global')
                    src = rec.get('supply_source') or 'no_action'
                    if buy_action == RETURN_TO_CD_ACTION_SAFE:
                        src = SUPPLY_RETURN_CD_SAFE
                    if central_enabled:
                        decision_parts.append('supply=' + src)
                    else:
                        if buy_action == 'reponer_ahora':
                            decision_parts.append('supply=buy_only_no_central')
                        elif buy_action == RETURN_TO_CD_ACTION_SAFE:
                            decision_parts.append('supply=' + SUPPLY_RETURN_CD_SAFE)
                    decision_reason_full = ' | '.join(decision_parts)

                    # ── [NUEVO v9.1.39+GMROI] Indicadores de priorización ──────────────
                    # gmroi_reponer: margen semanal recuperado por peso invertido en reponer.
                    #   Fuente de costo: x_margen_por_producto_ (costo_oh con ILA compra).
                    #   Fuente de pvp: precio_neto_unit del mismo modelo (neto sin IVA venta).
                    #   Fallback: purchase_price_cash_unit si no hay dato en modelo de margen.
                    # rotacion_por_peso: proxy sin margen, siempre calculable.
                    # Ambos son 0.0 si no hay orden de compra (valor_orden_compra == 0).
                    # --------------------------------------------------------------------
                    _costo_oh_sku   = costo_oh_map.get(tid) or purchase_price_cash_unit
                    _pvp_neto_sku   = pvp_neto_map.get(tid, 0.0)
                    _margin_pct_sku = margin_pct_map.get(tid, 0.0)

                    if _pvp_neto_sku > 0.0 and _costo_oh_sku > 0.0:
                        # Caso principal: tenemos pvp_neto real del modelo de margen
                        _margen_unit_sku = max(_pvp_neto_sku - _costo_oh_sku, 0.0)
                    elif 0.0 < _margin_pct_sku < 1.0 and _costo_oh_sku > 0.0:
                        # Caso fallback: reconstruir desde margin_pct
                        # margin_pct = margen/pvp_neto => pvp = costo/(1-mp) => margen = pvp*mp
                        _pvp_est         = _costo_oh_sku / (1.0 - _margin_pct_sku)
                        _margen_unit_sku = _pvp_est * _margin_pct_sku
                    else:
                        _margen_unit_sku = 0.0

                    _margen_semanal_sku = demanda_semanal * _margen_unit_sku
                    _gmroi_reponer      = (_margen_semanal_sku / valor_orden_compra) if valor_orden_compra > 0.0 else 0.0
                    _rot_por_peso       = (demanda_semanal / valor_orden_compra)     if valor_orden_compra > 0.0 else 0.0
                    # ── fin bloque GMROI ─────────────────────────────────────────────

                    # ── [NUEVO v9.1.57] Venta bruta estimada semanal ─────────────────
                    # Precio bruto unitario: product.template.list_price.
                    # Cantidad estimada: demanda_semanal redondeada a entero.
                    # Monto: precio bruto unitario * demanda estimada entera.
                    _pvp_bruto_sku = _safe_float(meta.get('list_price'), 0.0)
                    _demanda_estimada_entera = _round_units(demanda_semanal)
                    _venta_bruta_estimada = _pvp_bruto_sku * _demanda_estimada_entera
                    # ── fin bloque venta bruta estimada ───────────────────────────────

                    # ── [v9.1.71] Compra mensual estimada (presupuesto operativo) ────
                    # Reemplaza la formula financiera teorica de v9.1.68 por una proyeccion
                    # operativa que refleja lo que el plan_de_compra mandaria a comprar
                    # durante el mes corriendo semanalmente.
                    #
                    # Logica:
                    #   compra_w1   = unidades que el plan ya manda esta semana
                    #                 (qty_a_pedir local OR aporte a compra_cd consolidada).
                    #   demanda_mes = demanda_semanal * MONTH_REMAINING_WEEKS
                    #   stock_disp  = stock_proyectado (= stock_effective + stock_pedido_total)
                    #                 Incluye OC/transferencias abiertas porque los proveedores
                    #                 nacionales entregan en dias, no semanas.
                    #                 (lead_weeks del FWD es PERIODICIDAD de compra, NO tiempo de
                    #                  entrega del proveedor.)
                    #   gap_residual= max(demanda_mes - stock_disp - compra_w1, 0)
                    #   total_units = compra_w1 + gap_residual
                    #   monto       = total_units * purchase_price_cash_unit
                    #
                    # Casos forzados a 0 (no presupuestar):
                    #   - phantom_block_procurement: SKU bloqueado por politica phantom.
                    #     En v9.1.78 normalmente corresponde a hijo/componente bloqueado
                    #     porque compra el padre del pool.
                    #   - no_disponible_compra: productos a descatalogar. (v9.1.70)
                    #   - congelar_compra / liquidar / retorno_a_cd: no generan caja de compra.
                    #   - box_or_wait_no_qty: el motor detecto necesidad, pero la politica
                    #     de caja-o-esperar decidio no comprar caja esta semana.
                    #
                    # Casos especiales en el calculo:
                    #   - 'compra_cd': qty_a_pedir local fue movido a la fila CD y seteado a
                    #     0 en la linea local. Para presupuesto mensual usamos
                    #     qty_compra_cd_consolidada_local que guarda el aporte real.
                    #   - 'transferir_desde_cd': qty_a_pedir local = 0 (reposicion desde
                    #     stock interno). compra_w1 = transfer_qty pero se descuenta del
                    #     total final porque NO es compra al proveedor.
                    #   - 'congelar_compra' / 'liquidar': W1=0; gap=0 si stock cubre demanda.
                    #
                    # No afecta qty_a_pedir, OC, transferencias, MOQ. Solo informa caja.
                    if (
                        rec.get('phantom_block_procurement')
                        or rec.get('no_disponible_compra')
                        or _zero_qty_action_cleanup
                        or buy_action == NO_DISP_ACTION_SAFE
                        or buy_action == 'compra_cd'
                        or buy_action == 'congelar_compra'
                        or buy_action == 'liquidar'
                        or buy_action == RETURN_TO_CD_ACTION_SAFE
                    ):
                        # compra_cd: el presupuesto mensual se calcula UNA VEZ a nivel
                        # SKU-red en la fila CD (vals_cd), no por local. Acumular aqui
                        # generaria double counting cuando varios locales del pool
                        # comparten la misma compra fisica consolidada en bodega central.
                        _compra_mensual_units = 0.0
                        _compra_mensual_estimada = 0.0
                    else:
                        if buy_action == 'compra_cd':
                            _compra_w1_units = _safe_float(
                                rec.get('qty_compra_cd_consolidada_local', 0.0), 0.0
                            )
                        elif buy_action == 'transferir_desde_cd':
                            # Stock disponible local = stock_proyectado + transferencia
                            # No hay compra externa W1, pero sigue habiendo demanda mensual
                            _compra_w1_units = transfer_qty
                        else:
                            _compra_w1_units = qty_a_pedir
                        _demanda_mes_units = max(demanda_semanal * MONTH_REMAINING_WEEKS, 0.0)
                        _gap_residual_units = max(
                            _demanda_mes_units - stock_proyectado - _compra_w1_units,
                            0.0
                        )
                        _compra_mensual_units = _compra_w1_units + _gap_residual_units
                        if buy_action == 'transferir_desde_cd':
                            # Transferencias internas no son compra al proveedor - se descuenta
                            _compra_mensual_units = max(_compra_mensual_units - transfer_qty, 0.0)
                        _compra_mensual_estimada = _compra_mensual_units * purchase_price_cash_unit
                    # ── fin compra mensual estimada ───────────────────────────────────

                    # ── [NUEVO v9.1.68] Venta bruta mensual estimada ─────────────────
                    # Campo de validacion: permite cruzar compra estimada vs venta esperada.
                    # Fórmula: demanda_semanal * MONTH_REMAINING_WEEKS * pvp_bruto_sku
                    # Usa demanda_semanal float (NO demanda_estimada_entera) para evitar
                    # error de redondeo acumulado en SKUs de alta rotacion.
                    # Mismo MONTH_REMAINING_WEEKS que compra_mensual → coherencia garantizada.
                    # Referencia externa: presupuesto real ~ estimado / 1.14
                    #   (gap = list_price catalogo vs venta real con descuentos).
                    _venta_bruta_mensual_estimada = (
                        demanda_semanal * MONTH_REMAINING_WEEKS * _pvp_bruto_sku
                    )
                    # ── fin venta bruta mensual estimada ─────────────────────────────

                    vals = {
                        'x_name':                              'STOCK LOCAL T%s · PT%s' % (team_id, tid),
                        'x_studio_company_id':                 company.id,
                        'x_studio_currency_id':                currency.id,
                        'x_studio_fecha_1':                    snapshot_date,
                        'x_studio_product_id':                 tid,
                        'x_studio_team_id':                    team_id,
                        'x_studio_categ_id':                   meta.get('categ_id') or False,
                        'x_studio_proveedor_id':               rec.get('supplier_id') or False,

                        'x_studio_abcxyz':                     rec.get('abcxyz') or '',
                        'x_studio_importancia_abc':            rec.get('importancia_abc') or False,
                        'x_studio_rank_abcxyz':                _safe_int(rec.get('rank_abcxyz'), 0),

                        'x_studio_stock_real':                 stock_real,
                        'x_studio_stock_effective':            stock_effective,
                        'x_studio_stock_pedido_compra':        stock_pedido_compra,
                        'x_studio_stock_pedido_transfer':      stock_pedido_transfer,
                        'x_studio_stock_pedido_total':         stock_pedido_total,
                        'x_studio_stock_proyectado':           stock_proyectado,
                        'x_studio_demanda_semanal':            demanda_semanal,
                        'x_studio_demanda_estimada_entera':    _demanda_estimada_entera,
                        'x_studio_pvp_bruto_sku':              _pvp_bruto_sku,
                        'x_studio_venta_bruta_estimada':       _venta_bruta_estimada,

                        'x_studio_cover_weeks':                _safe_float(rec.get('cover_weeks'), 0.0),
                        'x_studio_cover_label':                rec.get('cover_label') or '',

                        'x_studio_reorder_target_weeks':       _safe_float(rec.get('reorder_target_weeks'), 0.0),
                        'x_studio_target_units':               target_units,
                        'x_studio_target_stat_units':          _safe_float(rec.get('target_units_stat'), 0.0),
                        'x_studio_display_stock_units':        _safe_float(rec.get('display_stock_units'), 0.0),
                        'x_studio_is_top_cash':                bool(rec.get('is_top_cash')),
                        'x_studio_safety_factor_used':         _safe_float(rec.get('safety_factor_used'), 0.0),
                        'x_studio_venta_bruta_week_est_raw':   _safe_float(rec.get('venta_bruta_week_est_raw'), 0.0),
                        'x_studio_over_target_units':          over_target_units,

                        'x_studio_purchase_price_cash_unit':   purchase_price_cash_unit,
                        'x_studio_price_cash_source':          rec.get('price_cash_source') or 'none',
                        'x_studio_stock_value_cash_physical':  _safe_float(rec.get('stock_value_cash_physical'), 0.0),
                        'x_studio_stock_value_cash_effective': _safe_float(rec.get('stock_value_cash_effective'), 0.0),
                        'x_studio_over_target_value_cash':     _safe_float(rec.get('over_target_value_cash'), 0.0),

                        'x_studio_buy_action':                 buy_action,
                        'x_studio_decision_reason':            decision_reason_full,
                        'x_studio_severity':                   _safe_int(rec.get('severity'), 0),
                        'x_studio_importancia':                rec.get('short_state') or 'ok',

                        'x_studio_share_of_pool':              _safe_float(rec.get('share_of_pool'), 1.0),
                        'x_studio_cob_extra_weeks':            _safe_float(rec.get('cob_extra_weeks'), 0.0),
                        'x_studio_rango_sobrestock':           rec.get('rango_sobrestock') or 'sin_exceso',
                        'x_studio_valor_reponer':              valor_reponer,
                        'x_studio_qty_a_pedir':                qty_a_pedir,
                        'x_studio_qty_a_pedir_cajas':          qty_a_pedir_cajas,
                        'x_studio_valor_orden_compra':         valor_orden_compra,
                        'x_studio_compra_mensual_estimada':    _compra_mensual_estimada,
                        'x_studio_venta_bruta_mensual_estimada': _venta_bruta_mensual_estimada,
                        'x_studio_sobrestock_moq':             sobrestock_moq,
                        'x_studio_mu_week':                    _safe_float(rec.get('mu_week'), 0.0),
                        'x_studio_sigma_week':                 _safe_float(rec.get('sigma_week'), 0.0),
                        'x_studio_lead_weeks':                 _safe_float(rec.get('lead_weeks'), 0.0),
                        'x_studio_moq':                        moq,
                        'x_studio_safety_stock_units':         _safe_float(rec.get('safety_stock_units'), 0.0),
                        'x_studio_banda_actual':               _normalize_banda_actual(rec.get('banda_actual')),

                        # Opcionales central
                        'x_studio_stock_central':              central_stock_total,
                        'x_studio_qty_transferir':             transfer_qty,
                        'x_studio_supply_source':              supply_src or 'none',

                        # ── [NUEVO v9.1.39+GMROI] ────────────────────────────────────
                        # Indicadores de priorización con restricción de caja.
                        # Requieren campos Studio tipo Float en x_analisis_de_stock:
                        #   x_studio_gmroi_reponer     | GMROI Reposición
                        #   x_studio_rotacion_por_peso | Rotación / Peso Invertido
                        #   x_studio_margen_unit       | Margen Unit. (OH)
                        #   x_studio_costo_oh_sku      | Costo OH (desde Margen)
                        #   x_studio_pvp_neto_sku      | PVP Neto (desde Margen)
                        # gmroi_reponer = 0 si no hay orden de compra o sin historial de margen.
                        # rotacion_por_peso = 0 si no hay orden de compra.
                        # Filtrar gmroi_reponer > 0 para rankings de reposición.
                        'x_studio_gmroi_reponer':              _gmroi_reponer,
                        'x_studio_rotacion_por_peso':          _rot_por_peso,
                        'x_studio_margen_unit':                _margen_unit_sku,
                        'x_studio_costo_oh_sku':               _costo_oh_sku,
                        'x_studio_pvp_neto_sku':               _pvp_neto_sku,
                        # ── fin campos GMROI ─────────────────────────────────────────
                    }

                    if fields_map.get('x_studio_motivo_eliminar'):
                        vals['x_studio_motivo_eliminar'] = rec.get('motivo_eliminar') or ''

                    if fields_map.get('x_studio_periodo_repos_weeks'):
                        vals['x_studio_periodo_repos_weeks'] = _safe_float(rec.get('period_weeks'), 0.0)
                    if fields_map.get('x_studio_warehouse_id'):
                        vals['x_studio_warehouse_id'] = rec.get('warehouse_id') or False
                    if fields_map.get('x_studio_stock_root_location_id'):
                        vals['x_studio_stock_root_location_id'] = rec.get('root_location_id') or False
                    if fields_map.get('x_studio_stock_source_mode'):
                        vals['x_studio_stock_source_mode'] = rec.get('stock_source_mode') or ''
                    # Trazabilidad OC/picking que disparan stock_pedido.
                    if fields_map.get('x_studio_oc_pendientes'):
                        vals['x_studio_oc_pendientes'] = rec.get('oc_pendientes_txt') or ''

                    vals = _filter_vals(vals, fields_map)
                    batch.append(vals)

                    if len(batch) >= BATCH_SIZE:
                        _anal_create(batch)
                        created += len(batch)
                        batch = []

                # Filas pseudo-sucursal Bodega Central (team analitico)
                central_batch = []
                for tid in sorted(central_team_map.keys()):
                    c = central_team_map.get(tid) or {}
                    meta = tmpl_meta.get(tid) or {}
                    moq = max(_safe_float(c.get('moq'), 1.0), 1.0)
                    qty_a_pedir = (_smart_moq_box_or_wait(_safe_float(c.get('qty_a_pedir'), 0.0), moq, _safe_float(c.get('stock_proyectado'), 0.0), 0.0, _safe_float(c.get('qty_a_pedir'), 0.0), 1.0, '', True) if SMART_MOQ_ROUNDING else _ceil_moq(_safe_float(c.get('qty_a_pedir'), 0.0), moq))
                    qty_transferir = _round_units(_safe_float(c.get('qty_transferir'), 0.0))
                    qty_retorno_cd = _round_units(_safe_float(c.get('qty_retorno_cd'), 0.0))
                    qty_a_pedir_cajas = (qty_a_pedir / moq) if moq and moq > 0.0 else 0.0
                    stock_real = _safe_float(c.get('stock_real'), 0.0)
                    stock_effective = _safe_float(c.get('stock_effective'), 0.0)
                    stock_pedido_compra = _safe_float(c.get('stock_pedido_compra'), 0.0)
                    stock_pedido_transfer = _safe_float(c.get('stock_pedido_transfer'), 0.0)
                    stock_pedido_total = _safe_float(c.get('stock_pedido_total'), 0.0)
                    stock_proyectado = _safe_float(c.get('stock_proyectado'), stock_real + stock_pedido_total)
                    purchase_price_cash_unit = _safe_float(c.get('purchase_price_cash_unit'), 0.0)
                    valor_orden_compra = qty_a_pedir * purchase_price_cash_unit
                    valor_reponer = valor_orden_compra
                    pvp_bruto_sku = _safe_float(meta.get('list_price'), 0.0)
                    demanda_estimada_entera = _safe_float(c.get('demanda_estimada_entera'), 0.0)
                    venta_bruta_estimada = _safe_float(c.get('venta_bruta_estimada'), 0.0)
                    buy_action = 'compra_cd' if qty_a_pedir > 0.0 else 'no_comprar_esta_semana'
                    supply_source = 'buy_only' if qty_a_pedir > 0.0 else 'no_action'
                    decision_reason_full = 'central_team=1 | team_id=%s | cd_stock=1 | cd_pedido_total=%s | cd_proyectado=%s' % (
                        CENTRAL_TEAM_ID,
                        round(stock_pedido_total, 2),
                        round(stock_proyectado, 2),
                    )
                    if _safe_float(c.get('demanda_semanal_origen_cd'), 0.0) > 0.0:
                        decision_reason_full += ' | cd_demanda_origen=' + str(round(_safe_float(c.get('demanda_semanal_origen_cd'), 0.0), 2))
                    if _safe_float(c.get('venta_bruta_estimada'), 0.0) > 0.0:
                        decision_reason_full += ' | cd_venta_bruta_est=' + str(round(_safe_float(c.get('venta_bruta_estimada'), 0.0), 2))
                    if bool(c.get('solo_bodega_cd_replenish')):
                        decision_reason_full += ' | solo_bodega_cd_replenish=1'
                        decision_reason_full += ' | cd_target_w=' + str(round(_safe_float(c.get('cd_target_weeks'), 0.0), 3))
                        decision_reason_full += ' | cd_target_units=' + str(round(_safe_float(c.get('cd_target_units'), 0.0), 2))
                        decision_reason_full += ' | cd_mu_red=' + str(round(_safe_float(c.get('cd_mu_red'), 0.0), 2))
                        decision_reason_full += ' | cd_sigma_red=' + str(round(_safe_float(c.get('cd_sigma_red'), 0.0), 3))
                        decision_reason_full += ' | cd_safety=' + str(round(_safe_float(c.get('cd_safety_units'), 0.0), 2))
                        decision_reason_full += ' | cd_z=' + str(round(_safe_float(c.get('cd_z'), 0.0), 2))
                        decision_reason_full += ' | cd_qty_neta=' + str(round(_safe_float(c.get('cd_qty_neta'), 0.0), 2))
                    if bool(kit_components_tmpl.get(tid)):
                        decision_reason_full += ' | pool=phantom | phantom_value=' + ('on' if VALUE_PHANTOM_KITS else 'off')
                        if PHANTOM_PROCUREMENT_MODE == 'block_parent':
                            decision_reason_full += ' | phantom_procurement=blocked_parent'
                        _kc, _ks = _kit_component_cost_for_tmpl(tid)
                        if _ks:
                            decision_reason_full += ' | kit_cost_source=' + _ks
                        if _kc > 0.0:
                            decision_reason_full += ' | kit_cost=' + str(round(_kc, 2))

                    # ── [v9.1.72] Compra mensual estimada en fila CD ──────────────────
                    # Calculo a nivel SKU-red (no por local) para evitar double counting.
                    # Se computa SOLO si esta fila CD origina compras consolidadas
                    # (qty_a_pedir > 0 OR demanda_semanal_origen_cd > 0).
                    #
                    # Logica:
                    #   demanda_mes_cd = demanda_semanal_origen_cd * MONTH_REMAINING_WEEKS
                    #     (suma de demandas de los locales que estan en compra_cd para
                    #      este SKU)
                    #   stock_red_cd  = stock_proyectado_cd + stock_proyectado_origen_cd
                    #     (stock CD + suma del stock proyectado de los locales del pool)
                    #   gap_residual_cd = max(demanda_mes_cd - stock_red_cd - qty_a_pedir, 0)
                    #   compra_mensual_cd = (qty_a_pedir + gap_residual_cd) * precio
                    #
                    # Excluye phantom_block_procurement: el padre no se compra, los
                    # componentes presupuestan en sus propias filas locales.
                    _phantom_blocked_cd = bool(
                        kit_components_tmpl.get(tid)
                        and PHANTOM_PROCUREMENT_MODE == 'block_parent'
                    )
                    _demanda_origen_cd = _safe_float(c.get('demanda_semanal_origen_cd'), 0.0)
                    _stock_proy_origen_cd = _safe_float(c.get('stock_proyectado_origen_cd'), 0.0)
                    if _phantom_blocked_cd or (qty_a_pedir <= 0.0 and _demanda_origen_cd <= 0.0):
                        _compra_mensual_estimada_cd = 0.0
                    else:
                        _demanda_mes_cd = max(_demanda_origen_cd * MONTH_REMAINING_WEEKS, 0.0)
                        _stock_red_cd = stock_proyectado + _stock_proy_origen_cd
                        _gap_residual_cd = max(_demanda_mes_cd - _stock_red_cd - qty_a_pedir, 0.0)
                        _compra_mensual_units_cd = qty_a_pedir + _gap_residual_cd
                        _compra_mensual_estimada_cd = _compra_mensual_units_cd * purchase_price_cash_unit
                    # ── fin compra mensual CD ─────────────────────────────────────────
                    vals_cd = {
                        'x_name':                              'STOCK CENTRAL T%s · PT%s' % (CENTRAL_TEAM_ID, tid),
                        'x_studio_company_id':                 company.id,
                        'x_studio_currency_id':                currency.id,
                        'x_studio_fecha_1':                    snapshot_date,
                        'x_studio_product_id':                 tid,
                        'x_studio_team_id':                    CENTRAL_TEAM_ID,
                        'x_studio_categ_id':                   meta.get('categ_id') or False,
                        'x_studio_proveedor_id':               c.get('supplier_id') or False,
                        'x_studio_abcxyz':                     c.get('abcxyz') or '',
                        'x_studio_importancia_abc':            c.get('importancia_abc') or False,
                        'x_studio_rank_abcxyz':                _safe_int(c.get('rank_abcxyz'), 0),
                        'x_studio_stock_real':                 stock_real,
                        'x_studio_stock_effective':            stock_effective,
                        'x_studio_stock_pedido_compra':        stock_pedido_compra,
                        'x_studio_stock_pedido_transfer':      stock_pedido_transfer,
                        'x_studio_stock_pedido_total':         stock_pedido_total,
                        'x_studio_stock_proyectado':           stock_proyectado,
                        'x_studio_demanda_semanal':            0.0,
                        'x_studio_demanda_estimada_entera':    demanda_estimada_entera,
                        'x_studio_pvp_bruto_sku':              pvp_bruto_sku,
                        'x_studio_venta_bruta_estimada':       venta_bruta_estimada,
                        'x_studio_cover_weeks':                999.0,
                        'x_studio_cover_label':                'sin_salida',
                        'x_studio_reorder_target_weeks':       0.0,
                        'x_studio_target_units':               0.0,
                        'x_studio_over_target_units':          0.0,
                        'x_studio_purchase_price_cash_unit':   purchase_price_cash_unit,
                        'x_studio_price_cash_source':          c.get('price_cash_source') or 'none',
                        'x_studio_stock_value_cash_physical':  stock_real * purchase_price_cash_unit,
                        'x_studio_stock_value_cash_effective': stock_effective * purchase_price_cash_unit,
                        'x_studio_over_target_value_cash':     0.0,
                        'x_studio_buy_action':                 buy_action,
                        'x_studio_decision_reason':            decision_reason_full,
                        'x_studio_severity':                   0,
                        'x_studio_importancia':                'ok',
                        'x_studio_share_of_pool':              1.0,
                        'x_studio_cob_extra_weeks':            0.0,
                        'x_studio_rango_sobrestock':           'sin_exceso',
                        'x_studio_valor_reponer':              valor_reponer,
                        'x_studio_qty_a_pedir':                qty_a_pedir,
                        'x_studio_qty_a_pedir_cajas':          qty_a_pedir_cajas,
                        'x_studio_valor_orden_compra':         valor_orden_compra,
                        'x_studio_compra_mensual_estimada':    _compra_mensual_estimada_cd,
                        # venta_bruta_mensual_estimada en CD = 0 para evitar double counting.
                        # La venta ya se reporta integramente en las filas locales (cada local
                        # tiene su demanda y su pvp). Sumar en CD duplica el monto de la red.
                        'x_studio_venta_bruta_mensual_estimada': 0.0,
                        'x_studio_sobrestock_moq':             0.0,
                        'x_studio_mu_week':                    0.0,
                        'x_studio_sigma_week':                 0.0,
                        'x_studio_lead_weeks':                 0.0,
                        'x_studio_moq':                        moq,
                        'x_studio_safety_stock_units':         0.0,
                        'x_studio_banda_actual':               _normalize_banda_actual(c.get('banda_actual')),
                        'x_studio_stock_central':              stock_real,
                        'x_studio_qty_transferir':             qty_transferir,
                        'x_studio_supply_source':              supply_source,
                        'x_studio_gmroi_reponer':              0.0,
                        'x_studio_rotacion_por_peso':          0.0,
                        'x_studio_margen_unit':                0.0,
                        'x_studio_costo_oh_sku':               costo_oh_map.get(tid) or purchase_price_cash_unit,
                        'x_studio_pvp_neto_sku':               pvp_neto_map.get(tid, 0.0),
                    }
                    if fields_map.get('x_studio_stock_source_mode'):
                        vals_cd['x_studio_stock_source_mode'] = 'central'
                    # Trazabilidad OC/picking que disparan stock_pedido en CD.
                    if fields_map.get('x_studio_oc_pendientes'):
                        vals_cd['x_studio_oc_pendientes'] = c.get('oc_pendientes_txt') or ''
                    vals_cd = _filter_vals(vals_cd, fields_map)
                    central_batch.append(vals_cd)
                    if len(central_batch) >= BATCH_SIZE:
                        _anal_create(central_batch)
                        created += len(central_batch)
                        central_batch = []
                if central_batch:
                    _anal_create(central_batch)
                    created += len(central_batch)

                try:
                    log(
                        '%s | purged=%s | created=%s | teams=%s | local_hit=%s | global_hit=%s | fwd_miss=%s | central_on=%s | central_alloc_lines=%s | central_alloc_units=%.2f | snapshot=%s | smart_moq=%s' % (
                            VERSION_ID, purge_count, created, len(valid_team_ids), local_hit, global_hit, fwd_miss,
                            ('Y' if central_enabled else 'N'), central_alloc_lines, central_alloc_units, snapshot_date,
                            ('Y' if SMART_MOQ_ROUNDING else 'N')
                        ),
                        level='info'
                    )
                except Exception:
                    pass

                action = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': VERSION_ID,
                        'message': (
                            'purged=%s | created=%s | teams=%s | local_hit=%s | global_hit=%s | fwd_miss=%s | central_on=%s | alloc_lines=%s | alloc_u=%.1f | snapshot=%s'
                        ) % (
                            purge_count, created, len(valid_team_ids), local_hit, global_hit, fwd_miss,
                            ('Y' if central_enabled else 'N'), central_alloc_lines, central_alloc_units, snapshot_date
                        ),
                        'type': 'success',
                        'sticky': False,
                    }
                }

    finally:
        env.cr.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
        