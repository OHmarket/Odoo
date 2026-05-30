"""
DIAG read-only: por que el detector v5.x NO emitio alerta para SKU 9407
(CERVEZA STELLA ARTOIS BOTELLA UNIDAD 660 CC).

Tira via XML-RPC:
  1. product.product 9407 (resolver pid).
  2. x_loyalty_promo_event ultimos 8 semanas: ver min_qty, lift_qty,
     baseline_8w, period_start, program_name -> con eso decidimos en
     cual rama del detector cae (PAREO / MIXTA / STOCK-UP) y por que
     se descarta.
  3. x_price_coreccion activos para 9407: confirmar si quedo registro
     o no (esperado: vacio).
  4. ABC del SKU desde x_calculo_abc_xyz.

NO escribe nada en Odoo.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

TODAY = date(2026, 5, 27)
LOOKBACK_WEEKS = 8  # cubre periodo backtest W18-W20 + margen


def _iso_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")
    print(f"Hoy: {TODAY}  |  Lookback: {LOOKBACK_WEEKS} sem")

    # ------------------------------------------------------------
    # 1. Resolver SKU 9407
    # ------------------------------------------------------------
    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', '=', '9407')],
        fields=['id', 'name', 'default_code', 'active', 'sale_ok', 'categ_id'],
    )
    if not prods:
        prods = odoo.search_read(
            'product.product',
            domain=[('name', 'ilike', 'STELLA ARTOIS BOTELLA UNIDAD 660')],
            fields=['id', 'name', 'default_code', 'active', 'sale_ok', 'categ_id'],
        )
    if not prods:
        print("NO ENCONTRADO en product.product")
        return
    print("\n=== product.product ===")
    for p in prods:
        print(f"  id={p['id']} code={p.get('default_code')!r} active={p['active']} "
              f"sale_ok={p['sale_ok']} categ={p['categ_id']}")
        print(f"    name={p['name']!r}")
    pids = [p['id'] for p in prods]

    # ------------------------------------------------------------
    # 2. ABC del SKU
    # ------------------------------------------------------------
    abc_fields = odoo.fields_get('x_calculo_abc_xyz')
    abc_pf = next((k for k in abc_fields if abc_fields[k].get('type') == 'many2one'
                   and abc_fields[k].get('relation') == 'product.product'), None)
    if abc_pf:
        abc_rows = odoo.search_read(
            'x_calculo_abc_xyz',
            domain=[(abc_pf, 'in', pids)],
            fields=[abc_pf, 'x_studio_abcxyz', 'x_studio_categ_id'],
        )
        print("\n=== x_calculo_abc_xyz ===")
        for r in abc_rows:
            print(f"  pid={r[abc_pf]} abcxyz={r.get('x_studio_abcxyz')} "
                  f"categ={r.get('x_studio_categ_id')}")

    # ------------------------------------------------------------
    # 3. x_loyalty_promo_event lookback 8 sem
    # ------------------------------------------------------------
    lookback_start = _iso_monday(TODAY) - timedelta(weeks=LOOKBACK_WEEKS)
    print(f"\n=== x_loyalty_promo_event period_start >= {lookback_start} ===")

    promo_fields = odoo.fields_get('x_loyalty_promo_event')
    promo_pf = next((k for k in promo_fields if promo_fields[k].get('type') == 'many2one'
                     and promo_fields[k].get('relation') == 'product.product'
                     and 'variant' in k.lower()), None)
    if not promo_pf:
        promo_pf = next((k for k in promo_fields if promo_fields[k].get('type') == 'many2one'
                         and promo_fields[k].get('relation') == 'product.product'), None)
    print(f"  campo m2o product: {promo_pf}")

    candidate_fields = [
        'x_studio_period_start', 'x_studio_lift_qty', 'x_studio_program_name',
        'x_studio_minimum_qty', 'x_studio_qty_baseline_8w', 'x_studio_categ_id',
        'x_studio_qty_total',
    ]
    fields_to_read = [promo_pf] + [f for f in candidate_fields if f in promo_fields]
    promo_rows = odoo.search_read(
        'x_loyalty_promo_event',
        domain=[
            (promo_pf, 'in', pids),
            ('x_studio_period_start', '>=', lookback_start.strftime('%Y-%m-%d')),
        ],
        fields=fields_to_read,
        order='x_studio_period_start desc',
    )
    print(f"  filas: {len(promo_rows)}")
    if not promo_rows:
        print("  *** NO HAY EVENTOS DE PROMO para 9407 en el lookback ***")
        print("  -> SA 1557 (feed manual) puede estar desfasado")
    else:
        df = pd.DataFrame(promo_rows)
        # Limpiar columnas m2o (vienen como [id, name])
        for c in df.columns:
            if df[c].apply(lambda v: isinstance(v, (list, tuple))).any():
                df[c] = df[c].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else v)
        # Calcular weeks_active vs hoy
        if 'x_studio_period_start' in df.columns:
            df['weeks_since_period'] = df['x_studio_period_start'].apply(
                lambda s: ((TODAY - pd.to_datetime(s).date()).days // 7) if s else None
            )
        # Decidir rama del detector
        def rama(row):
            mq = int(row.get('x_studio_minimum_qty') or 0)
            lift = float(row.get('x_studio_lift_qty') or 0)
            bl = float(row.get('x_studio_qty_baseline_8w') or 0)
            if mq <= 2:
                if lift >= 2.5:
                    return f'PAREO -> alerta PROMO_PAREO_LIFT_EXTREMO (factor~{min(2.0, lift*0.7):.2f})'
                elif lift >= 1.5 and bl >= 5:
                    return f'PAREO -> v5.9 PROMO_PAREO_MODERADO (factor~{min(1.7, 1+(lift-1)*0.6):.2f})'
                return 'PAREO -> DESCARTA (lift<2.5 y/o baseline<5, v5.8 lo trataba como ruido)'
            if 3 <= mq <= 4:
                if lift >= 1.8:
                    return 'MIXTA -> alerta DISPARO_MIXTO_W1'
                return f'MIXTA -> DESCARTA (lift {lift:.2f} < 1.8)'
            if mq >= 6:
                if lift >= 1.5:
                    return 'STOCK-UP -> alerta DISPARO_STOCKUP_W1'
                return 'STOCK-UP -> DESCARTA (lift bajo)'
            return f'min_qty={mq} indefinido'
        df['rama_detector'] = df.apply(rama, axis=1)
        print(df.to_string(index=False))

    # ------------------------------------------------------------
    # 4. x_price_coreccion (activos) para 9407
    # ------------------------------------------------------------
    print("\n=== x_price_coreccion (registros activos) ===")
    corr_fields = odoo.fields_get('x_price_coreccion')
    corr_pf = next((k for k in corr_fields if corr_fields[k].get('type') == 'many2one'
                    and corr_fields[k].get('relation') == 'product.product'), None)
    print(f"  campo m2o product: {corr_pf}")

    domain = [(corr_pf, 'in', pids)]
    if 'x_studio_active' in corr_fields:
        domain.append(('x_studio_active', '=', True))
    candidate_corr = [
        'x_studio_target_week_start', 'x_studio_factor_corr', 'x_studio_tipo_alerta',
        'x_studio_razon', 'x_studio_source', 'x_studio_var_pct', 'x_studio_lift_qty',
        'x_studio_weeks_since_change',
    ]
    fields_corr = [corr_pf] + [f for f in candidate_corr if f in corr_fields]
    corr_rows = odoo.search_read(
        'x_price_coreccion',
        domain=domain,
        fields=fields_corr,
        order='x_studio_target_week_start desc' if 'x_studio_target_week_start' in corr_fields else '',
    )
    print(f"  filas: {len(corr_rows)}")
    if not corr_rows:
        print("  *** CONFIRMADO: NO HAY REGISTRO ACTIVO en x_price_coreccion para 9407 ***")
        print("  -> motor productivo aplico correccion_factor=1.0 (sin promo)")
    else:
        dfc = pd.DataFrame(corr_rows)
        for c in dfc.columns:
            if dfc[c].apply(lambda v: isinstance(v, (list, tuple))).any():
                dfc[c] = dfc[c].apply(lambda v: v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else v)
        print(dfc.to_string(index=False))


if __name__ == "__main__":
    main()
