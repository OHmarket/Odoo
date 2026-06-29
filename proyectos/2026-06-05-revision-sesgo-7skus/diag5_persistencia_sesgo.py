# -*- coding: utf-8 -*-
"""
DIAG5 read-only: PERSISTENCIA del sesgo del motor a traves de 8 origenes rolling.
Pregunta unica: el sesgo es consistente semana a semana por segmento
(corregible) o se da vuelta (ruido)?

- Fuente: x_forecast_backtest (8 semanas, cada una cutoff = semana-1 => walk-forward).
- Excluye contaminacion (forecast_noise_feedback): (a) filas con quiebre cruzando
  x_stock_balance_daily en la semana medida, (b) Ventas San Jose (crm_team 11).
- Marca aparte la semana 2026-04-06 (apr06 motor cutoff bug).
- Agrega BIAS volume-weighted por (segmento ABCxseries_type, semana).
- Imprime matriz 8sem x segmento + persistencia (# sem mismo signo, mean, std)
  + tracking signal de Trigg al ultimo origen.
NO toca el motor. Solo lee.
"""
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SAN_JOSE_TEAM = 11
APR06 = '2026-04-06'   # semana contaminada por motor cutoff bug
TRIGG_ALPHA = 0.2      # suavizado EWMA del tracking signal (canon Trigg)

odoo = OdooReader()

# ---------- 1. BACKTEST 8 semanas ----------
bt = odoo.search_read('x_forecast_backtest', domain=[],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_target_week_start',
            'x_studio_forecast_qty','x_studio_real_qty',
            'x_studio_abcxyz','x_studio_series_type'])
weeks = sorted(set(r['x_studio_target_week_start'] for r in bt))
print(f"filas backtest={len(bt)}  semanas={weeks}")

# ---------- 2. QUIEBRE: solo dias con stockout (filtrado, barato) ----------
wk_dates = {}
for w in weeks:
    d0 = date.fromisoformat(w)
    wk_dates[w] = [(d0 + timedelta(days=i)).isoformat() for i in range(7)]
all_days = sorted({d for ds in wk_dates.values() for d in ds})
day2week = {d: w for w, ds in wk_dates.items() for d in ds}

sbd = odoo.search_read('x_stock_balance_daily',
    domain=['&', '&',
            ('x_studio_date', '>=', all_days[0]),
            ('x_studio_date', '<=', all_days[-1]),
            '|', ('x_studio_stockout', '=', True),
                 ('x_studio_stockout_partial', '=', True)],
    fields=['x_studio_product_id','x_studio_team_id','x_studio_date'])
broke = set()
for r in sbd:
    if not r['x_studio_team_id'] or not r['x_studio_product_id']:
        continue
    w = day2week.get(r['x_studio_date'])
    if w:
        broke.add((r['x_studio_product_id'][0], r['x_studio_team_id'][0], w))
print(f"combos (pid,team,sem) con quiebre={len(broke)}  dias-stockout leidos={len(sbd)}")

# ---------- 3. filtro contaminacion ----------
def contaminada(r):
    if not r['x_studio_team_id']:
        return True
    tid = r['x_studio_team_id'][0]
    if tid == SAN_JOSE_TEAM:
        return True
    pid = r['x_studio_product_id'][0] if r['x_studio_product_id'] else None
    w = r['x_studio_target_week_start']
    if (pid, tid, w) in broke:
        return True
    return False

clean = [r for r in bt if not contaminada(r)]
print(f"filas limpias (sin SanJose, sin quiebre)={len(clean)}  ({len(clean)/len(bt)*100:.0f}%)")

# ---------- 4. agrega BIAS vol-weighted por (segmento, semana) ----------
def seg_of(r):
    abc = (r['x_studio_abcxyz'] or '??')
    st = (r['x_studio_series_type'] or 'na')
    return f"{abc}-{st}"

# sumF, sumR por (segmento, semana)
agg = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # seg -> week -> [F,R]
segs = set()
for r in clean:
    s = seg_of(r); w = r['x_studio_target_week_start']
    segs.add(s)
    agg[s][w][0] += r['x_studio_forecast_qty'] or 0
    agg[s][w][1] += r['x_studio_real_qty'] or 0

def bias_pct(F, R):
    return (F - R) / R * 100 if R else float('nan')

