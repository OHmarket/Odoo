# Test standalone del helper de lote de cola larga. Pure-Python, sin Odoo.
# Correr: python proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py

def _safe_float(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d

# Copia byte-identica del helper productivo (safe_eval no permite import).
def _calc_cola_larga_lote(mu_week, moq, lead_weeks, objetivo_dias, plazo_pago_dias, piso_units):
    # Politica (s,S) de lote minimo para la cola larga, traslado CD->sala.
    # Devuelve (S_units, rop_units).
    #   S (order-up-to): 1 caja entera si la caja rinde <= plazo_pago (autofinanciada,
    #     limpia); si no, fraccion dimensionada al objetivo mensual (~30d). El traslado
    #     interno fracciona caja: el pack/MOQ solo ata la compra al proveedor.
    #   ROP (s): mu*lead + presencia. Lead CD->sala ~0-1d -> ROP ~= piso (dispara casi vacio).
    # PROXY: plazo de pago global (no por proveedor).
    mu   = max(_safe_float(mu_week,    0.0), 0.0)
    moq  = max(_safe_float(moq,        1.0), 1.0)
    piso = max(_safe_float(piso_units, 1.0), 1.0)
    if mu <= 0.0:
        return 0.0, 0.0
    obj  = max(_safe_float(objetivo_dias,   30.0), 1.0)
    pago = max(_safe_float(plazo_pago_dias, 45.0), obj)
    cobertura_caja_dias = (moq / mu) * 7.0
    q30 = float(int(mu * obj / 7.0)) + piso                           # order-up-to mensual: ciclo ~obj SOBRE el piso (ROP)
    if obj <= cobertura_caja_dias <= pago:
        S = moq                                                       # caja rinde ~1 mes y autofinanciada -> caja limpia
    else:
        S = q30                                                       # caja chica (<obj): caja+unidades a ~obj ; cola profunda (>pago): fraccion a ~obj. Siempre q30>moq cuando caja chica
    lead = max(_safe_float(lead_weeks, 0.0), 0.0)
    rop  = mu * lead + piso                                           # ROP = demanda en lead + presencia
    return S, rop

def _aprox(a, b, tol=1e-6):
    return abs(a - b) < tol

def run():
    OBJ, PAGO, PISO = 30.0, 45.0, 1.0
    # Caso A: mu=1/sem, caja=6 -> caja rinde 42d (30<=42<=45) -> caja limpia S=6 ; ROP=1 (lead 0)
    S, rop = _calc_cola_larga_lote(1.0, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 6.0), ('A.S', S); assert _aprox(rop, 1.0), ('A.rop', rop)
    # Caso B: mu=2/sem, caja=6 -> caja rinde 21d (<30, CAJA CHICA) -> caja+unidades a ~30d:
    #   q30 = floor(2*30/7)+1 = 8+1 = 9 (caja 6 + 3 sueltas). Cobertura 9/2=4.5sem~31.5d
    S, _ = _calc_cola_larga_lote(2.0, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 9.0), ('B.S', S)
    # Caso H: mu=1/sem, caja=5 -> caja rinde 35d (30<=35<=45) -> caja limpia S=5
    S, _ = _calc_cola_larga_lote(1.0, 5.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 5.0), ('H.S', S)
    # Caso C: mu=0.5/sem, caja=6 -> caja rinde 84d (>45) -> FRAC floor(0.5*30/7)=2 +piso 1 = 3
    #   ciclo (S-ROP)/mu = (3-1)/0.5 = 4 sem ~= 30d (antes S=2 daba ciclo 2 sem = 17d)
    S, _ = _calc_cola_larga_lote(0.5, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 3.0), ('C.S', S)
    # Caso D: mu=0.2/sem, caja=6 -> caja rinde 210d (>45) -> floor(0.857)=0 +piso 1 = 1
    #   S=ROP=1: transfiere 1u al llegar a 0; dura 1/mu = 5 sem ~= 35d
    S, _ = _calc_cola_larga_lote(0.2, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 1.0), ('D.S', S)
    # Caso G: mu=1/sem en FRAC (caja grande) -> floor(1*30/7)=4 +piso 1 = 5 ; ciclo (5-1)/1=4 sem
    S, _ = _calc_cola_larga_lote(1.0, 60.0, 0.0, OBJ, PAGO, PISO)  # caja 60 rinde 420d (>45) -> FRAC
    assert _aprox(S, 5.0), ('G.S', S)
    # Caso E: mu=0 -> sin demanda -> S=0, ROP=0
    S, rop = _calc_cola_larga_lote(0.0, 6.0, 0.0, OBJ, PAGO, PISO)
    assert _aprox(S, 0.0) and _aprox(rop, 0.0), ('E', S, rop)
    # Caso F: ROP con lead real 1 semana, mu=2 -> rop = 2*1 + 1 = 3
    _, rop = _calc_cola_larga_lote(2.0, 6.0, 1.0, OBJ, PAGO, PISO)
    assert _aprox(rop, 3.0), ('F.rop', rop)
    print('OK: 8 casos canonicos')

if __name__ == '__main__':
    run()
