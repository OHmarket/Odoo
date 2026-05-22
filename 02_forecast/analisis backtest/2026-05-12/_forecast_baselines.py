"""
Baselines canonicos para benchmark del backtest.

Cualquier modelo de forecast debe superar al menos al naive forecast
(Box-Jenkins). Si no, no aporta valor.

Baselines implementados (Hyndman & Athanasopoulos 2021, cap. 5):
  - naive(history)            : forecast = ultima observacion
  - seasonal_naive(history,m) : forecast = misma semana ano anterior (lag m)
  - mean_baseline(history)    : forecast = promedio de la historia

Metricas (Hyndman & Koehler 2006):
  - wape(real, fcst)   : weighted absolute percentage error (legacy)
  - bias_pct(real,fcst): bias relativo (legacy)
  - mase(real, fcst, naive_errors): mean absolute scaled error.
    MASE < 1 = mejor que naive; MASE > 1 = peor.

Uso:
  Importar como modulo. No es runner Odoo, es analisis post-backtest.
  Se cruza con el CSV exportado de x_forecast_backtest.
"""


# ======================================================================
# BASELINES
# ======================================================================

def naive(history, h=1):
    """Naive forecast: forecast = ultima observacion (Box-Jenkins).

    Es el suelo absoluto. Cualquier modelo serio debe superarlo en MASE.
    """
    if not history:
        return 0.0
    return max(0.0, float(history[-1]))


def seasonal_naive(history, m=52, h=1):
    """Seasonal naive: forecast = misma semana del ano anterior (lag m).

    El baseline retail estandar. Si tu modelo no supera esto en SKUs
    estacionales, esta perdiendo info gratuita.

    Si history < m, fallback a naive.
    """
    n = len(history)
    if n < m:
        return naive(history, h=h)
    # Forecast h pasos adelante = observacion en t - m + h
    idx = n - m + (h - 1)
    if idx < 0 or idx >= n:
        return naive(history, h=h)
    return max(0.0, float(history[idx]))


def mean_baseline(history, h=1):
    """Forecast = promedio de toda la historia. Util como referencia simple."""
    if not history:
        return 0.0
    return max(0.0, sum(history) / len(history))


# ======================================================================
# METRICAS
# ======================================================================

def wape(real_list, fcst_list):
    """Weighted Absolute Percentage Error.

    WAPE = sum(|y - f|) / sum(|y|)

    Util a nivel agregado (no por fila). Es la metrica que usamos en el
    backtest historico.
    """
    if not real_list or not fcst_list or len(real_list) != len(fcst_list):
        return float('nan')
    num = 0.0
    den = 0.0
    for r, f in zip(real_list, fcst_list):
        num += abs(float(r) - float(f))
        den += abs(float(r))
    return (num / den * 100.0) if den > 0 else float('nan')


def bias_pct(real_list, fcst_list):
    """Bias relativo = sum(real - fcst) / sum(real) * 100.

    Positivo = sub-forecast (el modelo se queda corto).
    Negativo = sobre-forecast.
    """
    if not real_list or not fcst_list or len(real_list) != len(fcst_list):
        return float('nan')
    num = 0.0
    den = 0.0
    for r, f in zip(real_list, fcst_list):
        num += (float(r) - float(f))
        den += abs(float(r))
    return (num / den * 100.0) if den > 0 else float('nan')


def mae(real_list, fcst_list):
    """Mean Absolute Error puntual (no porcentaje)."""
    if not real_list or len(real_list) != len(fcst_list):
        return float('nan')
    n = len(real_list)
    if n == 0:
        return float('nan')
    s = 0.0
    for r, f in zip(real_list, fcst_list):
        s += abs(float(r) - float(f))
    return s / n


def naive_in_sample_mae(history, m=1):
    """MAE in-sample del naive con lag m. Denominador de MASE.

    Hyndman & Koehler (2006): para series no-estacionales m=1 (naive=last obs).
    Para estacionales, m=52 (weekly anual) — usa seasonal naive.
    """
    n = len(history)
    if n <= m:
        return float('nan')
    s = 0.0
    count = 0
    for t in range(m, n):
        s += abs(float(history[t]) - float(history[t - m]))
        count += 1
    return (s / count) if count > 0 else float('nan')


