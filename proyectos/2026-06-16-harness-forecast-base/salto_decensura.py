"""
salto_decensura — Mide la CONTINUIDAD de la serie de-censurada en las semanas de
quiebre. La pregunta de Marco: en un SKU con quiebre, la demanda corregida por
quiebre, ¿salta respecto a las semanas vecinas SIMILARES (excluyendo semanas con
evento)? Una buena reconstruccion refleja el promedio de periodos similares ->
la semana corregida deberia quedar al NIVEL local (~1.0x), no spikear.

Para cada semana-quiebre LEVANTADA (corr>raw) que NO sea semana de evento:
  base_local = mediana de las semanas vecinas in-stock y sin-evento (ventana +-W)
  salto_raw  = raw[i]  / base_local   (caida por censura; deberia ser <1)
  salto_corr = corr[i] / base_local   (la de-censura; ideal ~1; >1 = salto inflado)

Evento = (pid, week) chain-wide o (tid, pid, week) en price_corr.
Desglosa leve/severo. Pondera por volumen del combo.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forecast_base_local import (  # noqa: E402
    load_cache, _build_series_map, load_dow_weight, build_qweight, _median,
    CACHE_DIR_DEFAULT, DEMAND_WINDOW_WEEKS,
    CLEANSE_MIN_DAYS, CLEANSE_BASE_WEEKS, CLEANSE_SEVERE_WEIGHT,
)
W_NEIGH = 4          # ventana +-W semanas para la base local
MIN_NEIGH = 3        # minimo de vecinos validos para evaluar


def load_event_mask(cache_dir):
    """Retorna (chainwide:set[(pid,week)], teamlvl:set[(tid,pid,week)])."""
    p = Path(cache_dir) / "price_corr.parquet"
    chain = set(); team = set()
    if not p.exists():
        return chain, team
    df = pd.read_parquet(p)
    df = df[df.get('x_studio_active', True) != False]
    for r in df.itertuples(index=False):
        try:
            pid = int(r.product_id)
        except Exception:
            continue
        w = pd.to_datetime(r.x_studio_target_week_start).date()
        w = w - timedelta(days=w.weekday())
        tid = getattr(r, 'team_id', None)
        if tid is None or (isinstance(tid, float) and pd.isna(tid)):
            chain.add((pid, w))
        else:
            team.add((int(tid), pid, w))
    return chain, team


def cleanse_full(raw, weeks, tid, pid, qw):
    """Como _cleanse_stockout pero retorna tambien (is_q, lifted, modo) por semana."""
    out = []; instock = []; isq = []; lifted = []; modo = []
    for i in range(len(weeks)):
        w = weeks[i]; y = raw[i]
        info = qw.get((tid, pid, w)); nd = info[0] if info else 0; pw = info[1] if info else 0.0
        q = nd >= CLEANSE_MIN_DAYS and pw > 0.0
        isq.append(q)
        if q:
            if pw < CLEANSE_SEVERE_WEIGHT and pw < 0.95:
                val = y / (1.0 - pw); modo.append('leve')
            elif instock:
                base = sum(instock[-CLEANSE_BASE_WEEKS:]) / len(instock[-CLEANSE_BASE_WEEKS:])
                val = base if base > y else y; modo.append('severo')
            else:
                val = y; modo.append('severo')
            out.append(val); lifted.append(val > y + 1e-9)
        else:
            out.append(y); instock.append(y); lifted.append(False); modo.append('')
    return out, isq, lifted, modo


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cache = Path(CACHE_DIR_DEFAULT)
    pos = load_cache(cache); pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    cm = cutoff - timedelta(days=cutoff.weekday())
    series, _c, weeks = _build_series_map(pos, cutoff, DEMAND_WINDOW_WEEKS)
    qw = build_qweight(cache, load_dow_weight(cache), cm)
    chain_ev, team_ev = load_event_mask(cache)
    nW = len(weeks)

    def is_event(tid, pid, i):
        return (pid, weeks[i]) in chain_ev or (tid, pid, weeks[i]) in team_ev

    recs = []
    for (tid, pid), raw in series.items():
        corr, isq, lifted, modo = cleanse_full(raw, weeks, tid, pid, qw)
        vol = sum(raw)
        for i in range(nW):
            if not lifted[i] or is_event(tid, pid, i):
                continue
            # vecinos in-stock, sin evento, dentro de +-W
            nb = [raw[j] for j in range(max(0, i - W_NEIGH), min(nW, i + W_NEIGH + 1))
                  if j != i and not isq[j] and not is_event(tid, pid, j)]
            if len(nb) < MIN_NEIGH:
                continue
            base_local = _median(nb)
            if base_local <= 0:
                continue
            recs.append({
                'modo': modo[i], 'vol': vol, 'base_local': base_local,
                'raw': raw[i], 'corr': corr[i],
                'salto_raw': raw[i] / base_local, 'salto_corr': corr[i] / base_local,
            })

    df = pd.DataFrame(recs)
    print(f"cutoff={cutoff}  semanas-quiebre levantadas (no-evento, con vecinos): {len(df):,}\n")

    def rep(d, label):
        w = d['vol'].values
        sr = float(np.average(d['salto_raw'], weights=w))
        sc = float(np.average(d['salto_corr'], weights=w))
        mr = d['salto_raw'].median(); mc = d['salto_corr'].median()
        p_up15 = 100 * (d['salto_corr'] > 1.5).mean()
        p_up2 = 100 * (d['salto_corr'] > 2.0).mean()
        print(f"  {label:8} n={len(d):>6,}  "
              f"salto_raw(w)={sr:.2f}  salto_corr(w)={sc:.2f}  | "
              f"mediana raw={mr:.2f} corr={mc:.2f}  | corr>1.5x:{p_up15:.0f}%  corr>2x:{p_up2:.0f}%")

    rep(df, 'TODOS')
    for m in ['severo', 'leve']:
        s = df[df['modo'] == m]
        if len(s):
            rep(s, m)
    print("\nbase_local = mediana de vecinas in-stock sin-evento (+-4 sem)")
    print("salto_raw <1  => la venta censurada cayo (hubo quiebre real).")
    print("salto_corr~1  => la de-censura devolvio al nivel de periodos similares (OK).")
    print("salto_corr>1  => la de-censura SALTA por encima del nivel vecino (sobre-corrige).")

    out = Path(__file__).resolve().parent / "resultados" / "salto_decensura.parquet"
    out.parent.mkdir(exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
