#!/usr/bin/env python3
"""
Validar llenado de los 4 campos bias-outlier en x_hm_si_forecast via XML-RPC.

Campos a validar:
  1. x_studio_bias_outlier (boolean) — flag si se aplicó corrección
  2. x_studio_bias_outlier_factor (float) — factor multiplicativo (0.65-4.0)
  3. x_studio_bias_outlier_delta (float) — delta en unidades (real - mu)
  4. x_studio_mu_week_pre_bias_outlier (float) — mu antes de bias-outlier (auditoria)

Ademas verificar:
  - mu_week vs mu_week_pre_bias_outlier (debe ser mu * factor)
  - rango de factores (0.65 a 4.0)
  - distribucion por regimen, team
"""

from datetime import datetime, timedelta
from shared.odoo_xmlrpc import OdooReader
import json


def main():
    print("=" * 80)
    print("VALIDAR LLENADO: BIAS-OUTLIER CORRECTION (v3.48)")
    print("=" * 80)

    odoo = OdooReader()
    print(f"\n[OK] Conectado: {odoo}")

    # Buscar la semana MAS RECIENTE que existe en x_hm_si_forecast
    print("\n[INFO] Buscando semana mas reciente con datos...")
    all_weeks = odoo.search_read('x_hm_si_forecast',
                                  fields=['x_studio_week_start'],
                                  limit=1,
                                  order='x_studio_week_start desc')

    if not all_weeks:
        print("[WARN] No hay registros en x_hm_si_forecast. Ejecuta el motor primero.")
        return

    target_week_str = str(all_weeks[0]['x_studio_week_start'])
    print(f"\n[OK] Semana mas reciente: {target_week_str}")

    # Query: registros con bias_outlier=True para esa semana
    domain = [
        ('x_studio_week_start', '=', target_week_str),
        ('x_studio_bias_outlier', '=', True),
    ]

    fields = [
        'id',
        'x_studio_product_id',
        'x_studio_team_id',
        'x_studio_categ_id',
        'x_studio_week_start',
        'x_studio_mu_week',
        'x_studio_mu_week_pre_bias_outlier',
        'x_studio_bias_outlier',
        'x_studio_bias_outlier_factor',
        'x_studio_bias_outlier_delta',
        'x_studio_regimen',
        'x_studio_abcxyz',
        'x_studio_sigma_week',
    ]

    print(f"\nConsultando x_hm_si_forecast...")
    print(f"Domain: {domain}")

    rows = odoo.search_read('x_hm_si_forecast', domain=domain, fields=fields)

    total = len(rows)
    print(f"\n[OK] Registros con bias_outlier=True: {total}")

    if total == 0:
        print("\n[WARN] No hay outliers detectados. Diagnosticando...")
        # Verificar si existen registros TOTALES para esa semana
        total_recs = odoo.search_count('x_hm_si_forecast', domain=[
            ('x_studio_week_start', '=', target_week_str),
        ])
        print(f"  - Total registros en semana {target_week}: {total_recs}")

        if total_recs == 0:
            print("    -> El motor NO ha ejecutado aun para esta semana.")
            print("    -> Ejecuta el motor HM-SI Forecast antes de validar.")
            return
        else:
            print(f"    -> El motor SI ejecuto ({total_recs} registros).")
            print("    -> Posibles causas de 0 outliers:")
            print("       a) APPLY_BIAS_OUTLIER estaba False en context")
            print("       b) No hay anomalias detectables (datos limpios)")
            print("       c) Campos Studio no existen (error silencioso)")

            # Revisar si los campos existen en el modelo
            print("\n    Verificando campos Studio en x_hm_si_forecast...")
            try:
                fields_meta = odoo.fields_get('x_hm_si_forecast', attributes=['string', 'type'])
                bias_fields = [f for f in fields_meta if 'bias' in f.lower() or 'outlier' in f.lower()]
                if bias_fields:
                    print(f"    Campos bias encontrados:")
                    for f in sorted(bias_fields)[:10]:
                        ftype = fields_meta.get(f, {}).get('type', 'unknown')
                        print(f"      - {f} ({ftype})")
                else:
                    print(f"    [WARN] Campos bias NO encontrados en Studio!")
            except Exception as e:
                print(f"    Error al leer campos: {e}")
        return

    # Analisis de campos
    print("\n" + "=" * 80)
    print("VALIDACION DE CAMPOS")
    print("=" * 80)

    # 1. Validar que todos los campos esten llenos
    missing_count = 0
    factor_invalid = 0
    delta_nan = 0
    pre_bias_missing = 0

    for r in rows:
        if not r.get('x_studio_bias_outlier_factor'):
            factor_invalid += 1
        if r.get('x_studio_bias_outlier_delta') is None:
            delta_nan += 1
        if not r.get('x_studio_mu_week_pre_bias_outlier'):
            pre_bias_missing += 1

    print(f"\n1. x_studio_bias_outlier_factor:")
    print(f"   - Llenos: {total - factor_invalid} / {total}")
    if factor_invalid:
        print(f"   [WARN] Vacios: {factor_invalid}")

    print(f"\n2. x_studio_bias_outlier_delta:")
    print(f"   - Llenos: {total - delta_nan} / {total}")
    if delta_nan:
        print(f"   [WARN] NULL/NaN: {delta_nan}")

    print(f"\n3. x_studio_mu_week_pre_bias_outlier (auditoria):")
    pre_bias_zeros = 0
    pre_bias_values = []
    for r in rows:
        v = r.get('x_studio_mu_week_pre_bias_outlier')
        if v is None:
            pre_bias_missing += 1
        elif v == 0.0 or v == 0:
            pre_bias_zeros += 1
        else:
            pre_bias_values.append(v)

    print(f"   - NULL/vacios: {pre_bias_missing} / {total}")
    print(f"   - CEROS (0.0): {pre_bias_zeros} / {total} <-- PROBLEMA")
    print(f"   - Valores validos (>0): {len(pre_bias_values)} / {total}")
    if pre_bias_values:
        print(f"   - Min valor: {min(pre_bias_values):.3f}")
        print(f"   - Max valor: {max(pre_bias_values):.3f}")
        print(f"   - Promedio: {sum(pre_bias_values)/len(pre_bias_values):.3f}")
    if pre_bias_zeros > 0:
        print(f"   [ERROR] {pre_bias_zeros} campos con CERO - campo NO se esta llenando!")

    # 2. Validar rango de factor (0.65 a 4.0)
    print(f"\n4. Rango de factores (clamp asimetrico [0.65, 4.0]):")
    factors = []
    for r in rows:
        f = r.get('x_studio_bias_outlier_factor')
        if f:
            factors.append(f)
    if factors:
        min_f = min(factors)
        max_f = max(factors)
        avg_f = sum(factors) / len(factors)
        print(f"   - Min: {min_f:.3f}")
        print(f"   - Max: {max_f:.3f}")
        print(f"   - Promedio: {avg_f:.3f}")
        if min_f < 0.65 or max_f > 4.0:
            print(f"   [WARN] FUERA DE RANGO: {len([f for f in factors if f < 0.65 or f > 4.0])} factores")

    # 3. Validar coherencia: mu_week ≈ mu_week_pre_bias_outlier * factor
    print(f"\n5. Coherencia mu_week vs pre_bias * factor:")
    inconsistent = 0
    diffs = []
    for r in rows:
        mu = r.get('x_studio_mu_week', 0.0)
        mu_pre = r.get('x_studio_mu_week_pre_bias_outlier', 0.0)
        factor = r.get('x_studio_bias_outlier_factor', 1.0)
        if mu_pre and factor:
            expected = mu_pre * factor
            if expected > 0:
                pct_diff = abs(mu - expected) / expected * 100
                if pct_diff > 1.0:  # tolerancia 1%
                    inconsistent += 1
                diffs.append(pct_diff)
    if diffs:
        print(f"   - Filas evaluadas: {len(diffs)}")
        print(f"   - % promedio diferencia: {sum(diffs) / len(diffs):.2f}%")
        print(f"   - Max diferencia: {max(diffs):.2f}%")
        if inconsistent:
            print(f"   [WARN] Inconsistentes (>1%): {inconsistent}")

    # 4. Distribucion por regimen
    print(f"\n6. Distribucion por REGIMEN:")
    regimen_counts = {}
    for r in rows:
        reg = r.get('x_studio_regimen', 'UNKNOWN')
        regimen_counts[reg] = regimen_counts.get(reg, 0) + 1
    for reg in sorted(regimen_counts.keys()):
        cnt = regimen_counts[reg]
        pct = cnt / total * 100
        print(f"   {reg}: {cnt:4d} ({pct:5.1f}%)")

    # 5. Distribucion por ABCXYZ
    print(f"\n7. Distribucion por ABCXYZ:")
    abcxyz_counts = {}
    for r in rows:
        abc = r.get('x_studio_abcxyz', 'UNKNOWN')
        abcxyz_counts[abc] = abcxyz_counts.get(abc, 0) + 1
    for abc in sorted(abcxyz_counts.keys()):
        cnt = abcxyz_counts[abc]
        pct = cnt / total * 100
        print(f"   {abc}: {cnt:4d} ({pct:5.1f}%)")

    # 6. Top 10 SKUs outlier (mayor |delta|)
    print(f"\n8. Top 10 SKUs outlier (mayor |delta|):")
    sorted_rows = sorted(rows, key=lambda r: abs(r.get('x_studio_bias_outlier_delta', 0.0)), reverse=True)
    for i, r in enumerate(sorted_rows[:10], 1):
        pid = r.get('x_studio_product_id', [False, 'N/A'])[1] if isinstance(r.get('x_studio_product_id'), (list, tuple)) else r.get('x_studio_product_id')
        tid = r.get('x_studio_team_id', [False, 'N/A'])[1] if isinstance(r.get('x_studio_team_id'), (list, tuple)) else r.get('x_studio_team_id')
        factor = r.get('x_studio_bias_outlier_factor', 1.0)
        delta = r.get('x_studio_bias_outlier_delta', 0.0)
        mu = r.get('x_studio_mu_week', 0.0)
        print(f"   {i:2d}. SKU={pid:6} TEAM={tid:2} | factor={factor:6.3f} | delta={delta:+7.2f} | mu={mu:6.2f}")

    # Resumen final
    print("\n" + "=" * 80)
    print("RESUMEN")
    print("=" * 80)
    print(f"[OK] Total outliers: {total}")
    print(f"[OK] Campos requeridos llenos: {total - factor_invalid} / {total}")
    if inconsistent == 0 and factor_invalid == 0:
        print("[OK] VALIDACION OK: Todos los campos completados y coherentes.")
    else:
        print(f"[WARN] Revisar: {factor_invalid} factores vacios, {inconsistent} inconsistencias")


if __name__ == '__main__':
    main()
