"""
backtest_cap — Backtest local del cap del leve: capado vs uncapped vs venta REAL POS.
Para cada cutoff en una ventana de semanas cerradas, corre el motor (mu para target =
cutoff+1) con cap_leve True/False y compara contra la venta real de esa semana
(de la propia cache). Reporta WAPE, BIAS y FVA vs naive SMA(4).

Excluye, segun feedback: filas con quiebre en la SEMANA TARGET (real censurado, no es
error de forecast) y combos sin venta. No filtra categorias.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, load_abc, _build_series_map, _select_model, _cleanse_stockout,
    load_dow_weight, build_qweight, CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)


def forecast_at(series, weeks, qw, abc, cap_leve, naive=False, stype_out=None):
    """dict (tid,pid)->mu para target=weeks[-1]+1, usando datos hasta weeks[-1].
    Si stype_out es un dict, guarda (tid,pid)->series_type."""
    out = {}
    for (tid, pid), raw in series.items():
        if naive:
            tail = raw[-4:] if len(raw) >= 4 else raw
            out[(tid, pid)] = (sum(tail) / len(tail)) if tail else 0.0
            continue
        vals, _ = _cleanse_stockout(raw, weeks, tid, pid, qw, CLEANSE_MIN_DAYS,
                                    CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT, cap_leve=cap_leve)
        st, _m, mu = _select_model(vals, abc.get(pid, ''))
        out[(tid, pid)] = max(0.0, mu)
        if stype_out is not None:
            stype_out[(tid, pid)] = st
    return out


def main():
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abc = load_abc(cache)
    doww = load_dow_weight(cache)

    wmax = max(pos['week_start'])
    # ventana de evaluacion: ultimas N semanas con venta real disponible (target<=wmax)
    n_eval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    targets = [wmax - timedelta(weeks=k) for k in range(n_eval)][::-1]

    # venta real por (tid,pid,week) y mapa de quiebre target
    actual = {}
    for r in pos.itertuples(index=False):
        actual[(int(r.team_id), int(r.product_id), r.week_start)] = float(r.qty_sold or 0.0)

    rows = []
    for tgt in targets:
        cutoff = tgt - timedelta(days=1)            # domingo previo al lunes target
        cm = tgt                                    # target es lunes
        series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
        qw = build_qweight(cache, doww, cutoff - timedelta(days=cutoff.weekday()))
        # quiebre en la semana TARGET (para excluir censura)
        qtgt = build_qweight(cache, doww, tgt)
        stmap = {}
        f_cap = forecast_at(series, weeks, qw, abc, cap_leve=True, stype_out=stmap)
        f_unc = forecast_at(series, weeks, qw, abc, cap_leve=False)
        f_nai = forecast_at(series, weeks, qw, abc, cap_leve=True, naive=True)
        for (tid, pid) in series:
            a = actual.get((tid, pid, tgt), 0.0)
            info = qtgt.get((tid, pid, tgt))
            q = bool(info and info[0] >= CLEANSE_MIN_DAYS and info[1] > 0.0)
            if q:
                continue                            # target censurado -> fuera
            rows.append({'tgt': tgt, 'a': a, 'stype': stmap.get((tid, pid), ''),
                         'cap': f_cap[(tid, pid)], 'unc': f_unc[(tid, pid)], 'nai': f_nai[(tid, pid)]})

    df = pd.DataFrame(rows)
    df = df[(df['a'] > 0) | (df['cap'] > 0) | (df['unc'] > 0)]
    A = df['a'].sum()
    print(f"backtest local | semanas={len(targets)} ({targets[0]}..{targets[-1]})  "
          f"filas (target sin quiebre)={len(df):,}  venta_real={A:.0f}\n")

    def metrics(col):
        wape = (df[col] - df['a']).abs().sum() / A
        bias = (df[col].sum() - A) / A
        return wape, bias

    wn, _ = metrics('nai')
    print(f"{'modelo':10} {'WAPE':>8} {'BIAS':>9} {'FVA vs naive':>13}")
    for col, lbl in [('nai', 'naive SMA4'), ('unc', 'uncapped'), ('cap', 'CAPADO')]:
        w, b = metrics(col)
        fva = (wn - w) / wn if wn else 0.0
        print(f"{lbl:10} {100*w:7.1f}% {100*b:+8.1f}% {100*fva:+12.1f}%")
    print("\nWAPE menor = mejor acierto. BIAS + = over, - = sub. FVA + = le gana al naive.")
    print("Si CAPADO tiene WAPE <= uncapped y BIAS menos sobre-estimado -> el cap mejora.")

    # --- desglose FVA capado vs naive por series_type ---
    print("\n--- FVA capado vs naive POR series_type (donde pierde el motor) ---")
    print(f"{'series_type':13} {'venta':>9} {'%vta':>6} {'WAPE_cap':>9} {'WAPE_nai':>9} {'FVA':>8} {'BIAS_cap':>9}")
    for st in ['smooth', 'erratic', 'intermittent', 'lumpy', 'no_signal']:
        d = df[df['stype'] == st]
        if not len(d):
            continue
        a = d['a'].sum()
        if a <= 0:
            continue
        wc = (d['cap'] - d['a']).abs().sum() / a
        wnv = (d['nai'] - d['a']).abs().sum() / a
        bc = (d['cap'].sum() - a) / a
        fva = (wnv - wc) / wnv if wnv else 0.0
        print(f"{st:13} {a:9.0f} {100*a/A:5.1f}% {100*wc:8.1f}% {100*wnv:8.1f}% {100*fva:+7.1f}% {100*bc:+8.1f}%")
    print("FVA + = el motor le gana al naive en ese tipo; - = el naive gana (lever).")

    out = Path(__file__).resolve().parent / "resultados" / "backtest_cap.parquet"
    out.parent.mkdir(exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
