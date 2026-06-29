"""
Explora la serie DIARIA de los testigos alrededor de su evento de precio.
Objetivo: ver el ESCALON real de demanda — cuando cambia el nivel y en cuantos
dias se estabiliza. Eso define la regla de confirmacion del demand sensing.

Run-rate = media movil TRAILING de 7 dias (causal, neutraliza dia-de-semana).
"""
from pathlib import Path
from datetime import timedelta

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'proyectos' / '2026-05-27-harness-local' / 'cache'
DAILY = Path(__file__).parent / 'pos_daily_cerv.parquet'

# testigo -> (code, fecha deteccion price_corr)
TESTIGOS = [
    ('Royal Guard', '451500', '2026-04-20'),
    ('Cristal',     '451548', '2026-04-13'),
    ('Budweiser',   '9413',   '2026-05-04'),
    ('Quilmes',     '9430',   '2026-04-13'),
    ('Cusquena',    '9958',   '2026-04-27'),
]


def main():
    df = pd.read_parquet(DAILY)
    df['day'] = pd.to_datetime(df['day'])
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    code2id = dict(zip(prod['default_code'].astype(str), prod['id']))
    all_days = pd.date_range(df['day'].min(), df['day'].max(), freq='D')

    for nm, code, ev in TESTIGOS:
        pid = code2id.get(code)
        ev = pd.Timestamp(ev)
        s = df[df['product_id'] == pid].set_index('day')['qty'].reindex(all_days, fill_value=0.0)
        mm7 = s.rolling(7).mean()
        pre = s[(s.index >= ev - timedelta(days=21)) & (s.index < ev - timedelta(days=7))].mean()
        post = s[(s.index >= ev + timedelta(days=14)) & (s.index < ev + timedelta(days=28))].mean()
        print(f"\n=== {nm} [{code}]  evento(detección)={ev.date()} ===")
        print(f"  run-rate/día  pre(ev-21..ev-7)={pre:.1f}   post(ev+14..ev+28)={post:.1f}   "
              f"cambio={'?' if pre==0 else f'{post/pre-1:+.0%}'}")
        print(f"  {'fecha':<12}{'qty_día':>8}{'MM7':>8}")
        d = ev - timedelta(days=14)
        while d <= ev + timedelta(days=28) and d <= all_days[-1]:
            mark = '  <-- evento' if d == ev else ''
            q = s.get(d, float('nan'))
            m = mm7.get(d, float('nan'))
            print(f"  {d.date()}{q:>8.0f}{m:>8.1f}{mark}")
            d += timedelta(days=2)


if __name__ == '__main__':
    main()
