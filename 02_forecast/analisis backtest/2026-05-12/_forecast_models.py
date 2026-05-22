"""
Modelos de forecast canonicos en Python puro.

Implementaciones segun papers originales:
  - Holt (1957): linear exponential smoothing (level + trend)
  - Winters (1960): triple exponential smoothing (level + trend + seasonal)
  - Croston (1972): intermittent demand
  - Syntetos-Boylan (2005): SBA, Croston con correccion de sesgo

Sin dependencias externas. Para portar a HM-SI runner.

Tests canonicos al final reproducen ejemplos del paper.
"""


def holt_doble(history, alpha=0.2, beta=0.1, h=1):
    """Holt linear exponential smoothing (1957).

    L_t = alpha * y_t + (1-alpha) * (L_{t-1} + T_{t-1})
    T_t = beta  * (L_t - L_{t-1}) + (1-beta) * T_{t-1}
    Forecast(h): L_t + h * T_t

    Args:
      history: lista de cantidades semanales (oldest first).
      alpha: smoothing del nivel (0..1).
      beta: smoothing de la tendencia (0..1).
      h: pasos adelante.

    Returns:
      float forecast en t+h. Si history vacio o invalido, retorna 0.0.
    """
    n = len(history)
    if n == 0:
        return 0.0
    if n == 1:
        return max(0.0, history[0])

    # Inicializacion estandar: L0 = y0, T0 = y1 - y0
    L = float(history[0])
    T = float(history[1] - history[0]) if n >= 2 else 0.0

    for t in range(1, n):
        y = float(history[t])
        L_prev = L
        L = alpha * y + (1.0 - alpha) * (L + T)
        T = beta * (L - L_prev) + (1.0 - beta) * T

    f = L + h * T
    return max(0.0, f)


def holt_winters(history, m=52, alpha=0.2, beta=0.1, gamma=0.15, h=1):
    """Triple exponential smoothing multiplicativo (Winters 1960).

    L_t = alpha * (y_t / S_{t-m}) + (1-alpha) * (L_{t-1} + T_{t-1})
    T_t = beta  * (L_t - L_{t-1}) + (1-beta) * T_{t-1}
    S_t = gamma * (y_t / L_t) + (1-gamma) * S_{t-m}
    Forecast(h): (L_t + h*T_t) * S_{t-m+h}

    Args:
      history: lista de cantidades semanales (oldest first), requiere >= 2m.
      m: periodo estacional (52 para weekly anual).
      alpha, beta, gamma: smoothing del nivel, tendencia, estacional.
      h: pasos adelante.

    Returns:
      float forecast. Si len(history) < 2m, fallback a holt_doble automatico.
    """
    n = len(history)
    if n < 2 * m:
        return holt_doble(history, alpha=alpha, beta=beta, h=h)

    # Inicializacion seasonal con primer ciclo
    L = sum(history[:m]) / m
    T = (sum(history[m:2*m]) / m - sum(history[:m]) / m) / m
    S = [0.0] * m
    for i in range(m):
        S[i] = (history[i] / L) if L > 0 else 1.0

    # Loop principal
    for t in range(n):
        y = float(history[t])
        idx = t % m
        L_prev = L
        S_prev = S[idx]
        if S_prev <= 0:
            S_prev = 1.0
        L = alpha * (y / S_prev) + (1.0 - alpha) * (L + T)
        T = beta * (L - L_prev) + (1.0 - beta) * T
        S[idx] = (gamma * (y / L) + (1.0 - gamma) * S_prev) if L > 0 else S_prev

    idx_future = (n - 1 + h) % m
    f = (L + h * T) * S[idx_future]
    return max(0.0, f)


def croston(history, alpha=0.1, h=1):
    """Croston (1972) — demanda intermitente.

    Si y_t > 0:
        z_t = alpha * y_t + (1-alpha) * z_{t-1}    (tamano esperado)
        p_t = alpha * q + (1-alpha) * p_{t-1}       (intervalo esperado)
        q = 1
    Si y_t == 0:
        z_t = z_{t-1}, p_t = p_{t-1}, q += 1

    Forecast: z_t / p_t (constante en h, modelo no proyecta tendencia).

    Args:
      history: lista de cantidades semanales.
      alpha: smoothing (0..1). Croston original sugiere 0.10-0.30.
      h: pasos adelante (no afecta el forecast en Croston puro).

    Returns:
      float forecast = z / p, o 0.0 si no hay demanda positiva.
    """
    n = len(history)
    if n == 0:
        return 0.0

    z = None
    p = None
    q = 0

    for t in range(n):
        y = float(history[t])
        q += 1
        if y > 0:
            if z is None:
                z = y
                p = float(q)
            else:
                z = alpha * y + (1.0 - alpha) * z
                p = alpha * q + (1.0 - alpha) * p
            q = 0

    if z is None or p is None or p <= 0:
        return 0.0
    return z / p