def mase(real_list, fcst_list, history, m=1):
    """Mean Absolute Scaled Error (Hyndman & Koehler 2006).

    MASE = MAE(forecast) / MAE_in_sample(naive_con_lag_m)

    Interpretacion:
      MASE < 1 = mejor que naive
      MASE = 1 = igual que naive
      MASE > 1 = peor que naive

    Args:
      real_list:  cantidades reales del periodo de evaluacion.
      fcst_list:  forecast del periodo de evaluacion.
      history:    serie historica que el modelo vio (para calcular MAE naive).
      m:          lag del naive. m=1 para no-estacional, m=52 para weekly anual.

    Returns:
      float MASE; nan si no se puede calcular.
    """
    mae_fcst = mae(real_list, fcst_list)
    mae_naive = naive_in_sample_mae(history, m=m)
    if mae_naive is None or mae_naive == 0 or mae_naive != mae_naive:  # nan check
        return float('nan')
    return mae_fcst / mae_naive


# ======================================================================
# Validacion contra ejemplo Hyndman
# ======================================================================

def _approx(a, b, tol=0.05):
    return abs(a - b) <= tol


def test_naive_devuelve_ultima_obs():
    assert naive([1, 2, 3, 4, 5]) == 5.0
    return True


def test_seasonal_naive_lag52():
    """Con m=4 y historia de 8 puntos, el seasonal_naive debe devolver el valor a 4 atras."""
    serie = [10, 20, 30, 40, 50, 60, 70, 80]
    # Para h=1, idx = 8 - 4 + 0 = 4 => serie[4] = 50
    assert seasonal_naive(serie, m=4, h=1) == 50.0
    return True


def test_seasonal_naive_fallback_corto():
    """Si len(history) < m, fallback a naive."""
    serie = [1, 2, 3]
    assert seasonal_naive(serie, m=52, h=1) == 3.0
    return True


def test_mase_naive_es_uno():
    """Si el forecast ES el naive (last obs constante), MASE in-sample = 1.

    Construyo serie donde la naive prediction puede medirse:
    historia = [1, 2, 3, 4, 5], real = [6], forecast = naive(5) = 5.
    MAE forecast = |6 - 5| = 1.
    MAE naive in-sample con m=1: promedio de |y_t - y_{t-1}| en historia
                                 = (1+1+1+1)/4 = 1.
    MASE = 1 / 1 = 1.
    """
    historia = [1, 2, 3, 4, 5]
    real = [6]
    forecast = [naive(historia)]
    m = mase(real, forecast, historia, m=1)
    assert _approx(m, 1.0, tol=0.001), f'MASE esperado 1.0, got {m}'
    return True


def test_mase_modelo_perfecto_es_cero():
    historia = [1, 2, 3, 4, 5]
    real = [6]
    forecast = [6]   # oracle
    m = mase(real, forecast, historia, m=1)
    assert _approx(m, 0.0, tol=0.001)
    return True


def test_mase_peor_que_naive():
    historia = [1, 2, 3, 4, 5]
    real = [6]
    forecast = [10]   # error grande
    m = mase(real, forecast, historia, m=1)
    assert m > 1.0, f'forecast peor que naive deberia dar MASE>1, got {m}'
    return True


def test_wape_basico():
    real = [10, 20, 30]
    fcst = [9, 22, 28]
    # abs_err = 1+2+2 = 5; total_real = 60; WAPE = 5/60 = 8.33%
    assert _approx(wape(real, fcst), 8.333, tol=0.01)
    return True


def test_bias_sub_forecast():
    real = [10, 10, 10]
    fcst = [5, 5, 5]   # forecast bajo el real -> bias positivo
    b = bias_pct(real, fcst)
    assert b > 0, f'Sub-forecast deberia dar BIAS > 0, got {b}'
    return True


def run_all_tests():
    tests = [
        test_naive_devuelve_ultima_obs,
        test_seasonal_naive_lag52,
        test_seasonal_naive_fallback_corto,
        test_mase_naive_es_uno,
        test_mase_modelo_perfecto_es_cero,
        test_mase_peor_que_naive,
        test_wape_basico,
        test_bias_sub_forecast,
    ]
    passed = 0
    failed = []
    for t in tests:
        try:
            t()
            passed += 1
            print(f'  OK  {t.__name__}')
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
            print(f'  FAIL {t.__name__}: {e}')
        except Exception as e:
            failed.append((t.__name__, f'EXC {type(e).__name__}: {e}'))
            print(f'  ERR  {t.__name__}: {type(e).__name__}: {e}')
    print(f'\n{passed}/{len(tests)} tests passed')
    return not failed


if __name__ == '__main__':
    print('=' * 70)
    print('Tests baselines + MASE')
    print('=' * 70)
    ok = run_all_tests()
    print()
    if ok:
        print('Listos para usar como benchmark del backtest.')
    else:
        print('Hay fallos. Revisar antes de usar en backtest.')
