"""
descompone_modos — Descompone el lift de mu_sum de la de-censura en su parte
SEVERA vs LEVE (parcial), corriendo cada modo aislado. min_days=1 (config actual).
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


def cleanse(vals, weeks, tid, pid, qw, apply_leve, apply_severo, min_days=1,
            base_k=CLEANSE_BASE_WEEKS, severe_w=CLEANSE_SEVERE_WEIGHT):
    out = []; instock = []
    for i in range(len(weeks)):
        w = weeks[i]; y = vals[i]
        info = qw.get((tid, pid, w)); nd = info[0] if info else 0; pw = info[1] if info else 0.0
        if nd >= min_days and pw > 0.0:
            if pw < severe_w and pw < 0.95:
                corr = (y / (1.0 - pw)) if apply_leve else y
            elif instock and apply_severo:
                b = sum(instock[-base_k:]) / len(instock[-base_k:]); corr = b if b > y else y
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

    def mu_sum(apply_leve, apply_severo, raw=False):
        tot = 0.0
        for (tid, pid), r in series.items():
            vals = r if raw else cleanse(r, weeks, tid, pid, qw, apply_leve, apply_severo)
            _s, _m, mu = _select_model(vals, abc.get(pid, ''))
            tot += max(0.0, mu)
        return tot

    crudo = mu_sum(False, False, raw=True)
    solo_sev = mu_sum(False, True)
    solo_lev = mu_sum(True, False)
    ambos = mu_sum(True, True)
    print(f"crudo (sin de-censura):     {crudo:9.0f}   +0.0%")
    print(f"solo SEVERO:                {solo_sev:9.0f}   {100*(solo_sev/crudo-1):+.1f}%")
    print(f"solo LEVE (parcial):        {solo_lev:9.0f}   {100*(solo_lev/crudo-1):+.1f}%")
    print(f"AMBOS (actual productivo):  {ambos:9.0f}   {100*(ambos/crudo-1):+.1f}%")
    print(f"\nlift total: {ambos-crudo:+.0f} u  |  severo aporta {solo_sev-crudo:+.0f}  |  "
          f"leve aporta {solo_lev-crudo:+.0f}")


if __name__ == "__main__":
    main()