def trigg_ts(errs):
    """tracking signal de Trigg sobre secuencia de errores con signo (unidades).
    TS = EWMA(e)/EWMA(|e|) in [-1,1]. |TS|->1 sesgo sistematico; ->0 ruido."""
    e_s = None; ae_s = None
    for e in errs:
        e_s = e if e_s is None else TRIGG_ALPHA * e + (1 - TRIGG_ALPHA) * e_s
        ae_s = abs(e) if ae_s is None else TRIGG_ALPHA * abs(e) + (1 - TRIGG_ALPHA) * ae_s
    return e_s / ae_s if ae_s else float('nan')

# ordenar segmentos por volumen real total (los que mueven la aguja primero)
seg_vol = {s: sum(agg[s][w][1] for w in weeks) for s in segs}
segs_ord = sorted(segs, key=lambda s: -seg_vol[s])

wlabels = [w[5:] for w in weeks]   # MM-DD
print("\n" + "=" * 120)
print("PERSISTENCIA DEL SESGO POR SEGMENTO (ABC-series_type)  vol-weighted bias%  "
      "[+ sobre / - sub]   *=apr06 (bug cutoff)")
print("=" * 120)
hdr = f"{'segmento':<14}{'volR':>8}"
for wl in wlabels:
    star = '*' if wl == APR06[5:] else ' '
    hdr += f"{wl + star:>8}"
hdr += f"{'mean':>7}{'std':>6}{'sgn':>5}{'TS':>7}"
print(hdr)
print("-" * 120)
for s in segs_ord:
    if seg_vol[s] < 50:   # ignora segmentos sin volumen
        continue
    biases = []
    errs = []
    line = f"{s:<14}{seg_vol[s]:>8.0f}"
    for w in weeks:
        F, R = agg[s][w]
        b = bias_pct(F, R)
        biases.append(b)
        errs.append(F - R)
        line += f"{b:>8.1f}"
    # persistencia: # semanas (excl apr06) con el mismo signo que la media
    bx = [b for w, b in zip(weeks, biases) if w != APR06 and b == b]
    mean = sum(bx) / len(bx) if bx else float('nan')
    var = sum((b - mean) ** 2 for b in bx) / len(bx) if bx else float('nan')
    std = var ** 0.5 if var == var else float('nan')
    same = sum(1 for b in bx if (b >= 0) == (mean >= 0))
    errs_x = [e for w, e in zip(weeks, errs) if w != APR06]
    ts = trigg_ts(errs_x)
    line += f"{mean:>7.1f}{std:>6.1f}{same:>3}/{len(bx):<2}{ts:>7.2f}"
    print(line)

print("\nLECTURA:")
print("  sgn = en cuantas de las 7 semanas (excl apr06) el sesgo va al mismo signo que la media.")
print("        7/7 o 6/7 = sesgo PERSISTENTE (corregible). 4/7 = ruido (no tocar).")
print("  TS  = tracking signal de Trigg al ultimo origen. |TS|>~0.5 = sistematico; ~0 = ruido.")
print("  std = dispersion del bias semanal; alta std + signo estable = nivel corregible pero ruidoso.")

# ---------- 5. sanity: los 7 SKUs de la queja ----------
PP = {10772:'0154 CocaCola3L', 11446:'1963 Monster', 11449:'1966 MonsterUltra',
      11967:'2233 Vital1.6', 11061:'6242 Cab2L', 11065:'6243 Merlot2L', 11063:'6244 Carmen2L'}
print("\n" + "=" * 120)
print("SANITY: los 7 SKUs de la queja (vol-weighted bias% por semana, limpio)")
print("=" * 120)
psum = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
for r in clean:
    pid = r['x_studio_product_id'][0] if r['x_studio_product_id'] else None
    if pid in PP:
        w = r['x_studio_target_week_start']
        psum[pid][w][0] += r['x_studio_forecast_qty'] or 0
        psum[pid][w][1] += r['x_studio_real_qty'] or 0
hdr2 = f"{'SKU':<18}"
for wl in wlabels:
    hdr2 += f"{wl:>8}"
hdr2 += f"{'mean':>7}{'sgn':>5}{'TS':>7}"
print(hdr2)
for pid in PP:
    biases = []; errs = []
    line = f"{PP[pid]:<18}"
    for w in weeks:
        F, R = psum[pid][w]
        b = bias_pct(F, R); biases.append(b); errs.append(F - R)
        line += f"{b:>8.1f}"
    bx = [b for w, b in zip(weeks, biases) if w != APR06 and b == b]
    mean = sum(bx) / len(bx) if bx else float('nan')
    same = sum(1 for b in bx if (b >= 0) == (mean >= 0)) if bx else 0
    ts = trigg_ts([e for w, e in zip(weeks, errs) if w != APR06])
    line += f"{mean:>7.1f}{same:>3}/{len(bx):<2}{ts:>7.2f}"
    print(line)
