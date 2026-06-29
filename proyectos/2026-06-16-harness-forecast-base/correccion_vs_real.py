"""
correccion_vs_real — Mide DIRECTO: venta corregida (de-censurada) en semanas de
quiebre vs venta REAL en semanas in-stock SIMILARES del mismo combo. Controla
estacionalidad comparando contra semanas in-stock del MISMO iso-week cuando existen,
con fallback al promedio in-stock del combo.

Niveles absolutos + ratio ponderado por volumen. Desglose leve/severo.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, _build_series_map, load_dow_weight, build_qweight, _cleanse_stockout,
    CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    iso = [w.isocalendar()[1] for w in weeks]
    qw = build_qweight(cache, load_dow_weight(cache), cm)

    rows = []
    for (tid, pid), raw in series.items():
        corr, _ = _cleanse_stockout(raw, weeks, tid, pid, qw,
                                    CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT)
        is_q = []
        for i in range(len(weeks)):
            info = qw.get((tid, pid, weeks[i]))
            is_q.append(bool(info and info[0] >= CLEANSE_MIN_DAYS and info[1] > 0.0))
        instock_idx = [i for i in range(len(weeks)) if not is_q[i]]
        q_idx = [i for i in range(len(weeks)) if is_q[i]]
        if len(instock_idx) < 4 or len(q_idx) < 1:
            continue
        real_mean = sum(raw[i] for i in instock_idx) / len(instock_idx)
        if real_mean <= 0:
            continue
        # corregida: media de las semanas-quiebre ya de-censuradas
        corr_mean = sum(corr[i] for i in q_idx) / len(q_idx)
        # control estacional: real por iso-week de las semanas-quiebre
        seas = []
        for i in q_idx:
            same = [raw[j] for j in instock_idx if iso[j] == iso[i]]
            if same:
                seas.append(sum(same) / len(same))
        real_seas = (sum(seas) / len(seas)) if seas else real_mean
        # modo dominante del combo
        n_sev = 0; n_lev = 0; instock = []
        for i in range(len(weeks)):
            if is_q[i]:
                info = qw.get((tid, pid, weeks[i])); pw = info[1]
                if pw < CLEANSE_SEVERE_WEIGHT and pw < 0.95:
                    n_lev += 1
                else:
                    n_sev += 1
            else:
                instock.append(raw[i])
        modo = 'severo' if n_sev >= n_lev else 'leve'
        vol = sum(raw)
        rows.append({'real_mean': real_mean, 'real_seas': real_seas, 'corr_mean': corr_mean,
                     'vol': vol, 'modo': modo})

    df = pd.DataFrame(rows)
    print(f"combos con quiebre e in-stock comparables: {len(df):,}\n")

    def report(d, label):
        rw = float(np.average(d['corr_mean'] / d['real_mean'], weights=d['vol']))
        rs = float(np.average(d['corr_mean'] / d['real_seas'], weights=d['vol']))
        med = (d['corr_mean'] / d['real_mean']).median()
        rmean = float(np.average(d['real_mean'], weights=d['vol']))
        cmean = float(np.average(d['corr_mean'], weights=d['vol']))
        print(f"  {label:8} n={len(d):>6,}  real~{rmean:.2f}  corregida~{cmean:.2f}  "
              f"ratio_w={rw:.2f}  ratio_w(iso)={rs:.2f}  mediana={med:.2f}")

    print("corregida vs venta REAL (ponderado por volumen):")
    report(df, 'TODOS')
    for m in ['severo', 'leve']:
        s = df[df['modo'] == m]
        if len(s):
            report(s, m)
    print("\nratio_w     = corregida / venta real promedio in-stock del combo")
    print("ratio_w(iso)= corregida / venta real in-stock del MISMO iso-week (control estacional)")


if __name__ == "__main__":
    main()