def sba(history, alpha=0.1, h=1):
    """Syntetos-Boylan Approximation (2005).

    Identica a Croston pero corrige sesgo positivo:
      forecast_SBA = (1 - alpha/2) * (z / p)

    El sesgo de Croston es alpha/2 hacia arriba; SBA lo elimina.
    Preferible para inventarios donde sobre-pronosticar genera exceso de stock.
    """
    base = croston(history, alpha=alpha, h=h)
    return (1.0 - alpha / 2.0) * base


def dispatch_forecast(regimen, history, m=52, h=1, return_code=False):
    """Selecciona modelo segun regimen ABCXYZ.

    Mapeo (ver AGENTS.md → Referencias Canonicas → Forecast operativo):
      REG-0  : no_forecast (productos terminales)         -> 0
      REG-1  : A x smooth x mature      (HW alpha=0.20)
      REG-2  : B x smooth x mature      (HW alpha=0.25)
      REG-3  : C x smooth               (HW alpha=0.30 gamma=0.10)
      REG-4  : any x erratic            (HW alpha=0.40 mas reactivo)
      REG-5  : A/B x lumpy              (SBA alpha=0.15)
      REG-6  : C x lumpy                (SBA alpha=0.10)
      REG-7  : intermittent/no_signal   (SBA alpha=0.05)
      REG-8  : seasonal (cualquier abc) (HW alpha=0.20 gamma=0.30, SI dominante)

    Cambio v4.1: REG-6/7 pasaron de Croston a SBA.
    Cambio v4.2: dispatch chequea len(history) >= 2*m antes de llamar HW.
      Si no alcanza, retorna fallback Holt doble con code 'holt_doble_fb_<REG>'
      para que el reporting refleje honestamente el modelo aplicado.

    Si return_code=True, retorna tupla (forecast, model_code).
    """
    if regimen == 'REG-0' or not history:
        return (0.0, 'no_forecast') if return_code else 0.0

    # Regimenes que requieren HW triple
    hw_regimes = ('REG-1', 'REG-2', 'REG-3', 'REG-4', 'REG-8')
    n = len(history)
    if regimen in hw_regimes and n < 2 * m:
        f = holt_doble(history, alpha=0.20, beta=0.10, h=h)
        code = 'holt_doble_fb_' + regimen
        return (f, code) if return_code else f

    if regimen == 'REG-1':
        f, code = holt_winters(history, m=m, alpha=0.20, beta=0.10, gamma=0.15, h=h), 'hw_a020_b010_g015'
    elif regimen == 'REG-2':
        f, code = holt_winters(history, m=m, alpha=0.25, beta=0.10, gamma=0.15, h=h), 'hw_a025_b010_g015'
    elif regimen == 'REG-3':
        f, code = holt_winters(history, m=m, alpha=0.30, beta=0.10, gamma=0.10, h=h), 'hw_a030_b010_g010'
    elif regimen == 'REG-4':
        f, code = holt_winters(history, m=m, alpha=0.40, beta=0.10, gamma=0.15, h=h), 'hw_a040_b010_g015'
    elif regimen == 'REG-5':
        f, code = sba(history, alpha=0.15, h=h), 'sba_a015'
    elif regimen == 'REG-6':
        f, code = sba(history, alpha=0.10, h=h), 'sba_a010'
    elif regimen == 'REG-7':
        f, code = sba(history, alpha=0.05, h=h), 'sba_a005'
    elif regimen == 'REG-8':
        f, code = holt_winters(history, m=m, alpha=0.20, beta=0.05, gamma=0.30, h=h), 'hw_seasonal_a020_g030'
    else:
        f, code = holt_doble(history, alpha=0.20, beta=0.10, h=h), 'holt_doble_fallback'
    return (f, code) if return_code else f


# ======================================================================
# TESTS — reproducen casos canonicos de los papers
# ======================================================================

def _approx(actual, expected, tol=0.05):
    return abs(actual - expected) <= tol


