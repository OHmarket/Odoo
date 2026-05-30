"""
Test del core puro de la capa bias-outlier (v3.48) ANTES de integrarla al motor.
Version CLOSURE-FREE: identica a la del motor (Odoo safe_eval prohibe closures,
o sea nada de comprehensions/genexpr/lambda que capturen variables del scope).

Valida con numeros reales de la watchlist 29-05:
  - Stella 660 (corto)        -> outlier, factor>1
  - Royal Guard Golden 710    -> outlier, factor<1 (clamp 0.65)
  - Cusquena 710 (quiebre)    -> tras limpiar stockout, sale del Pareto
  - SKU chico (2 vs 1)        -> NO entra (cola Pareto; % gritaria, unidades no)
  - SKU volatil (+,-,-)       -> excluido por guard de persistencia
  - SKU nuevo (1 sem, mu~0)   -> excluido (n_weeks < persistence_min)
"""


def compute_bias_outliers(cells, params):
    window = int(params['window'])
    lo = params['clamp'][0]
    hi = params['clamp'][1]
    pareto = float(params['pareto'])
    pmin = int(params['persistence_min'])

    agg = {}
    for c in cells:
        sw = c['stockout_weeks']
        rweeks = c['real_weeks']
        clean_idx = []
        clean_sum = 0.0
        for i in range(window):
            if i not in sw:
                clean_idx.append(i)
                clean_sum += rweeks[i]
        if not clean_idx:
            continue
        real_weekly = clean_sum / float(len(clean_idx))
        a = agg.get(c['sku'])
        if a is None:
            a = {'sum_real': 0.0, 'sum_mu': 0.0,
                 'week_real': [0.0] * window, 'week_mu': [0.0] * window,
                 'week_has': [0] * window, 'n_teams': 0}
            agg[c['sku']] = a
        a['sum_real'] += real_weekly
        a['sum_mu'] += c['mu']
        a['n_teams'] += 1
        for i in clean_idx:
            a['week_real'][i] += rweeks[i]
            a['week_mu'][i] += c['mu']
            a['week_has'][i] = 1

    scored = []
    for sku in agg:
        a = agg[sku]
        delta = a['sum_real'] - a['sum_mu']
        dir_sku = 1 if delta > 0 else (-1 if delta < 0 else 0)
        n_dir = 0
        n_weeks = 0
        for i in range(window):
            if a['week_has'][i]:
                n_weeks += 1
                di = a['week_real'][i] - a['week_mu'][i]
                if (di > 0 and dir_sku > 0) or (di < 0 and dir_sku < 0):
                    n_dir += 1
        a['delta'] = delta
        a['n_dir'] = n_dir
        a['n_weeks'] = n_weeks
        scored.append((sku, a))

    rank = []
    total_abs = 0.0
    ri = 0
    for sku, a in scored:
        ad = a['delta'] if a['delta'] >= 0 else -a['delta']
        total_abs += ad
        rank.append((ad, ri, sku))
        ri += 1
    out = {}
    if total_abs <= 0.0:
        return out
    rank.sort(reverse=True)
    threshold = pareto * total_abs
    cum = 0.0
    for ad, _ri, sku in rank:
        a = agg[sku]
        prev = cum
        cum += ad
        if prev >= threshold:
            break
        if a['sum_mu'] <= 0.0:
            continue
        if a['n_weeks'] < pmin or a['n_dir'] < pmin:
            continue
        factor = a['sum_real'] / a['sum_mu']
        if factor < lo:
            factor = lo
        elif factor > hi:
            factor = hi
        out[sku] = {'factor': factor, 'delta': a['delta'],
                    'sum_real': a['sum_real'], 'sum_mu': a['sum_mu'],
                    'n_teams': a['n_teams']}
    return out


PARAMS = {'window': 3, 'pareto': 0.80, 'clamp': (0.65, 4.0), 'persistence_min': 2}


def _cell(sku, mu, w, so=None):
    return {'sku': sku, 'team': 1, 'mu': mu, 'real_weeks': w,
            'stockout_weeks': set(so or [])}


def run():
    cells = [
        _cell('STELLA', 199.3, [372.0, 372.0, 373.0]),        # corto -> 1.87
        _cell('RG710', 239.3, [62.0, 61.0, 62.0]),            # largo -> clamp 0.65
        _cell('CUSQ710', 89.0, [24.0, 0.0, 0.0], so=[1, 2]),  # quiebre -> fuera
        _cell('CHICO', 1.0, [2.0, 2.0, 2.0]),                 # cola Pareto -> fuera
        _cell('VOLATIL', 6.0, [20.0, 1.0, 1.0]),              # +,-,- -> persistencia fuera
        _cell('NUEVO', 0.1, [35.0, 0.0, 0.0], so=[]),         # 1 sem util -> fuera
    ]
    res = compute_bias_outliers(cells, PARAMS)
    print("Outliers:")
    for sku in sorted(res, key=lambda s: -abs(res[s]['delta'])):
        r = res[sku]
        print("  %-8s factor=%.3f delta=%+.1f (real=%.1f mu=%.1f)" % (
            sku, r['factor'], r['delta'], r['sum_real'], r['sum_mu']))

    ok = [True]

    def check(cond, msg):
        print(("  OK  " if cond else "  FAIL") + " " + msg)
        ok[0] = ok[0] and cond

    print("\nAsserts:")
    check('STELLA' in res and abs(res['STELLA']['factor'] - 1.87) < 0.05, "Stella factor ~1.87")
    check('RG710' in res and abs(res['RG710']['factor'] - 0.65) < 1e-6, "Royal Guard clamp 0.65")
    check('CUSQ710' not in res, "Cusquena fuera (quiebre)")
    check('CHICO' not in res, "Chico fuera (cola Pareto)")
    check('VOLATIL' not in res, "Volatil fuera (persistencia)")
    check('NUEVO' not in res, "Nuevo fuera (n_weeks<2)")
    print("\n%s" % ("TODO OK" if ok[0] else "HAY FALLOS"))
    return 0 if ok[0] else 1


if __name__ == '__main__':
    raise SystemExit(run())
