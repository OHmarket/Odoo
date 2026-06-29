"""
validar_reconstructor — Valida OUT-OF-SAMPLE que metodo reconstruye mejor la venta
de una sala. Sobre semanas IN-STOCK (venta real conocida), finge que la sala quebro,
reconstruye con cada metodo y compara contra la venta real (leave-one-store-out).
NO circular: el target es la venta real observada, no la propia estimacion.

Metodos:
  actual   = media de las 6 semanas in-stock previas de la sala (lo que hace el motor severo).
  peer     = market_index de las OTRAS salas con stock esa semana x share de la sala.
  blend    = peer si hay pares; si no, actual (hibrido propuesto).

Reporta bias (pred/real) y MAE (|pred-real|/real), ponderado por volumen.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, _build_series_map, load_dow_weight, build_qweight,
    CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS, CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS,
)
MIN_PEERS = 3
MIN_SHARE_OK = 0.30
MIN_SHARE_S = 0.02
PREV_K = CLEANSE_BASE_WEEKS  # 6


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    qw = build_qweight(cache, load_dow_weight(cache), cm)
    nW = len(weeks)

    by_pid = {}
    isq = {}
    for (tid, pid), vals in series.items():
        by_pid.setdefault(pid, {})[tid] = vals
        flags = []
        for i in range(nW):
            info = qw.get((tid, pid, weeks[i]))
            flags.append(bool(info and info[0] >= CLEANSE_MIN_DAYS and info[1] > 0.0))
        isq[(tid, pid)] = flags

    recs = []
    for pid, salas in by_pid.items():
        teams = list(salas.keys())
        if len(teams) < MIN_PEERS + 1:
            continue
        base = {}
        for t in teams:
            ins = [salas[t][i] for i in range(nW) if not isq[(t, pid)][i]]
            base[t] = (sum(ins) / len(ins)) if ins else 0.0
        tot = sum(base.values())
        if tot <= 0:
            continue
        share = {t: base[t] / tot for t in teams}

        for s in teams:
            if share[s] < MIN_SHARE_S:
                continue
            prev = []  # ventas in-stock previas de s
            for i in range(nW):
                if isq[(s, pid)][i]:
                    continue   # solo evaluo semanas in-stock (target conocido)
                y_real = salas[s][i]
                pred_act = (sum(prev[-PREV_K:]) / len(prev[-PREV_K:])) if len(prev) >= 3 else None
                S_ok = [t for t in teams if t != s and not isq[(t, pid)][i]]
                pred_peer = None
                if len(S_ok) >= MIN_PEERS:
                    share_ok = sum(share[t] for t in S_ok)
                    if share_ok >= MIN_SHARE_OK:
                        market = sum(salas[t][i] for t in S_ok) / share_ok
                        pred_peer = market * share[s]
                if pred_act is not None and pred_peer is not None:
                    # ratio_prev: cuan alta fue la racha previa vs el nivel tipico de la sala-SKU.
                    # En quiebres reales este ratio es ALTO (te quedas sin stock tras vender mucho).
                    rp = pred_act / base[s] if base[s] > 0 else 1.0
                    recs.append({'real': y_real, 'actual': pred_act, 'peer': pred_peer, 'ratio_prev': rp})
                prev.append(y_real)

    df = pd.DataFrame(recs)
    R = df['real'].sum()
    print(f"semanas in-stock evaluadas (target real conocido): {len(df):,}")
    print(f"venta real total: {R:.0f}\n")
    print(f"{'metodo':8} {'bias(pred/real)':>16} {'MAE(/real)':>12}")
    for m in ['actual', 'peer']:
        bias = df[m].sum() / R
        mae = (df[m] - df['real']).abs().sum() / R
        print(f"{m:8} {bias:16.2f} {mae:12.2f}")
    # blend = peer (siempre hay pares aqui por el filtro); reportado = peer
    print("\nbias ~1.0 y MAE bajo = reconstruye mejor la venta real de la sala.")
    print("actual usa 6 sem previas (racha pre-quiebre); peer usa las otras salas esa semana.")

    print("\n--- ESTRATIFICADO por racha previa (ratio_prev = nivel 6-prev / nivel tipico) ---")
    print("(los quiebres viven en ratio_prev ALTO: te quedas sin stock tras vender mucho)")
    print(f"{'racha previa':>14} {'n':>8} {'bias_actual':>12} {'bias_peer':>11} {'MAE_act':>9} {'MAE_peer':>9}")
    for lo, hi in [(0, 0.8), (0.8, 1.2), (1.2, 2.0), (2.0, 1e9)]:
        s = df[(df['ratio_prev'] >= lo) & (df['ratio_prev'] < hi)]
        if not len(s):
            continue
        r = s['real'].sum()
        lbl = f"{lo:.1f}-{hi:.1f}" if hi < 1e9 else f">={lo:.1f}"
        print(f"{lbl:>14} {len(s):>8,} {s['actual'].sum()/r:12.2f} {s['peer'].sum()/r:11.2f} "
              f"{(s['actual']-s['real']).abs().sum()/r:9.2f} {(s['peer']-s['real']).abs().sum()/r:9.2f}")

    out = Path(__file__).resolve().parent / "resultados" / "validar_reconstructor.parquet"
    out.parent.mkdir(exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
