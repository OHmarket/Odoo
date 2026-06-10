"""Test local de la matematica pura-Python de OH Factor Semanal.py
(ln por serie atanh, Gauss-Jordan, ajuste armonico end-to-end) vs numpy."""
import math
import numpy as np

# --- copias exactas del script ---
E = 2.718281828459045

def ln(x):
    if x <= 0:
        return 0.0
    k = 0
    while x >= 2.0:
        x = x / 2.0
        k += 1
    while x < 0.5:
        x = x * 2.0
        k -= 1
    z = (x - 1.0) / (x + 1.0)
    z2 = z * z
    term, s, i = z, 0.0, 0
    while abs(term) > 1e-12 and i < 60:
        s += term / (2 * i + 1)
        term *= z2
        i += 1
    return 2.0 * s + k * 0.6931471805599453

def solve(A, b):
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = col
        for r in range(col + 1, n):
            if abs(M[r][col]) > abs(M[piv][col]):
                piv = r
        if abs(M[piv][col]) < 1e-10:
            return None
        M[col], M[piv] = M[piv], M[col]
        dv = M[col][col]
        M[col] = [v / dv for v in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0.0:
                f = M[r][col]
                M[r] = [M[r][j] - f * M[col][j] for j in range(n + 1)]
    return [M[i][n] for i in range(n)]

# --- test 1: ln ---
xs = [0.001, 0.07, 0.5, 0.99, 1.0, 1.7, 10.0, 850.0, 12345.6]
err = max(abs(ln(x) - math.log(x)) for x in xs)
print(f"ln: error max vs math.log = {err:.2e}  {'OK' if err < 1e-9 else 'FALLA'}")

# --- test 2: solve vs numpy ---
rng = np.random.default_rng(3)
ok = True
for _ in range(50):
    A = rng.normal(size=(9, 9)); A = A @ A.T + np.eye(9) * 0.1
    b = rng.normal(size=9)
    x_np = np.linalg.solve(A, b)
    x_py = solve([list(r) for r in A], list(b))
    if np.max(np.abs(np.array(x_py) - x_np)) > 1e-6:
        ok = False
print(f"solve 9x9 (50 casos SPD): {'OK' if ok else 'FALLA'}")

# --- test 3: ajuste armonico end-to-end con data sintetica ---
basis = {w: [math.sin(2*math.pi*k*w/52) for k in (1, 2, 3)
             for _f in (0,)] for w in range(1, 53)}
basis = {w: [math.sin(2*math.pi*1*w/52), math.cos(2*math.pi*1*w/52),
             math.sin(2*math.pi*2*w/52), math.cos(2*math.pi*2*w/52),
             math.sin(2*math.pi*3*w/52), math.cos(2*math.pi*3*w/52)]
         for w in range(1, 53)}
# serie sintetica: nivel 100, swing estacional 1.8x con peak en feb (iso ~6),
# tendencia -5%/ano, ruido, 80 semanas
true_amp = 0.3
weeks = list(range(80))
event_isos = {38, 51}              # semanas-evento con spike 2x (a absorber)
y, Xr = [], []
for i in weeks:
    iso = (i % 52) + 1
    t = i * 7 / 365.0
    season = true_amp * math.cos(2*math.pi*(iso - 6)/52)
    ev = 1.0 if iso in event_isos else 0.0
    val = 100 * math.exp(season - 0.05*t + 0.7*ev + rng.normal(0, 0.05))
    Xr.append([1.0, t] + basis[iso] + [ev])
    y.append(ln(val))
npar = 9
A = [[0.0]*npar for _ in range(npar)]; bv = [0.0]*npar
for r_i in range(len(Xr)):
    xr = Xr[r_i]
    for i in range(npar):
        bv[i] += xr[i] * y[r_i]
        for j in range(i, npar):
            A[i][j] += xr[i] * xr[j]
for i in range(npar):
    for j in range(i+1, npar):
        A[j][i] = A[i][j]
coef = solve(A, bv)
fcoef = coef[2:8]
s_log = [sum(basis[w][i]*fcoef[i] for i in range(6)) for w in range(1, 53)]
m = sum(s_log)/52
curve = [E**(v-m) for v in s_log]
amp_est = max(curve)/min(curve)
amp_true = math.exp(2*true_amp)
peak_iso = curve.index(max(curve)) + 1
print(f"armonico: amplitud estimada {amp_est:.2f} vs real {amp_true:.2f} | "
      f"peak iso {peak_iso} (real 6) | trend {coef[1]:+.3f} (real -0.050)")
ok3 = abs(amp_est - amp_true) < 0.15 and abs(peak_iso - 6) <= 1 and abs(coef[1] + 0.05) < 0.03
print(f"end-to-end: {'OK' if ok3 else 'FALLA'}")
