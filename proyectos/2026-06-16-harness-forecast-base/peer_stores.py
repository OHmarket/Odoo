"""
peer_stores — Valida la de-censura con el metodo canonico de unconstraining por
PARES (cross-section de salas). Para cada (SKU, semana) con algunas salas quebradas
y otras con stock:

  share_sala   = participacion normal de la sala en la demanda del SKU
                 (media de venta en semanas in-stock / total cadena).
  market_index = venta observada de las salas CON stock esa semana / suma de sus shares
                 (= nivel de demanda del SKU esa semana, sin estacionalidad: es la
                  misma semana).
  esperada_sw  = market_index * share_sala  (ground-truth de la sala quebrada).

Compara contra esperada:
  cruda  (venta censurada)      -> cuanto se vendio pese al quiebre  (lost = 1-ratio)
  corr   (de-censura del motor) -> la estimacion del motor (~1 acierta, >1 infla)
y si la de-censura ACERCA o ALEJA del ground-truth (MAE corr vs MAE crudo).

Sin confounder estacional ni de tendencia: todo es la MISMA semana.
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
MIN_PEERS = 3          # minimo de salas con stock esa semana
MIN_SHARE_OK = 0.30    # minimo de share-cadena representado por las salas con stock
MIN_SHARE_S = 0.02     # la sala quebrada debe vender el SKU normalmente


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    qw = build_qweight(cache, load_dow_weight(cache), cm)
    nW = len(weeks)

    # reorganizar por producto: pid -> {tid: vals}, y de-censura + flag quiebre
    by_pid = {}
    corr_of = {}
    isq_of = {}
    pw_of = {}
    for (tid, pid), vals in series.items():
        by_pid.setdefault(pid, {})[tid] = vals
        corr_of[(tid, pid)], _ = _cleanse_stockout(vals, weeks, tid, pid, qw,
                                                   CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT)
        flags = []; pws = []
        for i in range(nW):
            info = qw.get((tid, pid, weeks[i]))
            q = bool(info and info[0] >= CLEANSE_MIN_DAYS and info[1] > 0.0)
            flags.append(q); pws.append(info[1] if info else 0.0)
        isq_of[(tid, pid)] = flags; pw_of[(tid, pid)] = pws

    recs = []
    for pid, salas in by_pid.items():
        teams = list(salas.keys())
        if len(teams) < MIN_PEERS + 1:
            continue
        # share por sala: media de venta en semanas in-stock
        base = {}
        for tid in teams:
            v = salas[tid]; fq = isq_of[(tid, pid)]
            ins = [v[i] for i in range(nW) if not fq[i]]
            base[tid] = (sum(ins) / len(ins)) if ins else 0.0
        tot_base = sum(base.values())
        if tot_base <= 0:
            continue
        share = {tid: base[tid] / tot_base for tid in teams}

        for i in range(nW):
            S_ok = [t for t in teams if not isq_of[(t, pid)][i]]
            S_q = [t for t in teams if isq_of[(t, pid)][i] and base[t] > 0]
            if len(S_ok) < MIN_PEERS or not S_q:
                continue
            share_ok = sum(share[t] for t in S_ok)
            if share_ok < MIN_SHARE_OK:
                continue
            obs_ok = sum(salas[t][i] for t in S_ok)
            market = obs_ok / share_ok
            for s in S_q:
                if share[s] < MIN_SHARE_S:
                    continue
                esperada = market * share[s]
                if esperada <= 0:
                    continue
                cruda = salas[s][i]
                corr = corr_of[(s, pid)][i]
                pw = pw_of[(s, pid)][i]
                modo = 'leve' if (pw < CLEANSE_SEVERE_WEIGHT and pw < 0.95) else 'severo'
                recs.append({'esperada': esperada, 'cruda': cruda, 'corr': corr, 'modo': modo})

    df = pd.DataFrame(recs)
    print(f"eventos (sala-SKU-semana) con pares validos: {len(df):,}\n")

    def rep(d, label):
        E = d['esperada'].sum()
        rc = d['cruda'].sum() / E
        rm = d['corr'].sum() / E
        mae_c = (d['cruda'] - d['esperada']).abs().sum() / E
        mae_m = (d['corr'] - d['esperada']).abs().sum() / E
        print(f"  {label:8} n={len(d):>6,}  cruda/esp={rc:.2f} (lost={100*(1-rc):+.0f}%)  "
              f"corr/esp={rm:.2f}  MAE_crudo={mae_c:.2f}  MAE_motor={mae_m:.2f}  "
              f"{'motor ACERCA' if mae_m < mae_c else 'motor ALEJA'}")

    rep(df, 'TODOS')
    for m in ['severo', 'leve']:
        s = df[df['modo'] == m]
        if len(s):
            rep(s, m)
    print("\ncruda/esp < 1 => hubo lost-sales real (de-censurar ayuda).")
    print("corr/esp  > 1 => el motor INFLA por encima de la demanda real de los pares.")
    print("MAE_motor < MAE_crudo => la de-censura acerca al ground-truth; si no, lo aleja.")

    out = Path(__file__).resolve().parent / "resultados" / "peer_stores.parquet"
    out.parent.mkdir(exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
