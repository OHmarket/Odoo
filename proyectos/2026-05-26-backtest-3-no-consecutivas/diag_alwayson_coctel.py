"""
DIAG read-only: confirmar que los 8 cocteles ICE del top 20 tienen
promo always-on (>=6 semanas consecutivas) como SKU 9407.

Tira x_loyalty_promo_event ultimos 12 sem para cada SKU y reporta:
- semanas con promo registrada
- program_name unico
- min_qty
- rango de lift_qty
- weeks_consecutivas
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 60)

TODAY = date(2026, 5, 27)
LOOKBACK_WEEKS = 12

SKUS = {
    "9407":   "STELLA ARTOIS 660 (referencia)",
    "9640":   "CAPEL ICE APPLE 275",
    "447064": "KANTAL TROPICAL GIN 473",
    "9639":   "CAPEL ICE BERRIES 275",
    "9646":   "CAPEL ICE SANDIA 275",
    "447076": "3R ICE BERRIES 275",
    "7802175454076": "MISTRAL ICE BLEND 275",
    "7802175001645": "MISTRAL ICE SUPER FRUIT 275",
    # 8vo coctel: hay que buscar Kantal, falta uno. Inspeccionar top.
}


def _iso_monday(d): return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}  |  Lookback: {LOOKBACK_WEEKS} sem")

    # Resolver pids
    codes = list(SKUS.keys())
    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', 'in', codes)],
        fields=['id', 'default_code', 'name'],
    )
    pid_to_code = {p['id']: p['default_code'] for p in prods}
    code_to_pid = {p['default_code']: p['id'] for p in prods}
    found = set(pid_to_code.values())
    missing = set(codes) - found
    print(f"Encontrados: {len(found)} / {len(codes)}")
    if missing:
        print(f"  NO encontrados por default_code: {missing}")

    pids = list(pid_to_code.keys())
    if not pids:
        return

    # Pull promos lookback 12 sem
    lookback_start = _iso_monday(TODAY) - timedelta(weeks=LOOKBACK_WEEKS)
    rows = odoo.search_read(
        'x_loyalty_promo_event',
        domain=[
            ('x_studio_product_variant_id', 'in', pids),
            ('x_studio_period_start', '>=', lookback_start.strftime('%Y-%m-%d')),
        ],
        fields=[
            'x_studio_product_variant_id', 'x_studio_period_start',
            'x_studio_lift_qty', 'x_studio_program_name',
            'x_studio_minimum_qty', 'x_studio_qty_baseline_8w',
        ],
        order='x_studio_period_start desc',
    )
    print(f"Eventos promo total: {len(rows)}")

    df = pd.DataFrame(rows)
    if df.empty:
        print("Sin eventos para ninguno")
        return
    df['pid'] = df['x_studio_product_variant_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    df['default_code'] = df['pid'].map(pid_to_code)
    df['period_start'] = pd.to_datetime(df['x_studio_period_start']).dt.date

    # Summary por SKU
    print("\n========== RESUMEN POR SKU ==========")
    summary_rows = []
    for code in codes:
        if code not in code_to_pid:
            summary_rows.append({
                'code': code, 'nombre': SKUS[code],
                'n_eventos': 0, 'n_sem_unicas': 0, 'min_qty': '-',
                'program': '-', 'lift_min': '-', 'lift_max': '-',
                'baseline_8w': '-', 'always_on': '-',
            })
            continue
        sub = df[df['default_code'] == code].copy()
        n_eventos = len(sub)
        n_sem = sub['period_start'].nunique()
        prog = ' | '.join(sorted(sub['x_studio_program_name'].dropna().unique()))[:50]
        mq = sub['x_studio_minimum_qty'].dropna().unique()
        bl = sub['x_studio_qty_baseline_8w'].dropna().unique()
        lift_min = sub['x_studio_lift_qty'].min() if n_eventos else None
        lift_max = sub['x_studio_lift_qty'].max() if n_eventos else None
        always_on = "SI" if n_sem >= 6 else ("PARCIAL" if n_sem >= 3 else "NO")
        summary_rows.append({
            'code': code, 'nombre': SKUS[code][:40],
            'n_eventos': n_eventos, 'n_sem_unicas': n_sem,
            'min_qty': ','.join(str(int(x)) for x in mq) if len(mq) else '-',
            'program': prog,
            'lift_min': f"{lift_min:.2f}" if lift_min is not None else '-',
            'lift_max': f"{lift_max:.2f}" if lift_max is not None else '-',
            'baseline_8w': ','.join(f"{x:.0f}" for x in bl) if len(bl) else '-',
            'always_on': always_on,
        })
    summary = pd.DataFrame(summary_rows)
    print(summary.to_string(index=False))

    # Detalle full
    print("\n========== DETALLE TIMELINE POR SKU ==========")
    for code in codes:
        if code not in code_to_pid:
            continue
        sub = df[df['default_code'] == code].sort_values('period_start')
        if sub.empty:
            print(f"\n--- [{code}] {SKUS[code]}: SIN EVENTOS ---")
            continue
        print(f"\n--- [{code}] {SKUS[code]} ---")
        print(sub[['period_start', 'x_studio_program_name', 'x_studio_minimum_qty',
                   'x_studio_lift_qty', 'x_studio_qty_baseline_8w']].to_string(index=False))

    OUT = Path(__file__).parent / "diag_alwayson_coctel.csv"
    summary.to_csv(OUT, index=False, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
