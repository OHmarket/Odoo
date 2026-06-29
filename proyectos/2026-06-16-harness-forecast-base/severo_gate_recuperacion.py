"""
severo_gate_recuperacion — Separa los eventos SEVEROS en legitimos (el SKU se
recupera tras la semana-cero => quiebre real) vs espurios (sigue en ~0 => baja
demanda/muerte, no quiebre). Mide cuanto baja el mu_sum recortando SOLO lo espurio.

recupera = venta media de las POST_K sem siguientes >= RECOVER_FRAC * baseline_previo.
Eventos en el borde (sin POST_K sem por delante) -> se mantienen (conservador).
El modo LEVE se deja como el actual (no es el foco; aporta solo +6%).
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, load_abc, _build_series_map, _select_model,
    load_dow_weight, build_qweight, CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)
MIN_PREV = 3
POST_K = 4
RECOVER_FRAC = 0.5


def cleanse(vals, weeks, tid, pid, qw, severo_gate, stats=None, min_days=1,
            base_k=CLEANSE_BASE_WEEKS, severe_w=CLEANSE_SEVERE_WEIGHT):
    """severo_gate=False -> severo completo (actual). True -> severo solo si el SKU
    se recupera despues. stats: dict-contador opcional."""
    out = []; instock = []
    n = len(weeks)
    for i in range(n):
        w = weeks[i]; y = vals[i]
        info = qw.get((tid, pid, w)); nd = info[0] if info else 0; pw = info[1] if info else 0.0
        if nd >= min_days and pw > 0.0:
            if pw < severe_w and pw < 0.95:
                corr = y / (1.0 - pw)                       # leve: igual que actual
            elif instock:
                b = sum(instock[-base_k:]) / len(instock[-base_k:])
                if b > y:
                    if severo_gate:
                        post = vals[i + 1:i + 1 + POST_K]
                        if len(post) == 0:
                            corr = b; key = 'borde'
                        else:
                            mean_post = sum(post) / len(post)
                            if mean_post >= RECOVER_FRAC * b:
                                corr = b; key = 'recupera'
                            else:
                                corr = y; key = 'no_recupera'   # espurio -> no levantar
                        if stats is not None:
                            stats[key] = stats.get(key, 0) + 1
                    else:
                        corr = b
                else:
                    corr = y
            else:
                corr = y
            out.append(corr)
        else:
            out.append(y); instock.append(y)
    return out


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abc = load_abc(cache)
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    qw = build_qweight(cache, load_dow_weight(cache), cm)

    def mu_sum(severo_gate, stats=None, raw=False):
        tot = 0.0
        for (tid, pid), r in series.items():
            vals = r if raw else cleanse(r, weeks, tid, pid, qw, severo_gate, stats=stats)
            _s, _m, mu = _select_model(vals, abc.get(pid, ''))
            tot += max(0.0, mu)
        return tot

    crudo = mu_sum(False, raw=True)
    actual = mu_sum(False)
    stats = {}
    gated = mu_sum(True, stats=stats)

    print(f"crudo:                          {crudo:9.0f}   +0.0%")
    print(f"actual (severo completo):       {actual:9.0f}   {100*(actual/crudo-1):+.1f}%")
    print(f"severo gated por recuperacion:  {gated:9.0f}   {100*(gated/crudo-1):+.1f}%")
    print(f"\nahorro al recortar espurio: {actual-gated:+.0f} u  "
          f"({100*(actual-gated)/actual:.1f}% del forecast actual)")
    tot_ev = sum(stats.values())
    print(f"\neventos severos clasificados: {tot_ev:,}")
    for k in ['recupera', 'no_recupera', 'borde']:
        v = stats.get(k, 0)
        print(f"  {k:12}: {v:7,}  ({100*v/tot_ev:.1f}%)")


if __name__ == "__main__":
    main()
