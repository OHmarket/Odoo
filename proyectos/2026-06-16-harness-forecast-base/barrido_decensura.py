"""
barrido_decensura — Compara variantes de calibracion de la de-censura sobre el mismo
cutoff/cache (read-only). Para cada config mide:
  - mu_sum total (nivel de forecast -> proxy de compra)
  - combos levantados
  - ratio_correg ponderado por volumen + % de eventos sobre-corregidos (>1.15*baseline)

Variantes:
  crudo                 de-censura OFF (piso)
  actual (1d)           min_days=1, leve sin gate  (= motor productivo hoy)
  min_days=2 / =3       sube el umbral de dias para gatillar
  gate_leve             min_days=1 + gate: modo leve NO corrige si la venta no cayo
  2d+gate               combinacion

Uso: python barrido_decensura.py 2026-05-17
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, load_abc, _build_series_map, _select_model,
    load_dow_weight, build_qweight, CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)

MIN_PREV_INSTOCK = 3


def cleanse(vals, weeks, tid, pid, qweight, min_days, gate_leve,
            base_k=CLEANSE_BASE_WEEKS, severe_w=CLEANSE_SEVERE_WEIGHT, events=None):
    """De-censura parametrizable. Si events!=None, agrega (cruda, corr, base_local)
    de cada evento de quiebre con baseline_local valido."""
    out = []
    instock = []
    for i in range(len(weeks)):
        w = weeks[i]
        y = vals[i]
        info = qweight.get((tid, pid, w))
        nd = info[0] if info else 0
        pw = info[1] if info else 0.0
        if nd >= min_days and pw > 0.0:
            base = (sum(instock[-base_k:]) / len(instock[-base_k:])
                    if len(instock) >= MIN_PREV_INSTOCK else None)
            if pw < severe_w and pw < 0.95:
                if gate_leve and base is not None and y >= base:
                    corr = y                      # gate: la venta no cayo -> no tocar
                else:
                    corr = y / (1.0 - pw)
            elif instock:
                b = sum(instock[-base_k:]) / len(instock[-base_k:])
                corr = b if b > y else y
            else:
                corr = y
            out.append(corr)
            if events is not None and base is not None and base > 0:
                events.append((y, corr, base))
        else:
            out.append(y)
            instock.append(y)
    return out


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache)
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abc_letter = load_abc(cache)
    cutoff_monday = cutoff - timedelta(days=cutoff.weekday())
    series, _cat, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    dow = load_dow_weight(cache)
    qweight = build_qweight(cache, dow, cutoff_monday)
    print(f"cutoff={cutoff}  combos={len(series)}  qweight_keys={len(qweight)}\n")

    configs = [
        ('crudo',        None, None),
        ('actual (1d)',  1,    False),
        ('min_days=2',   2,    False),
        ('min_days=3',   3,    False),
        ('gate_leve',    1,    True),
        ('2d+gate',      2,    True),
    ]

    print(f"{'config':14} {'mu_sum':>9} {'vs crudo':>9} {'cleansed':>9} "
          f"{'ratio_correg_w':>14} {'sobre-corr%':>11}")
    rows = []
    mu_crudo = None
    for name, min_days, gate in configs:
        mu_sum = 0.0
        cleansed = 0
        events = []
        for (tid, pid), raw in series.items():
            if min_days is None:
                vals = raw
            else:
                vals = cleanse(raw, weeks, tid, pid, qweight, min_days, gate, events=events)
                if any(abs(a - b) > 1e-9 for a, b in zip(vals, raw)):
                    cleansed += 1
            abc = abc_letter.get(pid, '')
            _st, _mc, mu = _select_model(vals, abc)
            mu_sum += max(0.0, mu)
        if mu_crudo is None:
            mu_crudo = mu_sum
        if events:
            ev = pd.DataFrame(events, columns=['cruda', 'corr', 'base'])
            rc = ev['corr'] / ev['base']
            rc_w = float(np.average(rc, weights=ev['base']))
            over = 100 * (rc > 1.15).mean()
        else:
            rc_w, over = float('nan'), float('nan')
        pct = 100 * (mu_sum / mu_crudo - 1.0)
        print(f"{name:14} {mu_sum:9.0f} {pct:+8.1f}% {cleansed:9,} {rc_w:14.2f} {over:10.1f}%")
        rows.append({'config': name, 'mu_sum': mu_sum, 'pct_vs_crudo': pct,
                     'cleansed': cleansed, 'ratio_correg_w': rc_w, 'sobre_corr_pct': over})

    out = Path(__file__).resolve().parent / "resultados" / "barrido_decensura.parquet"
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_parquet(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
