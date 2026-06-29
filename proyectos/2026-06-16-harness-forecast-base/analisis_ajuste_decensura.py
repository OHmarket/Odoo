"""
analisis_ajuste_decensura — Evalua si la de-censura esta bien calibrada comparando,
por EVENTO de quiebre, la venta corregida contra el baseline LOCAL del mismo combo
(las CLEANSE_BASE_WEEKS semanas in-stock previas). Controla estacionalidad/tendencia
usando baseline contemporaneo, no promedio global. Read-only sobre el cache.

Metricas por evento (baseline_local = mean de las 6 sem in-stock previas):
  ratio_censura  = venta_cruda    / baseline_local   (<1 => hubo perdida real)
  ratio_correg   = venta_corregida/ baseline_local   (~1 ok ; >1.15 sobre-corrige)

Si ratio_censura ~1 en muchos eventos => el "quiebre" no censuro venta => la tabla
sobre-marca y la de-censura infla sin fundamento.

Uso: python analisis_ajuste_decensura.py 2026-05-17
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, _build_series_map, load_dow_weight, build_qweight,
    CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)

MIN_PREV_INSTOCK = 3   # minimo de semanas in-stock previas para un baseline_local creible


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache)
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    cutoff_monday = cutoff - timedelta(days=cutoff.weekday())
    series, _cat, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    dow = load_dow_weight(cache)
    qweight = build_qweight(cache, dow, cutoff_monday)
    print(f"cutoff={cutoff}  combos={len(series)}  qweight_keys={len(qweight)}")

    recs = []
    for (tid, pid), vals in series.items():
        instock = []
        for i in range(len(weeks)):
            w = weeks[i]
            y = vals[i]
            info = qweight.get((tid, pid, w))
            nd = info[0] if info else 0
            pw = info[1] if info else 0.0
            if nd >= CLEANSE_MIN_DAYS and pw > 0.0:
                # evento de quiebre — replica la decision del motor
                base_local = (sum(instock[-CLEANSE_BASE_WEEKS:]) / len(instock[-CLEANSE_BASE_WEEKS:])
                              if len(instock) >= MIN_PREV_INSTOCK else None)
                if pw < CLEANSE_SEVERE_WEIGHT and pw < 0.95:
                    corr = y / (1.0 - pw); mode = 'leve'
                elif instock:
                    b = sum(instock[-CLEANSE_BASE_WEEKS:]) / len(instock[-CLEANSE_BASE_WEEKS:])
                    corr = b if b > y else y; mode = 'severo'
                else:
                    corr = y; mode = 'sin_ref'
                recs.append({'tid': tid, 'pid': pid, 'week': w, 'pw': pw, 'mode': mode,
                             'cruda': y, 'corr': corr, 'base_local': base_local})
                # el motor NO agrega semanas-quiebre al instock
            else:
                instock.append(y)

    df = pd.DataFrame(recs)
    print(f"\neventos de quiebre totales: {len(df):,}")
    print(f"  por modo: {df['mode'].value_counts().to_dict()}")

    ev = df[df['base_local'].notna() & (df['base_local'] > 0)].copy()
    print(f"  con baseline_local valido (>={MIN_PREV_INSTOCK} sem in-stock, base>0): {len(ev):,}")
    if ev.empty:
        return
    ev['ratio_censura'] = ev['cruda'] / ev['base_local']
    ev['ratio_correg'] = ev['corr'] / ev['base_local']

    def _wmean(s, wt):
        return float(np.average(s, weights=wt)) if len(s) else float('nan')

    print("\n--- ¿Cuanto CAYO la venta en la semana de quiebre? (ratio_censura) ---")
    print(f"  mediana cruda/baseline:        {ev['ratio_censura'].median():.2f}")
    print(f"  ponderada por volumen:         {_wmean(ev['ratio_censura'], ev['base_local']):.2f}")
    print(f"  eventos con cruda>=0.9*baseline (venta NO cayo => quiebre dudoso): "
          f"{100*(ev['ratio_censura']>=0.9).mean():.1f}%")
    print(f"  eventos con cruda>=baseline      (vendio >= lo normal): "
          f"{100*(ev['ratio_censura']>=1.0).mean():.1f}%")

    print("\n--- ¿La de-censura DEVUELVE al nivel normal o lo PASA? (ratio_correg) ---")
    print(f"  mediana corregida/baseline:    {ev['ratio_correg'].median():.2f}   (~1.0 = ideal)")
    print(f"  ponderada por volumen:         {_wmean(ev['ratio_correg'], ev['base_local']):.2f}")
    for lo, hi in [(0, 0.8), (0.8, 1.15), (1.15, 1.5), (1.5, 2.0), (2.0, 1e9)]:
        m = (ev['ratio_correg'] >= lo) & (ev['ratio_correg'] < hi)
        lbl = f"{lo:.2f}-{hi:.2f}" if hi < 1e9 else f">={lo:.2f}"
        print(f"    corregida/baseline {lbl:>11}: {100*m.mean():5.1f}%  ({m.sum():,} ev)")
    print(f"  SOBRE-correccion (>1.15*baseline): {100*(ev['ratio_correg']>1.15).mean():.1f}% de eventos")

    print("\n--- desglose por modo ---")
    for mode in ['leve', 'severo']:
        s = ev[ev['mode'] == mode]
        if len(s):
            print(f"  {mode:7} n={len(s):>6,}  med ratio_censura={s['ratio_censura'].median():.2f}  "
                  f"med ratio_correg={s['ratio_correg'].median():.2f}  "
                  f"sobre-corr={100*(s['ratio_correg']>1.15).mean():.1f}%")

    out = Path(__file__).resolve().parent / "resultados" / "ajuste_decensura.parquet"
    out.parent.mkdir(exist_ok=True)
    ev.to_parquet(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
