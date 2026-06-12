"""
Test local de la REGLA de deteccion de v3.0 (independiente de Odoo).
Replica exactamente la logica booleana del detector y la valida contra los
casos canonicos del diseno. Tambien testea reliable[] y el gate activo (two-pointer).

Correr: python test_deteccion.py   (sin framework, usa assert)
"""
import datetime
EPS = 0.0001


def decidir(start_raw, end_raw, qin, qout, reliable, activo):
    """Misma logica que el detector v3.2 por dia."""
    disponible = end_raw > EPS or qout > EPS
    is_partial = start_raw > EPS and end_raw <= EPS and qout > EPS
    is_full = (reliable and (not disponible)
               and start_raw <= EPS and end_raw <= EPS and activo)
    return is_full, is_partial


# (nombre, start, end, in, out, reliable, activo) -> (full_esp, partial_esp)
CASOS = [
    ("intradia: vende 3 y queda en 0",       3.0,  0.0, 0.0, 3.0, True,  True,   (False, True)),
    ("vendio durante quiebre (drift neg)",  -2.0, -2.0, 0.0, 4.0, False, True,   (False, False)),
    ("drift plano negativo, sin venta",     -2.0, -2.0, 0.0, 0.0, False, True,   (False, False)),
    ("quiebre total real (activo)",          0.0,  0.0, 0.0, 0.0, True,  True,   (True,  False)),
    ("deslistado: cero pero inactivo",       0.0,  0.0, 0.0, 0.0, True,  False,  (False, False)),
    ("lento con stock, inactivo",            5.0,  5.0, 0.0, 0.0, True,  False,  (False, False)),
    ("tiene stock hoy (ancla +17)",         17.0, 17.0, 0.0, 0.0, True,  True,   (False, False)),
    ("recibio y quedo positivo",             0.0,  8.0, 8.0, 0.0, True,  True,   (False, False)),
]

print("=== Test regla de deteccion (v3.2) ===")
ok = 0
for nombre, st, en, qi, qo, rel, act, esp in CASOS:
    got = decidir(st, en, qi, qo, rel, act)
    estado = "OK " if got == esp else "FALLA"
    if got == esp:
        ok += 1
    print(f"  [{estado}] {nombre:<42} -> full,partial={got} (esp {esp})")
assert ok == len(CASOS), f"{len(CASOS)-ok} casos fallaron"


# --- episodio completo: marca CADA dia mientras falte y siga activo (v3.2) ---
def simular_episodio(balances, ventas_idx, N_activo):
    """balances: end_raw por dia; ventas_idx: dias con qout>0. Devuelve flags full."""
    n = len(balances)
    last_sale = None
    fulls = []
    for i in range(n):
        end = balances[i]
        qout = 1.0 if i in ventas_idx else 0.0
        start = balances[i-1] if i > 0 else end + qout
        if qout > EPS:
            last_sale = i
        activo = last_sale is not None and (i - last_sale) <= N_activo
        f, p = decidir(start, end, 0.0, qout, True, activo)
        fulls.append(f)
    return fulls

# SKU vende dias 0-3; el dia 3 vende su ultima unidad y queda en 0 (parcial);
# sigue en cero 60 dias. N_activo=45.
bal = [5.0, 3.0, 1.0] + [0.0]*60
fulls = simular_episodio(bal, {0, 1, 2, 3}, 45)
marcados = sum(fulls)
# dia 3 = parcial; dias 4..48 activos (<=45 desde venta dia 3) -> 45 dias full;
# dia 49+ inactivo (deslistado), deja de marcar.
assert fulls[3] is False                     # dia 3 es parcial, no full
assert marcados == 45, f"esperaba 45 dias full, dio {marcados}"
assert fulls[4] is True and fulls[48] is True and fulls[49] is False
print("=== Test episodio OK (parcial dia 3 + 45 dias full + corte por inactivo) ===")


# --- reliable[]: tramo reciente hasta el primer balance<0 hacia atras ---
def calc_reliable(balance_end_arr):
    n = len(balance_end_arr)
    reliable = [True] * n
    hit = False
    for i in range(n - 1, -1, -1):
        if balance_end_arr[i] < -EPS:
            hit = True
        if hit:
            reliable[i] = False
    return reliable

# serie: [-3, -1, 0, 2, 5]  (hoy=5 reliable; el -1 y -3 viejos no)
assert calc_reliable([-3.0, -1.0, 0.0, 2.0, 5.0]) == [False, False, True, True, True]
# todo positivo -> todo confiable
assert calc_reliable([1.0, 2.0, 3.0]) == [True, True, True]
# hoy negativo (no deberia pasar: 0 quants neg) -> todo no confiable
assert calc_reliable([2.0, -1.0]) == [False, False]
print("=== Test reliable[] OK ===")


# --- gate activo two-pointer: vendio en <=N dias respecto a cada dia ---
def calc_activo(days, sale_days, N):
    sd = sorted(sale_days)
    ptr = 0
    last_sale = None
    out = []
    for d_i in days:
        while ptr < len(sd) and sd[ptr] <= d_i:
            last_sale = sd[ptr]
            ptr += 1
        out.append(last_sale is not None and (d_i - last_sale).days <= N)
    return out

base = datetime.date(2026, 1, 1)
days = [base + datetime.timedelta(days=k) for k in range(0, 100, 10)]  # cada 10 dias
ventas = [base, base + datetime.timedelta(days=20)]  # vendio dia 0 y dia 20
N = 45
act = calc_activo(days, ventas, N)
# dia0:activo, dia10:activo(venta dia0 a 10d), dia20:activo, dia30..dia60: venta dia20 ->
#   dia60 = 40d desde venta20 -> activo; dia70 = 50d -> inactivo
assert act[0] is True and act[6] is True  # dia0, dia60
assert act[7] is False                    # dia70 (>45d sin venta)
print("=== Test gate activo OK ===")

print("\nTODOS LOS TESTS PASARON")
