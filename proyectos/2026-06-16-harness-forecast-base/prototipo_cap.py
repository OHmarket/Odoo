"""
prototipo_cap — Prueba el fix MINIMO sobre la de-censura: capar el modo LEVE al
nivel de periodos similares (baseline in-stock previo, el mismo que usa el severo),
manteniendo SOLO-LEVANTA. Regla unica:

    leve:   val = max(y, min(y/(1-pw), base))    # base = mean(instock previas)
    severo: val = max(y, base)                   # sin cambio

  - y >= base (la semana ya vendio sobre periodos similares): NO infla -> queda y.
  - y <  base: levanta por disponibilidad, pero nunca por encima de base.
  - sin instock previo: cae al leve actual y/(1-pw) (raro, primeras semanas).

Mide: (1) mu_sum crudo / actual / capped, (2) re-corre el salto (corr vs vecinas
sin-evento) para confirmar que el spike del leve desaparece.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, load_abc, _build_series_map, _select_model, _median,
    load_dow_weight, build_qweight, CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)
from salto_decensura import load_event_mask, W_NEIGH, MIN_NEIGH  # noqa: E402


def cleanse(raw, weeks, tid, pid, qw, cap_leve):
    """cap_leve=False -> motor actual. True -> leve capado a base in-stock previo.
    Retorna (vector, is_q, lifted, modo)."""
    out = []; instock = []; isq = []; lifted = []; modo = []
    for i in range(len(weeks)):
        w = weeks[i]; y = raw[i]
        info = qw.get((tid, pid, w)); nd = info[0] if info else 0; pw = info[1] if info else 0.0
        q = nd >= CLEANSE_MIN_DAYS and pw > 0.0
        isq.append(q)
        if q:
            base = (sum(instock[-CLEANSE_BASE_WEEKS:]) / len(instock[-CLEANSE_BASE_WEEKS:])) if instock else None
            if pw < CLEANSE_SEVERE_WEIGHT and pw < 0.95:
                val = y / (1.0 - pw)
                if cap_leve and base is not None and val > base:
                    val = base if base > y else y      # cap al nivel similar; nunca bajo y
                modo.append('leve')
            else:
                val = base if (base is not None and base > y) else y
                modo.append('severo')
            out.append(val); lifted.append(val > y + 1e-9)
        else:
            out.append(y); instock.append(y); lifted.append(False); modo.append('')
    return out, isq, lifted, modo


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abc = load_abc(cache)
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    qw = build_qweight(cache, load_dow_weight(cache), cm)
    chain_ev, team_ev = load_event_mask(cache)
    nW = len(weeks)

    def is_event(tid, pid, i):
        return (pid, weeks[i]) in chain_ev or (tid, pid, weeks[i]) in team_ev

    def mu_sum(cap_leve, raw_mode=False):
        tot = 0.0
        for (tid, pid), raw in series.items():
            vals = raw if raw_mode else cleanse(raw, weeks, tid, pid, qw, cap_leve)[0]
            _s, _m, mu = _select_model(vals, abc.get(pid, ''))
            tot += max(0.0, mu)
        return tot

    crudo = mu_sum(False, raw_mode=True)
    actual = mu_sum(False)
    capped = mu_sum(True)
    print(f"cutoff={cutoff}\n")
    print(f"{'metodo':34} {'mu_sum':>9} {'vs crudo':>9} {'vs actual':>10}")
    print(f"{'crudo (sin de-censura)':34} {crudo:9.0f} {0.0:+8.1f}% {'':>10}")
    print(f"{'actual (leve sin cap)':34} {actual:9.0f} {100*(actual/crudo-1):+8.1f}% {'':>10}")
    print(f"{'capped (leve capado a base)':34} {capped:9.0f} {100*(capped/crudo-1):+8.1f}% "
          f"{100*(capped/actual-1):+9.1f}%")

    # salto: corr vs vecinas in-stock sin-evento, con la serie CAPADA
    recs = []
    for (tid, pid), raw in series.items():
        corr, isq, lifted, modo = cleanse(raw, weeks, tid, pid, qw, True)
        vol = sum(raw)
        for i in range(nW):
            if not lifted[i] or is_event(tid, pid, i):
                continue
            nb = [raw[j] for j in range(max(0, i - W_NEIGH), min(nW, i + W_NEIGH + 1))
                  if j != i and not isq[j] and not is_event(tid, pid, j)]
            if len(nb) < MIN_NEIGH:
                continue
            bl = _median(nb)
            if bl <= 0:
                continue
            recs.append({'modo': modo[i], 'vol': vol, 'salto_corr': corr[i] / bl})
    df = pd.DataFrame(recs)
    print(f"\nsalto corr/vecinas (serie CAPADA), n={len(df):,}:")
    for m in ['TODOS', 'severo', 'leve']:
        d = df if m == 'TODOS' else df[df['modo'] == m]
        if len(d):
            sc = float(np.average(d['salto_corr'], weights=d['vol'].values))
            print(f"  {m:8} n={len(d):>6,}  salto_corr(w)={sc:.2f}  mediana={d['salto_corr'].median():.2f}  "
                  f">2x:{100*(d['salto_corr']>2).mean():.0f}%")
    print("\n(comparar con salto_decensura.py: leve actual era 1.84 / mediana 1.72 / >2x 44%)")


if __name__ == "__main__":
    main()
