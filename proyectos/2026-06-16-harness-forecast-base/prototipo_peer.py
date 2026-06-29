"""
prototipo_peer — Prototipo del reconstructor de quiebre por PEER-STORES (cross-sala),
para medir el mu_sum resultante vs el metodo actual (+31%) y crudo.

Mecanismo unificado (reemplaza leve/severo):
  reconstruida(s,SKU,sem) = max( venta_cruda , market_index_sem * share_s )   (solo levanta)
     market_index = venta de las salas CON stock esa sem / suma de sus shares
     share_s      = participacion normal de la sala en el SKU (semanas in-stock)
  - severo (vendio poco): peer >> cruda -> levanta al nivel real de los pares (~1.0x).
  - leve  (vendio normal/+): peer <= cruda -> NO levanta -> queda cruda (no infla).
Fallback (quiebre sistemico: <MIN_PEERS salas con stock o poca share): baseline
temporal actual (6 prev severo / escala leve). Solo levanta.

Compara mu_sum: crudo | actual (de-censura vieja) | peer-proto.
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
MIN_PEERS = 3
MIN_SHARE_OK = 0.30
MIN_SHARE_S = 0.02


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abc = load_abc(cache)
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    qw = build_qweight(cache, load_dow_weight(cache), cm)
    nW = len(weeks)

    by_pid = {}; isq = {}; pw_of = {}
    for (tid, pid), vals in series.items():
        by_pid.setdefault(pid, {})[tid] = vals
        fl = []; pws = []
        for i in range(nW):
            info = qw.get((tid, pid, weeks[i]))
            fl.append(bool(info and info[0] >= CLEANSE_MIN_DAYS and info[1] > 0.0))
            pws.append(info[1] if info else 0.0)
        isq[(tid, pid)] = fl; pw_of[(tid, pid)] = pws

    # reconstruccion peer por combo, con fallback parametrizable.
    # fb='temporal' = 6-prev (como el motor); fb='tipico' = nivel medio in-stock del combo.
    cov = {'peer': 0, 'fb': 0}

    def reconstruct(fb):
        out_map = {}
        cov['peer'] = 0; cov['fb'] = 0
        for pid, salas in by_pid.items():
            teams = list(salas.keys())
            base = {}
            for t in teams:
                ins = [salas[t][i] for i in range(nW) if not isq[(t, pid)][i]]
                base[t] = (sum(ins) / len(ins)) if ins else 0.0
            tot = sum(base.values())
            share = {t: (base[t] / tot if tot > 0 else 0.0) for t in teams}
            market = {}
            for i in range(nW):
                S_ok = [t for t in teams if not isq[(t, pid)][i]]
                sok = sum(share[t] for t in S_ok)
                market[i] = (sum(salas[t][i] for t in S_ok) / sok
                             if (len(S_ok) >= MIN_PEERS and sok >= MIN_SHARE_OK) else None)
            for s in teams:
                v = salas[s]; instock_prev = []; out = []
                for i in range(nW):
                    y = v[i]
                    if isq[(s, pid)][i]:
                        mk = market[i]
                        if mk is not None and share[s] >= MIN_SHARE_S:
                            corr = max(y, mk * share[s]); cov['peer'] += 1
                        else:
                            if fb == 'tipico':
                                corr = max(y, base[s])           # nivel tipico (sin sesgo racha)
                            else:                                # temporal (6-prev)
                                pw = pw_of[(s, pid)][i]
                                if pw < CLEANSE_SEVERE_WEIGHT and pw < 0.95:
                                    corr = y / (1.0 - pw)
                                elif instock_prev:
                                    b = sum(instock_prev[-CLEANSE_BASE_WEEKS:]) / len(instock_prev[-CLEANSE_BASE_WEEKS:])
                                    corr = b if b > y else y
                                else:
                                    corr = y
                            cov['fb'] += 1
                        out.append(corr)
                    else:
                        out.append(y); instock_prev.append(y)
                out_map[(s, pid)] = out
        return out_map

    peer_temporal = reconstruct('temporal')
    peer_tipico = reconstruct('tipico')
    n_peer = cov['peer']; n_fallback = cov['fb']
    peer_vals = peer_temporal

    def mu_sum(kind):
        tot = 0.0
        for (tid, pid), raw in series.items():
            if kind == 'crudo':
                vals = raw
            elif kind == 'actual':
                vals, _ = _cleanse_stockout(raw, weeks, tid, pid, qw,
                                            CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT)
            elif kind == 'peer_temporal':
                vals = peer_temporal[(tid, pid)]
            else:
                vals = peer_tipico[(tid, pid)]
            _s, _m, mu = _select_model(vals, abc.get(pid, ''))
            tot += max(0.0, mu)
        return tot

    crudo = mu_sum('crudo'); actual = mu_sum('actual')
    pt = mu_sum('peer_temporal'); pp = mu_sum('peer_tipico')
    print(f"eventos de quiebre: peer={n_peer:,}  fallback={n_fallback:,}  "
          f"(cobertura peer {100*n_peer/(n_peer+n_fallback):.0f}%)\n")
    print(f"{'metodo':32} {'mu_sum':>9} {'vs crudo':>9}")
    print(f"{'crudo (sin de-censura)':32} {crudo:9.0f} {0.0:+8.1f}%")
    print(f"{'actual (6-prev, productivo)':32} {actual:9.0f} {100*(actual/crudo-1):+8.1f}%")
    print(f"{'PEER + fallback temporal (6-prev)':32} {pt:9.0f} {100*(pt/crudo-1):+8.1f}%")
    print(f"{'PEER + fallback tipico':32} {pp:9.0f} {100*(pp/crudo-1):+8.1f}%")
    print(f"\nvs actual: peer+temporal {100*(pt-actual)/actual:+.1f}%  |  "
          f"peer+tipico {100*(pp-actual)/actual:+.1f}% menos forecast")


if __name__ == "__main__":
    main()
