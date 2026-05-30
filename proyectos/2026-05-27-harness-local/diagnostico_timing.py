"""
Diagnostico TIMING - cuando corrio cada SA?
+ analisis de raw_factor para entender si saturan en 0.80.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def main():
    odoo = OdooReader()

    # ====== TIMING ======
    print("[A] TIMING de los modelos")
    print("-" * 80)
    last_fwd = odoo.search_read(
        'x_hm_si_forecast', domain=[],
        fields=['create_date', 'x_studio_week_start'],
        limit=1, order='create_date desc',
    )
    print(f"  x_hm_si_forecast ultimo registro: create_date={last_fwd[0]['create_date']}  "
          f"week_start={last_fwd[0]['x_studio_week_start']}")

    last_calib = odoo.search_read(
        'x_categ_calib_factor', domain=[],
        fields=['create_date', 'x_studio_target_week'],
        limit=1, order='create_date desc',
    )
    print(f"  x_categ_calib_factor ultimo: create_date={last_calib[0]['create_date']}  "
          f"target_week={last_calib[0]['x_studio_target_week']}")

    last_bt = odoo.search_read(
        'x_forecast_backtest', domain=[],
        fields=['create_date', 'x_studio_target_week_start'],
        limit=1, order='create_date desc',
    )
    print(f"  x_forecast_backtest ultimo: create_date={last_bt[0]['create_date']}  "
          f"target_week={last_bt[0]['x_studio_target_week_start']}")

    # ====== Distribucion factor / raw_factor de los 71 factores ======
    print("\n[B] Distribucion raw_factor vs factor (saturacion)")
    print("-" * 80)
    factors = odoo.search_read(
        'x_categ_calib_factor',
        domain=[('x_studio_active', '=', True)],
        fields=['x_studio_categ_id', 'x_studio_abc_letter',
                'x_studio_factor_corr', 'x_studio_raw_factor',
                'x_studio_n_real_units', 'x_studio_bias_pct_pre'],
        limit=100,
    )
    print(f"  Total activos leidos: {len(factors)}")
    saturados_low = sum(1 for f in factors if f['x_studio_factor_corr'] == 0.80)
    saturados_high = sum(1 for f in factors if f['x_studio_factor_corr'] == 1.20)
    intermedios = len(factors) - saturados_low - saturados_high
    print(f"  Saturados en 0.80 (recorte max): {saturados_low}")
    print(f"  Saturados en 1.20 (amplificacion max): {saturados_high}")
    print(f"  Intermedios (0.80, 1.20):              {intermedios}")
    print(f"  Promedio factor: {sum(f['x_studio_factor_corr'] for f in factors)/len(factors):.3f}")
    print(f"  Promedio raw:    {sum(f['x_studio_raw_factor'] for f in factors)/len(factors):.3f}")

    # Top 10 con mayor recorte (raw mas chico)
    print(f"\n  Top 10 por RAW factor menor (cuanto cayo el cluster):")
    sorted_f = sorted(factors, key=lambda x: x['x_studio_raw_factor'])
    print(f"    {'categ':<48s} {'abc':>3s} {'raw':>5s} {'clamp':>5s} {'bias%':>7s} {'n_real':>7s}")
    for f in sorted_f[:10]:
        cat = f.get('x_studio_categ_id')
        cat_name = (cat[1][:46] if isinstance(cat, list) else str(cat)[:46])
        print(f"    {cat_name:<48s} {f['x_studio_abc_letter']:>3s} "
              f"{f['x_studio_raw_factor']:>5.2f} {f['x_studio_factor_corr']:>5.2f} "
              f"{f['x_studio_bias_pct_pre']:>+6.1f}% {f['x_studio_n_real_units']:>7.0f}")

    # Top 10 con mayor amplificacion (raw mas alto)
    print(f"\n  Top 10 por RAW factor mayor (cuanto subio el cluster):")
    for f in sorted_f[-10:][::-1]:
        cat = f.get('x_studio_categ_id')
        cat_name = (cat[1][:46] if isinstance(cat, list) else str(cat)[:46])
        print(f"    {cat_name:<48s} {f['x_studio_abc_letter']:>3s} "
              f"{f['x_studio_raw_factor']:>5.2f} {f['x_studio_factor_corr']:>5.2f} "
              f"{f['x_studio_bias_pct_pre']:>+6.1f}% {f['x_studio_n_real_units']:>7.0f}")


if __name__ == "__main__":
    main()