def test_croston_paper_tabla1():
    """Croston (1972) Tabla 1 caso ilustrativo.

    Serie de demanda con intervalos variables. Validar que z y p convergen.
    """
    # Serie: ceros y picos. Tras procesar, z (size) ~ 3.33, p (interval) ~ 3
    serie = [0, 0, 3, 0, 2, 0, 0, 5]
    # Inicializacion: en t=2 entra primer dato no-cero z=3, p=3
    # t=4 y=2, q=2: z = 0.1*2 + 0.9*3 = 2.9, p = 0.1*2 + 0.9*3 = 2.9
    # t=7 y=5, q=3: z = 0.1*5 + 0.9*2.9 = 3.11, p = 0.1*3 + 0.9*2.9 = 2.91
    f = croston(serie, alpha=0.1)
    # Forecast = 3.11 / 2.91 ~ 1.069
    assert _approx(f, 1.069, tol=0.02), f"Croston paper falla: got {f}, expected ~1.07"
    return True


def test_sba_corrige_sesgo():
    """SBA debe ser menor que Croston por factor (1 - alpha/2)."""
    serie = [0, 0, 3, 0, 2, 0, 0, 5]
    f_croston = croston(serie, alpha=0.1)
    f_sba = sba(serie, alpha=0.1)
    factor = 1.0 - 0.1 / 2.0   # 0.95
    expected_sba = f_croston * factor
    assert _approx(f_sba, expected_sba, tol=0.001), f"SBA factor falla: {f_sba} vs {expected_sba}"
    return True


def test_holt_doble_tendencia_pura():
    """Serie con tendencia lineal pura debe ser pronosticada exactamente."""
    # Serie: y_t = 10 + 2*t para t=0..9
    serie = [10 + 2 * t for t in range(10)]
    # Tras 10 puntos con tendencia +2 estable, forecast t=10 deberia ~ 30
    f = holt_doble(serie, alpha=0.3, beta=0.2, h=1)
    assert _approx(f, 30.0, tol=2.0), f"Holt tendencia falla: got {f}, expected ~30"
    return True


def test_holt_winters_recupera_seasonal():
    """Serie con estacionalidad pura debe recuperar SI."""
    # 3 ciclos de 4 semanas: base 10, multiplicador estacional [1.5, 0.5, 1.0, 1.0]
    pattern = [15, 5, 10, 10]
    serie = pattern * 3   # 12 semanas
    # Con m=4 y 3 ciclos, debe recuperar el patron
    # Forecast en t=12 (semana 13, idx 0 del ciclo) debe ~ 15
    f = holt_winters(serie, m=4, alpha=0.3, beta=0.05, gamma=0.5, h=1)
    assert _approx(f, 15.0, tol=2.0), f"HW seasonal falla: got {f}, expected ~15"
    return True


def test_holt_winters_fallback_corto():
    """Historia < 2m debe degradar a Holt doble silenciosamente."""
    serie = [10, 12, 14, 16, 18]   # solo 5 puntos
    f_hw = holt_winters(serie, m=52, alpha=0.3, beta=0.2, h=1)
    f_holt = holt_doble(serie, alpha=0.3, beta=0.2, h=1)
    assert _approx(f_hw, f_holt, tol=0.01), f"Fallback falla: HW={f_hw} Holt={f_holt}"
    return True


def test_dispatch_reg0_zero():
    """REG-0 siempre debe retornar 0."""
    serie = [10, 20, 30]
    assert dispatch_forecast('REG-0', serie) == 0.0
    return True


def test_dispatch_reg7_sba():
    """REG-7 intermittent debe llamar a SBA alpha=0.05 (v4.1: cambio de Croston a SBA)."""
    serie = [0, 0, 3, 0, 2, 0, 0, 5]
    f_dispatch = dispatch_forecast('REG-7', serie, h=1)
    f_sba = sba(serie, alpha=0.05, h=1)
    assert _approx(f_dispatch, f_sba, tol=0.001)
    return True


def test_dispatch_reg6_sba():
    """REG-6 lumpy C debe llamar a SBA alpha=0.10 (v4.1: cambio de Croston a SBA)."""
    serie = [0, 0, 5, 0, 0, 0, 3, 0, 0, 4]
    f_dispatch = dispatch_forecast('REG-6', serie, h=1)
    f_sba = sba(serie, alpha=0.10, h=1)
    assert _approx(f_dispatch, f_sba, tol=0.001)
    return True


def test_dispatch_reg5_sba():
    """REG-5 lumpy A/B debe llamar a SBA con alpha=0.15."""
    serie = [0, 0, 5, 0, 0, 0, 3, 0, 0, 4]
    f_dispatch = dispatch_forecast('REG-5', serie, h=1)
    f_sba = sba(serie, alpha=0.15, h=1)
    assert _approx(f_dispatch, f_sba, tol=0.001)
    return True


