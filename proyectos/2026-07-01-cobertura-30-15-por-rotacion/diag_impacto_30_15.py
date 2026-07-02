"""
Diagnostico read-only: impacto de la politica order-up-to 30/15 por rotacion
vs el target actual de x_analisis_de_stock.

Caja > Quiebre > Viajes. NO toca nada productivo (solo search_read).
Corre desde la raiz del repo:  python proyectos/2026-07-01-.../diag_impacto_30_15.py
"""
import sys
from collections import defaultdict
from statistics import median
from shared.odoo_xmlrpc import OdooReader

_arg1 = sys.argv[1] if len(sys.argv) > 1 else None
K_FAST      = float(_arg1) if (_arg1 and _arg1 != 'sweep') else 2.0    # cajas/semana -> 15d ; menos -> 30d
T_FAST_D    = 15.0
T_SLOW_D    = 30.0
DEMAND_FLOOR_WEEK = 1.0 / 4.345
EXCL_TEAMS  = [26, 2]   # CD y Web no son salas

o = OdooReader()

fields = ['x_studio_team_id', 'x_studio_product_id', 'x_studio_mu_week', 'x_studio_moq',
          'x_studio_target_units', 'x_studio_stock_real', 'x_studio_stock_value_cash_physical']

rows = o.search_read(
    'x_analisis_de_stock',
    domain=[('x_studio_mu_week', '>', DEMAND_FLOOR_WEEK), ('x_studio_team_id', 'not in', EXCL_TEAMS)],
    fields=fields,
)
print('filas leidas:', len(rows))

# costo unitario por SKU = mediana de value/real entre salas con stock
cost_samples = defaultdict(list)
for r in rows:
    real = r.get('x_studio_stock_real') or 0.0
    val  = r.get('x_studio_stock_value_cash_physical') or 0.0
    pid  = r.get('x_studio_product_id')
    if real > 0 and val > 0 and pid:
        cost_samples[pid[0]].append(val / real)
cost_by_sku = {k: median(v) for k, v in cost_samples.items()}


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


# --- modo barrido: python diag... sweep  -> curva cash/viajes vs K (1 sola lectura) ---
if len(sys.argv) > 1 and sys.argv[1] == 'sweep':
    print('\n=== BARRIDO de K_FAST (cap/techo) ===')
    print(' K   n_fast  cash_cap_liberado   toques_fast_prom  toques_slow_prom')
    for K in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        n_fast = 0; freed = 0.0; tf_c = tf_n = ts_c = ts_n = 0.0; nf = ns = 0
        for r in rows:
            mu = _f(r.get('x_studio_mu_week')); moq = max(_f(r.get('x_studio_moq'), 1.0), 1.0)
            if mu <= DEMAND_FLOOR_WEEK:
                continue
            pid = r.get('x_studio_product_id')
            cu = cost_by_sku.get(pid[0] if pid else None)
            if cu is None:
                continue
            fast = (mu / moq) >= K
            T = T_FAST_D if fast else T_SLOW_D
            d = mu / 7.0
            S_cur = _f(r.get('x_studio_target_units')); S_cap = min(S_cur, d * T)
            freed += (S_cur - S_cap) * cu
            mu_month = mu * 4.345
            tc = mu_month / S_cur if S_cur > 0 else 0.0
            tn = mu_month / S_cap if S_cap > 0 else 0.0
            if fast:
                n_fast += 1; tf_c += tc; tf_n += tn; nf += 1
            else:
                ts_c += tc; ts_n += tn; ns += 1
        print(' %-4.1f %5d   $%-14s   %.2f->%.2f       %.2f->%.2f'
              % (K, n_fast, '{:,.0f}'.format(freed),
                 tf_c/nf if nf else 0, tf_n/nf if nf else 0,
                 ts_c/ns if ns else 0, ts_n/ns if ns else 0))
    sys.exit(0)


def fmt(x):
    return '{:,.0f}'.format(x)


# dos interpretaciones de 30/15:
#   TARGET: S = d*T                (piso: puede LEVANTAR stock)
#   CAP:    S = min(S_cur, d*T)    (techo anti-sobrestock: nunca sube)
agg = {}
for b in ('fast', 'slow'):
    agg[b] = dict(n=0, cash_cur=0.0, cash_tgt=0.0, cash_cap=0.0,
                  cov_days_cur=[], n_above=0, n_below=0,
                  touch_cur=0.0, touch_tgt=0.0)
no_cost = 0

for r in rows:
    mu  = _f(r.get('x_studio_mu_week'))
    moq = max(_f(r.get('x_studio_moq'), 1.0), 1.0)
    if mu <= DEMAND_FLOOR_WEEK:
        continue
    pid = r.get('x_studio_product_id')
    cu  = cost_by_sku.get(pid[0] if pid else None)
    if cu is None:
        no_cost += 1
        continue

    cajas_sem = mu / moq
    bucket = 'fast' if cajas_sem >= K_FAST else 'slow'
    T = T_FAST_D if bucket == 'fast' else T_SLOW_D

    d = mu / 7.0
    S_cur = _f(r.get('x_studio_target_units'))
    S_tgt = d * T
    S_cap = min(S_cur, S_tgt)

    cov_days_cur = S_cur / d if d > 0 else 0.0

    a = agg[bucket]
    a['n'] += 1
    a['cash_cur'] += S_cur * cu
    a['cash_tgt'] += S_tgt * cu
    a['cash_cap'] += S_cap * cu
    a['cov_days_cur'].append(cov_days_cur)
    if cov_days_cur > T:
        a['n_above'] += 1
    else:
        a['n_below'] += 1
    mu_month = mu * 4.345
    a['touch_cur'] += (mu_month / S_cur) if S_cur > 0 else 0.0
    a['touch_tgt'] += (mu_month / S_tgt) if S_tgt > 0 else 0.0

