"""
pull_quiebres — Pull read_group (server-side, read-only) de los dias de quiebre de
x_stock_balance_daily a parquet, para la ventana de paridad. ACOTADO:
  - pids con venta (del pos_weekly cache),
  - teams filtrados,
  - chunked por semana (16 llamadas ~6s c/u, no un golpe de 237k).

La tabla es solo-quiebre (stockout=True siempre), asi que cada fila = 1 dia de
quiebre de un (product, team). Escribe cache/quiebres_daily.parquet con columnas
product_id, team_id, date, isodow (1=Lun..7=Dom), ndays(=1).

Uso:
    python pull_quiebres.py 2026-05-17     # cutoff domingo de la ult. sem. cerrada
"""
from __future__ import annotations
import sys, time
from pathlib import Path
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

MODEL = 'x_stock_balance_daily'
TEAMS = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
LOOKBACK_WEEKS = 16
CACHE = Path(__file__).resolve().parent.parent / "2026-05-27-harness-local" / "cache"

# guardas de seguridad: si un chunk excede esto, abortar (no esperabamos tanto)
MAX_GROUPS_PER_CHUNK = 60000


def main():
    cutoff = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 5, 17)
    cutoff_monday = cutoff - timedelta(days=cutoff.weekday())
    win_from = cutoff_monday - timedelta(weeks=LOOKBACK_WEEKS - 1)
    print(f"Ventana quiebres: {win_from} .. {cutoff}  ({LOOKBACK_WEEKS} sem)")

    # pids con venta (acota el universo)
    pos = pd.read_parquet(CACHE / "pos_weekly.parquet")
    pids = sorted(int(p) for p in pos['product_id'].dropna().unique())
    print(f"pids con venta (acota domain): {len(pids):,}")

    o = OdooReader()
    rows = []
    wk = win_from
    chunk = 0
    while wk <= cutoff:
        wk_end = min(wk + timedelta(days=6), cutoff)
        dom = [('x_studio_date', '>=', str(wk)), ('x_studio_date', '<=', str(wk_end)),
               ('x_studio_team_id', 'in', TEAMS), ('x_studio_product_id', 'in', pids)]
        t = time.time()
        # search_read ANGOSTO (3 campos) chunked: read_group reventaba por el __domain
        # que mete en cada grupo (97MB IncompleteRead). 3 campos/sem ~ 1-2MB.
        g = o.search_read(MODEL, dom, ['x_studio_product_id', 'x_studio_team_id', 'x_studio_date'])
        dt = time.time() - t
        chunk += 1
        print(f"  sem {wk}..{wk_end}: {len(g):,} filas en {dt:.1f}s")
        if len(g) > MAX_GROUPS_PER_CHUNK:
            print(f"  ABORTO: chunk excede {MAX_GROUPS_PER_CHUNK:,} filas (inesperado).")
            sys.exit(1)
        for r in g:
            p = r.get('x_studio_product_id'); tm = r.get('x_studio_team_id')
            d = r.get('x_studio_date')
            if not p or not tm or not d:
                continue
            rows.append({'product_id': int(p[0]), 'team_id': int(tm[0]), 'date_raw': d})
        wk += timedelta(days=7)

    df = pd.DataFrame(rows)
    # 'x_studio_date:day' viene como '02 jun 2026' (locale es); parsear robusto
    df['date'] = pd.to_datetime(df['date_raw'], dayfirst=True, errors='coerce')
    bad = df['date'].isna().sum()
    if bad:
        print(f"  ⚠ {bad} fechas no parseadas (locale). Muestras: {df.loc[df['date'].isna(),'date_raw'].head(3).tolist()}")
    df = df.dropna(subset=['date']).copy()
    df['isodow'] = df['date'].dt.dayofweek + 1   # dayofweek 0=Lun..6=Dom -> 1..7
    df['date'] = df['date'].dt.date
    df = df[['product_id', 'team_id', 'date', 'isodow']].copy()
    df['ndays'] = 1

    dest = CACHE / "quiebres_daily.parquet"
    df.to_parquet(dest, index=False)
    print(f"\nTotal dias de quiebre: {len(df):,}  combos unicos: {df.groupby(['product_id','team_id']).ngroups:,}")
    print(f"escrito: {dest}")


if __name__ == "__main__":
    main()