def test_sba_strictly_less_than_croston():
    """SBA debe ser estrictamente menor que Croston en cualquier serie con demanda
    positiva (factor 1 - alpha/2 < 1). Validacion del fix v4.1."""
    serie = [0, 0, 3, 0, 2, 0, 0, 5]
    f_croston = croston(serie, alpha=0.10)
    f_sba = sba(serie, alpha=0.10)
    assert f_sba < f_croston, f"SBA debe ser < Croston: SBA={f_sba} Croston={f_croston}"
    assert _approx(f_sba / f_croston, 0.95, tol=0.001), "factor esperado 1 - 0.10/2 = 0.95"
    return True


def test_dispatch_reporta_fallback_honestamente():
    """v4.2: si history corta y regimen pide HW, el code debe ser holt_doble_fb_REG-X.

    Antes del fix v4.2 el dispatcher reportaba 'hw_*' aunque internamente
    cayera al fallback Holt doble. Eso ocultaba que el componente seasonal
    nunca corria.
    """
    # history de 50 puntos, m=52, n < 2*m=104 → debe caer al fallback
    serie = [float(i) for i in range(50)]
    f, code = dispatch_forecast('REG-1', serie, m=52, h=1, return_code=True)
    assert code == 'holt_doble_fb_REG-1', f"Esperado holt_doble_fb_REG-1, got {code}"
    # Y debe coincidir con llamar Holt doble directamente
    f_holt = holt_doble(serie, alpha=0.20, beta=0.10, h=1)
    assert _approx(f, f_holt, tol=0.001), f"Forecast del fallback no calza: {f} vs {f_holt}"
    return True


def test_dispatch_hw_real_con_historia_suficiente():
    """v4.2: con history >= 2*m, debe reportar el HW code real, no fallback."""
    # serie de 120 puntos con patron sintetico (m=52, 2*m=104, asi 120 > 104)
    serie = [float((i % 5) + 10) for i in range(120)]
    f, code = dispatch_forecast('REG-1', serie, m=52, h=1, return_code=True)
    assert code == 'hw_a020_b010_g015', f"Esperado hw_a020_b010_g015, got {code}"
    return True


def test_dispatch_sba_no_afectado_por_fallback():
    """v4.2: SBA y Croston no tienen requirement de 2*m, deben reportar code real."""
    serie = [0, 0, 3, 0, 2, 0, 0, 5]
    f, code = dispatch_forecast('REG-7', serie, m=52, h=1, return_code=True)
    assert code == 'sba_a005', f"REG-7 con history corta debe reportar sba_a005, got {code}"
    return True


def test_serie_vacia():
    """Serie vacia debe retornar 0."""
    assert holt_doble([]) == 0.0
    assert holt_winters([]) == 0.0
    assert croston([]) == 0.0
    assert sba([]) == 0.0
    return True


def test_serie_un_punto():
    """Serie con 1 punto: retorna ese punto (sin tendencia)."""
    assert _approx(holt_doble([5.0]), 5.0)
    return True


def test_solo_ceros():
    """Demanda toda en cero: forecast cero."""
    serie = [0, 0, 0, 0, 0]
    assert croston(serie) == 0.0
    assert sba(serie) == 0.0
    return True


def run_all_tests():
    tests = [
        test_croston_paper_tabla1,
        test_sba_corrige_sesgo,
        test_holt_doble_tendencia_pura,
        test_holt_winters_recupera_seasonal,
        test_holt_winters_fallback_corto,
        test_dispatch_reg0_zero,
        test_dispatch_reg5_sba,
        test_dispatch_reg6_sba,
        test_dispatch_reg7_sba,
        test_sba_strictly_less_than_croston,
        test_dispatch_reporta_fallback_honestamente,
        test_dispatch_hw_real_con_historia_suficiente,
        test_dispatch_sba_no_afectado_por_fallback,
        test_serie_vacia,
        test_serie_un_punto,
        test_solo_ceros,
    ]
    passed = 0
    failed = []
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  OK  {t.__name__}")
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failed.append((t.__name__, f"EXC {type(e).__name__}: {e}"))
            print(f"  ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    if failed:
        print("Failures:")
        for name, msg in failed:
            print(f"  - {name}: {msg}")
        return False
    return True


if __name__ == '__main__':
    print("=" * 70)
    print("Tests modelos canonicos de forecast")
    print("=" * 70)
    ok = run_all_tests()
    print()
    if ok:
        print("Todos los tests pasaron. Modelos listos para integrar al HM-SI runner.")
    else:
        print("Hay fallos. NO integrar hasta resolver.")
