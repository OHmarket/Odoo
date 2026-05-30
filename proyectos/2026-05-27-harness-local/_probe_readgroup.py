"""
Probe v2: read_group con domain por (team, semana especifica) y solo
product_id en groupby. Sin dotted paths.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def _iso_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    today = date.today()
    week_start = _iso_monday(today - timedelta(days=7))
    week_end = week_start + timedelta(days=7)
    print(f"Semana probe: {week_start} -> {week_end}")

    teams = odoo.search_read('crm.team', [], fields=['id', 'name'])
    # crm.team todos se llaman 'Sales' (memory ref). Probar varios.
    for t in teams[:3]:
        print(f"\nTeam id={t['id']} name={t['name']!r}")
        t0 = time.time()
        try:
            grp = odoo.execute(
                'pos.order.line', 'read_group',
                [
                    ('order_id.crm_team_id', '=', t['id']),
                    ('order_id.date_order', '>=', week_start.strftime('%Y-%m-%d')),
                    ('order_id.date_order', '<', week_end.strftime('%Y-%m-%d')),
                    ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                ],
                ['qty:sum', 'price_subtotal:sum'],
                ['product_id'],
                lazy=False,
            )
            dt = time.time() - t0
            tot_qty = sum(r.get('qty', 0) for r in grp)
            print(f"  {dt:.2f}s  {len(grp):,} productos  qty_sum={tot_qty:,.0f}")
            if grp:
                print(f"  Sample row: {grp[0]}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