print('\nsin costo estimable (excluidas del cash):', no_cost)
tot = dict(cur=0.0, tgt=0.0, cap=0.0)
for b in ('fast', 'slow'):
    a = agg[b]
    if a['n'] == 0:
        continue
    T = 15 if b == 'fast' else 30
    med_cov = median(a['cov_days_cur'])
    tot['cur'] += a['cash_cur']; tot['tgt'] += a['cash_tgt']; tot['cap'] += a['cash_cap']
    print('\n[%s -> %dd]  n=%d SKUxsala   cobertura actual mediana: %.0f dias' % (b.upper(), T, a['n'], med_cov))
    print('  hoy ARRIBA de %dd (sobrestock, el cap recorta): %d   |   ABAJO: %d' % (T, a['n_above'], a['n_below']))
    print('  cash actual:        $%s' % fmt(a['cash_cur']))
    print('  cash TARGET (piso): $%s  (delta %+.1f%%)' % (fmt(a['cash_tgt']), 100.0*(a['cash_tgt']-a['cash_cur'])/a['cash_cur']))
    print('  cash CAP   (techo): $%s  (delta %+.1f%%)' % (fmt(a['cash_cap']), 100.0*(a['cash_cap']-a['cash_cur'])/a['cash_cur']))
    print('  toques/mes prom  actual: %.2f  target: %.2f (%+.1f%%)'
          % (a['touch_cur']/a['n'], a['touch_tgt']/a['n'], 100.0*(a['touch_tgt']-a['touch_cur'])/a['touch_cur']))

print('\n=== TOTAL cash a target ===')
print('  actual:        $%s' % fmt(tot['cur']))
print('  TARGET (piso): $%s  (delta %+.1f%%)' % (fmt(tot['tgt']), 100.0*(tot['tgt']-tot['cur'])/tot['cur']))
print('  CAP   (techo): $%s  (delta %+.1f%%)' % (fmt(tot['cap']), 100.0*(tot['cap']-tot['cur'])/tot['cur']))


# ---------------------------------------------------------------------------
# Concentracion del ahorro (cap) por SKU y casos canonicos
# ---------------------------------------------------------------------------
saving_by_sku = defaultdict(float)   # cash recortado (positivo = libera caja)
name_by_sku   = {}
for r in rows:
    mu  = _f(r.get('x_studio_mu_week'))
    moq = max(_f(r.get('x_studio_moq'), 1.0), 1.0)
    if mu <= DEMAND_FLOOR_WEEK:
        continue
    pid = r.get('x_studio_product_id')
    if not pid:
        continue
    cu = cost_by_sku.get(pid[0])
    if cu is None:
        continue
    T = T_FAST_D if (mu / moq) >= K_FAST else T_SLOW_D
    d = mu / 7.0
    S_cur = _f(r.get('x_studio_target_units'))
    recorte = max(S_cur - min(S_cur, d * T), 0.0) * cu
    saving_by_sku[pid[0]] += recorte
    name_by_sku[pid[0]] = pid[1]

top = sorted(saving_by_sku.items(), key=lambda kv: -kv[1])[:20]
tot_sav = sum(saving_by_sku.values())
print('\n=== concentracion del ahorro (cap) ===')
print('  ahorro total: $%s   | top-20 SKU = $%s (%.0f%%)'
      % (fmt(tot_sav), fmt(sum(v for _, v in top)), 100.0*sum(v for _, v in top)/tot_sav if tot_sav else 0))
print('  top-20 SKU por caja liberada:')
for pid, v in top:
    print('   $%s  %s' % (fmt(v), name_by_sku.get(pid, '?')[:48]))


def _canon(name_like):
    hits = o.search_read('product.template', domain=[('name', 'ilike', name_like)],
                         fields=['id', 'name'], limit=3)
    return hits


print('\n=== CASOS CANONICOS (por sala: cajas/sem | S_cur | cap | S_new | dCash) ===')
canon_ids = {}
for nm in ['royal guard 710', 'jagermeister 700']:
    for h in _canon(nm):
        canon_ids[h['id']] = h['name']
for tid, tname in canon_ids.items():
    crows = o.search_read('x_analisis_de_stock',
                          domain=[('x_studio_product_id', '=', tid), ('x_studio_team_id', 'not in', EXCL_TEAMS),
                                  ('x_studio_mu_week', '>', DEMAND_FLOOR_WEEK)],
                          fields=['x_studio_team_id', 'x_studio_mu_week', 'x_studio_moq', 'x_studio_target_units'])
    cu = cost_by_sku.get(tid)
    print('\n%s  (costo/u ~$%s)' % (tname, fmt(cu) if cu else 's/d'))
    dc = 0.0
    for r in sorted(crows, key=lambda x: -(x.get('x_studio_mu_week') or 0)):
        mu = _f(r.get('x_studio_mu_week')); moq = max(_f(r.get('x_studio_moq'), 1.0), 1.0)
        d = mu / 7.0; T = T_FAST_D if (mu/moq) >= K_FAST else T_SLOW_D
        S_cur = _f(r.get('x_studio_target_units')); S_new = min(S_cur, d*T)
        ddc = (S_new - S_cur) * (cu or 0.0); dc += ddc
        print('  team %-3s cajas/sem %.1f  S_cur %5.1f  cap %2dd  S_new %5.1f  dCash $%s'
              % (r['x_studio_team_id'][0], mu/moq, S_cur, int(T), S_new, fmt(ddc)))
    print('  -> dCash SKU: $%s' % fmt(dc))
