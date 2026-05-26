"""
Inspeccion en vivo de x_forecast_backtest (estado actual via XML-RPC).
Muestra metricas resumen sin exportar CSV.
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_forecast_backtest'


def main():
    odoo = OdooReader()
    print(odoo)

    total = odoo.search_count(MODEL, [])
    print(f"\nTotal filas en {MODEL}: {total:,}")
    if total == 0:
        print("Modelo vacio. Corre OH Forecast Backtest antes.")
        return

    # Sample para detectar campos
    sample = odoo.search_read(MODEL, [], limit=1)
    print(f"\nCampos en una fila: {sorted(sample[0].keys())}")

    # Detectar campos clave
    def _detect(candidates, names):
        for c in candidates:
            if c in names:
                return c
        return None

    names = set(sample[0].keys())
    method_col = _detect(['x_studio_method', 'x_studio_metodo', 'x_studio_forecast_method'], names)
    fc_col     = _detect(['x_studio_forecast_qty', 'x_studio_mu_week', 'x_studio_demanda_estimada'], names)
    real_col   = _detect(['x_studio_real_qty', 'x_studio_demanda_real', 'x_studio_venta_real'], names)
    zone_col   = _detect(['x_studio_forecast_zone', 'x_studio_z_segment', 'x_studio_zona_forecast'], names)
    reg_col    = _detect(['x_studio_regimen'], names)
    abc_col    = _detect(['x_studio_abc'], names)
    xyz_col    = _detect(['x_studio_xyz'], names)
    abcxyz_col = _detect(['x_studio_abcxyz'], names)
    team_col   = _detect(['x_studio_team_id'], names)
    week_col   = _detect(['x_studio_target_week_start', 'x_studio_week_start'], names)
    bucket_col = _detect(['x_studio_error_bucket', 'x_studio_bucket', 'x_studio_estado_error'], names)

    print(f"\nDetectados:")
    print(f"  method={method_col}")
    print(f"  forecast={fc_col}  real={real_col}")
    print(f"  zone={zone_col}  regimen={reg_col}")
    print(f"  abcxyz={abcxyz_col}")

    if not fc_col or not real_col:
        print("\nNo se detectaron columnas forecast/real. Output completo de un sample:")
        print(sample[0])
        return

    # Bajar todo
    print(f"\nDescargando {total:,} filas...")
    fields = [f for f in [method_col, fc_col, real_col, zone_col, reg_col,
                          abcxyz_col, abc_col, xyz_col, team_col, week_col, bucket_col]
              if f]
    rows = odoo.search_read(MODEL, [], fields=fields)

    # ----------------------------------------
    # Resumen por metodo
    # ----------------------------------------
    print("\n=== Resumen por metodo ===")
    by_method = defaultdict(lambda: {'n': 0, 'sum_fc': 0.0, 'sum_real': 0.0, 'sum_ae': 0.0, 'sum_err': 0.0})
    for r in rows:
        m = r.get(method_col) or 'unknown'
        fc = float(r.get(fc_col) or 0)
        re = float(r.get(real_col) or 0)
        err = re - fc
        by_method[m]['n'] += 1
        by_method[m]['sum_fc'] += fc
        by_method[m]['sum_real'] += re
        by_method[m]['sum_ae'] += abs(err)
        by_method[m]['sum_err'] += err

    print(f"{'method':<25s} {'n':>8s} {'sum_real':>12s} {'sum_fc':>12s} {'WAPE%':>8s} {'BIAS%':>8s}")
    for m, s in sorted(by_method.items()):
        wape = s['sum_ae'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
        bias = s['sum_err'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
        print(f"{str(m):<25s} {s['n']:>8,} {s['sum_real']:>12,.0f} {s['sum_fc']:>12,.0f} {wape:>8.2f} {bias:>+8.2f}")

    # ----------------------------------------
    # Por semana
    # ----------------------------------------
    if week_col:
        print("\n=== Por semana (hm_si) ===")
        by_week = defaultdict(lambda: {'n': 0, 'sum_real': 0.0, 'sum_fc': 0.0, 'sum_ae': 0.0, 'sum_err': 0.0})
        for r in rows:
            if r.get(method_col) != 'hm_si':
                continue
            w = r.get(week_col) or 'unknown'
            fc = float(r.get(fc_col) or 0)
            re = float(r.get(real_col) or 0)
            by_week[w]['n'] += 1
            by_week[w]['sum_real'] += re
            by_week[w]['sum_fc'] += fc
            by_week[w]['sum_ae'] += abs(re - fc)
            by_week[w]['sum_err'] += re - fc

        for w, s in sorted(by_week.items()):
            wape = s['sum_ae'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
            bias = s['sum_err'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
            print(f"  {w}: n={s['n']:,} real={s['sum_real']:,.0f} fc={s['sum_fc']:,.0f} WAPE={wape:.2f}% BIAS={bias:+.2f}%")

    # ----------------------------------------
    # Por regimen (HM-SI)
    # ----------------------------------------
    if reg_col:
        print("\n=== Por regimen (hm_si) ===")
        by_reg = defaultdict(lambda: {'n': 0, 'sum_real': 0.0, 'sum_fc': 0.0, 'sum_ae': 0.0, 'sum_err': 0.0})
        for r in rows:
            if r.get(method_col) != 'hm_si':
                continue
            reg = r.get(reg_col) or 'NA'
            fc = float(r.get(fc_col) or 0)
            re = float(r.get(real_col) or 0)
            by_reg[reg]['n'] += 1
            by_reg[reg]['sum_real'] += re
            by_reg[reg]['sum_fc'] += fc
            by_reg[reg]['sum_ae'] += abs(re - fc)
            by_reg[reg]['sum_err'] += re - fc

        print(f"{'reg':<10s} {'n':>8s} {'sum_real':>12s} {'sum_fc':>12s} {'WAPE%':>8s} {'BIAS%':>8s}")
        for reg in sorted(by_reg.keys()):
            s = by_reg[reg]
            wape = s['sum_ae'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
            bias = s['sum_err'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
            print(f"{str(reg):<10s} {s['n']:>8,} {s['sum_real']:>12,.0f} {s['sum_fc']:>12,.0f} {wape:>8.2f} {bias:>+8.2f}")

    # ----------------------------------------
    # Por ABCXYZ (HM-SI)
    # ----------------------------------------
    if abcxyz_col:
        print("\n=== Por ABCXYZ (hm_si) ===")
        by_abc = defaultdict(lambda: {'n': 0, 'sum_real': 0.0, 'sum_fc': 0.0, 'sum_ae': 0.0, 'sum_err': 0.0})
        for r in rows:
            if r.get(method_col) != 'hm_si':
                continue
            c = r.get(abcxyz_col) or 'NA'
            fc = float(r.get(fc_col) or 0)
            re = float(r.get(real_col) or 0)
            by_abc[c]['n'] += 1
            by_abc[c]['sum_real'] += re
            by_abc[c]['sum_fc'] += fc
            by_abc[c]['sum_ae'] += abs(re - fc)
            by_abc[c]['sum_err'] += re - fc

        print(f"{'class':<8s} {'n':>8s} {'sum_real':>12s} {'sum_fc':>12s} {'WAPE%':>8s} {'BIAS%':>8s}")
        for c in sorted(by_abc.keys()):
            s = by_abc[c]
            wape = s['sum_ae'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
            bias = s['sum_err'] / s['sum_real'] * 100 if s['sum_real'] > 0 else 0
            print(f"{str(c):<8s} {s['n']:>8,} {s['sum_real']:>12,.0f} {s['sum_fc']:>12,.0f} {wape:>8.2f} {bias:>+8.2f}")

    # ----------------------------------------
    # Por bucket de error (HM-SI)
    # ----------------------------------------
    if bucket_col:
        print("\n=== Por bucket de error (hm_si) ===")
        by_bk = defaultdict(int)
        for r in rows:
            if r.get(method_col) != 'hm_si':
                continue
            by_bk[r.get(bucket_col) or 'NA'] += 1
        for b, n in sorted(by_bk.items(), key=lambda x: -x[1]):
            print(f"  {str(b):<30s} {n:,}")


if __name__ == '__main__':
    main()
