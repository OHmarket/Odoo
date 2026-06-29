"""
inspect_stock_balance — Fase 1 read-only: valida estructura y COSTO de la query
de x_stock_balance_daily antes de pull masivo al cache. No escribe nada.

Mide:
  1. Campos relevantes (date/stockout/partial/qty_balance/product/team) existen y tipo.
  2. search_count del universo de quiebre acotado (ventana 16 sem + teams) -> cuantas
     filas traeria el snapshot. Si es manejable, recien ahi se hace el pull.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_stock_balance_daily'
TEAM_IDS = [18, 17, 16, 13, 12, 11, 10, 9, 8, 7, 6, 5]
LOOKBACK_WEEKS = 16

WANT_FIELDS = ['x_studio_product_id', 'x_studio_team_id', 'x_studio_date',
               'x_studio_stockout', 'x_studio_stockout_partial', 'x_studio_qty_balance']


def main():
    odoo = OdooReader()
    print(f"Conectado. Inspeccionando {MODEL}...\n")

    # 1. Campos
    fmap = odoo.fields_get(MODEL)
    print("Campos relevantes:")
    for f in WANT_FIELDS:
        meta = fmap.get(f)
        if meta:
            rel = meta.get('relation') or ''
            print(f"  OK  {f:32s} {meta.get('type'):10s} {rel}")
        else:
            print(f"  ?? {f:32s} NO EXISTE")

    # 2. Ventana
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    last_closed_monday = monday - timedelta(days=7)
    win_from = last_closed_monday - timedelta(weeks=LOOKBACK_WEEKS - 1)
    print(f"\nVentana lookback: {win_from} .. {last_closed_monday}  ({LOOKBACK_WEEKS} sem)")

    # 3. Conteos de costo (search_count = barato)
    total = odoo.search_count(MODEL, [])
    print(f"\nFilas TOTALES del modelo: {total:,}")

    dom_win = [('x_studio_date', '>=', str(win_from)), ('x_studio_date', '<=', str(last_closed_monday))]
    n_win = odoo.search_count(MODEL, dom_win)
    print(f"Filas en ventana 16 sem: {n_win:,}")

    dom_win_teams = dom_win + [('x_studio_team_id', 'in', TEAM_IDS)]
    n_win_teams = odoo.search_count(MODEL, dom_win_teams)
    print(f"  + teams filtrados:     {n_win_teams:,}")

    dom_quiebre = dom_win_teams + ['|', '|',
                  ('x_studio_stockout', '=', True),
                  ('x_studio_stockout_partial', '=', True),
                  ('x_studio_qty_balance', '<=', 0.0)]
    n_quiebre = odoo.search_count(MODEL, dom_quiebre)
    print(f"  + solo QUIEBRE (OR):   {n_quiebre:,}   <-- criterio del motor")

    # desglose: que condicion infla
    print("\nDesglose por condicion (ventana + teams):")
    n_so = odoo.search_count(MODEL, dom_win_teams + [('x_studio_stockout', '=', True)])
    n_sp = odoo.search_count(MODEL, dom_win_teams + [('x_studio_stockout_partial', '=', True)])
    n_qb = odoo.search_count(MODEL, dom_win_teams + [('x_studio_qty_balance', '<=', 0.0)])
    n_qb_neg = odoo.search_count(MODEL, dom_win_teams + [('x_studio_qty_balance', '<', 0.0)])
    print(f"  stockout=True:              {n_so:,}")
    print(f"  stockout_partial=True:      {n_sp:,}")
    print(f"  qty_balance <= 0:           {n_qb:,}")
    print(f"  qty_balance <  0 (negativo imposible): {n_qb_neg:,}")


if __name__ == "__main__":
    main()
